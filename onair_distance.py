"""On-demand historical neighbor evidence; indexed reads, no new worker/service."""
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta
import hashlib
import json
import math
from zoneinfo import ZoneInfo

from onair_neighbors import distance_km, resolve_path_tokens

ZONE = ZoneInfo('Europe/Berlin')
MAX_RECEPTIONS = 25000
MAX_DAYS = 31
# The predicate must be identical in the partial index and evidence queries.
FLOOD_WHERE = """json_extract(packet_json,'$.direction')='rx'
    AND json_extract(packet_json,'$.decoded.route_type') IN (0,1)
    AND json_extract(packet_json,'$.decoded.payload_type') != 9
    AND json_array_length(packet_json,'$.decoded.hops') >= 2"""
INDEX_SQL = f"""CREATE INDEX IF NOT EXISTS packets_flood_path_received
    ON packets(json_extract(packet_json,'$.decoded.hops'),received,id)
    WHERE {FLOOD_WHERE}"""


class AnalysisLimitError(ValueError):
    pass


def validate_window(start, end, minimum):
    if (not all(math.isfinite(v) for v in (start, end, minimum))
            or start < 0 or end <= start or end - start > MAX_DAYS * 86400):
        raise ValueError('Zeitraum muss positiv sein und darf höchstens 31 Tage umfassen.')
    if not 100 <= minimum <= 20000:
        raise ValueError('Mindestentfernung muss zwischen 100 und 20000 km liegen.')


def packet_identity(decoded):
    # The payload rather than a path/observer/session ID identifies repeated content.
    # Including type, version and transport prevents merging unrelated equal payloads.
    data = [decoded.get(k) for k in ('payload_type', 'payload_ver', 'payload_hex', 'transport_code')]
    return hashlib.sha256(json.dumps(data, separators=(',', ':')).encode()).hexdigest()


class Positions:
    """Position state known at reception time, with the same advert ordering as nodes.

    No interpolation or retroactive use of later adverts. Raw adverts may have been
    pruned: in that case historical position is explicitly unavailable.
    """
    def __init__(self, db, start, end):
        self.times = defaultdict(list)
        self.values = defaultdict(list)
        newest = {}
        for received, raw in db.execute("""SELECT received,
                json_extract(packet_json,'$.decoded.advert') FROM packets
                WHERE kind='ADVERT' AND received<?
                AND json_extract(packet_json,'$.decoded.advert_status') IS NULL
                ORDER BY received,id""", (end,)):
            if not raw:
                continue
            a = json.loads(raw)
            key = a.get('public_key')
            stamp = a.get('timestamp')
            if (not key or stamp is None or a.get('signature_status') != 'Gültig'
                    or a.get('latitude') is None or a.get('longitude') is None
                    or stamp < newest.get(key, -1)):
                continue
            newest[key] = stamp
            pos = dict(latitude=a['latitude'], longitude=a['longitude'])
            # Keep the last state before the window and subsequent actual changes.
            if self.times[key] and received < start:
                self.times[key][-1] = received
                self.values[key][-1] = pos
            elif not self.values[key] or self.values[key][-1] != pos:
                self.times[key].append(received)
                self.values[key].append(pos)
        self.bounds = {}
        for key, values in self.values.items():
            valid = [p for p in values if distance_km(p, p) is not None]
            if valid:
                anchor = valid[0]
                self.bounds[key] = (anchor, max(distance_km(anchor, p) for p in valid))

    def at(self, key, received):
        index = bisect_right(self.times[key], received) - 1
        return self.values[key][index] if index >= 0 else None

    def possibly_distant(self, a, b, minimum):
        if a not in self.bounds or b not in self.bounds:
            return False
        pa, ra = self.bounds[a]
        pb, rb = self.bounds[b]
        # Triangle bound also finds formerly distant nodes that have since moved.
        return distance_km(pa, pb) + ra + rb >= minimum


def bins(start, end):
    day = datetime.fromtimestamp(start, ZONE).date()
    last = datetime.fromtimestamp(end - .000001, ZONE).date()
    result = {}
    while day <= last:
        result[str(day)] = dict(label=str(day), forward=0, reverse=0,
                                forward_receptions=0, reverse_receptions=0)
        day += timedelta(days=1)
    return result


