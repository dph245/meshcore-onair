"""Synthetic fixtures follow Gessaman's documented builder, not a live capture."""
import asyncio
import contextlib
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from queue import Full
import sqlite3
import tempfile
from threading import Event
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from onair_archive import Archive
import onair_mqtt as mqtt
from onair_rf_neighbors import parse_report, topic_identity


OBSERVER = 'AB' * 32
NEIGHBOR = 'CD' * 32
TOPIC = f'meshcore/BER/{OBSERVER}/neighbors'
STAMP = '2026-11-05T12:00:00+00:00'


def report(**fields):
    return dict(timestamp=STAMP, origin='Observer ü', origin_id=OBSERVER,
                self={'scopes': 'de,de-ni,*', 'default_scope': 'de'},
                total_neighbors=4, queried_neighbors=3, truncated=True,
                neighbors=[dict(pubkey=NEIGHBOR, snr=-2.25, heard_secs_ago=90,
                                scopes='de,de-ni', status='responded')], **fields)


def delivery(payload=None, topic=TOPIC, **metadata):
    return SimpleNamespace(topic=topic, payload=json.dumps(report(), ensure_ascii=False).encode()
                           if payload is None else payload,
                           **dict(dict(qos=0, retain=True, dup=False, mid=7), **metadata))


