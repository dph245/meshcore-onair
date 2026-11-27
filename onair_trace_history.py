"""Incremental projection of passive TRACE receptions and directed hop samples."""
from bisect import bisect_left
from collections import Counter, defaultdict
import json

from onair_neighbors import distance_km
from onair_map_visibility import MapVisibility
from onair_observer_radio import CORE_FIELDS, RadioProfiles, observer_identity, radio_profile_at
from onair_payload import decode_payload_details
from onair_trace import WINDOW_SECONDS
from onair_trace_positions import TracePositionCache
from onair_trace_quality import DirectionSamples, RULES, assess_link, assess_profile, directional_coverage, percentiles

BACKFILL_BATCH = 100
SAME_STAGE_SECONDS = 3
PAGE = 50
RADIO_FIELDS = CORE_FIELDS + ('tx_power_dbm', 'preamble_length', 'sync_word', 'radio_ic')


def migrate(db):
    for sql in (
        '''CREATE TABLE IF NOT EXISTS trace_measurement (
            id INTEGER PRIMARY KEY REFERENCES packets(id), wire_key BLOB NOT NULL,
            hash_bytes INTEGER NOT NULL, route BLOB NOT NULL, snrs BLOB NOT NULL,
            first_at REAL NOT NULL, last_at REAL NOT NULL
        )''',
        '''CREATE INDEX IF NOT EXISTS trace_measurement_wire_time ON trace_measurement(wire_key,first_at,last_at)''',
        '''CREATE TABLE IF NOT EXISTS trace_observation (
            packet_id INTEGER PRIMARY KEY REFERENCES packets(id),
            measurement_id INTEGER REFERENCES trace_measurement(id),
            received REAL NOT NULL, source_at REAL, event_at REAL NOT NULL,
            observer_id TEXT, retained INTEGER NOT NULL, snr_count INTEGER,
            relation TEXT NOT NULL, duplicate_of INTEGER REFERENCES trace_observation(packet_id),
            radio_match TEXT NOT NULL, radio_reason TEXT, radio_observed_at REAL
        )''',
        '''CREATE INDEX IF NOT EXISTS trace_observation_measurement ON trace_observation(measurement_id,event_at,packet_id)''',
        '''CREATE INDEX IF NOT EXISTS trace_observation_time ON trace_observation(event_at,measurement_id)''',
        '''CREATE TABLE IF NOT EXISTS trace_sample (
            measurement_id INTEGER NOT NULL REFERENCES trace_measurement(id),
            hop INTEGER NOT NULL, source BLOB NOT NULL, target BLOB NOT NULL,
            snr_qdb INTEGER NOT NULL, event_at REAL NOT NULL,
            PRIMARY KEY(measurement_id,hop)
        ) WITHOUT ROWID''',
        '''CREATE INDEX IF NOT EXISTS trace_sample_time ON trace_sample(event_at)''',
        '''CREATE INDEX IF NOT EXISTS trace_sample_link_time ON trace_sample(source,target,event_at)''',
        '''CREATE TABLE IF NOT EXISTS trace_backfill (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), high INTEGER NOT NULL,
            cursor INTEGER NOT NULL, scanned INTEGER NOT NULL, done INTEGER NOT NULL
        )''',
        '''INSERT OR IGNORE INTO trace_backfill
            SELECT 1,COALESCE(MAX(id),0),0,0,COUNT(*)=0 FROM
            (SELECT id FROM packets WHERE kind='TRACE' ORDER BY id DESC LIMIT 1)''',
    ):
        db.execute(sql)
    db.execute('PRAGMA user_version=18')


def status(db):
    high, cursor, scanned, done = db.execute('SELECT high,cursor,scanned,done FROM trace_backfill').fetchone()
    return dict(high=high, cursor=cursor, scanned=scanned, done=bool(done))


