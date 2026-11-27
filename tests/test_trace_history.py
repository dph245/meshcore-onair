from contextlib import closing, ExitStack
from datetime import datetime, timezone
import asyncio
import gzip
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
from threading import Thread
import time
import unittest
from collections import Counter
from http.client import HTTPConnection
from unittest.mock import patch
import uvicorn

from onair_archive import Archive
from onair_mqtt import build_packet
from onair_observer_radio import RadioReport, radio_profile_at, record_radio
from onair_trace_history import backfill_batch, links, measurement, record, status
from onair_trace_positions import QUIET_SECONDS, TracePositionCache
from onair_trace_quality import DAY, asymmetry_category, percentiles, reserve_category
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
C5355091 = '2607312F262A2A2B33915035C5E0DC6EFD0277730034747400E76F33A924BF92B9896F33A924747400E777730034'


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

    def advert(self, key, offset, lat, *, stamp=None, lon=11):
        packet = build_packet(dict(raw='1500', direction='rx')).to_dict()
        packet['received_at'] = iso(offset)
        packet['decoded'].update(payload_name='ADVERT', payload_type=4, advert=dict(
            signature_status='Gültig', public_key=key, name=key[:8], node_type=2,
            latitude=lat, longitude=lon, timestamp=BASE + (offset if stamp is None else stamp)))
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
        self.assertEqual(sf7['reverse'], dict(count=2, last=.25, min=0, p10=.025, median=.125, p90=.225, max=.25,
                    first_at=BASE + 4, last_at=BASE + 10, quality=dict(confirmed=1, last_known=1), reserve=None, sf7=None))
        self.assertEqual(sf7['forward']['median'], -2.5)
        self.assertIsNone(groups[8]['forward'])
        self.assertEqual(self.read(sf='8')['summary']['visible_samples'], 1)
        self.assertEqual(self.read(sf='unknown')['summary']['visible_samples'], 1)
        self.assertEqual(link['analysis']['reserve']['category'], 'unknown')
        self.assertEqual(link['analysis']['sf7']['category'], 'unknown')
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
        self.assertEqual(self.read(sf='unknown')['links'][0]['analysis']['sf7'], dict(category='unknown'))

    def test_reserve_boundaries_and_histogram_interpolation(self):
        self.assertEqual([reserve_category(x) for x in (-1, 2.999, 3, 5.999, 6)], ['low', 'low', 'watch', 'watch', 'good'])
        self.assertEqual([asymmetry_category(x) for x in (0, 3, 3.001, 6, 6.001)], ['good', 'good', 'watch', 'watch', 'low'])
        q = (0, .1, .5, .9, 1)
        self.assertEqual(percentiles(Counter({-12: 1}), 1, q), [-3] * 5)
        self.assertEqual(percentiles(Counter({-12: 2, -4: 1, 0: 1, 8: 1}), 5, q), [-3, -3, -1, 1.2, 2])

    def test_sf_only_is_insufficient_for_reserve_and_forecast(self):
        self.advert(A, 1, 52)
        self.advert(B, 1, 51)
        with self.db:
            record_radio(self.db, RadioReport(EAST, None, BASE + 2, BASE + 3, False, dict(spreading_factor=8)))
        for index in range(3):
            self.packet(10 + index, (1, -3, -5), tag=index, path=(A, B, A))
        link, = self.read(sf='8')['links']
        self.assertEqual(link['profiles'][0]['profile'], dict(spreading_factor=8))
        self.assertEqual(link['profiles'][0]['forward']['count'], 3)
        self.assertEqual(link['coverage']['forward']['assigned'], 0)
        self.assertEqual(link['analysis']['reserve']['category'], 'unknown')
        self.assertEqual(link['analysis']['sf7']['category'], 'unknown')

    def test_lower_tail_forecast_and_single_direction_use_one_trace_per_profile(self):
        self.advert(A, 1, 52)
        self.advert(B, 1, 51)
        self.radio(EAST, 2, 8)
        self.radio(WEST, 2, 8)
        for index in range(10):
            # A → B twice in the same TRACE. Keep the lower SNR while retaining both raw hops.
            stamp = 10 + index * 10
            snr = -12 if index == 0 else -4
            self.packet(stamp, (1, 2, -3, snr), tag=index, path=(A, B, A, B))
            self.packet(stamp + 1, (1, 2, -3, snr), tag=index, path=(A, B, A, B), observer=WEST)
        self.assertEqual(self.read(end=35)['links'][0]['analysis']['reserve']['category'], 'good')
        summary = self.read(sf='8')
        link, = summary['links']
        group, = link['profiles']
        self.assertEqual(group['reverse']['count'], 10)
        self.assertEqual((group['reverse']['min'], group['reverse']['p10'], group['reverse']['median']), (-12, -4.8, -4))
        self.assertAlmostEqual(group['reverse']['reserve']['db'], 5.2)
        self.assertEqual(group['reverse']['reserve']['statistic'], 'p10')
        self.assertEqual(link['analysis']['reserve'], dict(category='watch', db=5.2, profile_index=0,
                                                          direction='reverse', directions=2))
        self.assertEqual(link['analysis']['sf7'], dict(category='low', db=2.7, profile_index=0,
                                                       direction='reverse', directions=2))
        self.assertEqual(link['analysis']['asymmetry']['category'], 'unknown')  # Same-hour burst.
        self.assertEqual(link['coverage']['reverse']['count'], 10)
        self.assertEqual(link['analysis']['coverage']['category'], 'low')
        self.assertEqual(summary['summary']['visible_samples'], 30)
        page = self.read(sf='8', pair=(B, A))
        self.assertEqual(page['total'], 30)
        self.assertEqual(page['observers'], sorted([EAST, WEST]))

    def test_exact_profiles_and_temporal_comparability(self):
        self.advert(A, 1, 52)
        self.advert(B, 1, 51)
        self.radio(EAST, 2, 8, cr=5)
        self.radio(WEST, 2, 8, cr=8)
        for index in range(4):
            delta = index // 2 * 3600 + index % 2 * 10
            self.packet(30 + delta, (1, -4), tag=10 + index, path=(B, A))
            self.packet(40 + delta, (1, -9), tag=20 + index, path=(A, B), observer=WEST)
            self.packet(7300 + delta, (1, -9), tag=30 + index, path=(A, B))
        link, = self.read(end=15000)['links']
        self.assertEqual(len(link['profiles']), 2)
        self.assertEqual(link['analysis']['asymmetry']['category'], 'unknown')
        driver = link['profiles'][link['analysis']['reserve']['profile_index']]
        self.assertEqual(driver['profile']['coding_rate'], 5)
        self.assertEqual(link['analysis']['reserve']['directions'], 2)
        before = self.read(end=7200)['links'][0]
        selected = before['profiles'][before['analysis']['reserve']['profile_index']]
        self.assertEqual(selected['profile']['coding_rate'], 8)
        self.assertEqual(before['analysis']['reserve']['directions'], 1)
        self.assertEqual(before['analysis']['asymmetry']['category'], 'unknown')
        for index in range(4):
            delta = index // 2 * 3600 + index % 2 * 10
            self.packet(50 + delta, (1, -9), tag=40 + index, path=(A, B))
        link, = self.read(end=15000, sf='8')['links']
        finding = link['analysis']['asymmetry']
        self.assertEqual((finding['category'], finding['db']), ('watch', 5))
        self.assertEqual(link['profiles'][finding['profile_index']]['asymmetry'],
                         dict(db=5, signed_db=5, windows=2, counts=[4, 4]))
        for index in range(8):
            self.packet(80 + index, (1, -4), tag=50 + index, path=(B, A))
        link, = self.read(end=15000)['links']
        self.assertEqual(link['analysis']['asymmetry']['category'], 'unknown')  # One window is now 10:2.

    def test_temporal_coverage_age_and_missing_counter_direction(self):
        self.advert(A, 1, 52)
        self.advert(B, 1, 51)
        self.radio(EAST, 2, 8)
        for index in range(12):
            stamp = 10 + (index // 4) * DAY + (index % 4) * 2
            self.packet(stamp, (1, -4, -6), tag=index, path=(B, A, B))
        def category(end):
            return self.read(end=end)['links'][0]['analysis']['coverage']['category']

        self.assertEqual(category(900), 'low')
        self.assertEqual(category(2 * DAY), 'watch')
        self.assertEqual(category(3 * DAY), 'good')
        self.assertEqual(category(13 * DAY), 'watch')
        self.assertEqual(category(40 * DAY), 'low')
        self.packet(3 * DAY, (1, -4), tag=20, path=(A, B), observer=None)
        link, = self.read(end=4 * DAY, sf='unknown')['links']
        self.assertIsNone(link['coverage']['forward'])
        self.assertEqual(link['coverage']['reverse']['assigned'], 0)
        self.assertEqual(link['analysis']['coverage']['category'], 'low')
        self.assertEqual(link['analysis']['sf7']['category'], 'unknown')

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
        during = self.packet(9, (1, 3), tag=4, size=4, path=(A, B))
        result = self.read()
        self.assertEqual(result['summary']['visible_samples'], 1)
        self.assertEqual(result['summary']['unmapped_samples']['position_conflict'], 1)
        self.assertEqual(measurement(self.db, during)['hops'][0]['state'], 'resolved')
        self.assertEqual(measurement(self.db, during)['hops'][0]['location_issue'], 'position_conflict')

    def test_real_c5355091_and_four_resolved_repeaters(self):
        # Raw TRACE from archive #2654833. Coordinates and old stamp ties are
        # reproduced from the companion ADVERT evidence with compact test times.
        self.advert(A, 1, 52.167070, lon=10.554380)
        self.advert(A, 2, 0, lon=0, stamp=1)
        self.advert(A, 3, 52.167090, lon=10.554400, stamp=1)
        self.advert(B, 4, 52.168030, lon=10.554110)
        self.advert(C, 5, 52.173110, lon=10.550730)
        self.advert(D, 6, 52.165830, lon=10.540430)
        self.advert(D, 7, 52.165853, lon=10.538736, stamp=6)
        later = QUIET_SECONDS + 10
        self.advert(D, later - 1, 52.165853, lon=10.538736)
        self.advert(D, later, 52.165853, lon=10.538736)
        raw = build_packet(dict(raw=C5355091, direction='rx', origin_id=EAST)).to_dict()
        self.archive._write(self.db, [dict(raw, received_at=iso(later + 2), source_at=BASE + later + 1)])
        ident = self.db.execute('SELECT id FROM trace_measurement').fetchone()[0]
        details = measurement(self.db, ident)
        self.assertEqual(details['tag'], 'c5355091')
        self.assertEqual({hop['public_key'] for hop in details['hops']}, {A, B, C, D})
        self.assertTrue(all(hop['state'] == 'resolved' and hop['location_issue'] is None for hop in details['hops']))
        samples = self.db.execute('SELECT source,target,snr_qdb FROM trace_sample ORDER BY hop').fetchall()
        self.assertEqual([(a.hex(), b.hex(), q / 4) for a, b, q in samples],
            [(A[:8], B[:8], 11.75), (B[:8], C[:8], 9.5), (C[:8], D[:8], 10.5),
             (D[:8], C[:8], 10.5), (C[:8], B[:8], 10.75), (B[:8], A[:8], 12.75)])
        result = self.read(start=later + 1, end=later + 2)
        self.assertEqual(result['summary']['visible_samples'], 6)
        self.assertEqual(len(result['links']), 3)
        self.assertTrue(all(link['profiles'][0]['forward']['count'] == link['profiles'][0]['reverse']['count'] == 1
                            for link in result['links']))
        individual = self.archive.trace_map_detail(ident)
        self.assertEqual([(h['position'], h['location_issue']) for h in individual['hops']],
                         [(h['position'], h['location_issue']) for h in details['hops']])
        self.assertEqual(self.db.execute('SELECT source,target,snr_qdb FROM trace_sample ORDER BY hop').fetchall(), samples)

    def test_location_moves_and_duplicate_adverts_do_not_confirm(self):
        self.advert(A, 1, 52)
        self.advert(B, 1, 51)
        before = self.packet(2, (1, 2), path=(A, B))
        change = QUIET_SECONDS + 2
        self.advert(A, change, 53)
        self.advert(A, change + 1, 53, stamp=change)
        pending = self.packet(change + 2, (1, 2), path=(A, B), tag=2)
        self.assertEqual(measurement(self.db, pending)['hops'][0]['location_issue'], 'position_unconfirmed')
        self.advert(A, change + 3, 53)
        after = self.packet(change + 4, (1, 2), path=(A, B), tag=3)
        for ident, lat in ((before, 52), (after, 53)):
            self.assertEqual(measurement(self.db, ident)['hops'][0]['position']['latitude'], lat)
        self.assertIsNone(measurement(self.db, pending)['hops'][0]['position'])
        self.assertEqual(self.read(0, 10)['links'][0]['positions'][1]['latitude'], 52)
        self.assertEqual(self.read(change, change + 5)['links'][0]['positions'][1]['latitude'], 53)

    def test_alternating_sites_and_a_historical_conflict_interval(self):
        self.advert(A, 1, 52)
        self.advert(B, 1, 51)
        before = self.packet(2, (1, 9), path=(A, B))
        self.advert(A, 3, 53, stamp=1)
        for offset, lat in enumerate((52, 53, 52, 53, 53), start=4):
            self.advert(A, offset, lat)
        during = self.packet(9, (1, 99), tag=2, path=(A, B))
        self.assertEqual(measurement(self.db, during)['hops'][0]['location_issue'], 'position_conflict')
        later = QUIET_SECONDS + 10
        self.advert(A, later, 53, stamp=8)
        self.assertEqual(self.read(9, later + 1)['summary']['unmapped_samples'], {'position_conflict': 1})
        self.advert(A, later + 1, 53)
        after = self.packet(later + 2, (1, 10), tag=3, path=(A, B))
        for ident, lat in ((before, 52), (after, 53)):
            self.assertEqual(measurement(self.db, ident)['hops'][0]['position']['latitude'], lat)
        self.assertEqual(measurement(self.db, during)['hops'][0]['location_issue'], 'historical_position_conflict')
        self.assertEqual(self.archive.trace_map_detail(during)['hops'][0]['location_issue'],
                         'historical_position_conflict')
        self.assertEqual(self.read(0, later + 3)['links'][0]['profiles'][0]['reverse']['max'], 10)

    def test_position_tolerance_and_unset_coordinates(self):
        self.advert(A, 1, None, lon=None)
        self.advert(A, 2, 0, lon=0)
        self.advert(B, 2, 51)
        early = self.packet(3, (1, 2), path=(A, B))
        self.advert(A, 4, 52)
        self.advert(A, 5, 52.00001, stamp=4)
        self.advert(A, 6, 0, lon=0)
        late = self.packet(7, (1, 2), tag=2, path=(A, B))
        self.assertEqual(measurement(self.db, early)['hops'][0]['location_issue'], 'missing_position')
        self.assertEqual(measurement(self.db, late)['hops'][0]['position']['latitude'], 52)
        self.assertEqual(measurement(self.db, late, position_cache=TracePositionCache(0))['hops'][0]['location_issue'],
                         'position_conflict')

    def test_funkfeuer_prefix_collision_and_unset_bridge(self):
        bridge = 'dd4c42a153b97c11'.ljust(64, '0')
        ampleben = 'dd4c42d1ac55b5ac'.ljust(64, '0')
        self.advert(bridge, 1, 0, lon=0)
        self.advert(ampleben, 1, 52.18563, lon=10.75014)
        self.advert(B, 1, 51)
        short = self.packet(2, (1, 2), path=(ampleben, B), size=2)
        exact = self.packet(3, (1, 2), tag=2, path=(bridge, B), size=4)
        for ident, expected in ((short, 'ambiguous'), (exact, 'missing_position')):
            self.assertEqual(measurement(self.db, ident)['hops'][0]['location_issue'], expected)
            self.assertEqual(self.archive.trace_map_detail(ident)['hops'][0]['location_issue'], expected)
        self.assertEqual(self.read()['links'], [])

    def test_cached_evidence_catches_up_and_reloads_after_archive_edit(self):
        cache = TracePositionCache()
        self.advert(A, 1, 52)
        self.advert(B, 1, 51)
        ident = self.packet(3, (1, 2), path=(A, B))
        self.assertIsNone(measurement(self.db, ident, position_cache=cache)['hops'][0]['location_issue'])
        self.advert(A, 2, 53, stamp=1)
        self.assertEqual(measurement(self.db, ident, position_cache=cache)['hops'][0]['location_issue'],
                         'position_conflict')
        with self.db:
            self.db.execute('DELETE FROM packets WHERE id=?', (ident + 1,))
        self.assertIsNone(measurement(self.db, ident, position_cache=cache)['hops'][0]['location_issue'])

    def test_both_link_endpoints_use_the_receiver_measurement_time(self):
        self.advert(B, 1, 51)
        ident = self.packet(25, (1,), size=4, path=(A, B), source=20)
        self.advert(A, 21, 52)
        full = self.packet(26, (1, 2), size=4, path=(A, B), source=22)
        self.assertEqual(self.read()['summary']['visible_samples'], 1)
        correlated = measurement(self.db, ident)['hops']
        individual = self.archive.trace_map_detail(full)['hops']
        self.assertIsNone(correlated[0]['position'])
        self.assertEqual(correlated[1]['from_position'], dict(latitude=52, longitude=11))
        self.assertEqual(individual[1]['from_position'], correlated[1]['from_position'])
        self.assertEqual(individual[1]['position'], correlated[1]['position'])

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

    def test_trace_overview_gzip_respects_accept_encoding(self):
        self.advert(A, 1, 52)
        self.advert(B, 1, 51)
        self.packet(3, (1, -5), path=(A, B))
        # Use the real HTTP server and worker pool, with the MQTT lifespan off.
        with ExitStack() as resources:
            listener = resources.enter_context(socket.socket())
            resources.enter_context(patch.object(app.state, 'archive', self.archive, create=True))
            listener.bind(('127.0.0.1', 0))
            server = uvicorn.Server(uvicorn.Config(app, lifespan='off', loop='asyncio',
                                                   log_level='error', access_log=False))
            worker = Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
            worker.start()

            def stop_server():
                server.should_exit = True
                worker.join(4)
                self.assertFalse(worker.is_alive())

            resources.callback(stop_server)
            deadline = time.monotonic() + 4
            while worker.is_alive() and not server.started and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(server.started)

            def request(encoding=None):
                with closing(HTTPConnection(*listener.getsockname(), timeout=3)) as client:
                    client.putrequest('GET', '/api/trace-links', skip_accept_encoding=True)
                    if encoding is not None:
                        client.putheader('Accept-Encoding', encoding)
                    client.endheaders()
                    response = client.getresponse()
                    return response.status, response.headers, response.read()

            status, headers, original = request()
            self.assertEqual(status, 200)
            self.assertEqual(headers['vary'], 'Accept-Encoding')
            self.assertNotIn('content-encoding', headers)
            status, headers, body = request('br, gzip;q=0.7')
            self.assertEqual(status, 200)
            self.assertEqual(headers['content-encoding'], 'gzip')
            self.assertEqual(headers['cache-control'], 'no-store')
            self.assertLess(len(body), len(original))
            self.assertEqual(gzip.decompress(body), original)
            _, headers, body = request('gzip;q=0, br')
            self.assertNotIn('content-encoding', headers)
            self.assertEqual(body, original)

    def test_advert_conflict_uses_expression_index_seek_in_attached_archive(self):
        from tools.benchmark_trace_history import build_projection, connect_source

        other = self.path.with_name('projection.sqlite3')
        with closing(sqlite3.connect(other)) as db:
            connect_source(db, self.path)
            build_projection(db)
            cache = TracePositionCache(attached_source=True)
            plan = [description for _, _, _, description in db.execute(
                'EXPLAIN QUERY PLAN ' + cache.evidence_sql, (json.dumps([A, B]),))]
            self.assertTrue(any('SEARCH' in line and 'packets_advert_key_received' in line
                                for line in plan), plan)
            self.assertFalse(any('SCAN source.packets' in line for line in plan), plan)
            plan = str(db.execute('EXPLAIN QUERY PLAN ' + cache.new_sql, (0, 10)).fetchall())
            self.assertIn('packets_kind_id (kind=? AND id>? AND id<?)', plan)

    def test_benchmark_cli_timeout_progress_and_cleanup(self):
        self.packet(3, (1, 2))
        root = Path(__file__).resolve().parents[1]
        temp = self.path.parent / 'scratch'
        temp.mkdir()
        fixture = self.path.parent / 'fixtures'
        command = [sys.executable, str(root / 'tools/benchmark_trace_history.py'),
                   str(self.path), '--fixture-dir', str(fixture)]
        env = dict(os.environ, PYTHONPATH=str(root), TMPDIR=str(temp))
        stopped = subprocess.run(command + ['--timeout', '.06'], env=env, capture_output=True,
                                 text=True, timeout=5)
        self.assertEqual(stopped.returncode, 124, stopped.stderr)
        self.assertIn('Zeitlimit', stopped.stderr)
        self.assertEqual(stopped.stdout, '')
        self.assertFalse(fixture.exists())
        self.assertEqual(list(temp.iterdir()), [])

        completed = subprocess.run(command + ['--timeout', '4'], env=env, capture_output=True,
                                   text=True, timeout=6, check=True)
        report = json.loads(completed.stdout)
        self.assertEqual(report['trace_receptions'], 1)
        self.assertIn('backfill', report['section_seconds'])
        self.assertIn('window_all', report['section_seconds'])
        self.assertIn('fixtures', report['section_seconds'])
        self.assertIn('Aggregation', completed.stderr)
        self.assertEqual({path.name for path in fixture.iterdir()},
                         {f'trace-links-{days}.json' for days in (0, 1, 7, 30)})
        self.assertEqual(list(temp.iterdir()), [])

    def test_benchmark_deadline_interrupts_running_sql(self):
        from tools.benchmark_trace_history import Run

        run = Run(.04)
        with closing(sqlite3.connect(':memory:')) as db, self.assertRaisesRegex(sqlite3.OperationalError, 'interrupted'):
            db.set_progress_handler(run.sqlite_progress, 10000)
            with run.section('sql-test', 'SQLite-Deadline prüfen'):
                db.execute('''WITH RECURSIVE seq(n) AS (
                    SELECT 1 UNION ALL SELECT n+1 FROM seq WHERE n<1000000000
                ) SELECT sum(n) FROM seq''').fetchone()
