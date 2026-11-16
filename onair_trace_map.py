"""Bounded, read-only browsing of individual TRACE receptions."""
import json
from onair_payload import decode_payload_details
from onair_trace import trace_sessions
from onair_neighbors import distance_km
from onair_map_visibility import MapVisibility

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
    nodes = [dict(public_key=key, name=name, node_type=kind)
             for key, name, kind in db.execute('SELECT public_key,name,node_type FROM nodes')]
    manual = [dict(public_key=row[0]) for row in db.execute('SELECT public_key FROM manual_nodes')]
    visibility = MapVisibility(nodes, manual)
    names = {node['public_key']: node['name'] for node in nodes}
    types = {node['public_key']: node['node_type'] for node in nodes}
    sessions, _, _ = trace_sessions([(row_id, received, json.loads(raw))], names)
    if not sessions:
        return None
    item = sessions[0]
    item.update(source=None, target=None, map_repeater_keys=visibility.repeater_keys)
    for hop in item['hops']:
        hop['node_type'] = types.get(hop['public_key'])
        pos = (positions.at(hop['public_key'], received)
               if hop['public_key'] and not visibility.hidden(hop['public_key'], hop['node_type']) else None)
        hop['position'] = pos if distance_km(pos, pos) is not None else None
    return item


def grouped_snapshot(db, start, end, first='', last='', hops=None):
    """Bounded snapshot using the SAME correlation as the TRACE analysis tab."""
    rows = db.execute("""SELECT id,received,packet_json FROM packets
        WHERE kind='TRACE' AND received>=? AND received<?
        ORDER BY id DESC LIMIT 5001""", (start, end)).fetchall()
    names = dict(db.execute('SELECT public_key,name FROM nodes'))
    sessions, _, ignored = trace_sessions(
        [(identity, stamp, json.loads(raw)) for identity, stamp, raw in rows[:5000]], names, include_packets=True)
    items = []
    for session in sessions:
        route = [hop['hash'] for hop in session['hops']]
        if ((first and (not route or route[0] != first))
                or (last and (not route or route[-1] != last))
                or (hops is not None and len(route) != hops)):
            continue
        items.append(session)
    return dict(items=items, scanned=min(len(rows), 5000), ignored=ignored,
                truncated=len(rows) > 5000, grouped=True)


def grouped_page(snapshot, before=9223372036854775807):
    offset = 0 if before == 9223372036854775807 else before
    items = snapshot['items'][offset:offset + PAGE]
    return dict(snapshot, items=items, total=len(snapshot['items']),
                before=offset + PAGE if offset + PAGE < len(snapshot['items']) else None)