def backfill_batch(db, limit=BACKFILL_BATCH):
    progress = status(db)
    if progress['done']:
        return None
    rows = db.execute('''SELECT id,received,packet_json FROM packets
        WHERE kind='TRACE' AND id>? AND id<=? ORDER BY id LIMIT ?''',
                      (progress['cursor'], progress['high'], limit)).fetchall()
    # Parsing JSON need not hold the writer lock. The cursor and projection advance together.
    packets = []
    for ident, received, raw in rows:
        try:
            packet = json.loads(raw)
        except ValueError:
            packet = None
        packets.append((ident, received, packet if isinstance(packet, dict) else {}))
    with db:
        record_batch(db, packets)
        cursor = packets[-1][0] if packets else progress['high']
        done = cursor == progress['high'] or len(packets) < limit
        db.execute('UPDATE trace_backfill SET cursor=?,scanned=scanned+?,done=?',
                   (cursor, len(packets), done))
    return status(db)


def _correlate(db, wire, snrs, event_at, source_at, observer):
    """Retain a separate observation whenever the available evidence is ambiguous."""
    candidates = db.execute('''SELECT m.id,m.snrs,m.first_at,m.last_at,
            o.packet_id,o.observer_id,o.event_at,o.source_at,o.snr_count
        FROM trace_measurement m JOIN trace_observation o ON o.measurement_id=m.id
        WHERE m.wire_key=? AND m.first_at>=? AND m.last_at<=?
        AND o.duplicate_of IS NULL AND (o.retained=0 OR o.source_at IS NOT NULL)
        ORDER BY m.id,o.packet_id''',
        (wire, event_at - WINDOW_SECONDS, event_at + WINDOW_SECONDS))
    matches = {}
    rejected = set()
    duplicates = []
    conflict = False
    count = len(snrs)
    for ident, known, first, last, packet_id, receiver, stamp, reported, stage in candidates:
        if max(last, event_at) - min(first, event_at) > WINDOW_SECONDS:
            continue
        common = min(len(known), count)
        if known[:common] != snrs[:common]:
            conflict = True
            continue
        same_receiver = observer is not None and observer == receiver
        if same_receiver and stage == count:
            if source_at == reported and event_at == stamp and (source_at is None or source_at % 1):
                duplicates.append((ident, packet_id))
            rejected.add(ident)
        # Within one receiver's clock, a reset or reversed progression is evidence
        # for a new run. Legacy arrivals allow jitter in the MQTT delivery order.
        if same_receiver and (stage - count) * (stamp - event_at) < 0:
            if (source_at is not None and reported is not None) or abs(stamp - event_at) > SAME_STAGE_SECONDS:
                rejected.add(ident)
        same_stage, close_stage, anchored = matches.get(ident, (False, False, False))
        matches[ident] = (same_stage or stage == count,
                          close_stage or (stage == count and observer != receiver
                                          and abs(stamp - event_at) <= SAME_STAGE_SECONDS),
                          anchored or same_receiver)
    if len(duplicates) == 1:
        ident, packet_id = duplicates[0]
        return ident, 'duplicate', packet_id
    plausible = [ident for ident, (same_stage, close_stage, anchored) in matches.items()
                 if ident not in rejected and (close_stage if same_stage else anchored or count > 0)]
    if len(plausible) == 1 and not duplicates:
        return plausible[0], 'correlated', None
    if duplicates or len(plausible) > 1:
        return None, 'ambiguous_correlation', None
    return None, 'conflicting_snr' if conflict else 'separate', None


def record_batch(db, packets):
    if packets:
        radio = RadioProfiles(db, {observer_identity(packet.get('origin_id')) for _, _, packet in packets})
        for packet_id, received, packet in packets:
            record(db, packet_id, received, packet, radio)


