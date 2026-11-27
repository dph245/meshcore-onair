"""Bounded, read-only browsing of individual TRACE receptions."""
import json
from onair_payload import decode_payload_details
from onair_trace import trace_sessions
from onair_trace_history import Identities, load_locations, locate

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


def detail(db, identity, *, position_cache=None):
    row = db.execute("SELECT id,received,packet_json FROM packets WHERE id=? AND kind='TRACE'", (identity,)).fetchone()
    if row is None:
        return None
    row_id, received, raw = row
    packet = json.loads(raw)
    identities = Identities(db)
    names = {key: node['name'] for key, node in identities.nodes.items()}
    sessions, _, _ = trace_sessions([(row_id, received, packet)], names)
    if not sessions:
        return None
    item = sessions[0]
    item.update(source=None, target=None, map_repeater_keys=identities.visibility.repeater_keys)
    nodes = [identities.resolve(bytes.fromhex(hop['hash'])) for hop in item['hops']]
    locations = load_locations(db, nodes, position_cache, include_non_repeaters=True)
    stamp = packet.get('source_at')
    if stamp is None:
        stamp = received
    sample_times = {}
    if db.execute('PRAGMA user_version').fetchone()[0] >= 18:
        sample_times = dict(db.execute('''SELECT s.hop,s.event_at FROM trace_observation o
            JOIN trace_sample s USING(measurement_id) WHERE o.packet_id=?''', (row_id,)))
    for index, (hop, node) in enumerate(zip(item['hops'], nodes)):
        hop.update(node)
        measured_at = sample_times.get(index, stamp)
        hop['position'], hop['location_issue'] = locate(node, locations, measured_at)
        if index and hop['snr_min'] is not None:
            hop['from_position'], hop['from_location_issue'] = locate(nodes[index - 1], locations, measured_at)
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
