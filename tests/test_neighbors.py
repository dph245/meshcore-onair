import sqlite3
import json
import random
from concurrent.futures import ThreadPoolExecutor
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onair_archive import Archive
from onair_mqtt import build_packet
from onair_neighbors import distance_km, neighbor_summary


def packet(raw, **extra):
    return build_packet({'raw': raw, 'direction': 'rx', **extra})


class NeighborTests(unittest.TestCase):
    def test_distance_positions_and_geographic_edges(self):
        def position(lat, lon):
            return dict(latitude=lat, longitude=lon)
        self.assertAlmostEqual(distance_km(position(0, 1), position(0, 2)), 111.195, places=3)
        self.assertEqual(distance_km(position(52, 13), position(52, 13)), 0)
        self.assertAlmostEqual(distance_km(position(0, 179), position(0, -179)), 222.390, places=3)
        self.assertAlmostEqual(distance_km(position(0, 90), position(0, -90)), 20015.114, places=3)
        for invalid in [None, position(None, 13), position(52, None), position(0, 0),
                        position(91, 13), position(52, 181), position(float('nan'), 13)]:
            self.assertIsNone(distance_km(invalid, position(52, 13)))
            self.assertIsNone(distance_km(position(52, 13), invalid))

    def test_distance_requires_unambiguous_positioned_repeaters(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(Path(folder) / 'archive.db')
            archive.accept(packet('1502aabb'))
            archive.close()
            self.assertIsNone(archive.neighbors()['items'][0]['distance_km'])
            with archive.connect() as db, db:
                for key, lat, lon in [('aa' + '0' * 62, 52.52, 13.405),
                                      ('bb' + '0' * 62, 48.137, 11.575)]:
                    db.execute('''INSERT INTO nodes(public_key,advert_time,first_seen,last_seen,node_type,latitude,longitude)
                                  VALUES(?,1,1,1,2,?,?)''', (key, lat, lon))
            self.assertAlmostEqual(archive.neighbors()['items'][0]['distance_km'], 504.3, delta=0.2)
            with archive.connect() as db, db:
                db.execute('''INSERT INTO nodes(public_key,advert_time,first_seen,last_seen,node_type,latitude,longitude)
                              VALUES(?,1,1,1,2,50,10)''', ('aa' + '1' * 62,))
            self.assertIsNone(archive.neighbors()['items'][0]['distance_km'])

    def test_counts_only_adjacent_rx_flood_pairs_once_per_reception(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(Path(folder) / 'archive.db')
            for raw in ['1504aabb aacc'.replace(' ', ''), '1502bbaa',
                        '1502aabb', '1602aabb', '1501aa', '1502aaaa',
                        '140000000002aabb']:
                archive.accept(packet(raw))
            archive.accept(packet('1502aabb', direction='tx'))
            archive.close()
            links = archive.neighbors()['items']
            pairs = {(link['source']['id'], link['target']['id']): link['count'] for link in links}
            self.assertEqual(pairs, {('aa', 'bb'): 4, ('aa', 'cc'): 1})
            directions = {(link['source']['id'], link['target']['id']):
                          (link['forward_count'], link['reverse_count']) for link in links}
            self.assertEqual(directions, {('aa', 'bb'): (3, 2), ('aa', 'cc'): (1, 0)})
            import onair_web as web
            with patch.object(web.app.state, 'archive', archive, create=True):
                response = web.repeater_neighbors()
                self.assertEqual(json.loads(response.body)['items'], links)
                self.assertEqual(response.media_type, 'application/json')
            # Rebuild from historical packets, then restart without recounting.
            with sqlite3.connect(archive.path) as db:
                db.execute('DROP TABLE repeater_paths')
                db.execute('PRAGMA user_version=8')
            for _ in range(2):
                archive = Archive(archive.path)
                archive.close()
                self.assertEqual(archive.neighbors()['items'], links)

    def test_resolution_collision_and_known_non_repeater(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(Path(folder) / 'archive.db')
            for raw in ['1502aabb', '1542aabbccdd', '1582aabb01ccdd02']:
                archive.accept(packet(raw))
            archive.close()
            a, b = 'aabb01' + '0' * 58, 'ccdd02' + '0' * 58
            with sqlite3.connect(archive.path) as db:
                for key, name in [(a, 'A'), (b, 'B')]:
                    db.execute('INSERT INTO nodes(public_key,name,advert_time,first_seen,last_seen,node_type) VALUES(?,?,1,1,1,2)', (key, name))
            links = archive.neighbors()['items']
            known = next(link for link in links if link['target']['id'] == b)
            self.assertEqual(known['count'], 2)
            self.assertEqual((known['forward_count'], known['reverse_count']), (2, 0))
            self.assertTrue(known['source']['resolved'])
            # A later collision must separate the shorter tokens again.
            with sqlite3.connect(archive.path) as db:
                db.execute('INSERT INTO nodes(public_key,name,advert_time,first_seen,last_seen,node_type) VALUES(?,?,1,1,1,1)', ('aabb99' + '0' * 58, 'Companion'))
            links = archive.neighbors()['items']
            ambiguous = next(link for link in links if link['source']['id'] == 'aabb')
            self.assertTrue(ambiguous['source']['ambiguous'])
            self.assertFalse(ambiguous['source']['resolved'])
            self.assertEqual(ambiguous['count'], 1)
            with sqlite3.connect(archive.path) as db:
                db.execute('UPDATE nodes SET node_type=1 WHERE public_key=?', (b,))
            self.assertFalse(any(link['target']['id'] == b for link in archive.neighbors()['items']))

    def test_direction_loops_and_reverse_only(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(Path(folder) / 'archive.db')
            archive.accept(packet('1505aabbaabbaa'))
            archive.accept(packet('1502ddcc'))
            archive.close()
            links = {(link['source']['id'], link['target']['id']): link
                     for link in archive.neighbors()['items']}
            loop = links['aa', 'bb']
            self.assertEqual((loop['count'], loop['forward_count'], loop['reverse_count']), (1, 1, 1))
            reverse = links['cc', 'dd']
            self.assertEqual((reverse['count'], reverse['forward_count'], reverse['reverse_count']), (1, 0, 1))

    def test_pair_migration_uses_paths_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(Path(folder) / 'archive.db')
            archive.close()
            with archive.connect() as db, db:
                db.execute('DROP TABLE repeater_pairs')
                db.execute('PRAGMA user_version=10')
                # No packets: upgrading must use historical path counters.
                db.executemany('INSERT INTO repeater_paths VALUES(?,?,?,?)', [
                    (json.dumps(['aa', 'bb', 'aa', 'bb']), 7, 10, 20),
                    (json.dumps(['bb', 'aa']), 3, 5, 30)])
            for _ in range(2):
                archive = Archive(archive.path)
                archive.close()
                with archive.connect() as db:
                    queries = []
                    db.set_trace_callback(queries.append)
                    link, = neighbor_summary(db)['items']
                    self.assertFalse(any('repeater_paths' in query or 'packets' in query for query in queries))
                self.assertEqual((link['count'], link['forward_count'], link['reverse_count'],
                                  link['first_seen'], link['last_seen']), (10, 7, 10, 5, 30))

    def test_loop_only_tokens_still_create_collisions(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(Path(folder) / 'archive.db')
            for raw in ['1502aabb', '1542aa01aa01', '1542aa02aa02']:
                archive.accept(packet(raw))
            archive.close()
            link, = archive.neighbors()['items']
            self.assertEqual(link['source']['id'], 'aa')
            self.assertTrue(link['source']['ambiguous'])
            self.assertEqual(link['count'], 1)

    def test_random_paths_match_per_reception_counts_across_batches(self):
        rng = random.Random(42)
        expected = {}
        batch = []
        for i in range(300):
            hops = [rng.choice(['aa', 'bb', 'cc', 'dd']) for _ in range(rng.randrange(2, 20))]
            batch.append(packet('15' + format(len(hops), '02x') + ''.join(hops)).to_dict())
            directed = set(zip(hops, hops[1:]))
            for a, b in {tuple(sorted(pair)) for pair in directed if pair[0] != pair[1]}:
                counts = expected.setdefault((a, b), [0, 0, 0])
                counts[0] += 1
                counts[1] += (a, b) in directed
                counts[2] += (b, a) in directed
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(Path(folder) / 'archive.db')
            archive.close()
            with archive.connect() as db:
                for start in range(0, len(batch), 17):
                    archive._write(db, batch[start:start + 17])
            actual = {(link['source']['id'], link['target']['id']):
                      [link['count'], link['forward_count'], link['reverse_count']]
                      for link in archive.neighbors()['items']}
            self.assertEqual(actual, expected)
            before_failure = archive.neighbors()
            # A failed batch must roll back both paths and the new pair counters.
            with archive.connect() as db:
                with patch('onair_archive.record_path_pairs', side_effect=RuntimeError('failed')):
                    with self.assertRaises(RuntimeError):
                        archive._write(db, batch[:10])
                self.assertEqual(db.execute('SELECT SUM(count) FROM repeater_paths').fetchone()[0], 300)
            self.assertEqual(archive.neighbors(), before_failure)

    def test_shared_json_cache_refreshes_after_expiry(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(Path(folder) / 'archive.db')
            archive.accept(packet('1502aabb'))
            archive.close()
            with patch('onair_archive.time.monotonic', return_value=100) as clock, \
                    patch.object(archive, 'neighbors', wraps=archive.neighbors) as compute:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(lambda _: archive.neighbors_json(), range(16)))
                self.assertEqual(compute.call_count, 1)
                self.assertTrue(all(result is results[0] for result in results))
                self.assertEqual(json.loads(results[0])['items'][0]['count'], 1)
                with archive.connect() as db:
                    archive._write(db, [packet('1502aabb').to_dict()])
                clock.return_value = 129
                self.assertIs(archive.neighbors_json(), results[0])
                clock.return_value = 130
                self.assertEqual(json.loads(archive.neighbors_json())['items'][0]['count'], 2)
                self.assertEqual(compute.call_count, 2)

    def test_failed_refresh_can_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(Path(folder) / 'archive.db')
            archive.close()
            with patch.object(archive, 'neighbors', side_effect=[RuntimeError('failed'), {'items': []}]):
                with self.assertRaises(RuntimeError):
                    archive.neighbors_json()
                self.assertEqual(json.loads(archive.neighbors_json()), {'items': []})