def record(db, packet_id, received, packet, radio=None):
    if db.execute('SELECT 1 FROM trace_observation WHERE packet_id=?', (packet_id,)).fetchone():
        return
    decoded = packet.get('decoded', {})
    observer = observer_identity(packet.get('origin_id'))
    source_at = packet.get('source_at')
    event_at = received if source_at is None else source_at
    retained = bool(packet.get('mqtt_retained'))
    event = decode_payload_details(decoded).get('trace') if packet.get('direction') == 'rx' else None
    ident, relation, duplicate, count = None, 'undecodable', None, None
    if event is not None:
        size = event['hash_size']
        route = [bytes.fromhex(token) for token in event['route']]
        snrs = bytes(round(value * 4) & 255 for value in event['snrs'])
        count = len(snrs)
        # Entire immutable wire identity, including the raw transport codes.
        wire = bytes([decoded['route_type'], decoded.get('payload_ver', 0)]) + bytes.fromhex(
            (decoded.get('transport_code') or '') + decoded['payload_hex'])
        if retained and source_at is None:
            relation = 'untimed_retained'
        else:
            ident, relation, duplicate = _correlate(db, wire, snrs, event_at, source_at, observer)
        if ident is None:
            ident = packet_id
            db.execute('INSERT INTO trace_measurement VALUES(?,?,?,?,?,?,?)',
                       (ident, wire, size, b''.join(route), snrs, event_at, event_at))
        elif duplicate is None:
            db.execute('''UPDATE trace_measurement SET first_at=MIN(first_at,?),
                last_at=MAX(last_at,?),snrs=CASE WHEN length(snrs)<? THEN ? ELSE snrs END WHERE id=?''',
                       (event_at, event_at, count, snrs, ident))
        if duplicate is None:
            db.executemany('''INSERT INTO trace_sample VALUES (?,?,?,?,?,?)
                ON CONFLICT(measurement_id,hop) DO UPDATE SET event_at=MIN(event_at,excluded.event_at)
                WHERE excluded.event_at<event_at''',
                ((ident, hop, route[hop - 1], route[hop], round(event['snrs'][hop] * 4), event_at)
                 for hop in range(1, count)))
    if retained and source_at is None:
        profile = dict(match='unknown', reason='untimed_retained')
    else:
        profile = radio_profile_at(db, observer, event_at) if radio is None else radio.at(observer, event_at)
    # The Schema 17 compound key retains the assignment made at indexing. Read-side
    # resolution also reflects subsequently reported historical transitions/conflicts.
    db.execute('INSERT INTO trace_observation VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
               (packet_id, ident, received, source_at, event_at, observer, retained, count, relation, duplicate,
                profile['match'], profile.get('reason'), profile.get('observed_at')))


def _profile_assignment(observations, hop):
    candidates = [o['radio'] for o in observations if o['duplicate_of'] is None and o['snr_count'] > hop]
    known = [(tuple((name, item['profile'][name]) for name in RADIO_FIELDS if name in item['profile']),
              item['match']) for item in candidates if item.get('profile')]
    if any(item.get('reason') == 'conflicting_status' for item in candidates):
        return (), 'conflicting_status'
    if any(item.get('reason') in ('transition', 'untimed_retained') for item in candidates):
        return (), 'uncertain'
    if not known:
        return (), 'unknown'
    best, _ = max(known, key=lambda item: len(item[0]))
    values = dict(best)
    if any(values.get(name) != value for profile, _ in known for name, value in profile):
        return (), 'conflicting_profiles'
    if 'spreading_factor' not in values:
        return (), 'unknown'
    quality = 'confirmed' if any(profile == best and match == 'confirmed' for profile, match in known) else 'last_known'
    return best, quality


def _observations(db, selection, args):
    rows = db.execute(f'''SELECT o.packet_id,o.measurement_id,o.received,o.source_at,o.event_at,
        o.observer_id,o.retained,o.snr_count,o.relation,o.duplicate_of
        FROM ({selection}) q JOIN trace_observation o ON o.measurement_id=q.measurement_id
        ORDER BY o.measurement_id,o.event_at,o.packet_id''', args).fetchall()
    radio = RadioProfiles(db, {r[5] for r in rows})
    groups = defaultdict(list)
    for packet, ident, received, source, stamp, observer, retained, count, relation, duplicate in rows:
        profile = (dict(match='unknown', reason='untimed_retained') if retained and source is None
                   else radio.at(observer, stamp))
        groups[ident].append(dict(packet_id=packet, received=received, source_at=source,
            event_at=stamp, observer_id=observer, retained=bool(retained), snr_count=count,
            relation=relation, duplicate_of=duplicate, radio=profile))
    return groups


