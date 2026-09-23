import sqlite3
import json
from concurrent.futures import ThreadPoolExecutor
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onair_archive import Archive
from onair_mqtt import build_packet


def packet(raw, **extra):
    return build_packet({'raw': raw, 'direction': 'rx', **extra})


class NeighborTests(unittest.TestCase):
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
