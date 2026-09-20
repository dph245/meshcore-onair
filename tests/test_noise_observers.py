import contextlib
import io
import json
from types import SimpleNamespace
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onair_archive import Archive
from onair_mqtt import noise_sample, handle_status, on_message
from onair_web import Dashboard


def sample(identity, value=-112, name='Observer'):
    return noise_sample({'origin_id': identity, 'origin': name, 'stats': {'noise_floor': value}})


class NoiseObserverTests(unittest.TestCase):
    def test_metadata_validation_and_terminal_separation(self):
        self.assertEqual(sample('east')['origin_id'], 'east')
        self.assertNotIn('origin_id', sample(' '))
        self.assertNotIn('origin_id', sample(123))
        self.assertIsNone(sample('east', float('nan')))
        output = io.StringIO()
        with patch('onair_mqtt.last_noise_floor', {}), contextlib.redirect_stdout(output):
            for identity in ('east', 'west', 'east', 'west'):
                handle_status({'origin_id': identity, 'stats': {'noise_floor': -112}})
        self.assertEqual(output.getvalue().count('STATUS'), 2)

    def test_retained_source_timestamp_survives_delivery_archive_and_restart(self):
        data = {'origin_id': 'C0CADC', 'origin': 'Old observer',
                'timestamp': '2026-09-15T18:44:14.000000', 'stats': {'noise_floor': -104}}
        captured = []
        with patch('onair_mqtt.handle_status'):
            on_message(None, {'status_sink': captured.append}, SimpleNamespace(
                topic='meshcore/test/status', payload=json.dumps(data).encode(), retain=True))
        self.assertTrue(captured[0]['_mqtt_retained'])
        reading = noise_sample(captured[0])
        self.assertEqual(reading['status_at'], '2026-09-15T18:44:14+00:00')
        self.assertNotEqual(reading['received_at'], reading['status_at'])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'noise.db'
            archive = Archive(path)
            archive.accept_noise(reading)
            archive.close()
            # Exercise an actual schema-7 upgrade with an existing measurement.
            with sqlite3.connect(path) as db:
                db.execute('ALTER TABLE noise_samples DROP COLUMN status_at')
                db.execute('PRAGMA user_version=7')
            archive = Archive(path)
            archive.accept_noise(reading)
            archive.close()
            archive = Archive(path)
            archive.close()
            restored = Dashboard(archive).status()['noise_observers'][0]
            self.assertEqual(restored['status_at'], reading['status_at'])
            self.assertEqual(len(archive.noise_history()), 2)
        for timestamp in (None, '', 'invalid', 123):
            self.assertIsNone(noise_sample(dict(data, timestamp=timestamp, _mqtt_retained=True)))
            self.assertIsNotNone(noise_sample(dict(data, timestamp=timestamp, _mqtt_retained=False)))
        aware = noise_sample(dict(data, timestamp='2026-09-15T20:44:14+02:00'))
        self.assertEqual(aware['status_at'], '2026-09-15T20:44:14+02:00')

    def test_live_buffers_are_independent_and_snapshot_immutable(self):
        dashboard = Dashboard()
        dashboard.accept_status({'origin_id': 'west', 'origin': 'Same', 'stats': {'noise_floor': -120}})
        for i in range(502):
            dashboard.accept_status({'origin_id': 'east', 'origin': 'Same', 'stats': {'noise_floor': -100}})
        before = dashboard.status()
        self.assertEqual(len(before['noise_history']), 501)
        latest = {s['origin_id']: s for s in before['noise_observers']}
        self.assertEqual(latest['west']['noise_floor'], -120)
        self.assertEqual(latest['east']['noise_floor'], -100)
        self.assertIsNone(before['noise_floor'])
        dashboard.accept_status({'origin_id': 'east', 'origin': 'New name', 'stats': {'noise_floor': -105}})
        self.assertEqual(latest['east']['noise_floor'], -100)
        self.assertEqual(len(dashboard.status()['noise_observers']), 2)
        self.assertEqual(dashboard.status()['noise_observers'][1]['origin'], 'New name')

    def test_schema6_migration_restarts_and_per_observer_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.db'
            archive = Archive(path)
            old = {'received_at': '2026-09-01T00:00:00+00:00', 'noise_floor': -111}
            archive.accept_noise(old)
            archive.close()
            with sqlite3.connect(path) as db:
                db.execute('DROP INDEX noise_origin_id')
                db.execute('ALTER TABLE noise_samples DROP COLUMN origin_id')
                db.execute('ALTER TABLE noise_samples DROP COLUMN origin')
                db.execute('PRAGMA user_version=6')
            archive = Archive(path)
            for identity, value, name in [('west', -120, 'Same'), ('east', -110, 'Same'),
                                          ('east', -109, 'Same'), ('east', -108, 'Renamed')]:
                archive.accept_noise(sample(identity, value, name))
            archive.close()
            for _ in range(2):
                archive = Archive(path)
                archive.close()
                readings = archive.noise_history(limit=2)
                self.assertEqual(len(readings), 4)
                self.assertEqual(readings[0], old)
                self.assertEqual([s['noise_floor'] for s in readings if s.get('origin_id') == 'east'], [-109, -108])
                restored = Dashboard(archive).status()['noise_observers']
                self.assertEqual(len(restored), 3)
                self.assertEqual({s.get('origin_id'): s['noise_floor'] for s in restored},
                                 {None: -111, 'east': -108, 'west': -120})
                with sqlite3.connect(path) as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM noise_samples').fetchone()[0], 5)
