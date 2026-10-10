"""Bounded, read-only MeshLive replay snapshot. No archive writes or background work."""
import json
import time
from datetime import datetime, timezone

WINDOW_SECONDS = 600
MAX_EVENTS = 5000
MAX_SEED_ADVERTS = 2000
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_INPUT_BYTES = 16 * 1024 * 1024
QUERY_SECONDS = 3
NODE_COLUMNS = ('public_key', 'name', 'node_type', 'advert_time', 'latitude',
                'longitude', 'position_time', 'first_seen', 'last_seen')


class ReplayLimitError(ValueError):
    pass


def compact_packet(raw, received):
    """Keep exactly the fields consumed by MeshLive, without re-decoding payloads."""
    packet = json.loads(raw)
    decoded = packet['decoded']
    result = {key: packet.get(key) for key in ('direction', 'observer_hash', 'origin_id')}
    result['received_at'] = datetime.fromtimestamp(received, timezone.utc).isoformat()
    result['decoded'] = {key: decoded.get(key) for key in (
        'route_type', 'payload_type', 'payload_ver', 'payload_hex',
        'transport_code', 'hops', 'advert_status')}
    advert = decoded.get('advert')
    if isinstance(advert, dict):
        result['decoded']['advert'] = {key: advert.get(key) for key in (
            'public_key', 'name', 'node_type', 'timestamp', 'latitude',
            'longitude', 'signature_status')}
    return result


def replay_response(connect):
    end = time.time()
    start = end - WINDOW_SECONDS
    deadline = time.monotonic() + QUERY_SECONDS
    response_size, input_size = 4096, 0

    def encode(value):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')

    def charge(value):
        nonlocal response_size
        response_size += len(encode(value)) + 1
        if response_size > MAX_RESPONSE_BYTES:
            raise ReplayLimitError('Replay überschreitet das Antwortlimit von 4 MiB. Es wurde nichts abgeschnitten.')
        return value

    def decode(raw, received):
        nonlocal input_size
        input_size += len(raw.encode('utf-8'))
        if input_size > MAX_INPUT_BYTES:
            raise ReplayLimitError('Zu viele Archivdaten für einen begrenzten Replay-Abruf. Bitte später erneut versuchen.')
        return compact_packet(raw, received)

    with connect() as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        latest = db.execute('SELECT received FROM packets ORDER BY received DESC LIMIT 1').fetchone()
        events = []
        for packet_id, received, raw in db.execute('''SELECT id,received,packet_json FROM packets
                WHERE received>=? AND received<? ORDER BY received,id LIMIT ?''',
                                                  (start, end, MAX_EVENTS + 1)):
            if len(events) == MAX_EVENTS:
                raise ReplayLimitError('Mehr als 5.000 Empfänge in zehn Minuten. Replay wurde nicht gestartet; es wurde nichts abgeschnitten.')
            events.append(charge(dict(id=packet_id, received=received, packet=decode(raw, received))))

        nodes, uncertain = [], set()
        for row in db.execute('SELECT ' + ','.join(NODE_COLUMNS) + ' FROM nodes'):
            node = dict(zip(NODE_COLUMNS, row))
            # The device's position_time alone cannot prove when we learned a position.
            if node['last_seen'] >= start:
                uncertain.add(node['public_key'])
                node.update(name=None, node_type=None, advert_time=-1, latitude=None,
                            longitude=None, position_time=None, last_seen=0)
            nodes.append(charge(node))
        tokens = [charge(row[0]) for row in db.execute('''SELECT token FROM repeater_receptions
            UNION SELECT source FROM repeater_pairs UNION SELECT target FROM repeater_pairs''')]

        seeds, scanned, seed_limited = [], 0, False
        if uncertain:
            # Limit inspected rows BEFORE time filtering: even clock jumps or an empty
            # historical interval cannot cause an unbounded ADVERT scan.
            for packet_id, received, raw in db.execute('''SELECT id,received,packet_json FROM packets
                    WHERE kind='ADVERT' ORDER BY id DESC LIMIT ?''', (MAX_SEED_ADVERTS + 1,)):
                if scanned == MAX_SEED_ADVERTS:
                    seed_limited = True
                    break
                scanned += 1
                if not start - 28 * 86400 < received < start:
                    continue
                packet = decode(raw, received)
                d = packet['decoded']
                advert = d.get('advert')
                if (packet['direction'] != 'rx' or not advert or d.get('advert_status') or
                        advert.get('signature_status') != 'Gültig' or advert.get('public_key') not in uncertain):
                    continue
                # Position learning is shared with the frontend's live model. Safe
                # snapshot nodes must NOT be overwritten by older seed ADVERTs.
                seed = {'direction': 'rx', 'received_at': packet['received_at'],
                        'decoded': {'advert': advert, 'advert_status': None}}
                seeds.append((received, packet_id, charge(seed)))
        seeds.sort(key=lambda row: (row[0], row[1]))
        db.set_progress_handler(None, 0)

    body = encode(dict(window_start=start, window_end=end, speed=10,
                       archive_latest_received=latest[0] if latest else None,
                       events=events,
                       bootstrap=dict(nodes=nodes, tokens=tokens, seed_packets=[row[2] for row in seeds]),
                       seed_adverts_scanned=scanned, seed_scan_limited=seed_limited))
    if len(body) > MAX_RESPONSE_BYTES:
        raise ReplayLimitError('Replay überschreitet das Antwortlimit von 4 MiB. Es wurde nichts abgeschnitten.')
    return body
