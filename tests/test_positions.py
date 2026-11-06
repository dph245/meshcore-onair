"""Position projection parity, transactional recovery and conservative fallback."""
import copy
from contextlib import closing
import json
from pathlib import Path
import random
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from onair_archive import Archive
from onair_distance import Positions, analyze, response
from onair_positions import (NormalizedPositions, PositionMismatch, PositionUnavailable,
                             current_generation, evaluate, maintain, migrate, rebuild, synchronize)
from onair_trace_map import detail
from test_distance import A, B, START, add, packet
from test_trace import reception


class PositionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'archive.sqlite3'
        self.archive = Archive(self.path)
        self.archive.close()
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)

    def advert(self, received, stamp, latitude=50, longitude=12, key=A,
               signature='Gültig', status=None, direction='rx'):
        p = packet([], received, kind='ADVERT', direction=direction)
        p['decoded'].update(advert=dict(public_key=key, timestamp=stamp,
            latitude=latitude, longitude=longitude, signature_status=signature), advert_status=status)
        return add(self.db, p)

    def states(self):
        return self.db.execute('''SELECT i.public_key,s.received,s.packet_id,s.advert_timestamp,
            s.latitude,s.longitude FROM position_state s JOIN position_identity i USING(node_id)
            WHERE s.generation=(SELECT generation FROM position_active) ORDER BY received,packet_id''').fetchall()

    def parity(self, start=0, end=100, keys=()):
        legacy, normalized = Positions(self.db, start, end, keys), NormalizedPositions(self.db, start, end, keys)
        self.assertEqual(legacy.bounds, normalized.bounds)
        samples = {start, end - .000001}
        samples.update(r[0] for r in self.db.execute('SELECT received FROM packets WHERE received>=? AND received<?', (start, end)))
        for key in set(legacy.values) | set(normalized.values) | {A, B}:
            for t in samples:
                self.assertEqual(legacy.at(key, t), normalized.at(key, t), (key, t, start, end))

    def test_timestamp_watermark_without_coordinate_change(self):
        self.advert(1, 100)
        self.advert(2, 200)
        self.advert(3, 150, 60)
        synchronize(self.db)
        self.assertEqual(len(self.states()), 1)
        self.assertEqual(self.db.execute('SELECT max_position_timestamp FROM position_head').fetchone()[0], 200)
        self.parity()

    def test_equal_stamp_and_equal_reception_time_last_advert_wins(self):
        self.advert(10, 100, 50)
        self.advert(10, 100, 51)
        self.advert(10, 100, 50)
        self.advert(10, 99, 60)
        synchronize(self.db)
        self.assertEqual(len(self.states()), 3)
        self.parity(start=10)
        self.assertEqual(NormalizedPositions(self.db, 0, 100).at(A, 10)['latitude'], 50)

    def test_zero_invalid_missing_signature_status_and_no_direction_filter(self):
        self.advert(1, 1)
        self.advert(2, 2, 0, 0)
        self.advert(3, 100, None, None)
        self.advert(4, 200, 80, signature='Ungültig')
        self.advert(5, 200, 80, status='Ungültige ADVERT-Position')
        self.advert(6, 200, 80, status='')  # SQL IS NULL, not Python truthiness.
        self.advert(7, 3, 0, 10, direction='tx')
        synchronize(self.db)
        self.assertEqual(len(self.states()), 3)
        self.assertEqual(NormalizedPositions(self.db, 0, 100).at(A, 2), dict(latitude=0, longitude=0))
        self.parity()

    def test_missing_position_does_not_raise_position_watermark(self):
        self.advert(1, 100)
        self.advert(2, 1000, None, None)
        self.advert(3, 200, 51)
        synchronize(self.db)
        self.assertEqual(len(self.states()), 2)
        self.parity()

    def test_future_advert_timestamp_is_not_clamped(self):
        self.advert(1, 4294967295)
        self.advert(2, 1000, 51)
        synchronize(self.db)
        self.assertEqual(len(self.states()), 1)
        self.parity()

    def test_window_seed_and_exclusive_end(self):
        for received, lat in [(1, 50), (2, 50), (3, 51), (4, 51), (5, 52)]:
            self.advert(received, received, lat)
        synchronize(self.db)
        for start, end in [(0, 1), (0, 5), (2, 5), (3, 5), (4, 5), (5, 6), (7, 8)]:
            self.parity(start, end)

    def test_historical_insert_replays_downstream_watermarks(self):
        self.advert(10, 100)
        self.advert(30, 150, 51)
        synchronize(self.db)
        self.assertEqual(len(self.states()), 2)
        self.advert(20, 200)
        synchronize(self.db)
        self.assertEqual(len(self.states()), 1)
        self.parity()

    def test_historical_insert_and_new_changes_in_same_batch(self):
        self.advert(30, 150, 51)
        synchronize(self.db)
        self.advert(40, 300, 53)
        self.advert(10, 200)
        self.advert(20, 250, 52)
        synchronize(self.db)
        self.assertEqual([s[1] for s in self.states()], [10, 20, 40])
        self.parity()

    def test_restart_and_repeated_sync_are_idempotent(self):
        self.advert(1, 100)
        synchronize(self.db)
        before = self.states()
        self.db.commit()
        restarted = Archive(self.path, position_mode='normalized')
        restarted.close()
        self.assertIsNone(restarted.position_backup)
        synchronize(self.db)
        migrate(self.db)
        self.assertEqual(before, self.states())
        self.assertEqual(self.db.execute('SELECT count(*) FROM position_generation').fetchone()[0], 1)
        self.parity()

    def test_writer_batch_repetition_preserves_raw_receptions(self):
        p = packet([], START, kind='ADVERT')
        p['path'] = 'direct'
        p['decoded']['advert'] = dict(public_key=A, timestamp=100, latitude=50,
                                     longitude=12, signature_status='Gültig')
        self.archive._write(self.db, [p])
        self.archive._write(self.db, [copy.deepcopy(p)])
        self.assertEqual(self.db.execute('SELECT count(*) FROM packets').fetchone()[0], 2)
        self.assertEqual(len(self.states()), 1)
        self.parity(START, START + 10)

    def test_writer_failure_rolls_back_projection_only(self):
        p = packet([], START, kind='ADVERT')
        p['path'] = 'direct'
        p['decoded']['advert'] = dict(public_key=A, timestamp=100, latitude=50,
                                     longitude=12, signature_status='Gültig')
        with patch('onair_positions._save_heads', side_effect=RuntimeError('injected failure')), self.assertLogs(level='ERROR'):
            self.archive._write(self.db, [p])
        self.assertEqual(self.db.execute('SELECT count(*) FROM packets').fetchone()[0], 1)
        self.assertEqual(self.states(), [])
        with self.assertRaises(PositionUnavailable):
            current_generation(self.db)
        rebuild(self.db)
        self.parity(START, START + 10)

    def test_backfill_abort_keeps_active_generation_and_retry_works(self):
        self.advert(1, 100)
        synchronize(self.db)
        old_generation = current_generation(self.db)
        old_states = self.states()
        def abort(_):
            raise InterruptedError('cancel backfill')
        with self.assertRaises(InterruptedError):
            rebuild(self.db, progress=abort)
        self.assertEqual(current_generation(self.db), old_generation)
        self.assertEqual(self.states(), old_states)
        self.assertEqual(self.db.execute('SELECT count(*) FROM position_generation').fetchone()[0], 1)
        rebuild(self.db)
        self.parity()

    def test_first_migration_abort_rolls_back_schema_and_user_version(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE packets(id INTEGER PRIMARY KEY,received REAL,kind TEXT,packet_json TEXT)')
        db.execute('INSERT INTO packets VALUES(1,1,\'ADVERT\',?)', (json.dumps(dict(decoded=dict(advert={}))),))
        db.execute('PRAGMA user_version=15')
        db.commit()
        with self.assertRaises(InterruptedError):
            migrate(db, progress=lambda _: (_ for _ in ()).throw(InterruptedError()))
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 15)
        self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='position_state'").fetchone())
        migrate(db)
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 16)

    def test_migration_is_inside_callers_transaction(self):
        self.db.execute('BEGIN')
        generation = current_generation(self.db)
        rebuild(self.db)
        self.db.rollback()
        self.assertEqual(current_generation(self.db), generation)

    def test_raw_update_delete_and_low_id_insert_invalidate(self):
        first = self.advert(1, 100)
        self.advert(2, 200, 51)
        synchronize(self.db)
        for sql, args in [('UPDATE packets SET received=received+.1 WHERE id=?', (first,)),
                          ('DELETE FROM packets WHERE id=?', (first,)),
                          ("INSERT INTO packets(id,received,kind,search_text,packet_json) VALUES(0,0,'ADVERT','','{}')", ())]:
            self.db.execute(sql, args)
            with self.assertRaises(PositionUnavailable):
                current_generation(self.db)
            rebuild(self.db)
            self.parity()

    def test_missing_stale_and_corrupt_projection_fall_back_completely(self):
        self.advert(1, 1)
        operation = lambda factory: factory(self.db, 0, 100).at(A, 5)
        for mode in ('compare', 'normalized'):
            failures = []
            with self.assertLogs(level='ERROR'):
                result = evaluate(self.db, mode, operation, failures.append)
            self.assertEqual(result, dict(latitude=50, longitude=12))
            self.assertEqual(len(failures), 1)
        synchronize(self.db)
        with patch('onair_positions.NormalizedPositions', side_effect=sqlite3.DatabaseError('injected')), self.assertLogs(level='ERROR'):
            self.assertEqual(evaluate(self.db, 'normalized', operation), operation(Positions))

    def test_comparison_mismatch_returns_legacy_and_latches_archive(self):
        self.advert(1, 1)
        synchronize(self.db)
        self.db.execute('UPDATE position_state SET latitude=60')
        failures = []
        with self.assertLogs(level='ERROR'):
            result = evaluate(self.db, 'compare', lambda factory: factory(self.db, 0, 100).at(A, 5), failures.append)
        self.assertEqual(result['latitude'], 50)
        self.assertIsInstance(failures[0], PositionMismatch)
        self.archive._position_failed(failures[0])
        self.assertTrue(self.archive.position_failure)

    def test_compare_uses_one_snapshot_with_concurrent_writer(self):
        self.advert(1, 1)
        synchronize(self.db)
        self.db.commit()
        other = sqlite3.connect(self.path)
        self.addCleanup(other.close)
        calls = []
        def operation(factory):
            value = factory(self.db, 0, 100).at(A, 5)
            if not calls:
                p = packet([], 2, kind='ADVERT')
                p['decoded']['advert'] = dict(public_key=A, timestamp=2, latitude=60,
                                             longitude=12, signature_status='Gültig')
                add(other, p)
                synchronize(other)
                other.commit()
            calls.append(factory)
            return value
        failures = []
        self.assertEqual(evaluate(self.db, 'compare', operation, failures.append)['latitude'], 50)
        self.assertEqual(failures, [])
        self.assertEqual(NormalizedPositions(self.db, 0, 100).at(A, 5)['latitude'], 60)

    def test_actual_pre16_archive_is_backed_up_before_migration(self):
        path = Path(self.tmp.name) / 'old.sqlite3'
        old = sqlite3.connect(path)
        old.executescript('''CREATE TABLE packets(id INTEGER PRIMARY KEY,received REAL NOT NULL,
            kind TEXT NOT NULL,channel TEXT,observer_hash TEXT,search_text TEXT NOT NULL,
            packet_json TEXT NOT NULL,repeater_token TEXT,origin_id TEXT,origin TEXT);
            CREATE TABLE nodes(public_key TEXT PRIMARY KEY,name TEXT,advert_time INTEGER NOT NULL,
            first_seen REAL NOT NULL,last_seen REAL NOT NULL,node_type INTEGER,latitude REAL,
            longitude REAL,position_time INTEGER); PRAGMA user_version=15;''')
        old.close()
        archive = Archive(path)
        archive.close()
        self.assertTrue(archive.position_backup.exists())
        with closing(sqlite3.connect(archive.position_backup)) as backup:
            self.assertEqual(backup.execute('PRAGMA user_version').fetchone()[0], 15)
            self.assertIsNone(backup.execute("SELECT name FROM sqlite_master WHERE name='position_state'").fetchone())

    def test_dx_and_trace_keep_different_prefix_and_type_resolvers(self):
        self.db.executemany('INSERT INTO nodes VALUES(?,?,1,0,1,?,?,?,1)',
                            [(A, 'A', 2, 50, 12), (B, 'B', 1, 53, 11)])
        self.advert(START - 1, 1, key=A)
        self.advert(START - 1, 1, 53, 11, key=B)
        add(self.db, packet([A[:6], B[:6]], START))
        trace = reception(route=A[:2] + B[:2], snrs=(1, 2))
        trace['received_at'] = packet([], START)['received_at']
        ident = add(self.db, trace)
        synchronize(self.db)
        dx = lambda factory: analyze(self.db, START, START + 100, 0, A, B, positions_factory=factory)
        self.assertEqual(evaluate(self.db, 'compare', dx)['items'], [])
        tr = lambda factory: detail(self.db, ident, factory(self.db, 0, START + 100))
        self.assertTrue(all(h['position'] for h in evaluate(self.db, 'compare', tr)['hops']))
        collision = A[:2] + 'ff' * 31
        self.db.execute('INSERT INTO nodes VALUES(?,?,1,0,1,1,NULL,NULL,NULL)', (collision, 'collision'))
        self.assertTrue(evaluate(self.db, 'compare', tr)['hops'][0]['ambiguous'])
        self.assertIsNone(evaluate(self.db, 'compare', tr)['hops'][0]['position'])
        self.db.execute('UPDATE nodes SET node_type=2 WHERE public_key=?', (B,))
        self.db.execute("INSERT INTO repeater_receptions VALUES(?,1,NULL,NULL,NULL,0)", (A[:6] + 'ff',))
        self.assertEqual(evaluate(self.db, 'compare', dx)['items'], [])

    def test_randomized_backfill_incremental_and_historical_parity(self):
        rng = random.Random(5812)
        keys = [f'{n:02x}' + '00' * 31 for n in range(1, 7)]
        for batch in range(6):
            for _ in range(40):
                latitude, longitude = rng.choice([(50, 12), (51, 13), (0, 0), (0, 10), (None, None)])
                self.advert(rng.randrange(1, 80), rng.randrange(0, 30), latitude, longitude,
                            key=rng.choice(keys), signature=rng.choice(['Gültig'] * 4 + ['Ungültig']))
            if batch == 0:
                rebuild(self.db)
            else:
                synchronize(self.db)
            for start, end in [(0, 100), (20, 60), (40, 41), (79, 80), (80, 100)]:
                self.parity(start, end)
                self.parity(start, end, tuple(keys[:2]))

    def test_archive_dx_and_trace_entrypoints_in_both_modes(self):
        self.db.executemany('INSERT INTO nodes VALUES(?,?,1,0,1,2,?,?,1)',
                            [(A, 'A', 50, 12), (B, 'B', 53, 11)])
        self.advert(START - 1, 1)
        self.advert(START - 1, 1, 53, 11, key=B)
        add(self.db, packet([A[:6], B[:6]], START))
        trace = reception(route=A[:2] + B[:2], snrs=(1, 2))
        trace['received_at'] = packet([], START)['received_at']
        ident = add(self.db, trace)
        synchronize(self.db)
        self.db.commit()
        expected_dx = response(analyze(self.db, START, START + 100, 0, A, B), A, B)
        expected_trace = detail(self.db, ident, Positions(self.db, 0, START + 100))
        for mode in ('compare', 'normalized'):
            archive = Archive(self.path, position_mode=mode)
            archive.close()
            self.assertEqual(archive.distance_analysis(START, START + 100, 0, A, B), expected_dx)
            self.assertEqual(archive.trace_map_detail(ident), expected_trace)
            self.assertIsNone(archive.position_failure)

    def test_compare_detects_position_mismatch_even_without_result_difference(self):
        self.advert(1, 1)
        synchronize(self.db)
        self.db.execute('UPDATE position_state SET latitude=60')
        failures = []
        def operation(factory):
            factory(self.db, 0, 100)
            return 'same business result'
        with self.assertLogs(level='ERROR'):
            self.assertEqual(evaluate(self.db, 'compare', operation, failures.append), 'same business result')
        self.assertIsInstance(failures[0], PositionMismatch)

    def test_offline_cli_backs_up_and_rebuilds_without_workers(self):
        self.advert(1, 1)
        synchronize(self.db)
        self.db.commit()
        command = [sys.executable, '-B', str(Path(__file__).resolve().parents[1] / 'onair_positions.py'),
                   '--db', str(self.path)]
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=20)
        report = json.loads(result.stdout)
        self.assertEqual(report['generation'], current_generation(self.db))
        with closing(sqlite3.connect(report['backup'])) as backup:
            self.assertEqual(current_generation(backup), 1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM packets').fetchone()[0], 1)
        self.parity()


if __name__ == '__main__':
    unittest.main()
