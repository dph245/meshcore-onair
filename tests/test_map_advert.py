import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from onair_archive import Archive
from onair_mqtt import build_packet


def advert(key, name):
    prefix = key.public_key().public_bytes_raw() + (123).to_bytes(4, 'little')
    data = b'\x82' + name.encode()
    return build_packet({'raw': '1100' + (prefix + key.sign(prefix + data) + data).hex(), 'direction': 'rx'})


class MapAdvertTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'archive.sqlite3'

    def test_advert_path_latest_rx_and_migration(self):
        key = Ed25519PrivateKey.generate()
        packet = advert(key, 'Sender').to_dict()
        packet['decoded']['advert'].update(latitude=52, longitude=10)
        packet['origin'] = '<Observer>'
        packet['decoded']['hops'] = ['abcd', 'ee']
        packet['received_at'] = '2026-09-28T10:00:00+00:00'
        archive = Archive(self.path)
        archive.close()
        with archive.connect() as db:
            archive._write(db, [packet])
            packet['received_at'] = '2026-09-28T09:00:00+00:00'
            packet['decoded']['hops'] = []
            archive._write(db, [packet])
            packet['received_at'] = '2026-09-28T11:00:00+00:00'
            packet['direction'] = 'tx'
            archive._write(db, [packet])
            for public_key, name in [('abcd00', '<Relay>'), ('ee00', 'A'), ('ee11', 'B')]:
                db.execute('INSERT INTO nodes(public_key,name,advert_time,first_seen,last_seen) VALUES(?,?,0,0,0)',
                           (public_key, name))
            db.commit()
        with patch('onair_archive.time.time', return_value=1790600000):
            result = archive.map_nodes()
        path = result['items'][0]['advert_path']
        self.assertEqual(path['origin'], '<Observer>')
        self.assertEqual(path['hops'], [
            dict(token='abcd', name='<Relay>', resolved=True, ambiguous=False),
            dict(token='ee', name=None, resolved=False, ambiguous=True)])
        with archive.connect() as db, db:
            db.execute('DROP TABLE node_advert_paths')
            db.execute('PRAGMA user_version=9')
        archive = Archive(self.path)
        archive.close()
        with patch('onair_archive.time.time', return_value=1790600000):
            self.assertEqual(archive.map_nodes(), result)
        packet['direction'] = 'rx'
        with archive.connect() as db:
            archive._write(db, [packet])
        with patch('onair_archive.time.time', return_value=1790600000):
            self.assertEqual(archive.map_nodes()['items'][0]['advert_path']['hops'], [])
        packet['decoded']['route_type'] = 2
        with archive.connect() as db:
            archive._write(db, [packet])
        with patch('onair_archive.time.time', return_value=1790600000):
            self.assertIsNone(archive.map_nodes()['items'][0]['advert_path']['hops'])

