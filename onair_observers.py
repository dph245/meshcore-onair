"""Per-observer statistics; raw receptions remain in the packet archive."""
from datetime import datetime
from onair_repeaters import repeater_summary


def reception_token(packet):
    d = packet['decoded']
    if packet.get('direction') != 'rx' or d['route_type'] not in (0, 1):
        return None
    if d['hops']:
        return d['hops'][-1]
    a = d.get('advert')
    if a and not d.get('advert_status') and a.get('signature_status') == 'Gültig':
        return a['public_key']
    return None


def record_observer(db, packet):
    if packet.get('direction') != 'rx':
        return
    # Empty ID represents legacy/unassigned data, never a label-derived identity.
    identity = packet.get('origin_id') or ''
    received = datetime.fromisoformat(packet['received_at']).timestamp()
    db.execute('''INSERT INTO observers(origin_id,origin,last_seen,count) VALUES(?,?,?,1)
        ON CONFLICT(origin_id) DO UPDATE SET
        origin=CASE WHEN excluded.last_seen >= last_seen AND excluded.origin IS NOT NULL
                    THEN excluded.origin ELSE origin END,
        last_seen=MAX(last_seen,excluded.last_seen), count=count+1''',
        (identity, packet.get('origin'), received))
    token = reception_token(packet)
    if token is None:
        return
    db.execute('''INSERT INTO observer_receptions VALUES(?,?,1,?,?,?)
        ON CONFLICT(token,origin_id) DO UPDATE SET count=count+1,
        best_rssi=CASE WHEN best_rssi IS NULL THEN excluded.best_rssi
                      WHEN excluded.best_rssi IS NULL THEN best_rssi ELSE MAX(best_rssi,excluded.best_rssi) END,
        best_snr=CASE WHEN best_snr IS NULL THEN excluded.best_snr
                     WHEN excluded.best_snr IS NULL THEN best_snr ELSE MAX(best_snr,excluded.best_snr) END,
        last_seen=MAX(last_seen,excluded.last_seen)''',
        (token, identity, packet.get('rssi'), packet.get('snr'), received))


def observer_comparison(db):
    from onair_mqtt import node_label
    observers = [dict(origin_id=key or None, origin=name if key else None,
                      last_seen=seen, count=count)
                 for key, name, seen, count in db.execute(
                     'SELECT origin_id,origin,last_seen,count FROM observers ORDER BY origin_id')]
    rows = [dict(token=token, origin_id=key, count=count, best_rssi=rssi,
                 best_snr=snr, last_seen=seen)
            for token, key, count, rssi, snr, seen in db.execute('SELECT * FROM observer_receptions')]
    names = dict(db.execute('SELECT public_key,name FROM nodes'))
    # Resolve across ALL observers together, preserving ambiguous prefixes.
    tokens = {row['token'] for row in rows}
    identities = repeater_summary([dict(token=t, count=0, rssi=None, min_rssi=None,
                                       max_rssi=None, last_seen=0) for t in tokens], names, node_label)
    by_token = {}
    for item in identities:
        item['observers'] = []
        # Manual aliases take precedence, as in the packet views.
        label = node_label(item['id'])
        if label != item['id']:
            item['name'] = label
        for token in item['tokens']:
            by_token[token] = item
        for field in ('count', 'rssi', 'min_rssi', 'max_rssi', 'last_seen'):
            del item[field]
    for row in rows:
        item = by_token[row.pop('token')]
        row['origin_id'] = row['origin_id'] or None
        previous = next((r for r in item['observers'] if r['origin_id'] == row['origin_id']), None)
        if previous is None:
            item['observers'].append(row)
        else:
            previous['count'] += row['count']
            for field in ('best_rssi', 'best_snr', 'last_seen'):
                values = [v for v in (previous[field], row[field]) if v is not None]
                previous[field] = max(values) if values else None
    return {'observers': observers, 'items': sorted(identities, key=lambda i: (i['name'].casefold(), i['id']))}
