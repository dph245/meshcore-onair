import json
import sqlite3
import unittest
from onair_trace_map import browse, detail, grouped_snapshot, grouped_page
from onair_distance import Positions
from test_trace import reception


class TraceMapTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.executescript('''CREATE TABLE packets(id INTEGER PRIMARY KEY, received REAL, kind TEXT, packet_json TEXT);
            CREATE INDEX packets_kind_id ON packets(kind,id);
            CREATE TABLE nodes(public_key TEXT, name TEXT);''')
        self.addCleanup(self.db.close)
        self.a, self.b = 'aa' + '00'*31, 'bb' + '00'*31
        self.db.executemany('INSERT INTO nodes VALUES(?,?)', [(self.a, 'A'), (self.b, 'B')])

    def add(self, stamp, packet, kind='TRACE'):
        return self.db.execute('INSERT INTO packets(received,kind,packet_json) VALUES(?,?,?)',
                               (stamp, kind, json.dumps(packet))).lastrowid

    def advert(self, stamp, key, latitude):
        self.add(stamp, dict(decoded=dict(advert=dict(public_key=key, timestamp=stamp,
            latitude=latitude, longitude=10, signature_status='Gültig'))), 'ADVERT')

    def test_positions_missing_hops_and_alternative_routes(self):
        self.advert(1, self.a, 50)
        self.advert(1, self.b, 51)
        first = self.add(2, reception(snrs=(2, 3)))
        self.advert(3, self.a, 52)
        second = self.add(4, reception(route='aaccbb', snrs=(1, 2)))
        positions = Positions(self.db, 0, 10)
        full = detail(self.db, first, positions)
        partial = detail(self.db, second, positions)
        self.assertEqual(full['hops'][0]['position']['latitude'], 50)
        self.assertEqual(partial['hops'][0]['position']['latitude'], 52)
        self.assertIsNone(partial['hops'][1]['position'])
        self.assertIsNone(partial['hops'][2]['snr_min'])
        self.assertIsNone(full['source'])
        self.assertEqual(len(browse(self.db, 0, 10, first='aa', last='bb')['items']), 2)
        self.assertEqual(len(browse(self.db, 0, 10, hops=3)['items']), 1)
        self.assertEqual(len(browse(self.db, 3, 5)['items']), 1)
        self.assertEqual(browse(self.db, 0, 10, first='ff')['items'], [])

    def test_bounded_scan_and_pagination(self):
        self.db.executemany('INSERT INTO packets(received,kind,packet_json) VALUES(?,?,?)',
            [(i, 'TRACE', json.dumps(reception())) for i in range(1200)])
        page = browse(self.db, 0, 2000, first='cc')
        self.assertEqual(page['scanned'], 500)
        self.assertEqual(page['items'], [])
        seen = []
        cursor = 9223372036854775807
        while cursor:
            page = browse(self.db, 0, 2000, before=cursor)
            self.assertLessEqual(len(page['items']), 50)
            seen.extend(i['id'] for i in page['items'])
            cursor = page['before']
        self.assertEqual(len(seen), 1200)
        self.assertEqual(len(set(seen)), 1200)
        plan = str(self.db.execute("EXPLAIN QUERY PLAN SELECT id FROM packets WHERE kind='TRACE' AND id<? ORDER BY id DESC LIMIT 501", (9999,)).fetchall())
        self.assertIn('packets_kind_id', plan)

    def test_ambiguity_and_no_future_positions(self):
        self.db.execute('INSERT INTO nodes VALUES(?,?)', ('aa'+'11'*31, 'Collision'))
        identity = self.add(1, reception(snrs=(1,2)))
        self.advert(2, self.b, 51)
        item = detail(self.db, identity, Positions(self.db, 0, 10))
        self.assertTrue(item['hops'][0]['ambiguous'])
        self.assertTrue(all(h['position'] is None for h in item['hops']))

    def test_round_trip_snr_survives_decoder_archive_and_detail(self):
        from onair_payload import decode_payload_details
        self.advert(1, self.a, 50)
        self.advert(1, self.b, 51)
        # A -> B -> A: samples at B and the second A are separate directions.
        packet = reception(route='aabbaa', snrs=(12, 7.5, -3))
        decoded = decode_payload_details(packet['decoded'])['trace']
        self.assertEqual(decoded['route'], ['aa', 'bb', 'aa'])
        self.assertEqual(decoded['snrs'], [12, 7.5, -3])
        identity = self.add(2, packet)
        result = detail(self.db, identity, Positions(self.db, 0, 10))
        self.assertEqual([h['snr_min'] for h in result['hops']], [12, 7.5, -3])
        self.assertEqual([h['snr_max'] for h in result['hops']], [12, 7.5, -3])
        self.assertEqual(result['hops'][0]['public_key'], result['hops'][2]['public_key'])
        # Legacy archive decoding also retains both occurrences without mutation.
        packet['decoded'].pop('path_hex')
        packet['decoded']['hops'] = ['30', '1e', 'f4']
        packet['decoded'].pop('trace')
        legacy = self.add(3, packet)
        self.assertEqual([h['snr_min'] for h in detail(self.db, legacy, Positions(self.db, 0, 10))['hops']],
                         [12, 7.5, -3])

    def test_grouped_progress_and_single_representative(self):
        ids = []
        for i in range(10):
            ids.append(self.add(100 + i, reception(route='aabbaabbaa',
                snrs=tuple(range(min(5, i + 1))), observer='east' if i % 2 else 'west')))
        snapshot = grouped_snapshot(self.db, 0, 200)
        self.assertEqual(len(snapshot['items']), 1)
        group = snapshot['items'][0]
        self.assertEqual(group['receptions'], 10)
        self.assertEqual(len(group['observers']), 2)
        self.assertEqual(group['representative_id'], ids[-1])
        self.assertEqual(group['observed_hops'], 5)
        self.assertEqual(len(group['packets']), 10)
        self.assertEqual(grouped_page(snapshot)['items'], [group])
        # A partial, much weaker sample must not alter the representative's SNR.
        self.add(110, reception(route='aabbaabbaa', snrs=(-20,)))
        group = grouped_snapshot(self.db, 0, 200)['items'][0]
        self.assertEqual(group['weakest_snr'], -20)
        self.assertEqual(group['representative_id'], ids[-1])
        representative = detail(self.db, group['representative_id'], Positions(self.db, 0, 200))
        self.assertEqual([h['snr_min'] for h in representative['hops']], [0, 1, 2, 3, 4])

    def test_grouped_boundaries_filter_and_pagination(self):
        for i in range(120):
            self.add(100 + i, reception(tag=i))
        snapshot = grouped_snapshot(self.db, 0, 500)
        seen, cursor = [], 9223372036854775807
        while cursor is not None:
            page = grouped_page(snapshot, cursor)
            self.assertLessEqual(len(page['items']), 50)
            seen.extend(i['id'] for i in page['items'])
            cursor = page['before']
        self.assertEqual(len(set(seen)), 120)
        self.assertEqual(grouped_snapshot(self.db, 0, 500, first='cc')['items'], [])
        self.assertEqual(len(grouped_snapshot(self.db, 0, 500, hops=2)['items']), 120)
        self.db.executemany('INSERT INTO packets(received,kind,packet_json) VALUES(?,?,?)',
            [(i, 'TRACE', json.dumps(reception())) for i in range(5100)])
        bounded = grouped_snapshot(self.db, 0, 6000)
        self.assertEqual(bounded['scanned'], 5000)
        self.assertTrue(bounded['truncated'])

    def test_group_snapshot_cache_reuses_correlation(self):
        import threading
        from unittest.mock import patch
        from onair_archive import Archive
        from contextlib import nullcontext
        archive = Archive.__new__(Archive)
        archive._distance_lock = threading.Lock()
        archive.connect = lambda: nullcontext(self.db)
        for i in range(60):
            self.add(i, reception(tag=i))
        with patch('onair_trace_map.grouped_snapshot', wraps=grouped_snapshot) as build:
            first = archive.trace_map(0, 100, 9223372036854775807, '', '', None, grouped=True)
            second = archive.trace_map(0, 100, first['before'], '', '', None, grouped=True)
            self.assertEqual(len(first['items']), 50)
            self.assertEqual(len(second['items']), 10)
            self.assertEqual(build.call_count, 1)

    def test_api_validation(self):
        import asyncio
        from unittest.mock import patch
        from onair_web import app

        async def direct(fn, **kwargs):
            return fn(**kwargs)

        async def get(path, query=b''):
            sent = []
            async def receive():
                return {'type': 'http.request', 'body': b''}
            async def send(message):
                sent.append(message)
            await app({'type':'http', 'method':'GET', 'path':path,
                       'query_string':query, 'headers':[], 'scheme':'http',
                       'http_version':'1.1', 'root_path':''}, receive, send)
            return sent[0]['status']

        with patch('fastapi.routing.run_in_threadpool', direct):
            for query in (b'start=10&end=9', b'start=0&end=3000000',
                          b'start=0&end=10&first=xyz', b'start=0&end=10&hops=-1',
                          b'start=nan&end=10', b'start=0&end=10&before=0'):
                self.assertEqual(asyncio.run(get('/api/map-traces', query)), 422)
            self.assertEqual(asyncio.run(get('/api/map-traces/999999999999999999999999')), 422)
