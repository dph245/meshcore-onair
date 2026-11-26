import asyncio
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from onair_archive import Archive
from onair_mqtt import build_packet, noise_sample, on_message
from onair_observer_radio import radio_report
from onair_web import Dashboard


BASE = datetime(2026, 11, 26, 12, tzinfo=timezone.utc).timestamp()
EAST = 'AB' * 32
WEST = 'CD' * 32
CORE = dict(frequency_hz=869618000, bandwidth_hz=62500, spreading_factor=8, coding_rate=8)


def mqtt_timestamp(seconds):
    return datetime.fromtimestamp(BASE + seconds, timezone.utc).isoformat()


def status(seconds=0, sf=8, **fields):
    return dict(timestamp=mqtt_timestamp(seconds), status='online', origin='Mesh',
                origin_id=EAST, radio=f'869.618000,62.5,{sf},8') | fields


class RadioNormalizationTests(unittest.TestCase):
    def test_gessaman_and_openhop_wire_formats(self):
        gessaman = status(timestamp='2026-11-26T13:00:00+01:00', model='Heltec V3',
                          firmware_version='v1.14', client_version='meshcore/v1.14')
        report = radio_report(gessaman, BASE + 1)
        self.assertEqual(report.origin_id, EAST.lower())
        self.assertEqual(report.reported_at, BASE)
        self.assertEqual(report.parameters, dict(CORE, firmware='MeshCore', firmware_version='v1.14'))
        openhop = status(origin_id=WEST.lower(), model='openHop-Repeater', firmware_version='1.0',
                         client_version='openhop_repeater/1.0', radio='869.618,62.50,11,5',
                         timestamp='2026-11-26T12:00:00', _mqtt_topic='meshcore/repeater/Name/status')
        report = radio_report(openhop, BASE + 1)
        self.assertEqual(report.origin_id, WEST.lower())
        self.assertEqual(report.reported_at, BASE)
        self.assertEqual(report.parameters,
                         dict(CORE, spreading_factor=11, coding_rate=5, firmware='openHop Repeater',
                              firmware_version='1.0'))

    def test_explicit_units_and_missing_or_invalid_fields(self):
        payload = status(radio=dict(frequency_hz='869618000', bandwidth_hz=62500.0,
                       spreading_factor='7', coding_rate='4/8', tx_power_dbm=-3,
                       preamble_length='12', sync_word='0x1424', radio_ic='SX1262'),
                         firmware='Example', firmware_version='1')
        self.assertEqual(radio_report(payload, BASE + 1).parameters,
                         dict(CORE, spreading_factor=7, tx_power_dbm=-3, preamble_length=12,
                              sync_word=0x1424, radio_ic='SX1262', firmware='Example', firmware_version='1'))
        invalid = dict(frequency_hz=float('inf'), bandwidth_hz=0, spreading_factor=True,
                       coding_rate='4/9', tx_power_dbm=2.5, preamble_length=-1,
                       sync_word='0x10000', radio_ic='\ud800', frequency=869.618)
        self.assertIsNone(radio_report(status(radio=invalid), BASE + 1))
        self.assertIsNone(radio_report(status(radio=None), BASE + 1))
        self.assertIsNone(radio_report(status(radio='869.618,62.5,8'), BASE + 1))
        partial = radio_report(status(radio='bad,62.5,4,4/7'), BASE + 1)
        self.assertEqual(partial.parameters, dict(bandwidth_hz=62500, coding_rate=7))

    def test_identity_timestamp_and_retained_validation(self):
        topic = f'meshcore/HAN/{EAST}/status'
        self.assertIsNone(radio_report(status(origin_id=WEST, _mqtt_topic=topic), BASE))
        self.assertEqual(radio_report(status(origin_id=None, _mqtt_topic=topic), BASE).origin_id,
                         EAST.lower())
        no_id = status(origin_id=None, _mqtt_topic=topic, stats=dict(noise_floor=-115))
        self.assertEqual(noise_sample(no_id)['origin_id'], EAST.lower())
        self.assertIsNone(radio_report(status(origin_id=None, _mqtt_topic='meshcore/repeater/Name/status'), BASE))
        self.assertIsNone(radio_report(status(origin_id=' ', origin='Same'), BASE))
        self.assertIsNone(radio_report(status(status='offline'), BASE))
        self.assertIsNone(radio_report(status(1000), BASE))
        for unusable in (None, '', 'invalid', '2026-11-26', '1970-01-01T01:00:00Z'):
            with self.subTest(unusable=unusable):
                self.assertIsNone(radio_report(status(timestamp=unusable, _mqtt_retained=True), BASE))
                self.assertIsNone(radio_report(status(timestamp=unusable), BASE).reported_at)


class RadioArchiveTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(folder) / 'archive.sqlite3'
        self.archive = Archive(self.path)
        self.addCleanup(lambda: self.archive.close())

    def receive(self, seconds, sf=8, retain=False, receipt=None, **fields):
        data = status(seconds, sf, **fields)
        report = radio_report(dict(data, _mqtt_retained=retain),
                              BASE + (seconds + 1 if receipt is None else receipt))
        self.archive.accept_observer_status(None, report)

    def history(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('''SELECT observed_at, detected_at, last_confirmed_at, transition_after
                FROM observer_radio_history WHERE origin_id=? ORDER BY observed_at''',
                              (EAST.lower(),)).fetchall()

    def test_repeated_status_and_partial_confirmation_preserve_fields(self):
        self.receive(0)
        self.receive(10, radio='869.6180,62.50,8,4/8')
        self.receive(10, radio=dict(spreading_factor=8))  # Duplicate source time.
        self.receive(20, radio=dict(spreading_factor=8, frequency_hz='invalid'))
        self.receive(30, radio=None)  # No radio or firmware evidence.
        self.archive.close()
        self.assertEqual(self.history(), [(BASE, BASE + 1, BASE + 20, None)])
        current, = self.archive.observer_radio_status()
        self.assertEqual(current['profile'], CORE)
        self.assertEqual(current['field_times']['spreading_factor'], BASE + 20)
        self.assertEqual(current['field_times']['frequency_hz'], BASE + 10)
        for t in (0, 10):
            self.assertEqual(self.archive.observer_radio_at(EAST, BASE + t)['match'], 'confirmed')
        self.assertEqual(self.archive.observer_radio_at(EAST, BASE + 20)['match'], 'last_known')
        self.assertEqual(self.archive.saved, 0)

    def test_switches_transition_gaps_and_parallel_observers_across_restart(self):
        self.receive(0)
        self.receive(10)
        self.receive(15, radio=dict(bandwidth_hz=62500))
        self.receive(20, 7, receipt=24)
        self.receive(5, 11, origin_id=WEST)
        self.archive.close()
        self.archive = Archive(self.path)
        self.assertEqual({p['origin_id']: p['profile']['spreading_factor']
                          for p in self.archive.observer_radio_status()}, {EAST.lower(): 7, WEST.lower(): 11})
        self.receive(30, 7)
        self.receive(40, 8)
        self.archive.close()
        self.assertEqual(self.history(), [(BASE, BASE + 1, BASE + 15, None),
                                         (BASE + 20, BASE + 24, BASE + 30, BASE + 10),
                                         (BASE + 40, BASE + 41, BASE + 40, BASE + 30)])
        for second, match, sf, reason in [
            (-1, 'unknown', None, 'no_observation'),
            (0, 'confirmed', 8, None), (5, 'last_known', 8, None),
            (10, 'confirmed', 8, None), (15, 'unknown', None, 'transition'),
            (20, 'confirmed', 7, None), (25, 'last_known', 7, None),
            (35, 'unknown', None, 'transition'), (40, 'confirmed', 8, None),
            (45, 'last_known', 8, None),
        ]:
            with self.subTest(second=second):
                result = self.archive.observer_radio_at(EAST, BASE + second)
                self.assertEqual(result['match'], match)
                self.assertEqual(result.get('profile', {}).get('spreading_factor'), sf)
                self.assertEqual(result.get('reason'), reason)
                self.assertIsNone(result.get('known_valid_from'))
        self.assertEqual(self.archive.observer_radio_at(EAST, BASE + 20)['detected_at'], BASE + 24)
        self.assertEqual(self.archive.observer_radio_at(WEST, BASE + 21)['profile']['spreading_factor'], 11)

    def test_retained_late_and_conflicting_status(self):
        self.receive(0, 8, retain=True, receipt=120)
        self.receive(0, 8, retain=True, receipt=125)
        self.receive(10, 7, receipt=130)
        self.receive(10, 8, retain=True, receipt=135)  # Retained replay cannot contradict live state.
        self.receive(10, 9, receipt=140)  # Two live observations with the same source time.
        self.receive(10, 9, receipt=141)
        self.receive(5, 8, receipt=150)
        self.receive(7, 8, retain=True, receipt=155)
        self.receive(160, 7, retain=True, timestamp=None)
        self.archive.close()
        self.assertEqual(self.history(), [(BASE, BASE + 120, BASE, None),
                                         (BASE + 10, BASE + 130, BASE + 10, BASE)])
        self.assertEqual(self.archive.observer_radio_at(EAST, BASE)['match'], 'confirmed')
        self.assertEqual(self.archive.observer_radio_at(EAST, BASE + 10),
                         dict(match='unknown', reason='conflicting_status'))
        self.assertTrue(self.archive.observer_radio_status()[0]['ambiguous'])
        self.archive = Archive(self.path)
        self.assertTrue(self.archive.observer_radio_status()[0]['ambiguous'])
        self.receive(170, radio=dict(bandwidth_hz=62500))
        self.archive.close()
        self.assertTrue(self.archive.observer_radio_status()[0]['ambiguous'])
        self.archive = Archive(self.path)
        self.receive(180, 7)
        self.archive.close()
        self.assertFalse(self.archive.observer_radio_status()[0]['ambiguous'])
        self.assertEqual(self.archive.observer_radio_at(EAST, BASE + 179)['reason'], 'conflicting_status')
        self.assertEqual(self.archive.observer_radio_at(EAST, BASE + 180)['match'], 'confirmed')
        self.assertEqual(len(self.history()), 2)

    def test_migration_preserves_packet_noise_and_neighbor_data(self):
        self.archive.accept(build_packet(dict(direction='rx', origin_id=EAST, raw='1500')))
        self.archive.accept_noise(dict(noise_floor=-115, received_at=mqtt_timestamp(0), origin_id=EAST))
        self.archive.close()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO rf_neighbor_messages VALUES (1,'old','x','x',X'1122',0,0,0,NULL,NULL)")
            db.execute('DROP TABLE observer_radio_history')
            db.execute('DROP TABLE observer_radio_conflicts')
            db.execute('PRAGMA user_version=16')
            raw = db.execute('SELECT packet_json FROM packets').fetchone()
        self.archive = Archive(self.path)
        self.assertEqual(self.archive.observer_radio_status(), [])
        self.receive(5)
        self.archive.close()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 17)
            self.assertEqual(db.execute('SELECT packet_json FROM packets').fetchone(), raw)
            self.assertEqual(db.execute('SELECT noise_floor FROM noise_samples').fetchone(), (-115,))
            self.assertEqual(db.execute('SELECT payload FROM rf_neighbor_messages').fetchone(), (b'\x11\x22',))
        self.assertEqual(len(self.history()), 1)

    def test_mqtt_web_status_snapshot_and_delta(self):
        self.archive.close()
        self.archive = Archive(self.path, interval=0)
        dashboard = Dashboard(self.archive)
        dashboard.connected = True
        topic = f'meshcore/HAN/{EAST}/status'
        near = status(0, 8, stats=dict(noise_floor=-115))
        with patch('onair_mqtt.time.time', return_value=BASE + 1), redirect_stdout(StringIO()):
            on_message(None, {'status_sink': dashboard.accept_status},
                       SimpleNamespace(topic=topic, payload=json.dumps(near).encode(), retain=False))

        async def check_websocket():
            worker = asyncio.create_task(dashboard.pump())
            try:
                async with asyncio.timeout(3):
                    while not self.archive.observer_radio_status():
                        await asyncio.sleep(.01)
                    snapshot = json.loads(dashboard.snapshot_payload(dashboard.status()))
                    self.assertEqual(snapshot['status']['noise_observers'][0]['noise_floor'], -115)
                    self.assertEqual(snapshot['status']['radio_observers'][0]['profile'], CORE)
                    queue = asyncio.Queue()
                    dashboard.listeners[queue] = True
                    dashboard.accept_packet(build_packet(dict(direction='rx', raw='1500')))
                    # The pump may first deliver a status-only update for the commit.
                    while True:
                        delta = json.loads(await queue.get())
                        if delta['receptions']:
                            break
                    self.assertEqual(delta['type'], 'delta')
                    # Observe an unchanged-profile packet delta after the first update.
                    dashboard.accept_packet(build_packet(dict(direction='rx', raw='1500')))
                    delta = json.loads(await queue.get())
                    self.assertNotIn('radio_observers', delta['status'])
                    self.receive(60, 7)
                    delta = json.loads(await queue.get())
                    self.assertEqual(delta['receptions'], [])
                    self.assertEqual(delta['status']['radio_observers'][0]['profile']['spreading_factor'], 7)
            finally:
                worker.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await worker

        asyncio.run(check_websocket())
