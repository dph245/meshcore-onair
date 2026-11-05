"""RF browser API: temporary fixtures only; read-only checks include authorizer."""
import asyncio
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import json

from onair_archive import Archive
import onair_rf_neighbor_view as view
from onair_web import app

EAST, WEST, NODE = '74'*32, '77'*32, 'ab'*32


class RFViewTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(folder) / 'test.sqlite3'
        self.archive = Archive(self.path)
        self.archive.close()
        self.enterContext(patch.object(app.state, 'archive', self.archive, create=True))
        with self.archive.connect() as db, db:
            db.execute('INSERT INTO nodes(public_key,name,advert_time,first_seen,last_seen) VALUES(?,?,0,0,0)',
                       (NODE, 'Known <Node>'))
            db.execute('''INSERT INTO manual_nodes
                VALUES(?,?,52,10,'fixture',0,0)''', (WEST, 'Manual Observer'))

    def add(self, observer=EAST, timestamp='2026-11-05T12:00:00Z', received='2026-11-05T12:01:00+00:00',
            truncated=None, age=0, snr=0, scopes=None):
        data = dict(origin='RF Observer', origin_id=observer, timestamp=timestamp,
                    neighbors=[dict(pubkey=NODE, snr=snr, heard_secs_ago=age,
                                    scopes=scopes, status='timeout')], truncated=truncated)
        with self.archive.connect() as db:
            self.archive._write_rf_neighbors(db, dict(reception_id=f'fixture-{observer}-{timestamp}-{received}',
                topic=f'meshcore/BER/{observer}/neighbors', received_at=received,
                payload=json.dumps(data).encode(), qos=0, retain=True, dup=False, mid=0))
            return db.execute('SELECT MAX(id) FROM rf_neighbor_messages').fetchone()[0]

    def get(self, path, query=''):
        async def direct(fn, **kwargs):
            return fn(**kwargs)
        async def run():
            messages = []
            async def receive():
                return {'type': 'http.request', 'body': b''}
            async def send(message):
                messages.append(message)
            await app(dict(type='http', method='GET', path=path, query_string=query.encode(),
                           headers=[], scheme='http', server=('test', 80), client=('test', 1),
                           http_version='1.1', root_path=''), receive, send)
            return messages[0]['status'], json.loads(b''.join(m.get('body', b'') for m in messages[1:]))
        with patch('fastapi.routing.run_in_threadpool', direct):
            return asyncio.run(run())

    def test_endpoints_latest_source_time_names_unknown_values_and_observers(self):
        latest = self.add()
        self.add(timestamp='2026-11-04T12:00:00Z', received='2026-11-06T12:00:00+00:00')
        self.add(observer=WEST, age=None, snr=None, scopes='')
        code, data = self.get('/api/rf-neighbors/observers')
        self.assertEqual(code, 200)
        self.assertEqual(len(data['items']), 2)
        self.assertEqual(data['items'][0]['message_id'], latest)
        self.assertEqual(data['items'][1]['name'], 'Manual Observer')
        self.assertEqual(data['items'][0]['reports'], 2)
        code, page = self.get('/api/rf-neighbors/reports', 'observer=' + EAST.upper())
        self.assertEqual(code, 200)
        self.assertEqual(page['items'][0]['message_id'], latest)
        code, data = self.get(f'/api/rf-neighbors/reports/{latest}', 'observer=' + EAST)
        self.assertEqual(code, 200)
        self.assertIsNone(data['report']['truncated'])
        self.assertIsNone(data['report']['queried_neighbors'])
        self.assertIsNone(data['report']['self_scopes'])
        self.assertEqual(data['entries'][0]['name'], 'Known <Node>')
        self.assertEqual(data['entries'][0]['snr'], 0)
        self.assertEqual(data['entries'][0]['heard_secs_ago'], 0)
        self.assertEqual(data['entries'][0]['heard_at'], data['report']['reported_at'])
        self.assertIsNone(data['entries'][0]['scopes'])
        self.assertEqual(data['entries'][0]['status'], 'timeout')
        self.assertNotIn('payload', data['report'])

    def test_pagination_ties_unknown_times_and_cross_observer_cursor(self):
        ids = [self.add(timestamp=f'2026-11-{day:02}T12:00:00Z') for day in range(1, 6)]
        tie = self.add(received='2026-11-06T13:00:00+00:00')
        unknown = self.add(timestamp=None)
        other = self.add(observer=WEST)
        found, before = [], None
        while True:
            page = view.history(self.path, EAST, before=before, limit=2)
            self.assertLessEqual(len(page['items']), 2)
            found.extend(r['message_id'] for r in page['items'])
            before = page['next_before']
            if before is None:
                break
        self.assertEqual(found, [tie] + ids[::-1] + [unknown])
        self.assertEqual(view.history(self.path, EAST, before=unknown)['items'], [])
        self.assertIsNone(view.history(self.path, EAST, before=other))
        self.assertEqual(self.get('/api/rf-neighbors/reports', f'observer={EAST}&before={other}')[0], 404)
        self.assertEqual(self.get(f'/api/rf-neighbors/reports/{other}', f'observer={EAST}')[0], 404)

    def test_empty_bad_parameters_and_missing_report(self):
        self.assertEqual(view.observers(self.path)['items'], [])
        self.assertEqual(view.history(self.path, EAST)['items'], [])
        for path, query in [('/api/rf-neighbors/reports', ''),
                            ('/api/rf-neighbors/reports', 'observer=bad'),
                            ('/api/rf-neighbors/reports', f'observer={EAST}&limit=101'),
                            ('/api/rf-neighbors/reports', f'observer={EAST}&limit=0'),
                            ('/api/rf-neighbors/reports', f'observer={EAST}&before=0'),
                            ('/api/rf-neighbors/observers', 'limit=501')]:
            self.assertEqual(self.get(path, query)[0], 422)
        self.assertEqual(self.get('/api/rf-neighbors/reports/1', f'observer={EAST}')[0], 404)

    def test_detail_limits_entries_and_exact_key_resolution(self):
        message_id = self.add()
        with self.archive.connect() as db, db:
            db.executemany('''INSERT INTO rf_neighbor_entries(message_id,position,pubkey)
                VALUES(?,?,?)''', [(message_id, p, NODE[:6]+'0'*58) for p in range(1, 1002)])
        data = view.detail(self.path, EAST, message_id)
        self.assertEqual(len(data['entries']), 1000)
        self.assertTrue(data['entries_more'])
        self.assertIsNone(data['entries'][1]['name'])
        self.assertEqual(view.observers(self.path, limit=1)['more'], False)
        self.add(observer=WEST)
        self.assertTrue(view.observers(self.path, limit=1)['more'])

    def test_queries_are_read_only_and_do_not_migrate_or_create_database(self):
        message_id = self.add()
        with view.snapshot(self.path) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute('DELETE FROM rf_neighbor_entries')
        original = sqlite3.connect
        def checked(*args, **kwargs):
            self.assertIn('mode=ro', args[0])
            db = original(*args, **kwargs)
            def authorize(action, *unused):
                if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
                              sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_ALTER_TABLE):
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            db.set_authorizer(authorize)
            return db
        with patch.object(view.sqlite3, 'connect', side_effect=checked):
            view.observers(self.path)
            view.history(self.path, EAST)
            view.detail(self.path, EAST, message_id)
        with self.archive.connect() as db, db:
            db.execute('DROP TABLE rf_neighbor_entries')
            db.execute('DROP TABLE rf_neighbor_reports')
            db.execute('DROP TABLE rf_neighbor_messages')
            db.execute('PRAGMA user_version=14')
        self.assertEqual(self.get('/api/rf-neighbors/observers')[0], 503)
        with self.archive.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 14)
        missing = self.path.with_name('missing.sqlite3')
        with self.assertRaises(sqlite3.Error):
            view.observers(missing)
        self.assertFalse(missing.exists())


if __name__ == '__main__':
    unittest.main()
