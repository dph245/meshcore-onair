from contextlib import closing
from datetime import datetime, timezone
import asyncio
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from onair_archive import Archive
from onair_mqtt import build_packet
from onair_observer_radio import RadioReport, radio_profile_at, record_radio
from onair_trace_history import backfill_batch, links, measurement, record, status
from onair_web import app
from test_archive_http import get
from test_trace import reception

A = '77730034'.ljust(64, '0')
B = '747400e7'.ljust(64, '0')
C = '6f33a924'.ljust(64, '0')
D = 'bf92b989'.ljust(64, '0')
EAST = 'ff' * 32
WEST = 'ee' * 32
BASE = 1795000000
REAL_RAW = '26072C311E292925318256CBA8508BDF260277730034747400E76F33A924BF92B9896F33A924747400E777730034'


def iso(stamp):
    return datetime.fromtimestamp(BASE + stamp, timezone.utc).isoformat()


class TraceHistoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'onair.sqlite3'
        self.archive = Archive(self.path, interval=.01)
        self.archive.close()
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)

    def advert(self, key, offset, lat, *, stamp=None):
        packet = build_packet(dict(raw='1500', direction='rx')).to_dict()
        packet['received_at'] = iso(offset)
        packet['decoded'].update(payload_name='ADVERT', payload_type=4, advert=dict(
            signature_status='Gültig', public_key=key, name=key[:8], node_type=2,
            latitude=lat, longitude=11, timestamp=BASE + (offset if stamp is None else stamp)))
        self.archive._write(self.db, [packet])

    def packet(self, stamp, snrs, *, tag=1, observer=EAST, size=1,
               path=(A, B, C), source=None, retained=False):
        packet = reception(tag=tag, route=''.join(key[:size * 2] for key in path),
                           flags={1: 0, 2: 1, 4: 2}[size], snrs=snrs, observer=observer)
        packet.update(received_at=iso(stamp), source_at=None if source is None else BASE + source,
                      mqtt_retained=retained, rssi=-93, snr=2.75)
        self.archive._write(self.db, [packet])
        return self.db.execute('SELECT MAX(id) FROM packets').fetchone()[0]

    def read(self, start=0, end=10000, sf='all', pair=None, offset=0):
        return links(self.db, BASE + start, BASE + end, sf, pair, offset)

    def radio(self, observer, stamp, sf, cr=8):
        with self.db:
            record_radio(self.db, RadioReport(observer, None, BASE + stamp, BASE + stamp + 1, False,
                dict(frequency_hz=869618000, bandwidth_hz=62500, spreading_factor=sf, coding_rate=cr)))

    def test_real_four_byte_wire_sample_and_direction(self):
        packet = build_packet(dict(raw=REAL_RAW, direction='rx', origin_id=EAST))
        self.assertEqual(packet.decoded['hash_size'], 1)
        self.assertEqual(packet.decoded['trace']['hash_size'], 4)
        self.assertEqual(packet.decoded['trace']['snrs'], [11, 12.25, 7.5, 10.25, 10.25, 9.25, 12.25])
        raw = dict(packet.to_dict(), received_at=iso(10))
        self.archive._write(self.db, [raw])
        row = measurement(self.db, 1)
        self.assertEqual((row['tag'], row['auth_code'], row['flags'], row['complete']), ('a8cb5682', '26df8b50', 2, True))
        samples = [(a.hex(), b.hex(), value / 4) for a, b, value in self.db.execute(
            'SELECT source,target,snr_qdb FROM trace_sample ORDER BY hop')]
        self.assertEqual(samples, [(a[:8], b[:8], snr) for a, b, snr in (
            (A, B, 12.25), (B, C, 7.5), (C, D, 10.25), (D, C, 10.25), (C, B, 9.25), (B, A, 12.25))])

    def test_partial_duplicate_late_delivery_and_reused_wire_identity(self):
        root = self.packet(15, (1,), source=10)
        self.packet(17, (1, 0), observer=WEST, source=12)
        final = self.packet(20, (1, 0, -4), source=14.125)
        duplicate = self.packet(1000, (1, 0, -4), source=14.125, retained=True)
        late = self.packet(1010, (1, 0), source=12.5)
        repeat = self.packet(24, (1,), source=23)
        second = self.packet(26, (1, 0, -4), source=25)
        conflict = self.packet(27, (-1, 0), observer=WEST, source=26)
        untimed = self.packet(28, (1, 0, -4), retained=True)
        for reception_id, group in ((root, root), (final, root), (duplicate, root), (late, root),
                                    (repeat, repeat), (second, repeat), (conflict, conflict), (untimed, untimed)):
            self.assertEqual(self.db.execute('SELECT measurement_id FROM trace_observation WHERE packet_id=?',
                                             (reception_id,)).fetchone()[0], group)
        detail = measurement(self.db, root)
        self.assertTrue(detail['complete'])
        self.assertEqual([hop['snr'] for hop in detail['hops']], [1, 0, -4])
        duplicate_row = next(o for o in detail['observations'] if o['packet_id'] == duplicate)
        self.assertEqual(duplicate_row['duplicate_of'], final)
        self.assertEqual(duplicate_row['received'], BASE + 1000)
        self.assertEqual(duplicate_row['source_at'], BASE + 14.125)
        self.assertEqual(self.db.execute('SELECT count(*) FROM trace_sample WHERE measurement_id=?', (root,)).fetchone()[0], 2)
        self.assertEqual(measurement(self.db, conflict)['observations'][0]['relation'], 'conflicting_snr')

    def test_profile_filters_exact_median_direction_and_time(self):
        self.advert(A, 1, 52)
        self.advert(B, 1, 51)
        self.radio(EAST, 4, 7)
        self.radio(WEST, 4, 8)
        self.packet(4.1, (10, 0, -3), tag=1, size=2, path=(A, B, A), source=4)
        self.packet(10, (8, .25, -2), tag=2, size=4, path=(A, B, A))
        self.packet(20, (9, 9), tag=3, size=1, path=(A, B), observer=WEST)
        self.packet(30, (2, -2), tag=4, size=1, path=(A, B), observer=None)
        result = self.read()
        link, = result['links']
        self.assertEqual(result['spreading_factors'], [7, 8])
        self.assertEqual([p['public_key'] for p in link['endpoints']], [B, A])
        groups = {group['profile'].get('spreading_factor'): group for group in link['profiles']}
        sf7 = groups[7]
        self.assertEqual(sf7['reverse'], dict(count=2, last=.25, min=0, median=.125, max=.25,
                    first_at=BASE + 4, last_at=BASE + 10, quality=dict(confirmed=1, last_known=1)))
        self.assertEqual(sf7['forward']['median'], -2.5)
        self.assertIsNone(groups[8]['forward'])
        self.assertEqual(self.read(sf='8')['summary']['visible_samples'], 1)
        self.assertEqual(self.read(sf='unknown')['summary']['visible_samples'], 1)
        page = self.read(10, 20, '7', (B, A))
        self.assertEqual(page['total'], 2)
        self.assertEqual([item['snr'] for item in page['items']], [-2, .25])
        before_window = self.read(0, 4)
        self.assertEqual(before_window['links'], [])

    def test_conflicting_profiles_and_uncertain_transition(self):
        self.advert(A, 1, 52)
        self.advert(B, 1, 51)
        self.radio(EAST, 2, 7)
        self.radio(WEST, 2, 8)
        root = self.packet(8, (2, 3), path=(A, B), source=7)
        self.packet(9, (2, 3), path=(A, B), source=7.1, observer=WEST)
        unknown, = self.read(sf='unknown')['links'][0]['profiles']
        self.assertEqual(unknown['reverse']['quality'], {'conflicting_profiles': 1})
        self.assertEqual([o['radio']['profile']['spreading_factor'] for o in measurement(self.db, root)['observations']], [7, 8])
        self.radio(EAST, 10, 7)
        self.radio(EAST, 20, 8)
        self.packet(18, (1, 2), tag=4, path=(A, B), source=17)
        profile = radio_profile_at(self.db, EAST, BASE + 17)
        self.assertEqual(profile['reason'], 'transition')
        quality = self.read(sf='unknown')['links'][0]['profiles'][0]['reverse']['quality']
        self.assertEqual(quality, {'uncertain': 1, 'conflicting_profiles': 1})

    def test_later_identity_resolution_collisions_and_position_conflict(self):
        competing = '777300a4' + '1' * 56
        self.advert(B, 1, 51)
        early = self.packet(2, (1, 2), path=(A, B), size=4)
        self.assertEqual(measurement(self.db, early)['hops'][0]['state'], 'unknown')
        self.advert(A, 3, 52)
        self.assertEqual(measurement(self.db, early)['hops'][0]['public_key'], A)
        self.assertEqual(self.read()['links'], [])  # First position was later than the TRACE.
        self.packet(4, (1, 3), tag=2, size=4, path=(A, B))
        self.packet(5, (2, 4), tag=3, size=2, path=(A, B))
        self.advert(competing, 6, 53)
        result = self.read()
        self.assertEqual(result['summary']['unmapped_samples'], {'ambiguous': 1, 'missing_position': 1})
        self.assertEqual(result['summary']['visible_samples'], 1)
        self.assertEqual(result['links'][0]['prefix_bytes'], [4, 4])
        self.advert(A, 7, 52)
        self.advert(A, 8, 54, stamp=7)
        result = self.read()
        self.assertEqual(result['links'], [])
        self.assertEqual(result['summary']['unmapped_samples']['uncertain_position'], 2)

    def test_incomplete_and_asymmetric_paths_do_not_bridge_unresolved_hop(self):
        self.advert(A, 1, 52)
        self.advert(C, 1, 51)
        root = self.packet(3, (1, 7, 9), path=(A, B, C, D), size=4)
        self.assertEqual(self.read()['links'], [])
        row = measurement(self.db, root)
        self.assertFalse(row['complete'])
        self.assertEqual([hop['snr'] for hop in row['hops']], [1, 7, 9, None])
        self.assertEqual(self.read()['summary']['unmapped_samples'], {'unknown': 2})

    def test_backfill_resume_interleaved_ingestion_and_idempotence(self):
        old = [self.packet(10 + i, (1, i), tag=i) for i in range(4)]
        with self.db:
            for table in ('trace_sample', 'trace_observation', 'trace_measurement', 'trace_backfill'):
                self.db.execute(f'DROP TABLE {table}')
            self.db.execute('PRAGMA user_version=17')
        # Recreate only the schema synchronously to control batch boundaries.
        from onair_trace_history import migrate
        with self.db:
            migrate(self.db)
        before = self.db.execute('SELECT id,packet_json FROM packets').fetchall()
        self.assertEqual(backfill_batch(self.db, limit=2)['cursor'], old[1])
        live = self.packet(40, (2, 3), tag=99)
        with closing(sqlite3.connect(self.path)) as reopened:
            self.assertEqual(status(reopened)['scanned'], 2)
            self.assertTrue(backfill_batch(reopened, limit=2)['done'])
            self.assertEqual(reopened.execute('SELECT COUNT(*) FROM trace_observation').fetchone()[0], 5)
            with reopened:
                record(reopened, live, BASE + 40, json.loads(reopened.execute(
                    'SELECT packet_json FROM packets WHERE id=?', (live,)).fetchone()[0]))
            self.assertEqual(reopened.execute('SELECT COUNT(*) FROM trace_sample').fetchone()[0], 5)
            self.assertEqual(reopened.execute('SELECT id,packet_json FROM packets WHERE id<?', (live,)).fetchall(), before)
        self.assertIsNone(backfill_batch(self.db))
        self.assertEqual(self.db.execute('PRAGMA user_version').fetchone()[0], 18)

    def test_archive_automatically_catches_up_in_background(self):
        self.packet(10, (1, 2))
        with self.db:
            for name in ('trace_sample', 'trace_observation', 'trace_measurement', 'trace_backfill'):
                self.db.execute(f'DROP TABLE {name}')
            self.db.execute('PRAGMA user_version=17')
        archive = Archive(self.path, interval=.01)
        try:
            deadline = time.monotonic() + 2
            while not status(self.db)['done'] and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(status(self.db)['done'])
            self.assertGreaterEqual(archive.trace_revision, 1)
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM trace_sample').fetchone()[0], 1)
        finally:
            archive.close()

    def test_http_validation_and_lazy_pagination(self):
        self.advert(A, 1, 52)
        self.advert(B, 1, 51)
        ids = [self.packet(4 + i, (2, 3), tag=i, path=(A, B)) for i in range(51)]

        async def direct(fn, **kwargs):
            return fn(**kwargs)

        with patch.object(app.state, 'archive', self.archive, create=True), \
                patch('fastapi.routing.run_in_threadpool', direct):
            http_status, overview = asyncio.run(get('/api/trace-links'))
            self.assertEqual((http_status, len(overview['links'])), (200, 1))
            for query in (dict(start=20, end=10), dict(sf=42), dict(a=A), dict(a=A, b=B)):
                self.assertEqual(asyncio.run(get('/api/trace-links', **query))[0], 422)
            page = asyncio.run(get('/api/trace-links', a=B, b=A))[1]
            tail = asyncio.run(get('/api/trace-links', a=B, b=A, offset=page['next']))[1]
            self.assertEqual((page['total'], len(page['items']), len(tail['items'])), (51, 50, 1))
            self.assertEqual(tail['items'][0]['measurement_id'], ids[0])
            http_status, detail = asyncio.run(get(f'/api/trace-measurements/{ids[0]}'))
            self.assertEqual(http_status, 200)
            self.assertEqual(detail['observations'][0]['observer_rssi'], -93)
            self.assertEqual(detail['observations'][0]['observer_snr'], 2.75)
            self.assertEqual(detail['hops'][1]['snr'], 3)
            self.assertEqual(asyncio.run(get('/api/trace-measurements/9999'))[0], 404)

    def test_trace_mqtt_source_identity_and_retained_metadata(self):
        from types import SimpleNamespace
        from contextlib import redirect_stdout
        from io import StringIO
        from onair_mqtt import on_message

        reports = []
        data = {'raw': REAL_RAW, 'timestamp': iso(0), 'direction': 'rx'}
        topic = f'meshcore/HAN/{EAST.upper()}/packets'
        with redirect_stdout(StringIO()):
            for origin in (None, WEST):
                msg = SimpleNamespace(topic=topic, payload=json.dumps(dict(data, origin_id=origin)).encode(), retain=True)
                on_message(None, {'packet_sink': reports.append}, msg)
        self.assertEqual(reports[0].origin_id, EAST)
        self.assertIsNone(reports[1].origin_id)
        self.assertEqual(reports[0].source_at, BASE)
        self.assertTrue(reports[0].mqtt_retained)