class ParserTests(unittest.TestCase):
    def parse(self, data):
        return parse_report(json.dumps(data).encode(), OBSERVER.lower())

    def test_topic_requires_complete_firmware_structure(self):
        self.assertEqual(topic_identity(TOPIC), ('BER', OBSERVER.lower()))
        self.assertIsNotNone(topic_identity(TOPIC.replace('/BER/', '/b2r/')))
        for topic in ('other/BER/' + OBSERVER + '/neighbors',
                      TOPIC + '/extra', TOPIC + '/', 'meshcore/test/neighbors',
                      TOPIC.replace(OBSERVER, 'AB'), TOPIC.replace('/BER/', '/BE/'),
                      TOPIC.replace('/BER/', '/B_R/'), TOPIC.replace(OBSERVER, 'G'*64)):
            with self.subTest(topic=topic):
                self.assertIsNone(topic_identity(topic))

    def test_schema_time_scopes_and_truncation(self):
        snapshot, entries = self.parse(report())
        self.assertEqual(snapshot['reported_at'], datetime.fromisoformat(STAMP).timestamp())
        self.assertTrue(snapshot['truncated'])
        self.assertEqual((snapshot['total_neighbors'], snapshot['queried_neighbors']), (4, 3))
        self.assertEqual(snapshot['self_default_scope'], 'de')
        self.assertEqual(entries[0], dict(pubkey=NEIGHBOR.lower(), snr=-2.25,
                                         heard_secs_ago=90, heard_at=snapshot['reported_at'] - 90,
                                         scopes='de,de-ni', status='responded'))
        data = report()
        data['timestamp'] = '2026-11-05T13:00:00+01:00'
        self.assertEqual(self.parse(data)[0]['reported_at'], snapshot['reported_at'])
        data['timestamp'] = '2026-11-05T12:00:00'
        self.assertEqual(self.parse(data)[0]['reported_at'], snapshot['reported_at'])

    def test_missing_null_and_zero_are_distinct_from_completeness(self):
        data = {'neighbors': [dict(pubkey=NEIGHBOR, heard_secs_ago=None, status='timeout'),
                              dict(pubkey=NEIGHBOR, heard_secs_ago=0, scopes='', status='send_failed')]}
        snapshot, entries = self.parse(data)
        self.assertIsNone(snapshot['truncated'])
        self.assertIsNone(snapshot['total_neighbors'])
        self.assertIsNone(snapshot['self_scopes'])
        self.assertIsNone(entries[0]['heard_secs_ago'])
        self.assertEqual(entries[1]['heard_secs_ago'], 0)
        self.assertTrue(all(e['heard_at'] is None for e in entries))
        data['timestamp'] = STAMP
        snapshot, entries = self.parse(data)
        self.assertIsNone(entries[0]['heard_at'])
        self.assertEqual(entries[1]['heard_at'], snapshot['reported_at'])
        self.assertEqual(self.parse({'neighbors': []})[1], [])

    def test_unknown_fields_and_status_are_preserved_without_interpretation(self):
        data = report()
        data['extra'] = {'future': [1, 2]}
        data['neighbors'][0]['status'] = 'future_status'
        self.assertEqual(self.parse(data)[1][0]['status'], 'future_status')
        data['neighbors'][0]['snr'] = 2**70
        self.assertEqual(self.parse(data)[1][0]['snr'], float(2**70))

    def test_invalid_fields_reject_structured_snapshot(self):
        changes = [('origin_id', 'EF'*32), ('timestamp', 'bad'), ('truncated', 1),
                   ('queried_neighbors', -1), ('total_neighbors', True), ('self', None),
                   ('neighbors', {}), ('origin', '\ud800')]
        for field, value in changes:
            data = report()
            data[field] = value
            with self.subTest(field=field), self.assertRaises((ValueError, UnicodeError)):
                self.parse(data)
        for field, value in [('pubkey', 'bad'), ('snr', True), ('snr', float('nan')),
                             ('snr', float('inf')), ('heard_secs_ago', -1),
                             ('heard_secs_ago', 1.5), ('heard_secs_ago', True),
                             ('heard_secs_ago', 2**32), ('scopes', []), ('status', {})]:
            data = report()
            data['neighbors'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.parse(data)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(folder) / 'test.sqlite3'
        self.archive = Archive(self.path, interval=0.02)
        self.addCleanup(self.archive.close)

    def receive(self, message):
        mqtt.on_message(None, {'rf_neighbor_sink': self.archive.accept_rf_neighbors}, message)

    def rows(self, table):
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute('SELECT * FROM ' + table)]

    def test_raw_bytes_metadata_duplicate_deliveries_and_restart(self):
        message = delivery(b' \n' + delivery().payload + b'\n')
        self.receive(message)
        self.receive(delivery(message.payload, dup=True, mid=8))
        self.archive.close()
        raw = self.rows('rf_neighbor_messages')
        self.assertEqual(len(raw), 2)
        self.assertNotEqual(raw[0]['reception_id'], raw[1]['reception_id'])
        for row in raw:
            self.assertEqual(row['topic'], TOPIC)
            self.assertEqual(row['payload'], message.payload)
            self.assertIsNone(row['parse_error'])
            self.assertEqual(datetime.fromisoformat(row['received_at']).utcoffset().total_seconds(), 0)
            self.assertEqual((row['qos'], row['retain']), (0, 1))
        self.assertEqual((raw[1]['dup'], raw[1]['mid']), (1, 8))
        snapshots = self.rows('rf_neighbor_reports')
        entries = self.rows('rf_neighbor_entries')
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[0]['observer_key'], OBSERVER.lower())
        self.assertEqual(snapshots[0]['self_scopes'], 'de,de-ni,*')
        self.assertEqual(entries[0]['heard_at'], entries[1]['heard_at'])
        self.assertEqual(entries[0]['scopes'], 'de,de-ni')
        reopened = Archive(self.path)
        reopened.close()
        self.assertEqual(self.rows('rf_neighbor_messages'), raw)
        self.assertEqual(self.rows('packets'), [])
        self.assertEqual(self.archive.saved, 0)

    def test_malformed_and_binary_raw_survive_and_rx_status_continue(self):
        broken = [b'', b'\xff\x00', b'{', b'[]', b'{"neighbors":[null]}',
                  b'{"neighbors":[],"timestamp":"bad"}',
                  b'{"neighbors":[],"origin":"\\ud800"}']
        with self.assertLogs(level='WARNING'):
            for payload in broken:
                self.receive(delivery(payload))
            self.receive(delivery())
            with contextlib.redirect_stdout(io.StringIO()):
                mqtt.on_message(None, {'packet_sink': self.archive.accept},
                                delivery(b'{"direction":"rx","raw":"1500"}',
                                         topic='meshcore/test/packets'))
                mqtt.on_message(None, {'status_sink': lambda d: self.archive.accept_noise(mqtt.noise_sample(d))},
                                delivery(b'{"stats":{"noise_floor":-110}}', topic='meshcore/test/status', retain=False))
            self.archive.close()
        raw = self.rows('rf_neighbor_messages')
        self.assertEqual([r['payload'] for r in raw[:-1]], broken)
        self.assertTrue(all(r['parse_error'] for r in raw[:-1]))
        self.assertEqual(len(self.rows('rf_neighbor_reports')), 1)
        self.assertEqual(len(self.rows('packets')), 1)
        self.assertEqual(len(self.rows('noise_samples')), 1)
        self.assertEqual(self.archive.saved, 1)
        self.assertFalse(self.archive.worker.is_alive())
        self.assertFalse(self.archive.rf_neighbor_worker.is_alive())

    def test_history_keeps_observers_snapshots_and_omitted_neighbors(self):
        self.receive(delivery())
        data = report()
        data.update(origin_id='EF'*32, timestamp='2026-11-04T12:00:00Z', truncated=False)
        self.receive(delivery(json.dumps(data).encode(), topic=TOPIC.replace(OBSERVER, 'EF'*32)))
        self.receive(delivery(b'{"neighbors":[],"truncated":true}'))
        self.archive.close()
        reports = self.rows('rf_neighbor_reports')
        self.assertEqual(len(reports), 3)
        self.assertEqual({r['observer_key'] for r in reports}, {OBSERVER.lower(), 'ef'*32})
        self.assertEqual(len(self.rows('rf_neighbor_entries')), 2)
        self.assertIsNone(reports[2]['reported_at'])
        self.assertIsNone(reports[2]['total_neighbors'])

    def test_schema14_upgrade_preserves_existing_data(self):
        self.archive.accept(mqtt.build_packet({'raw': '1500'}))
        self.archive.close()
        with contextlib.closing(sqlite3.connect(self.path)) as db, db:
            original = db.execute('SELECT * FROM packets').fetchall()
            for table in ('rf_neighbor_entries', 'rf_neighbor_reports', 'rf_neighbor_messages'):
                db.execute('DROP TABLE ' + table)
            db.execute('PRAGMA user_version=14')
        upgraded = Archive(self.path)
        upgraded.close()
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 16)
            self.assertEqual(db.execute('SELECT * FROM packets').fetchall(), original)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM rf_neighbor_messages').fetchone()[0], 0)

    def test_raw_retry_after_commit_is_idempotent(self):
        original = self.archive._write_rf_neighbors
        attempts = []

        def ambiguous_commit(db, message):
            original(db, message)
            attempts.append(1)
            if len(attempts) == 1:
                raise sqlite3.OperationalError('simulated error after commit')

        with patch.object(self.archive, '_write_rf_neighbors', side_effect=ambiguous_commit), self.assertLogs(level='ERROR'):
            self.receive(delivery())
            deadline = time.monotonic() + 3
            while len(attempts) < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.archive.close()
        self.assertGreaterEqual(len(attempts), 2)
        self.assertEqual(len(self.rows('rf_neighbor_messages')), 1)
        self.assertEqual(len(self.rows('rf_neighbor_reports')), 1)
        self.assertEqual(len(self.rows('rf_neighbor_entries')), 1)
        self.assertIsNone(self.archive.rf_neighbor_error)

    def test_overload_does_not_use_rx_queue(self):
        with patch.object(self.archive.rf_neighbor_queue, 'put_nowait', side_effect=Full), self.assertLogs(level='ERROR'):
            self.archive.accept_rf_neighbors({})
        self.assertEqual(self.archive.rf_neighbor_dropped, 1)
        self.assertEqual(self.archive.dropped, 0)
        self.assertTrue(self.archive.queue.empty())

    def test_blocked_parser_does_not_block_rx_status_or_callback(self):
        entered, release = Event(), Event()
        original = parse_report

        def blocked(*args):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('test parser timed out')
            return original(*args)

        with patch('onair_archive.parse_report', side_effect=blocked):
            try:
                self.receive(delivery())
                self.assertTrue(entered.wait(2))
                self.archive.accept(mqtt.build_packet({'raw': '1500'}))
                self.archive.accept_noise(dict(received_at=STAMP, noise_floor=-110))
                deadline = time.monotonic() + 2
                while self.archive.saved < 1 and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(self.archive.saved, 1)
                self.assertEqual(len(self.rows('noise_samples')), 1)
            finally:
                release.set()
                self.archive.close()
        self.assertEqual(len(self.rows('rf_neighbor_reports')), 1)

    def test_rf_database_failure_retries_without_stalling_rx(self):
        original = self.archive._write_rf_neighbors
        failed, recover = Event(), Event()

        def locked(db, message):
            if not recover.is_set():
                failed.set()
                raise sqlite3.OperationalError('simulated RF write failure')
            return original(db, message)

        with patch.object(self.archive, '_write_rf_neighbors', side_effect=locked), self.assertLogs(level='ERROR'):
            try:
                self.receive(delivery())
                self.assertTrue(failed.wait(2))
                self.archive.accept(mqtt.build_packet({'raw': '1500'}))
                deadline = time.monotonic() + 2
                while self.archive.saved < 1 and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(self.archive.saved, 1)
            finally:
                recover.set()
                # Let the RF writer retry before close signals its stop event.
                deadline = time.monotonic() + 2
                while not self.archive.rf_neighbor_saved and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.archive.close()
        self.assertEqual(len(self.rows('rf_neighbor_reports')), 1)
        self.assertIsNone(self.archive.rf_neighbor_error)

    def test_failed_structured_insert_rolls_back_raw_then_retries(self):
        self.archive.close()
        message = vars(delivery()) | dict(received_at=STAMP, reception_id='stable-retry-id')
        with self.archive.connect() as db:
            db.execute('''CREATE TRIGGER fail_rf_report BEFORE INSERT ON rf_neighbor_reports
                BEGIN SELECT RAISE(ABORT, 'simulated report insert failure'); END''')
            with self.assertRaises(sqlite3.IntegrityError):
                self.archive._write_rf_neighbors(db, message)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM rf_neighbor_messages').fetchone()[0], 0)
            db.execute('DROP TRIGGER fail_rf_report')
            self.archive._write_rf_neighbors(db, message)
        self.assertEqual(len(self.rows('rf_neighbor_messages')), 1)
        self.assertEqual(len(self.rows('rf_neighbor_reports')), 1)
        self.assertEqual(len(self.rows('rf_neighbor_entries')), 1)


