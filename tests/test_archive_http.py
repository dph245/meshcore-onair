"""Archive HTTP regression tests using the real ASGI app and worker pool.

Run where asyncio worker completion notifications are supported:
    timeout 30 .venv/bin/python -m unittest discover -s tests -p test_archive_http.py -v

No server sockets, application lifespan or MQTT connections are started.
"""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from onair_archive import Archive
import onair_mqtt as mqtt
from onair_web import app


async def request(path, headers=(), **params):
    messages = []

    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}

    async def send(message):
        messages.append(message)

    await app({'type': 'http', 'asgi': {'version': '3.0'},
               'method': 'GET', 'path': path, 'raw_path': path.encode(),
               'query_string': urlencode(params).encode(), 'headers': list(headers),
               'scheme': 'http', 'server': ('test', 80), 'client': ('test', 1),
               'http_version': '1.1', 'root_path': ''}, receive, send)
    response = next(m for m in messages if m['type'] == 'http.response.start')
    body = b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')
    return response['status'], dict(response['headers']), body


async def get(path, **params):
    status, _, body = await request(path, **params)
    return status, json.loads(body)


class ArchiveHttpTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='onair-http-audit-')
        self.addCleanup(folder.cleanup)
        self.archive = Archive(Path(folder.name) / 'archive.sqlite3')
        self.archive.accept(mqtt.build_packet({'raw': '1500', 'hash': 'ABCD'}))
        self.archive.close()
        with self.archive.connect() as db, db:
            db.executemany('''INSERT INTO nodes
                (public_key,name,advert_time,first_seen,last_seen) VALUES(?,?,0,0,0)''',
                           [('ab' * 32, 'Normal node'), ('cd' * 32, 'Second node')])
        self.state_patch = patch.object(app.state, 'archive', self.archive, create=True)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

    def test_archive_stats(self):
        status, body = asyncio.run(get('/api/archive/stats'))
        self.assertEqual(status, 200)
        self.assertEqual(body, dict(total_packets=1, packets_last_24h=1,
                                    database_bytes=self.archive.path.stat().st_size))

    def test_injection_payloads_remain_literal(self):
        async def check():
            for payload in ("' OR 1=1 --", "x' UNION SELECT 1,2 --",
                            "'; DROP TABLE packets; --", "'/**/OR/**/1=1--",
                            '" OR "1"="1', '%', '_', "' OR 1=1 --*"):
                for path, fields in (('/api/archive', ('q', 'kind', 'channel', 'observer_hash')),
                                     ('/api/nodes', ('q',))):
                    for field in fields:
                        with self.subTest(path=path, field=field, payload=payload):
                            status, body = await get(path, **{field: payload})
                            self.assertEqual(status, 200)
                            self.assertEqual(body['items'], [])
        asyncio.run(check())
        self.assertEqual(len(self.archive.search()['items']), 1)
        with self.archive.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM nodes').fetchone()[0], 2)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_invalid_parameters_are_rejected(self):
        async def check():
            for path, fields in (('/api/archive', ('since', 'until', 'before', 'limit')),
                                 ('/api/nodes', ('after', 'limit'))):
                for field in fields:
                    with self.subTest(path=path, field=field):
                        self.assertEqual((await get(path, **{field: "' OR 1=1 --"}))[0], 422)
            for path in ('/api/archive', '/api/nodes'):
                for params in ({'q': 'x' * 201}, {'limit': 0}, {'limit': 101}):
                    with self.subTest(path=path, params=params):
                        self.assertEqual((await get(path, **params))[0], 422)
            self.assertEqual((await get('/api/archive', before=0))[0], 422)
            self.assertEqual((await get('/api/nodes', after='g' * 64))[0], 422)
        asyncio.run(check())

    def test_node_prefix_normalization_and_pagination(self):
        async def check():
            status, body = await get('/api/nodes', q=' AB* ')
            self.assertEqual(status, 200)
            self.assertEqual([n['public_key'] for n in body['items']], ['ab' * 32])
            status, first = await get('/api/nodes', limit=1)
            self.assertEqual(status, 200)
            status, second = await get('/api/nodes', limit=1, after=first['next_after'].upper())
            self.assertEqual(status, 200)
            self.assertEqual([n['public_key'] for n in second['items']], ['cd' * 32])
            self.assertIsNone(second['next_after'])
        asyncio.run(check())

    def test_stored_sql_text_is_searchable_as_data(self):
        literal = "' OR 1=1 --"
        with self.archive.connect() as db, db:
            db.execute('UPDATE nodes SET name=? WHERE public_key=?', (literal, 'cd' * 32))
            db.execute('UPDATE packets SET search_text=?', (literal.casefold(),))

        async def check():
            for path in ('/api/archive', '/api/nodes'):
                status, body = await get(path, q=literal)
                self.assertEqual(status, 200)
                self.assertEqual(len(body['items']), 1)
        asyncio.run(check())