class Identities:
    def __init__(self, db):
        nodes = [dict(public_key=key, name=name, node_type=kind)
                 for key, name, kind in db.execute('SELECT public_key,name,node_type FROM nodes')]
        manual = [dict(public_key=key, name=name, node_type=2)
                  for key, name in db.execute('SELECT public_key,name FROM manual_nodes')]
        self.nodes = {node['public_key'].lower(): node for node in manual + nodes}
        self.keys = sorted(self.nodes)
        self.visibility = MapVisibility(nodes, manual)
        self.cache = {}

    def resolve(self, token):
        if token not in self.cache:
            value = token.hex()
            index = bisect_left(self.keys, value)
            if index == len(self.keys) or not self.keys[index].startswith(value):
                node = dict(hash=value, public_key=None, state='unknown')
            elif index + 1 < len(self.keys) and self.keys[index + 1].startswith(value):
                node = dict(hash=value, public_key=None, state='ambiguous')
            else:
                key = self.keys[index]
                node = dict(self.nodes[key], hash=value, public_key=key, state='resolved')
                if node['node_type'] != 2:
                    node['state'] = 'non_repeater'
                elif self.visibility.hidden(key, prefix_bytes=len(token)):
                    node['state'] = 'collision'
            self.cache[token] = node
        return self.cache[token]


def load_locations(db, nodes, cache, *, include_non_repeaters=False):
    states = ('resolved', 'non_repeater') if include_non_repeaters else ('resolved',)
    return (cache or TracePositionCache()).load(db, {
        node['public_key'] for node in nodes if node['state'] in states
    })


def locate(node, locations, stamp):
    timeline = locations.get(node['public_key'])
    if timeline is None:
        return None, node['state']
    if stamp is None:
        return None, 'missing_measurement_time'
    return timeline.at(stamp)


def _sample_query(start, end, pair=None):
    where = 'event_at>=? AND event_at<?'
    args = [start, end]
    if pair:
        left, right = ([bytes.fromhex(key[:2 * size]) for size in (1, 2, 4, 8)] for key in pair)
        marks = '(?,?,?,?)'
        where += f' AND ((source IN {marks} AND target IN {marks}) OR (source IN {marks} AND target IN {marks}))'
        args.extend(left + right + right + left)
    return where, args


def _samples(db, start, end, pair=None):
    where, args = _sample_query(start, end, pair)
    groups = _observations(db, f'SELECT DISTINCT measurement_id FROM trace_sample WHERE {where}', args)
    for ident, hop, source, target, snr, stamp in db.execute(f'''SELECT measurement_id,hop,source,target,
            snr_qdb,event_at FROM trace_sample WHERE {where} ORDER BY event_at DESC,measurement_id DESC,hop DESC''',
            args):
        profile, quality = _profile_assignment(groups[ident], hop)
        yield ident, hop, source, target, snr, stamp, profile, quality, groups[ident]


def _visible_link(identities, locations, source, target, stamp):
    a, b = identities.resolve(source), identities.resolve(target)
    if a['state'] != 'resolved' or b['state'] != 'resolved':
        return None, None, a['state'] if a['state'] != 'resolved' else b['state']
    ka, kb = a['public_key'], b['public_key']
    if ka == kb:
        return None, None, 'same_identity'
    pa, issue_a = locate(a, locations, stamp)
    pb, issue_b = locate(b, locations, stamp)
    issue = issue_a or issue_b
    return (a, b), None if issue else (pa, pb), issue


def _summary(db, start, end):
    groups, partial, invalid, receptions = db.execute('''SELECT COUNT(DISTINCT o.measurement_id),
        COUNT(DISTINCT CASE WHEN length(m.snrs)<length(m.route)/m.hash_bytes THEN m.id END),
        COUNT(*)-COUNT(o.measurement_id),COUNT(*) FROM trace_observation o
        LEFT JOIN trace_measurement m ON m.id=o.measurement_id
        WHERE o.event_at>=? AND o.event_at<?''', (start, end)).fetchone()
    return dict(measurements=groups, partial=partial, undecodable=invalid, receptions=receptions)