def analyze(db, start, end, minimum=200):
    validate_window(start, end, minimum)
    nodes = {r[0]: dict(id=r[0], name=r[1] or r[0], node_type=r[2], latitude=r[3], longitude=r[4])
             for r in db.execute('SELECT public_key,name,node_type,latitude,longitude FROM nodes')}
    tokens = {t for row in db.execute('SELECT source,target FROM repeater_pairs') for t in row}
    resolved = resolve_path_tokens(db, nodes, tokens)
    positions = Positions(db, start, end)
    pair_cache = {}
    candidates = {}
    ambiguous_paths = 0
    missing_position_pairs = set()
    for raw, in db.execute('SELECT path FROM repeater_paths WHERE first_seen<? AND last_seen>=?', (end, start)):
        hops = json.loads(raw)
        directions = set()
        ambiguous = False
        for left, right in set(zip(hops, hops[1:])):
            key = (left, right)
            if key not in pair_cache:
                a, b = resolved.get(left), resolved.get(right)
                pair_cache[key] = None
                if (a and b and a['resolved'] and b['resolved'] and not a['ambiguous']
                        and not b['ambiguous'] and a['id'] != b['id']):
                    if a['id'] not in positions.bounds or b['id'] not in positions.bounds:
                        missing_position_pairs.add(tuple(sorted((a['id'], b['id']))))
                    elif positions.possibly_distant(a['id'], b['id'], minimum):
                        pair_cache[key] = (a['id'], b['id'])
            if pair_cache[key]:
                directions.add(pair_cache[key])
            ambiguous |= any(resolved.get(t, {}).get('ambiguous', False) for t in key)
        ambiguous_paths += ambiguous
        if directions:
            candidates[json.dumps(hops, separators=(',', ':'))] = directions
    rows = []
    # Each lookup seeks directly to a path AND its requested time range.
    for path in candidates:
        remaining = MAX_RECEPTIONS + 1 - len(rows)
        rows.extend(db.execute(f"""SELECT id,received,packet_json FROM packets
            WHERE {FLOOD_WHERE} AND json_extract(packet_json,'$.decoded.hops')=?
            AND received>=? AND received<? ORDER BY received,id LIMIT ?""",
                               (path, start, end, remaining)))
        if len(rows) > MAX_RECEPTIONS:
            raise AnalysisLimitError('Mehr als 25.000 passende Empfänge. Bitte Zeitraum verkürzen oder Mindestentfernung erhöhen.')
    rows.sort(key=lambda row: (row[1], row[0]))
    links = {}
    global_packets = set()
    missing_at_reception = 0
    for row_id, received, raw in rows:
        packet = json.loads(raw)
        d = packet['decoded']
        path = json.dumps(d['hops'], separators=(',', ':'))
        identity = packet_identity(d)
        matches = defaultdict(list)
        for a, b in candidates[path]:
            dist = distance_km(positions.at(a, received), positions.at(b, received))
            if dist is None:
                missing_at_reception += 1
                continue
            if dist < minimum:
                continue
            pair = tuple(sorted((a, b)))
            matches[pair].append(('forward' if a == pair[0] else 'reverse', dist))
        for pair, directions in matches.items():
            if pair not in links:
                links[pair] = dict(source=nodes[pair[0]], target=nodes[pair[1]],
                    receptions=0, forward_receptions=0, reverse_receptions=0,
                    first_seen=received, last_seen=received,
                    distance_min_km=directions[0][1], distance_max_km=directions[0][1],
                    _seen=set(), _directions=set(), _paths=set(),
                    days=bins(start, end), hours={str(h): dict(label=f'{h:02d}', forward=0, reverse=0,
                        forward_receptions=0, reverse_receptions=0) for h in range(24)}, evidence=[])
            link = links[pair]
            link['receptions'] += 1
            link['last_seen'] = received
            link['_seen'].add(identity)
            link['_paths'].add(path)
            global_packets.add(identity)
            moment = datetime.fromtimestamp(received, ZONE)
            buckets = [link['days'][str(moment.date())], link['hours'][str(moment.hour)]]
            for direction, dist in directions:
                link['distance_min_km'] = min(link['distance_min_km'], dist)
                link['distance_max_km'] = max(link['distance_max_km'], dist)
                link[direction + '_receptions'] += 1
                link.setdefault(direction + '_first', received)
                link[direction + '_last'] = received
                for bucket in buckets:
                    bucket[direction + '_receptions'] += 1
                if (identity, direction) not in link['_directions']:
                    link['_directions'].add((identity, direction))
                    for bucket in buckets:
                        bucket[direction] += 1
            link['evidence'].append(dict(id=row_id, received=received, kind=d['payload_name'],
                observer_hash=packet.get('observer_hash'), observer=packet.get('origin'),
                path=d['hops'], route=d['route_name'], packet_key=identity,
                directions=[v[0] for v in sorted(directions)]))
    for link in links.values():
        link['packets'] = len(link.pop('_seen'))
        link['paths'] = len(link.pop('_paths'))
        directions = link.pop('_directions')
        for direction in ('forward', 'reverse'):
            link[direction + '_packets'] = sum(d == direction for _, d in directions)
        link['days'] = list(link['days'].values())
        link['hours'] = list(link['hours'].values())
    extent = db.execute('SELECT (SELECT MIN(received) FROM packets), (SELECT MAX(received) FROM packets)').fetchone()
    return dict(start=start, end=end, minimum_km=minimum, timezone='Europe/Berlin',
                archive_first=extent[0], archive_last=extent[1], packet_count=len(global_packets),
                candidate_receptions=len(rows), ambiguous_candidate_paths=ambiguous_paths,
                missing_position_pairs=len(missing_position_pairs), missing_at_reception=missing_at_reception,
                items=sorted(links.values(), key=lambda l: (-l['packets'], l['source']['id'], l['target']['id'])))


def response(result, source='', target='', offset=0):
    """Do not mutate cached results; evidence pages have a stable reception ordering."""
    base = {k: v for k, v in result.items() if k != 'items'}
    if source or target:
        pair = tuple(sorted((source, target)))
        link = next((l for l in result['items'] if (l['source']['id'], l['target']['id']) == pair), None)
        if link is None:
            return dict(base, link=None, evidence=[], more=False)
        return dict(base, link={k: v for k, v in link.items() if k != 'evidence'},
                    evidence=link['evidence'][offset:offset + 100],
                    more=offset + 100 < len(link['evidence']))
    return dict(base, items=[{k: v for k, v in l.items() if k not in ('evidence', 'days', 'hours')}
                             for l in result['items']])
