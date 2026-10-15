"""Bounded, read-only browsing of individual TRACE receptions."""
import json
from onair_payload import decode_payload_details
from onair_trace import trace_sessions
from onair_neighbors import distance_km

BATCH = 500
PAGE = 50


def browse(db, start, end, before=9223372036854775807, first='', last='', hops=None):
    # Seek by kind/id; even restrictive filters inspect at most BATCH rows.
    rows = db.execute("""SELECT id,received,packet_json FROM packets
        WHERE kind='TRACE' AND id<? ORDER BY id DESC LIMIT ?""", (before, BATCH + 1)).fetchall()
    items = []
    consumed = 0
    for row_id, received, raw in rows[:BATCH]:
        consumed += 1
        before = row_id
        if not start <= received < end:
            continue
        packet = json.loads(raw)
        event = decode_payload_details(packet['decoded']).get('trace')
        if packet.get('direction') != 'rx' or not event:
            continue
        route = event['route']
        if ((first and (not route or route[0] != first))
                or (last and (not route or route[-1] != last))
                or (hops is not None and len(route) != hops)):
            continue
        items.append(dict(id=row_id, received=received, route=route,
                          observed_hops=len(event['snrs']), tag=event['tag']))
        if len(items) == PAGE:
            break
    return dict(items=items, scanned=consumed,
                before=before if len(rows) > consumed else None)


def detail(db, identity, positions):
    row = db.execute("SELECT id,received,packet_json FROM packets WHERE id=? AND kind='TRACE'", (identity,)).fetchone()
    if row is None:
        return None
    row_id, received, raw = row
    names = dict(db.execute('SELECT public_key,name FROM nodes'))
    sessions, _, _ = trace_sessions([(row_id, received, json.loads(raw))], names)
    if not sessions:
        return None
    item = sessions[0]
    item.update(source=None, target=None)
    for hop in item['hops']:
        pos = positions.at(hop['public_key'], received) if hop['public_key'] else None
        hop['position'] = pos if distance_km(pos, pos) is not None else None
    return item