def _snr_readings(profiles, forward):
    return [(stamp, ident, hop, snr) for directions in profiles.values() if forward in directions
            for ident, (snr, stamp, hop, _) in directions[forward].readings.items()]


def _snr_summary(readings):
    if not readings:
        return None
    histogram = Counter(reading[3] for reading in readings)
    count = len(readings)
    minimum, median, maximum = percentiles(histogram, count, (0, .5, 1))
    stamp, _, _, last = max(readings)
    return dict(count=count, last=last / 4, last_at=stamp, min=minimum, median=median, max=maximum)


def links(db, start, end, sf='all', pair=None, offset=0, compact=False, *, position_cache=None):
    """Aggregate the normalized projection and page a single link on demand."""
    identities = Identities(db)
    where, args = _sample_query(start, end, pair)
    tokens = {token for row in db.execute(f'''SELECT DISTINCT source,target FROM trace_sample
        WHERE {where}''', args) for token in row}
    locations = load_locations(db, (identities.resolve(token) for token in tokens), position_cache)
    links_by_key = {}
    stats = defaultdict(lambda: defaultdict(dict))
    missing = Counter()
    sfs = set()
    visible_ids = set()
    selected_ids = set()
    selected_visible_ids = set()
    observers = set()
    samples = []
    sample_count = 0
    for ident, hop, left, right, snr, stamp, profile, quality, observations in _samples(db, start, end, pair):
        spreading = dict(profile).get('spreading_factor')
        if spreading is not None:
            sfs.add(spreading)
        selected = sf == 'all' or sf == ('unknown' if spreading is None else str(spreading))
        endpoints, points, reason = _visible_link(identities, locations, left, right, stamp)
        if selected and not pair:
            selected_ids.add(ident)
            if reason:
                missing[reason] += 1
        if endpoints is None:
            continue
        a, b = endpoints
        ka, kb = a['public_key'], b['public_key']
        forward = ka < kb
        key = (ka, kb) if forward else (kb, ka)
        if pair and key != pair:
            continue
        if pair:
            if selected:
                sample_count += 1
                evidence = [o for o in observations if o['snr_count'] > hop]
                observers.update(o['observer_id'] for o in evidence if o['observer_id'] and o['duplicate_of'] is None)
                if offset < sample_count <= offset + PAGE:
                    samples.append(dict(measurement_id=ident, hop=hop + 1, source=ka, target=kb,
                        snr=snr / 4, time=stamp, profile=dict(profile), quality=quality, location_issue=reason,
                        observations=[o['packet_id'] for o in evidence]))
            if not compact or offset or not selected or points is None:
                continue
        elif points is None:
            continue
        elif selected:
            selected_visible_ids.add(ident)
            sample_count += 1
            pa, pb = points
            widths = [len(left), len(right)]
            if not forward:
                a, b, pa, pb, widths = b, a, pb, pa, widths[::-1]
            link = links_by_key.setdefault(key, dict(endpoints=[a, b], positions=[pa, pb],
                                                       position_at=stamp, prefix_bytes=widths))
            # Descending time order makes the newest location evidence the display geometry.
            link['prefix_bytes'] = list(map(min, link['prefix_bytes'], widths))
        visible_ids.add(ident)
        if compact and not selected:
            continue
        directions = stats[key][profile]
        direction = directions.get(forward)
        if direction is None:
            direction = directions[forward] = DirectionSamples()
        direction.add(stamp, ident, hop, snr, quality)
    if pair:
        page = dict(items=samples, total=sample_count, observers=sorted(observers),
                    next=offset + PAGE if sample_count > offset + PAGE else None)
        if compact and offset == 0:
            page['history'] = {
                label: [[stamp, snr / 4] for stamp, _, _, snr in sorted(_snr_readings(stats[pair], direction))]
                for label, direction in (('forward', True), ('reverse', False))
            }
        return page
    for key, link in links_by_key.items():
        if compact:
            link['snr'] = {label: _snr_summary(_snr_readings(stats[key], direction))
                           for label, direction in (('forward', True), ('reverse', False))}
            continue
        groups = []
        selected_groups = []
        selected_samples = []
        ordered = sorted(stats[key].items(), key=lambda item: str(item[0]))
        for index, (profile, by_direction) in enumerate(ordered):
            group = assess_profile(dict(profile), [by_direction.get(True), by_direction.get(False)])
            groups.append(group)
            if sf == 'all' or sf == str(group['profile'].get('spreading_factor', 'unknown')):
                selected_groups.append((index, group))
                selected_samples.append((profile, by_direction))
        coverage = {
            label: directional_coverage(((profile, by_direction[direction]) for profile, by_direction in selected_samples
                                         if direction in by_direction), end)
            for label, direction in (('forward', True), ('reverse', False))
        }
        link.update(profiles=groups, coverage=coverage, analysis=assess_link(selected_groups, coverage),
                    distance_km=distance_km(*link['positions']))
    summary = _summary(db, start, end)
    # Every sampled measurement has an observation in the same event window.
    summary.update(without_visible_links=summary['measurements'] - len(visible_ids),
                   visible_samples=sample_count, unmapped_samples=dict(missing),
                   unmapped_measurements=len(selected_ids - selected_visible_ids))
    result = dict(links=list(links_by_key.values()), summary=summary, spreading_factors=sorted(sfs),
                  backfill=status(db), start=start, end=end)
    if not compact:
        result['analysis_rules'] = RULES
    return result


