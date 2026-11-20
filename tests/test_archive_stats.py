import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from onair_archive import Archive, ARCHIVE_STATS_TTL


class ArchiveStatsTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'archive.sqlite3'
        self.archive = Archive(self.path)
        self.archive.close()
        self.now = 2_000_000_000
        clock = patch('onair_archive.time.time', side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)

    def insert(self, db, *rows):
        db.executemany("""INSERT INTO packets(id,received,kind,observer_hash,search_text,packet_json)
            VALUES(?,?,'ADVERT','ABCD','','{}')""", rows)

    def counts(self):
        stats = self.archive.archive_stats()
        return stats['total_packets'], stats['packets_last_24h']

    def test_exact_counts_and_delta_include_duplicates_and_sparse_ids(self):
        cutoff = self.now - 86400
        with self.archive.connect() as writer, writer:
            self.insert(writer, (1, cutoff - 0.001), (3, cutoff), (8, self.now), (20, self.now + 3600))
            writer.execute("INSERT INTO noise_samples(received_at,noise_floor) VALUES('',-110)")
            writer.execute("""INSERT INTO rf_neighbor_messages(reception_id,topic,received_at,payload,qos,retain,dup)
                VALUES('id','topic','',X'',0,0,0)""")

        statements = []
        connect = sqlite3.connect

        def traced_connect(*args, **kwargs):
            db = connect(*args, **kwargs)
            db.set_trace_callback(statements.append)
            return db

        with patch('onair_archive.sqlite3.connect', side_effect=traced_connect), \
                patch('onair_archive.time.monotonic', side_effect=lambda: self.now):
            self.assertEqual(self.counts(), (4, 2))
            with self.archive.connect() as writer:
                self.insert(writer, (101, self.now))
                self.assertEqual(self.counts(), (4, 2))
                self.now += ARCHIVE_STATS_TTL
                self.assertEqual(self.counts(), (4, 1))
                writer.commit()
            self.now += ARCHIVE_STATS_TTL
            self.assertEqual(self.counts(), (5, 2))
            self.now += ARCHIVE_STATS_TTL
            self.assertEqual(self.counts(), (5, 2))
        self.assertEqual(sum('INDEXED BY packets_received' in sql for sql in statements), 1)
        self.assertEqual(sum('COUNT(*) FROM packets WHERE id >' in sql for sql in statements), 1)

        reopened = Archive(self.path)
        reopened.close()
        self.assertEqual(reopened.archive_stats()['total_packets'], 5)

    def test_concurrent_requests_share_one_refresh(self):
        with patch.object(self.archive, '_packet_counts', wraps=self.archive._packet_counts) as counts:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: self.counts(), range(16)))
            self.assertEqual(results, [(0, 0)] * 16)
            counts.assert_called_once_with()

    def test_size_includes_sidecars(self):
        with self.archive.connect() as writer, writer:
            self.insert(writer, (1, self.now))
            writer.commit()
            files = [self.path.with_name(self.path.name + suffix) for suffix in ('', '-wal', '-shm')]
            self.assertGreater(files[1].stat().st_size, 0)
            self.assertGreater(files[2].stat().st_size, 0)
            self.assertEqual(self.archive.archive_stats()['database_bytes'],
                             sum(path.stat().st_size for path in files))

        # An inactive rollback journal can still occupy space on disk.
        self.path.with_suffix('.sqlite3-journal').write_bytes(bytes(512))
        self.assertEqual(self.archive._database_size(), self.path.stat().st_size + 512)

    def test_unavailable_values_are_cached_then_retried_independently(self):
        with patch('onair_archive.time.monotonic', side_effect=lambda: self.now):
            with patch.object(self.archive, '_packet_counts', side_effect=sqlite3.OperationalError):
                stats = self.archive.archive_stats()
                self.assertIsNone(stats['total_packets'])
                self.assertIsNone(stats['packets_last_24h'])
                self.assertGreater(stats['database_bytes'], 0)
            self.assertEqual(self.archive.archive_stats(), stats)

            self.now += ARCHIVE_STATS_TTL
            with patch.object(self.archive, '_database_size', side_effect=PermissionError):
                self.assertEqual(self.archive.archive_stats(), dict(
                    total_packets=0, packets_last_24h=0, database_bytes=None))

            self.now += ARCHIVE_STATS_TTL
            self.path.unlink()
            self.assertEqual(self.archive.archive_stats(), dict(
                total_packets=None, packets_last_24h=None, database_bytes=None))
            self.assertFalse(self.path.exists())
