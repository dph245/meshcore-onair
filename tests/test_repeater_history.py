"""Archive History must keep reception identity independently of the packet hash."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from onair_archive import Archive
import onair_web
from test_onair import packet


NOW = 1_800_000_000
EAST, WEST = 'abcdef' + '0' * 58, 'abcdef' + '1' * 58


def reception(received, observer, rssi, snr, raw='1541aabb', name='Same'):
    item = packet(raw, RSSI=rssi, SNR=snr).to_dict()
    item.update(received_at=datetime.fromtimestamp(received, timezone.utc).isoformat(),
                origin_id=observer, origin=name, snr=snr)
    return item


class RepeaterHistoryTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.archive = Archive(Path(folder) / 'archive.sqlite3')
        self.addCleanup(self.archive.close)

    def write(self, items):
        with self.archive.connect() as db:
            self.archive._write(db, items)

    def test_same_hash_and_timestamp_keep_every_reception_and_its_values(self):
        at = NOW - 3600
        old = reception(at - 0.25, EAST, -120, -15)
        first = reception(at, EAST, -90, 1)
        second = reception(at, WEST, -80, 8)
        third = reception(at, EAST, -90, 3)
        legacy = reception(at + 1, None, -100, -2, name=None)
        missing = reception(at + 2, WEST, None, 9)
        self.write([old, first, second, third, legacy, missing])

        result = self.archive.repeater_history('aabb', hours=1, now=NOW)
        self.assertEqual(result['total'], 4)
        self.assertFalse(result['sampled'])
        self.assertEqual(result['items'], [
            dict(received=at, rssi=-90, origin_id=EAST, origin='Same'),
            dict(received=at, rssi=-80, origin_id=WEST, origin='Same'),
            dict(received=at, rssi=-90, origin_id=EAST, origin='Same'),
            dict(received=at + 1, rssi=-100, origin_id=None, origin=None),
        ])
        with self.archive.connect() as db:
            rows = db.execute("""SELECT observer_hash, origin_id, json_extract(packet_json,'$.snr')
                                 FROM packets ORDER BY id""").fetchall()
        self.assertEqual(len({row[0] for row in rows}), 1)
        self.assertEqual([row[1:] for row in rows],
                         [(EAST, -15), (EAST, 1), (WEST, 8), (EAST, 3), (None, -2), (WEST, 9)])
        single = self.archive.repeater_history('aabb', 1, now=NOW + 0.25)
        self.assertEqual(single, dict(items=[result['items'][-1]], total=1, has_more=False, sampled=False))
        self.assertEqual(self.archive.repeater_history('aabb', 1, now=NOW + 2)['total'], 0)

    def test_dense_mixed_token_history_matches_bucket_reference(self):
        start = NOW - 9000
        # Out-of-order arrivals and tied times require sorting by reception time and row ID.
        times = [start + i // 2 for i in range(1400)]
        rows = [reception(times[i], (None, EAST, WEST)[i % 3], -80 - i % 21, i % 9,
                          ('1501aa', '1541aabb', '1581aabbcc')[i % 3],
                          'Before' if i < 500 else 'After')
                for i in list(range(700, 1400)) + list(range(700))]
        # A token with a different prefix must stay out of the history.
        self.write(rows + [reception(NOW, WEST, -10, 12, '1541dddd'),
                           reception(NOW, WEST, None, 12)])
        chronological = sorted(enumerate(rows), key=lambda pair: pair[1]['received_at'])
        limit = 40
        count = limit // 4
        expected = {}
        for observer in (None, EAST, WEST):
            for bucket in range(count):
                readings = [(row_id, reading) for row_id, reading in chronological
                            if reading['origin_id'] == observer and bucket == min(count - 1, int(
                                (datetime.fromisoformat(reading['received_at']).timestamp() - start)
                                / (times[-1] - start) * count))]
                extrema = (readings[0], readings[-1], min(readings, key=lambda pair: pair[1]['rssi']),
                           max(readings, key=lambda pair: pair[1]['rssi']))
                expected.update(extrema)
        expected_items = [
            dict(received=datetime.fromisoformat(reading['received_at']).timestamp(),
                 rssi=reading['rssi'], origin_id=reading['origin_id'], origin=reading['origin'])
            for row_id, reading in chronological if row_id in expected
        ]
        result = self.archive.repeater_history('aabbcc', hours=0, limit=limit)
        self.assertEqual(result, dict(items=expected_items, total=len(rows), has_more=False, sampled=True))

    def test_ambiguous_prefix_keeps_its_own_history(self):
        self.write([reception(NOW - i, EAST, -70 - i, 1, raw)
                    for i, raw in enumerate(('1501aa', '1541aabb', '1581aabbcc', '1541aadd'))])
        for identity, rssi in [('aa', [-70]), ('aabbcc', [-72, -71]), ('aadd', [-73]), ('aabb', [])]:
            with self.subTest(identity=identity):
                result = self.archive.repeater_history(identity, hours=0)
                self.assertEqual([item['rssi'] for item in result['items']], rssi)

    def test_compact_response_round_trip_preserves_names_and_expiry(self):
        self.write([reception(NOW - 3598, EAST, -100, 2, name='Old'),
                    reception(NOW - 100, EAST, -90, 5, name='New'),
                    reception(NOW - 50, WEST, -80, 7, name='New'),
                    reception(NOW - 49, None, -110, 1, name=None)])
        with patch.object(onair_web.app.state, 'archive', self.archive, create=True), \
                patch('onair_web.time.time', return_value=NOW):
            legacy = onair_web.repeater_history('AABB', 1)
            response = onair_web.repeater_history('AABB', 1, compact=True)
            whole = onair_web.repeater_history('AABB', 0, compact=True)
            empty = onair_web.repeater_history('FFFF', 1, compact=True)
        data = json.loads(response.body)
        self.assertEqual(data['valid_for'], 2)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(data['total'], legacy['total'])
        self.assertEqual([
            dict(received=received, rssi=rssi, origin_id=data['observers'][i][0],
                 origin=data['observers'][i][1])
            for received, rssi, i in data['points']
        ], legacy['items'])
        self.assertIsNone(json.loads(whole.body)['valid_for'])
        self.assertEqual(json.loads(empty.body), dict(points=[], observers=[], valid_for=None,
                                                     total=0, has_more=False, sampled=False))
