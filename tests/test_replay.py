"""Replay snapshots must stay bounded, read-only and free of future positions."""
import asyncio
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from onair_archive import Archive
from onair_mqtt import build_packet
from onair_replay import ReplayLimitError
from onair_web import app

END = 1791666000
START = END - 600
A, B, C = (prefix.ljust(64, '0') for prefix in ('aabbcc', 'bbccdd', 'ccddee'))


def packet(at, advert=None):
    p = build_packet({'raw': '1542aabbbbcceeff', 'direction': 'rx', 'hash': 'ABCD', 'origin_id': C}).to_dict()
    p['received_at'] = datetime.fromtimestamp(at, timezone.utc).isoformat()
    if advert:
        p['decoded'].update(payload_type=4, payload_name='ADVERT', advert=advert, advert_status=None)
    return p


def advert(key=A, stamp=100, latitude=52, signature='Gültig'):
    return dict(public_key=key, timestamp=stamp, name=f'Node {stamp}', node_type=2,
                latitude=latitude, longitude=10 if latitude is not None else None,
                signature_status=signature)


class ReplayTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.archive = Archive(Path(folder) / 'test.db')
        self.archive.close()
        self.enterContext(patch('onair_replay.time.time', return_value=END))

    def write(self, *packets):
        with self.archive.connect() as db:
            self.archive._write(db, packets)

    def result(self):
        return json.loads(self.archive.mesh_live_replay())

    def test_bounds_order_stable_ids_projection_and_no_writes(self):
        self.write(packet(START-1), packet(START+20), packet(START), packet(START+20), packet(END))
        with self.archive.connect() as db:
            before = '\n'.join(db.iterdump())
        result = self.result()
        self.assertEqual(result['window_start'], START)
        self.assertEqual(result['window_end'], END)
        self.assertEqual(result['speed'], 10)
        self.assertEqual([e['id'] for e in result['events']], [3, 2, 4])
        p = result['events'][0]['packet']
        self.assertNotIn('number', p)
        self.assertNotIn('raw_hex', p)
        self.assertNotIn('group_text', p['decoded'])
        self.assertEqual(p['decoded']['hops'], ['aabb', 'bbcc'])
        self.assertEqual(p['origin_id'], C)
        with self.archive.connect() as db:
            self.assertEqual('\n'.join(db.iterdump()), before)
            query = db.execute('EXPLAIN QUERY PLAN SELECT id,received,packet_json FROM packets '
                               'WHERE received>=? AND received<? ORDER BY received,id LIMIT 5001', (START, END)).fetchall()
        self.assertTrue(any('packets_received' in row[3] for row in query))
        self.assertFalse(any('TEMP B-TREE' in row[3] for row in query))

    def test_historical_seed_never_uses_future_snapshot_or_device_timestamp_alone(self):
        self.write(packet(START-50, advert(A, 100, 51)),
                   packet(START-40, advert(B, 100, 52)),
                   packet(START+20, advert(A, 200, 54)),
                   packet(START+30, advert(C, 10, 55)))
        result = self.result()
        nodes = {n['public_key']: n for n in result['bootstrap']['nodes']}
        self.assertIsNone(nodes[A]['latitude'])
        self.assertIsNone(nodes[C]['latitude'], 'Old device timestamp is NOT proof of old reception')
        self.assertEqual(nodes[B]['latitude'], 52)
        seeds = result['bootstrap']['seed_packets']
        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0]['decoded']['advert']['public_key'], A)
        self.assertEqual(seeds[0]['decoded']['advert']['latitude'], 51)
        self.assertTrue(all(datetime.fromisoformat(p['received_at']).timestamp() < START for p in seeds))
        # Future ADVERT is only a timed event, never a seed.
        self.assertEqual(result['events'][0]['packet']['decoded']['advert']['latitude'], 54)

    def test_seed_order_no_coordinates_bad_signatures_and_limited_scan(self):
        self.write(packet(START-40, advert(A, 100, 51)), packet(START-30, advert(A, 200, None)),
                   packet(START-20, advert(A, 300, 60, 'Ungültig')),
                   packet(START+10, advert(A, 400, 54)))
        result = self.result()
        self.assertEqual([p['decoded']['advert']['timestamp'] for p in result['bootstrap']['seed_packets']], [100, 200])
        with patch('onair_replay.MAX_SEED_ADVERTS', 2):
            result = self.result()
        self.assertTrue(result['seed_scan_limited'])
        self.assertEqual(result['seed_adverts_scanned'], 2)
        self.assertEqual(result['bootstrap']['seed_packets'], [])
        self.assertIsNone(result['bootstrap']['nodes'][0]['latitude'])

    def test_packet_limit_rejects_instead_of_truncating(self):
        self.write(packet(START), packet(START+1), packet(START+2))
        with patch('onair_replay.MAX_EVENTS', 2), self.assertRaises(ReplayLimitError):
            self.result()

    def test_input_and_response_byte_limits(self):
        self.write(packet(START))
        with patch('onair_replay.MAX_INPUT_BYTES', 10), self.assertRaises(ReplayLimitError):
            self.result()
        with patch('onair_replay.MAX_RESPONSE_BYTES', 4100), self.assertRaises(ReplayLimitError):
            self.result()

    def test_empty_window_and_archive_watermark(self):
        result = self.result()
        self.assertEqual(result['events'], [])
        self.assertIsNone(result['archive_latest_received'])
        self.write(packet(START-100))
        result = self.result()
        self.assertEqual(result['events'], [])
        self.assertEqual(result['archive_latest_received'], START-100)

    def test_sql_query_only_and_consistent_snapshot(self):
        original = self.archive.connect
        statements = []
        @contextmanager
        def checked():
            with original() as db:
                db.set_trace_callback(statements.append)
                yield db
        with patch.object(self.archive, 'connect', checked):
            self.result()
        self.assertIn('PRAGMA query_only=ON', statements)
        self.assertIn('BEGIN', statements)
        self.assertFalse(any(s.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER')) for s in statements))

    def test_http_errors_no_store_and_fixed_window(self):
        async def direct(fn, **kwargs):
            return fn(**kwargs)
        async def get(method='GET'):
            sent = []
            async def receive():
                return {'type':'http.request', 'body':b''}
            async def send(message):
                sent.append(message)
            await app({'type':'http', 'method':method, 'path':'/api/meshlive/replay',
                       'query_string':b'limit=999999&window=999999', 'headers':[], 'scheme':'http',
                       'server':('test',80), 'client':('test',1), 'http_version':'1.1', 'root_path':''}, receive, send)
            return sent
        with patch.object(app.state, 'archive', self.archive, create=True), patch('fastapi.routing.run_in_threadpool', direct):
            response = asyncio.run(get())
            self.assertEqual(response[0]['status'], 200)
            self.assertEqual(dict(response[0]['headers'])[b'cache-control'], b'no-store')
            result = json.loads(response[1]['body'])
            self.assertEqual(result['window_end']-result['window_start'], 600)
            self.assertEqual(asyncio.run(get('POST'))[0]['status'], 405)
            with patch.object(self.archive, 'mesh_live_replay', side_effect=ReplayLimitError('Limit')):
                self.assertEqual(asyncio.run(get())[0]['status'], 413)
            with patch.object(self.archive, 'mesh_live_replay', side_effect=sqlite3.OperationalError('private path')):
                response = asyncio.run(get())
                self.assertEqual(response[0]['status'], 503)
                self.assertNotIn(b'private path', response[1]['body'])
