"""Synthetic local identity archives: no MQTT, production DB or external APIs."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from onair_archive import Archive
from onair_neighbors import distance_km
from onair_prefix_explorer import WOLFENBUETTEL

NOW = 1800000000
A = '777300' + 'a' * 58
B = '777300' + 'b' * 58
C = '777301' + 'c' * 58
D = '777400' + 'd' * 58
E = 'ab1200' + 'e' * 58


class PrefixExplorerTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.archive = Archive(Path(folder) / 'archive.db')
        self.archive.close()
        self.explorer = self.archive.prefix_explorer
        self.enterContext(patch('onair_prefix_explorer.time.time', return_value=NOW))

    def add(self, key, seen=NOW, lat=52.164, lon=10.540, kind=2):
        with self.archive.connect() as db, db:
            db.execute('INSERT OR REPLACE INTO nodes VALUES(?,?,?,?,?,?,?,?,?)',
                       (key, '<Name>', 1, seen, seen, kind, lat, lon, 1))
        self.explorer.expires = 0

    def receive(self, token, seen=NOW):
        with self.archive.connect() as db, db:
            db.execute('INSERT OR REPLACE INTO repeater_receptions VALUES(?,?,?,?,?,?)',
                       (token, 9999, -90, -100, -80, seen))
        self.explorer.expires = 0

    def test_distinct_and_collisions_all_levels(self):
        for key in (A, B, C, D, E):
            self.add(key)
        # A full key plus a short token still denotes one identity.
        self.receive(A)
        self.receive('ab')
        data = self.explorer.query(prefix=A[:6])
        self.assertEqual(data['total'], 5)
        self.assertEqual([l['count'] for l in data['levels']], [4, 3, 2])
        self.assertEqual([s['collisions'] for s in data['statistics']], [1,1,1])
        self.assertEqual(data['items'][0]['unique_prefix'], A[:8])
        self.assertEqual(self.explorer.query(prefix='ab')['items'][0]['unique_prefix'], 'ab')
        self.assertEqual(len(data['cells']), 256)

    def test_periods_inclusive_cutoff_and_all(self):
        for days in (7,30,60,90):
            with self.subTest(days=days):
                self.add(A, NOW-days*86400)
                self.add(E, NOW-days*86400-.001)
                self.assertEqual(self.explorer.query(days=days)['total'], 1)
                self.assertEqual(self.explorer.query(days=0)['total'], 2)

    def test_tokens_never_create_identity_and_ambiguity_uses_all_history(self):
        self.add(A, NOW-100*86400)
        self.add(B, NOW-100*86400)
        self.add(E, NOW-100*86400)
        self.add('ab12', kind=2)
        self.add('cd'*32, kind=1)
        self.receive('777300')
        self.receive('fefe')
        self.receive('ab12')  # incomplete node excluded, E is the only full identity
        self.receive('xyz')
        self.assertEqual(self.explorer.query()['total'], 1)
        self.receive(A)
        self.assertEqual(self.explorer.query()['total'], 2)

    def test_missing_position_distance_and_hidden_old_collision(self):
        self.add(A)
        self.add(B, NOW-100*86400)
        self.add(C, lat=None, lon=None)
        self.add(E)
        data = self.explorer.query(prefix='77')
        self.assertEqual({r['position_status'] for r in data['items']}, {'Verborgen','Unbekannt'})
        self.assertTrue(all(r['distance_km'] is None for r in data['items']))
        self.assertNotIn(A, [r['public_key'] for r in data['references']])
        self.assertEqual(self.explorer.query(prefix='77', radius=25)['matched'], 0)
        with self.assertRaises(ValueError):
            self.explorer.query(reference=A)
        self.assertAlmostEqual(self.explorer.query(prefix='ab')['items'][0]['distance_km'], 0)
        london = dict(latitude=51.5074, longitude=-.1278)
        paris = dict(latitude=48.8566, longitude=2.3522)
        self.assertAlmostEqual(distance_km(london, paris), 343.557, delta=.1)
        self.assertIsNone(distance_km(WOLFENBUETTEL, dict(latitude=0, longitude=0)))
        self.assertNotIn('latitude', str(data))

    def test_large_snapshot_no_packet_reads_bounded_response_cache_and_paging(self):
        with self.archive.connect() as db, db:
            db.executemany('INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?)',
                ((f'77{i:062x}', 'large', 1, NOW, NOW, 2, None, None, None) for i in range(12000)))
        statements = []
        original = self.explorer.connect
        from contextlib import contextmanager
        @contextmanager
        def traced():
            with original() as db:
                db.set_trace_callback(statements.append)
                yield db
        self.explorer.connect = traced
        started = time.perf_counter()
        data = self.explorer.query(prefix='77')
        self.assertEqual(data['total'], 12000)
        self.assertEqual(len(data['items']), 100)
        self.assertEqual(data['next_offset'], 100)
        self.assertEqual(len(data['cells']), 256)
        count = len(statements)
        page = self.explorer.query(prefix='77', offset=100)
        self.assertEqual(len(statements), count)
        self.assertNotEqual(page['items'][0], data['items'][0])
        self.assertFalse(any('packets' in sql.lower() for sql in statements))
        self.assertLess(time.perf_counter()-started, 5)

    def test_repeated_real_packet_projection(self):
        from test_replay import packet, advert
        with self.archive.connect() as db:
            self.archive._write(db, [packet(NOW-i, advert(A)) for i in range(4)])
        self.assertEqual(self.explorer.query()['total'], 1)
        self.assertEqual(self.explorer.query(prefix='77')['levels'][0]['count'], 1)
        with self.archive.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM packets').fetchone()[0], 4)

    def test_normalization_distance_sort_and_reference(self):
        self.add(E.upper(), lat=53, lon=10.54)
        self.add(E, lat=53, lon=10.54)
        self.add(D, lat=52.164, lon=10.540)
        self.add(C, lat=None, lon=None)
        data = self.explorer.query(prefix='77', sort='distance', reference=E)
        self.assertEqual(data['total'], 3)
        self.assertEqual(data['items'][-1]['public_key'], C)
        self.assertGreater(data['items'][0]['distance_km'], 90)
        self.assertEqual(self.explorer.query(prefix='77', radius=25)['matched'], 1)
        self.assertEqual(self.explorer.query(prefix='77', radius=25)['items'][0]['public_key'], D)
        # Manual-only entries without observations never count.
        with self.archive.connect() as db, db:
            db.execute('INSERT INTO manual_nodes VALUES(?,?,?,?,?,?,?)',
                       ('ee'*32, 'Manual', 52, 10, 'local', NOW, NOW))
        self.explorer.expires = 0
        self.assertEqual(self.explorer.query()['total'], 3)

    def test_http_parameters_validation_and_privacy(self):
        import asyncio
        from test_archive_http import get
        from onair_web import app
        self.add(A)
        self.add(B, NOW-100*86400)
        async def check():
            with patch.object(app.state, 'archive', self.archive, create=True):
                for days in (0,7,30,60,90):
                    status, result = await get('/api/prefix-explorer', days=days, prefix='777300', radius=0)
                    self.assertEqual(status, 200)
                    self.assertEqual(result['levels'][-1]['count'], 2 if days == 0 else 1)
                    self.assertIsNone(result['items'][0]['distance_km'])
                for params in (dict(days=1), dict(radius=12), dict(prefix='xyz'),
                               dict(sort='bad'), dict(offset=-1), dict(reference=A)):
                    status, result = await get('/api/prefix-explorer', **params)
                    self.assertEqual(status, 422)
        asyncio.run(check())

    def test_validation(self):
        for prefix in ('7', '777', 'gg', '12 34', '12345678'):
            with self.assertRaises(ValueError):
                self.explorer.query(prefix=prefix)
        for options in (dict(days=1), dict(radius=1), dict(reference=A), dict(sort='bad')):
            with self.assertRaises(ValueError):
                self.explorer.query(**options)


if __name__ == '__main__':
    unittest.main()
