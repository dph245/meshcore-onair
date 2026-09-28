import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onair_archive import Archive
from onair_mqtt import build_packet
from onair_trace import trace_sessions
from onair_web import app


def reception(tag=1, route='aabb', snrs=(), auth=0, flags=0, observer='east', direction='rx'):
    payload = tag.to_bytes(4, 'little') + auth.to_bytes(4, 'little') + bytes([flags]) + bytes.fromhex(route)
    raw = bytes([0x26, len(snrs)]) + bytes(round(snr * 4) & 255 for snr in snrs) + payload
    return build_packet(dict(raw=raw.hex(), direction=direction, origin_id=observer,
                             origin=observer)).to_dict()


class TraceTests(unittest.TestCase):
    def test_partial_repeated_reordered_receptions_and_history(self):
        rows = [(3, 1003, reception(snrs=(-3, 5), observer='west')),
                (1, 1001, reception(snrs=(-2,))),
                (2, 1002, reception(snrs=(-2,))),
                (0, 1000, reception()),
                (4, 1010, reception(tag=2, snrs=(-1, 7)))]
        items, histories, ignored = trace_sessions(rows, {'aa' + '00' * 31: 'A'})
        self.assertEqual(ignored, 0)
        self.assertEqual(len(items), 2)
        first = items[-1]
        self.assertEqual(first['receptions'], 4)
        self.assertEqual(first['observed_hops'], 2)
        self.assertEqual(first['hops'][0]['name'], 'A')
        self.assertEqual((first['hops'][0]['snr_min'], first['hops'][0]['snr_max']), (-3, -2))
        self.assertEqual(first['weakest_snr'], -3)
        self.assertEqual(first['weakest_hops'], [1])
        self.assertEqual({o['id'] for o in first['observers']}, {'east', 'west'})
        self.assertEqual(len(histories), 1)
        self.assertEqual(histories[0]['point_count'], 2)
        self.assertEqual([p['snr_min'] for p in histories[0]['points']], [[-3, 5], [-1, 7]])

    def test_separate_tag_auth_route_scope_and_fixed_window(self):
        scoped = reception()
        scoped['decoded'].update(route_type=3, transport_code='11223344')
        packets = [reception(), reception(tag=2), reception(auth=1),
                   reception(route='aacc'), scoped, reception()]
        rows = [(i, 1000 + i if i < 5 else 1061, p) for i, p in enumerate(packets)]
        items, histories, _ = trace_sessions(rows, {})
        self.assertEqual(len(items), 6)
        self.assertEqual(len(histories), 3)
        self.assertTrue(all(item['weakest_snr'] is None for item in items))
        self.assertEqual(items[0]['hops'][0]['snr_min'], None)

    def test_ambiguous_hashes_loops_equal_minima_and_invalid_packets(self):
        names = {'aa' + '00' * 31: 'A', 'aa' + '11' * 31: 'B'}
        bad = reception()
        bad['decoded']['payload_hex'] = '00'
        future = reception()
        future['decoded']['payload_ver'] = 1
        rows = [(0, 1, reception(route='aaaa', snrs=(-4, -4))),
                (1, 2, bad), (2, 3, future), (3, 4, reception(direction='tx'))]
        items, _, ignored = trace_sessions(rows, names)
        self.assertEqual(ignored, 3)
        self.assertEqual(items[0]['weakest_hops'], [1, 2])
        self.assertTrue(all(hop['ambiguous'] and hop['name'] is None for hop in items[0]['hops']))

    def test_bounded_history_keeps_count(self):
        rows = [(i, i, reception(tag=i, snrs=(-1,))) for i in range(205)]
        _, histories, _ = trace_sessions(rows, {})
        self.assertEqual(histories[0]['point_count'], 205)
        self.assertEqual(len(histories[0]['points']), 200)
        self.assertEqual(histories[0]['points'][0]['time'], 5)

    def test_archive_old_packets_and_api_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(Path(folder) / 'test.sqlite3')
            archive.close()
            old = reception(snrs=(-2,))
            for key in ('trace', 'path_hex'):
                old['decoded'].pop(key)
            old['decoded']['hops'] = ['f8']
            with archive.connect() as db:
                archive._write(db, [old, reception(tag=2)])
                db.execute('UPDATE packets SET received=10000')
                db.commit()

            async def endpoint(fn, **kwargs):
                return fn(**kwargs)

            async def get(query):
                sent = []
                async def receive():
                    return {'type': 'http.request', 'body': b''}
                async def send(message):
                    sent.append(message)
                await app({'type': 'http', 'method': 'GET', 'path': '/api/traces',
                           'query_string': query, 'headers': [], 'scheme': 'http',
                           'http_version': '1.1', 'root_path': ''}, receive, send)
                return sent

            with patch('onair_archive.time.time', return_value=10002), \
                    patch.object(app.state, 'archive', archive, create=True), \
                    patch('fastapi.routing.run_in_threadpool', endpoint):
                messages = asyncio.run(get(b'hours=1&limit=1'))
                self.assertEqual(messages[0]['status'], 200)
                result = json.loads(messages[1]['body'])
                self.assertEqual(result['scanned'], 2)
                self.assertTrue(result['more_sessions'])
                self.assertEqual(result['histories'][0]['points'][0]['snr_min'], [-2, None])
                for query in (b'hours=0', b'hours=169', b'limit=101', b'limit=0'):
                    self.assertEqual(asyncio.run(get(query))[0]['status'], 422)
                with patch('onair_archive.time.time', return_value=20000):
                    self.assertEqual(archive.traces(hours=1)['items'], [])
            with archive.connect() as db:
                self.assertNotIn('trace', json.loads(db.execute(
                    'SELECT packet_json FROM packets ORDER BY id LIMIT 1').fetchone()[0])['decoded'])