def measurement(db, ident, *, position_cache=None):
    row = db.execute('''SELECT wire_key,hash_bytes,route,snrs,first_at,last_at
        FROM trace_measurement WHERE id=?''', (ident,)).fetchone()
    if row is None:
        return None
    wire, size, route, snrs, first, last = row
    payload_at = 6 if wire[0] == 3 else 2
    payload = wire[payload_at:]
    identities = Identities(db)
    tokens = [route[offset:offset + size] for offset in range(0, len(route), size)]
    nodes = [identities.resolve(token) for token in tokens]
    locations = load_locations(db, nodes, position_cache)
    observations = _observations(db, 'SELECT ? AS measurement_id', (ident,))[ident]
    metadata = {row[0]: row[1:] for row in db.execute('''SELECT o.packet_id,p.origin,
            json_extract(p.packet_json,'$.rssi'),json_extract(p.packet_json,'$.snr'),
            o.radio_match,o.radio_reason,o.radio_observed_at
        FROM trace_observation o JOIN packets p ON p.id=o.packet_id WHERE o.measurement_id=?''', (ident,))}
    for observation in observations:
        name, rssi, snr, match, reason, observed_at = metadata[observation['packet_id']]
        observation.update(observer_name=name, observer_rssi=rssi, observer_snr=snr,
            radio_at_indexing=dict(match=match, reason=reason, observed_at=observed_at))
    hops = []
    for index, node in enumerate(nodes):
        snr = (snrs[index] - 256 if snrs[index] >= 128 else snrs[index]) / 4 if index < len(snrs) else None
        evidence = [o for o in observations if o['duplicate_of'] is None and o['snr_count'] > index]
        stamp = min((o['event_at'] for o in evidence), default=None)
        point, issue = locate(node, locations, stamp)
        profile, quality = _profile_assignment(observations, index)
        hop = dict(node, snr=snr, time=stamp, position=point, location_issue=issue,
                   profile=dict(profile), quality=quality)
        if index and stamp is not None:
            from_point, from_issue = locate(nodes[index - 1], locations, stamp)
            hop.update(from_position=from_point, from_location_issue=from_issue)
        hops.append(hop)
    return dict(id=ident, tag=f'{int.from_bytes(payload[:4], "little"):08x}',
                auth_code=f'{int.from_bytes(payload[4:8], "little"):08x}', flags=payload[8],
                transport_code=wire[2:6].hex() if payload_at == 6 else None,
                first_at=first, last_at=last, prefix_bytes=size, hops=hops,
                complete=len(snrs) * size == len(route), observations=observations)