class RoutingTests(unittest.TestCase):
    def test_cli_and_web_connect_raw_sink_with_mocked_mqtt(self):
        archive, client = Mock(), Mock()
        client.loop_forever.side_effect = KeyboardInterrupt
        with patch('onair_archive.Archive', return_value=archive), \
                patch.object(mqtt, 'create_client', return_value=client) as factory, \
                contextlib.redirect_stdout(io.StringIO()):
            mqtt.main()
        self.assertIs(factory.call_args.kwargs['rf_neighbor_sink'], archive.accept_rf_neighbors)
        archive.close.assert_called_once()

        import onair_web as web
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(Path(folder) / 'web.sqlite3', interval=0.02)
            client = Mock()

            async def run():
                with patch.object(web, 'Archive', return_value=archive), \
                        patch.object(web, 'create_client', return_value=client) as factory:
                    async with web.lifespan(web.app):
                        factory.call_args.kwargs['rf_neighbor_sink'](
                            vars(delivery()) | dict(received_at=STAMP))
            asyncio.run(run())
            with archive.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM rf_neighbor_reports').fetchone()[0], 1)

    def test_no_payload_heuristics_and_no_legacy_sinks(self):
        raw_sink, packet_sink, status_sink = Mock(), Mock(), Mock()
        userdata = dict(rf_neighbor_sink=raw_sink, packet_sink=packet_sink, status_sink=status_sink)
        with contextlib.redirect_stdout(io.StringIO()):
            mqtt.on_message(None, userdata, delivery(topic='unrelated/BER/' + OBSERVER + '/neighbors'))
            raw_sink.assert_not_called()
            mqtt.on_message(None, userdata, delivery(b'not json'))
        raw_sink.assert_called_once()
        packet_sink.assert_not_called()
        status_sink.assert_not_called()

    def test_sink_exception_does_not_escape_callback(self):
        with self.assertLogs(level='ERROR'):
            mqtt.on_message(None, {'rf_neighbor_sink': Mock(side_effect=RuntimeError('test'))}, delivery())


if __name__ == '__main__':
    unittest.main()
