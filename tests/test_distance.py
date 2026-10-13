"""Historical direction, identity, geography and indexed-query regression tests."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo

from onair_archive import Archive
from onair_distance import (analyze, response, packet_identity, validate_window,
                            FLOOD_WHERE, AnalysisLimitError)
from onair_neighbors import record_path, record_path_pairs

A, B, C = [s.ljust(64, '0') for s in ('3134db', '3c4afc', 'bbccdd')]
START = datetime(2026, 9, 28, tzinfo=ZoneInfo('Europe/Berlin')).timestamp()


def packet(hops, t, payload='aaaa', route=1, direction='rx', kind='TEXT_MSG', hash_value='HASH'):
    return dict(received_at=datetime.fromtimestamp(t, ZoneInfo('Europe/Berlin')).isoformat(),
                direction=direction, observer_hash=hash_value, origin='Observer',
                decoded=dict(hops=hops, route_type=route, route_name='FLOOD' if route == 1 else 'DIRECT',
                             payload_type=9 if kind == 'TRACE' else 2, payload_name=kind,
                             payload_ver=0, payload_hex=payload, transport_code=None))


def add(db, p):
    t = datetime.fromisoformat(p['received_at']).timestamp()
    cursor = db.execute('INSERT INTO packets(received,kind,search_text,packet_json) VALUES(?,?,?,?)',
                       (t, p['decoded']['payload_name'], '', json.dumps(p)))
    record_path(db, p)
    record_path_pairs(db, [p])
    return cursor.lastrowid


def position(db, key, lat, lon, received, stamp=1):
    p = packet([], received, kind='ADVERT')
    p['decoded']['advert'] = dict(public_key=key, latitude=lat, longitude=lon,
                                 timestamp=stamp, signature_status='Gültig')
    add(db, p)


class DistanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.archive = Archive(Path(self.tmp.name) / 'archive.db')
        self.archive.close()
        self.db = sqlite3.connect(self.archive.path)
        self.addCleanup(self.db.close)
        for key, lat, lon in [(A, 50.456154, 12.64674), (B, 53.088157, 11.228116), (C, 50.45, 12.64)]:
            self.db.execute('INSERT INTO nodes VALUES(?,?,1,0,1,2,?,?,1)', (key, key[:6], lat, lon))
            position(self.db, key, lat, lon, START - 100)
        self.db.commit()

    def test_adjacent_direction_dedup_loops_and_exact_boundaries(self):
        # Same payload across observers, prefixes, days and absent hash: one content.
        for hops, t, payload in [(['3134', '3c4a'], START, 'aaaa'),
                                  (['3134db', '3c4afc'], START + 3600, 'aaaa'),
                                  (['3134db', '3c4afc'], START + 86400, 'aaaa'),
                                  (['3c4afc', '3134db'], START + 2, 'bbbb'),
                                  (['3134db', '3c4afc', '3134db', '3c4afc'], START + 3, 'cccc')]:
            add(self.db, packet(hops, t, payload))
        for extra in [dict(route=2), dict(direction='tx'), dict(kind='TRACE')]:
            add(self.db, packet(['3134db', '3c4afc'], START + 4, 'dddd', **extra))
        add(self.db, packet(['3134db', 'bbccdd', '3c4afc'], START + 4, 'eeee'))
        add(self.db, packet(['3134db', '3c4afc'], START + 2 * 86400, 'ffff'))
        result = analyze(self.db, START, START + 2 * 86400)
        link = next(l for l in result['items'] if l['source']['id'] == A and l['target']['id'] == B)
        self.assertEqual((link['receptions'], link['packets'], link['paths']), (5, 3, 4))
        self.assertEqual((link['forward_receptions'], link['reverse_receptions']), (4, 2))
        self.assertEqual((link['forward_packets'], link['reverse_packets']), (2, 2))
        self.assertEqual([d['forward'] for d in link['days']], [2, 0])
        self.assertEqual([d['forward_receptions'] for d in link['days']], [3, 1])
        self.assertEqual(link['hours'][1]['forward'], 0)
        self.assertEqual(link['hours'][1]['forward_receptions'], 1)
        self.assertAlmostEqual(link['distance_min_km'], 308.498, places=3)
        detail = response(result, A, B)
        self.assertEqual(len(detail['evidence']), 5)
        self.assertEqual(response(result, B, A), detail)
        self.assertNotIn('evidence', response(result)['items'][0])

    def test_collision_non_repeater_and_same_prefix_unknown_identity(self):
        add(self.db, packet(['3134', '3c4a'], START))
        self.db.execute('INSERT INTO nodes VALUES(?,?,1,0,1,1,NULL,NULL,NULL)', ('3134ff'.ljust(64, '0'), 'Companion'))
        self.assertEqual(analyze(self.db, START, START + 60)['items'], [])
        add(self.db, packet(['3134db', '3c4afc'], START + 1))
        self.assertEqual(len(analyze(self.db, START, START + 60)['items']), 1)
        self.db.execute("INSERT INTO repeater_receptions VALUES('3134dbff',1,NULL,NULL,NULL,0)")
        self.assertEqual(analyze(self.db, START, START + 60)['items'], [])

    def test_mobile_positions_no_future_position_or_interpolation(self):
        # B moves close before the window, despite its current nodes coordinates.
        position(self.db, B, 50.456, 12.647, START - 1, 2)
        add(self.db, packet(['3134db', '3c4afc'], START))
        self.assertEqual(analyze(self.db, START, START + 60)['items'], [])
        # A later position doesn't turn that earlier local hop into a distant hop.
        position(self.db, B, 53.088157, 11.228116, START + 10, 3)
        add(self.db, packet(['3134db', '3c4afc'], START + 11, 'bbbb'))
        result = analyze(self.db, START, START + 60)
        self.assertEqual(result['items'][0]['receptions'], 1)
        self.assertEqual(result['items'][0]['first_seen'], START + 11)
        # Nodes may since have moved close: formerly distant links must still appear.
        self.db.execute('UPDATE nodes SET latitude=50.456,longitude=12.647 WHERE public_key=?', (B,))
        self.assertEqual(analyze(self.db, START, START + 60)['items'][0]['receptions'], 1)

    def test_missing_or_invalid_historical_positions_are_not_filled_from_nodes(self):
        self.db.execute("DELETE FROM packets WHERE kind='ADVERT'")
        add(self.db, packet(['3134db', '3c4afc'], START))
        result = analyze(self.db, START, START + 60)
        self.assertEqual(result['items'], [])
        self.assertEqual(result['missing_position_pairs'], 1)
        position(self.db, A, 50, 12, START + 1)
        position(self.db, B, 53, 11, START + 1)
        result = analyze(self.db, START, START + 60)
        self.assertEqual(result['items'], [])
        self.assertEqual(result['missing_at_reception'], 1)

    def test_query_uses_partial_index_and_limit_rejects_incomplete_results(self):
        plan = self.db.execute(f"EXPLAIN QUERY PLAN SELECT id,received,packet_json FROM packets WHERE {FLOOD_WHERE} AND json_extract(packet_json,'$.decoded.hops')=? AND received>=? AND received<? ORDER BY received,id LIMIT 10", ('[]', START, START+60)).fetchall()
        self.assertIn('USING INDEX packets_flood_path_received', str(plan))
        for i in range(3): add(self.db, packet(['3134db', '3c4afc'], START + i, str(i)))
        with patch('onair_distance.MAX_RECEPTIONS', 2):
            with self.assertRaises(AnalysisLimitError): analyze(self.db, START, START + 60)

    def test_cache_reuses_scan_but_expires_and_paginates_evidence(self):
        for i in range(103): add(self.db, packet(['3134db', '3c4afc'], START + i))
        self.db.commit()
        import onair_archive
        with patch('onair_archive.analyze_distance', wraps=onair_archive.analyze_distance) as scan, \
                patch('onair_archive.time.monotonic', return_value=100) as clock:
            self.archive.distance_analysis(START, START + 200)
            self.assertTrue(self.archive.distance_analysis(START, START + 200, source=A, target=B)['more'])
            page = self.archive.distance_analysis(START, START + 200, source=A, target=B, offset=100)
            self.assertEqual(len(page['evidence']), 3)
            self.assertFalse(page['more'])
            self.assertEqual(scan.call_count, 1)
            clock.return_value = 221
            self.archive.distance_analysis(START, START + 200)
            self.assertEqual(scan.call_count, 2)

    def test_window_and_dst_bucket_semantics(self):
        for start, end, minimum in [(START, START, 200), (START, START+32*86400, 200),
                                    (float('nan'), START, 200), (START, START+60, 99)]:
            with self.assertRaises(ValueError): validate_window(start, end, minimum)
        zone = ZoneInfo('Europe/Berlin')
        start = datetime(2026, 10, 25, tzinfo=zone).timestamp()
        for fold, payload in [(0, 'aaaa'), (1, 'bbbb')]:
            t = datetime(2026, 10, 25, 2, 30, tzinfo=zone, fold=fold).timestamp()
            add(self.db, packet(['3134db', '3c4afc'], t, payload))
        l = analyze(self.db, start, start+25*3600)['items'][0]
        self.assertEqual(len(l['days']), 1)
        self.assertEqual(l['hours'][2]['forward'], 2)

    def test_identity_ignores_observer_and_path_not_payload_transport(self):
        p = packet(['aa', 'bb'], START)
        d = p['decoded']
        changed = copy.deepcopy(d); changed['hops'] = ['cc', 'dd']
        self.assertEqual(packet_identity(d), packet_identity(changed))
        for key, value in [('payload_hex','bbbb'),('payload_ver',1),('transport_code','11223344'),('payload_type',3)]:
            changed = dict(d, **{key:value})
            self.assertNotEqual(packet_identity(d), packet_identity(changed))


class DistanceApiTests(unittest.TestCase):
    def test_validation_and_errors(self):
        import asyncio
        from unittest.mock import Mock
        from onair_web import app
        archive = Mock()
        archive.distance_analysis.return_value = {'items': []}
        async def direct(fn, **kwargs): return fn(**kwargs)
        async def get(query):
            sent = []
            async def receive(): return {'type':'http.request', 'body':b''}
            async def send(message): sent.append(message)
            await app({'type':'http', 'method':'GET', 'path':'/api/repeater-neighbors/analysis',
                       'query_string':query.encode(), 'headers':[], 'scheme':'http',
                       'server':('test',80),'client':('test',1),'http_version':'1.1','root_path':''},receive,send)
            return sent
        with patch.object(app.state, 'archive', archive, create=True), \
                patch('fastapi.routing.run_in_threadpool', direct):
            for query in ('', 'start=nan&end=1', 'start=1&end=2&minimum=99',
                          'start=1&end=2&source=aa', f'start=1&end=2&source={A}',
                          f'start=1&end=2&source={A}&target={A}', 'start=1&end=2&offset=-1'):
                self.assertEqual(asyncio.run(get(query))[0]['status'], 422, query)
            self.assertEqual(asyncio.run(get('start=1&end=2'))[0]['status'], 200)
            archive.distance_analysis.assert_called_once_with(1.0,2.0,200,'','',0)
            archive.distance_analysis.side_effect = AnalysisLimitError('Zeitraum verkürzen')
            messages = asyncio.run(get('start=1&end=2'))
            self.assertEqual(messages[0]['status'], 422)
            self.assertIn('Zeitraum verkürzen', messages[1]['body'].decode())


if __name__ == '__main__': unittest.main()
