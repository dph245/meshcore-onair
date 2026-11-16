"""Synthetic archives only: collision policy and all geographic data sources."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from onair_archive import Archive
from onair_map_visibility import MapVisibility
from test_replay import packet, advert, START, END, A, B
from test_trace import reception


COLLISION = A[:6] + 'f' * 58


class MapVisibilityTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.archive = Archive(Path(folder) / 'test.db')
        self.archive.close()
        self.enterContext(patch('onair_archive.time.time', return_value=END))

    def write(self, *packets):
        with self.archive.connect() as db:
            self.archive._write(db, packets)

    def test_unique_duplicate_case_and_other_node_types(self):
        node = lambda key, kind=2: dict(public_key=key, node_type=kind)
        policy = MapVisibility([node(A), node(A.upper()), node(COLLISION, 1)])
        self.assertFalse(policy.hidden(A))
        self.assertEqual(policy.repeater_keys, [A])
        policy = MapVisibility([node(A.upper()), node(COLLISION), node(B)])
        self.assertTrue(policy.hidden(A))
        self.assertTrue(policy.hidden(COLLISION.upper()))
        self.assertFalse(policy.hidden(B))
        for kind in (0, 1, 3, 4):
            self.assertFalse(policy.hidden(A, kind))

    def test_repeated_adverts_and_new_historical_collision_preserve_archive(self):
        self.write(packet(START - 1, advert()), packet(START, advert()),
                   packet(START + 1, advert(B)))
        self.assertEqual({n['public_key'] for n in self.archive.map_nodes()['items']}, {A, B})
        # An older, positionless identity still suppresses the current location.
        self.write(packet(START - 40 * 86400, advert(COLLISION, latitude=None)))
        with self.archive.connect() as db:
            before = list(db.iterdump())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM packets').fetchone()[0], 4)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM nodes').fetchone()[0], 3)
        result = self.archive.map_nodes()
        self.assertEqual([n['public_key'] for n in result['items']], [B])
        self.assertTrue(all('Hash-Präfix-Kollision' in n['unavailable']
                            for n in result['repeaters'] if n['public_key'] != B))
        bootstrap = self.archive.mesh_live_nodes()
        self.assertEqual(len(bootstrap['nodes']), 3)
        self.assertEqual(bootstrap['map_repeater_keys'], result['map_repeater_keys'])
        with patch('onair_replay.time.time', return_value=END):
            replay = json.loads(self.archive.mesh_live_replay())
        self.assertEqual(replay['bootstrap']['map_repeater_keys'], result['map_repeater_keys'])
        self.assertEqual(len(replay['events']), 2)
        with self.archive.connect() as db:
            self.assertEqual(list(db.iterdump()), before)

    def test_same_prefix_companion_room_and_sensor_remain_visible(self):
        self.write(packet(START, advert()))
        for kind in (1, 3, 4):
            a = advert(A[:6] + f'{kind:058x}')
            a['node_type'] = kind
            self.write(packet(START, a))
        self.assertEqual(len(self.archive.map_nodes()['items']), 4)
        self.write(packet(START, advert(COLLISION)))
        self.assertEqual({n['node_type'] for n in self.archive.map_nodes()['items']}, {1, 3, 4})

    def test_trace_cached_positions_and_all_position_modes_obey_policy(self):
        self.write(packet(START - 1, advert()), packet(START - 1, advert(B)))
        trace = reception(route=A[:2] + B[:2], snrs=(2, 3))
        trace['received_at'] = packet(START)['received_at']
        self.write(trace)
        with self.archive.connect() as db:
            identity = db.execute("SELECT id FROM packets WHERE kind='TRACE'").fetchone()[0]
        initial = self.archive.trace_map_detail(identity)
        self.assertTrue(all(h['position'] for h in initial['hops']))
        # Manual reference identities participate, without changing TRACE's name resolver.
        with self.archive.connect() as db, db:
            db.execute('INSERT INTO manual_nodes VALUES(?,?,?,?,?,?,?)',
                       (COLLISION, 'Reference', 55, 12, 'test', START, START))
        with self.archive.connect() as db:
            before = list(db.iterdump())
        for mode in ('legacy', 'compare', 'normalized'):
            self.archive.position_mode = mode
            item = self.archive.trace_map_detail(identity)
            self.assertIsNone(item['hops'][0]['position'])
            self.assertIsNotNone(item['hops'][1]['position'])
            self.assertEqual([h['snr_min'] for h in item['hops']], [2, 3])
            self.assertIn(COLLISION, item['map_repeater_keys'])
            self.assertIsNone(self.archive.position_failure)
        with self.archive.connect() as db:
            self.assertEqual(list(db.iterdump()), before)
        self.assertIsNotNone(initial['hops'][0]['position'])

    def test_map_policy_reuses_loaded_nodes_without_packet_scan(self):
        self.write(packet(START, advert()), packet(START, advert(COLLISION)))
        with self.archive.connect() as db, db:
            db.execute('DROP TABLE packets')
        self.assertEqual(self.archive.map_nodes()['items'], [])
        self.assertEqual(len(self.archive.mesh_live_nodes()['map_repeater_keys']), 2)
