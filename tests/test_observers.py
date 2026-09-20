import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

import onair_mqtt as mqtt
from onair_archive import Archive
from onair_observers import reception_token
from onair_web import PacketStore


def packet(origin_id='east-id', origin='Ost', raw='1541dd4c', **extra):
    return mqtt.build_packet(dict(raw=raw, hash='SAME', direction='rx',
                                  origin_id=origin_id, origin=origin, **extra))


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'archive.sqlite3'

    def test_repeats_identity_labels_metrics_and_restart(self):
        archive = Archive(self.path)
        store = PacketStore()
        packets = [packet(RSSI=-100, SNR=7), packet(RSSI=-80, SNR=4),
                   packet('west-id', 'Ost', RSSI=-90, SNR=11.5),
                   packet(origin='Ost neu'), packet(None, 'Ost', RSSI=-50)]
        for p in packets:
            archive.accept(p)
            store.add(p)
        archive.close()
        self.assertEqual(len(store.groups), 1)
        self.assertEqual(next(iter(store.groups.values()))['count'], 5)
        self.assertEqual(len(next(iter(store.groups.values()))['receptions']), 5)
        archive = Archive(self.path)
        archive.close()
        data = archive.observer_comparison()
        observers = {o['origin_id']: o for o in data['observers']}
        self.assertEqual(observers['east-id']['origin'], 'Ost neu')
        self.assertEqual(observers['west-id']['origin'], 'Ost')
        self.assertEqual(observers[None]['count'], 1)
        self.assertEqual(len(data['items']), 1)
        node = data['items'][0]
        self.assertIn('Funkfeuer', node['name'])
        rx = {r['origin_id']: r for r in node['observers']}
        self.assertEqual((rx['east-id']['count'], rx['east-id']['best_rssi'], rx['east-id']['best_snr']), (3, -80, 7))
        self.assertEqual(rx['west-id']['best_snr'], 11.5)
        self.assertEqual(rx['east-id']['last_seen'], datetime.fromisoformat(packets[3].received_at).timestamp())
        self.assertEqual(len(archive.search()['items']), 5)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT origin_id,origin FROM packets ORDER BY id').fetchall(),
                             [(p.origin_id, p.origin) for p in packets])
        import onair_web as web
        with patch.object(web.app.state, 'archive', archive, create=True):
            self.assertEqual(web.compare_observers(), data)

    def test_schema5_backfill_and_idempotence(self):
        archive = Archive(self.path)
        archive.accept(packet())
        archive.close()
        legacy = packet().to_dict()
        legacy.pop('origin_id')
        legacy.pop('origin')
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE packets SET packet_json=?', (json.dumps(legacy),))
            db.execute('DROP INDEX packets_origin_id')
            db.execute('ALTER TABLE packets DROP COLUMN origin_id')
            db.execute('ALTER TABLE packets DROP COLUMN origin')
            db.execute('DROP TABLE observers')
            db.execute('DROP TABLE observer_receptions')
            db.execute('PRAGMA user_version=5')
        for _ in range(2):
            archive = Archive(self.path)
            archive.close()
            data = archive.observer_comparison()
            self.assertEqual(data['observers'][0]['origin_id'], None)
            self.assertEqual(data['items'][0]['observers'][0]['count'], 1)
            self.assertEqual(len(archive.search()['items']), 1)

    def test_prefix_resolution_shared_across_observers_and_collisions(self):
        archive = Archive(self.path)
        for p in [packet(raw='1501dd'), packet('west-id', raw='1541dd4c'),
                  packet(raw='1541aabb'), packet('west-id', raw='1581aabb01'),
                  packet('west-id', raw='1581aabb02')]:
            archive.accept(p)
        archive.close()
        items = {i['id']: i for i in archive.observer_comparison()['items']}
        self.assertEqual(set(items), {'dd4c', 'aabb', 'aabb01', 'aabb02'})
        self.assertEqual(len(items['dd4c']['observers']), 2)
        self.assertIsNone(items['dd4c']['observers'][0]['best_snr'])

    def test_only_identifiable_immediate_transmitters(self):
        for raw in ['1641dd4c', '170000000041dd4c', '1500']:
            self.assertIsNone(reception_token(packet(raw=raw).to_dict()))
        self.assertIsNone(reception_token(dict(packet().to_dict(), direction='tx')))
        for node_type in [1, 2, 3, 4]:
            p = packet(raw='1100').to_dict()
            p['decoded'].update(advert_status=None, advert=dict(public_key='ab'*32,
                node_type=node_type, signature_status='Gültig'))
            self.assertEqual(reception_token(p), 'ab'*32)
            p['decoded']['advert']['signature_status'] = 'Ungültig'
            self.assertIsNone(reception_token(p))
        self.assertIsNone(packet(origin_id=123).origin_id)
        self.assertIsNone(packet(origin_id=' ').origin_id)
