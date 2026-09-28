import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from onair_archive import Archive
from onair_discovery import discovery_sessions
from onair_mqtt import build_packet
from onair_web import app


KEY = 'aabbccddeeff0011' + '22' * 24


def request(tag=1, mask=4):
    return bytes([0x80, mask]) + tag.to_bytes(4, 'little')


def reply(tag=1, key=KEY, snr=-11):
    return b'\x92' + bytes([snr & 255]) + tag.to_bytes(4, 'little') + bytes.fromhex(key)


def reception(payload, received=1000, observer='east', direction='rx'):
    p = build_packet(dict(raw='2d00' + payload.hex(), direction=direction,
                          origin_id=observer, origin=observer)).to_dict()
    p['received_at'] = datetime.fromtimestamp(received, timezone.utc).isoformat()
    return p


def sessions(payloads, names=None):
    rows = [(i, when, reception(payload, when)) for i, (when, payload) in enumerate(payloads)]
    return discovery_sessions(rows, names or {})[0]


class DiscoveryTests(unittest.TestCase):
    def test_requests_replies_repeats_and_database_names(self):
        items = sessions([(1000, request()), (1001, reply()), (1002, reply()),
                          (1003, reply(key=KEY[:16], snr=8)), (1004, request())], {KEY: 'Repeater'})
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item['request']['node_types'], ['Repeater'])
        self.assertEqual(item['request_receptions'], 2)
        self.assertEqual(item['receptions'], 5)
        self.assertEqual(item['unknown_nodes'], 0)
        self.assertEqual(len(item['responses']), 1)
        response = item['responses'][0]
        self.assertEqual(response['name'], 'Repeater')
        self.assertEqual(response['public_key'], KEY)
        self.assertEqual(response['receptions'], 3)
        self.assertEqual((response['snr_min'], response['snr_max']), (-2.75, 2))

    def test_orphans_empty_requests_tag_reuse_and_reordered_delivery(self):
        items = sessions([(1000, reply()), (1002, request()), (1061, request()),
                          (1062, request(tag=2)), (1063, reply(tag=3))])
        self.assertEqual(len(items), 4)
        self.assertIsNone(items[0]['request'])
        self.assertEqual(items[0]['unknown_nodes'], 1)
        self.assertEqual(items[1]['responses'], [])
        self.assertIsNotNone(items[-1]['request'])
        self.assertEqual(len(sessions([(1, request()), (2, request(mask=8))])), 2)

    def test_unknown_and_ambiguous_prefixes(self):
        other = KEY[:16] + '33' * 24
        item = sessions([(1, reply(key=KEY[:16]))], {KEY: 'A', other: 'B'})[0]
        self.assertTrue(item['responses'][0]['ambiguous'])
        self.assertIsNone(item['responses'][0]['name'])
        self.assertEqual(item['responses'][0]['public_key'], KEY[:16])

    def test_observers_scopes_and_invalid_packets(self):
        a = reception(request(), observer='east')
        b = reception(reply(), observer='west')
        scoped = reception(reply())
        scoped['decoded'].update(route_type=0, transport_code='12345678')
        bad = reception(b'\x92')
        version = reception(reply())
        version['decoded']['payload_ver'] = 1
        rows = [(i, 1000+i, p) for i, p in enumerate([
            a, b, scoped, bad, version, reception(reply(), direction='tx'), reception(b'\x70')])]
        items, ignored = discovery_sessions(rows, {})
        self.assertEqual(ignored, 4)
        self.assertEqual(len(items), 2)
        self.assertEqual({o['id'] for o in items[1]['observers']}, {'east', 'west'})
        self.assertIsNone(items[0]['request'])

    def test_archive_old_packets_limits_and_http_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(Path(folder) / 'test.sqlite3')
            archive.close()
            p = reception(request(), 10000)
            p['decoded'].pop('discovery', None)
            with archive.connect() as db:
                archive._write(db, [p, reception(reply(), 10001), reception(request(2), 1)])
            async def run_endpoint(fn, **kwargs):
                return fn(**kwargs)
            async def get(query):
                sent = []
                async def receive():
                    return {'type': 'http.request', 'body': b''}
                async def send(message):
                    sent.append(message)
                await app({'type': 'http', 'method': 'GET', 'path': '/api/discovery',
                           'query_string': query, 'headers': [], 'scheme': 'http',
                           'http_version': '1.1', 'root_path': ''}, receive, send)
                return sent
            with patch('onair_archive.time.time', return_value=10002), \
                    patch.object(app.state, 'archive', archive, create=True), \
                    patch('fastapi.routing.run_in_threadpool', run_endpoint):
                messages = asyncio.run(get(b'hours=1'))
                self.assertEqual(messages[0]['status'], 200)
                result = json.loads(messages[1]['body'])
                self.assertEqual(result['scanned'], 2)
                self.assertEqual(len(result['items'][0]['responses']), 1)
                self.assertTrue(archive.discovery(hours=24, limit=1)['more_sessions'])
                for query in (b'hours=0', b'hours=169', b'limit=101'):
                    self.assertEqual(asyncio.run(get(query))[0]['status'], 422)
            with archive.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM nodes').fetchone()[0], 0)
                self.assertNotIn('discovery', json.loads(db.execute(
                    'SELECT packet_json FROM packets ORDER BY id LIMIT 1').fetchone()[0])['decoded'])
