"""Reception statistics for the immediate transmitter of flood packets."""
from datetime import datetime


def record_repeater(db, packet):
    d = packet['decoded']
    # A direct route contains a destination path, not a transmitter history.
    if packet.get('direction') != 'rx' or d['route_type'] not in (0, 1):
        return
    if d['hops']:
        token = d['hops'][-1]
    else:
        a = d.get('advert')
        if (not a or d.get('advert_status') or a.get('node_type') != 2
                or a.get('signature_status') != 'Gültig'):
            return
        token = a['public_key']
    db.execute('''INSERT INTO repeater_receptions
        VALUES(?,1,?,?,?,?) ON CONFLICT(token) DO UPDATE SET
        count=count+1,
        rssi=CASE WHEN excluded.last_seen >= last_seen THEN excluded.rssi ELSE rssi END,
        min_rssi=CASE WHEN min_rssi IS NULL THEN excluded.min_rssi
                     WHEN excluded.min_rssi IS NULL THEN min_rssi ELSE MIN(min_rssi,excluded.min_rssi) END,
        max_rssi=CASE WHEN max_rssi IS NULL THEN excluded.max_rssi
                     WHEN excluded.max_rssi IS NULL THEN max_rssi ELSE MAX(max_rssi,excluded.max_rssi) END,
        last_seen=MAX(last_seen,excluded.last_seen)''',
        (token, packet['rssi'], packet['rssi'], packet['rssi'],
         datetime.fromisoformat(packet['received_at']).timestamp()))


def repeater_summary(rows, names, label):
    rows = list(rows)
    # Use the longest known identifiers, including observed hops without ADVERTs.
    # Keep raw counters separate in SQLite so later collisions can be split again.
    candidates = set(names) | {row['token'] for row in rows}
    identities = []
    for candidate in sorted(candidates, key=lambda token: (-len(token), token)):
        if not any(identity.startswith(candidate) for identity in identities):
            identities.append(candidate)
    result = {}
    for row in rows:
        item = dict(row)
        token = item.pop('token')
        matches = [identity for identity in identities if identity.startswith(token)]
        identity = matches[0] if len(matches) == 1 else token
        item.update(id=identity, name=names.get(identity) or label(identity), tokens=[token])
        previous = result.get(identity)
        if previous:
            previous['count'] += item['count']
            previous['tokens'].append(token)
            for field, aggregate in (('min_rssi', min), ('max_rssi', max)):
                values = [v for v in (previous[field], item[field]) if v is not None]
                previous[field] = aggregate(values) if values else None
            if item['last_seen'] >= previous['last_seen']:
                previous.update(last_seen=item['last_seen'], rssi=item['rssi'])
        else:
            result[identity] = item
    return sorted(result.values(), key=lambda item: (item['name'].casefold(), item['id']))
