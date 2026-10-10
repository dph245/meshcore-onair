"""Read-only bootstrap: all identities, no packet-history scan, unchanged map API."""
import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from onair_archive import Archive
from onair_web import app


class MeshLiveTests(unittest.TestCase):
    def test_bootstrap_includes_invisible_collisions_without_scanning_packets(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(Path(folder) / 'test.db')
            archive.close()
            now = time.time()
            with archive.connect() as db, db:
                for key, lat, last in [('abcd00', 52, now), ('abcd11', None, now), ('abcd22', 53, 0)]:
                    db.execute('''INSERT INTO nodes(public_key,name,advert_time,first_seen,last_seen,
                        node_type,latitude,longitude,position_time) VALUES(?,?,1,0,?,2,?,10,1)''',
                               (key.ljust(64, '0'), key, last, lat))
                db.execute("INSERT INTO repeater_receptions VALUES('abcd33',1,NULL,NULL,NULL,0)")
                db.execute("INSERT INTO repeater_pairs VALUES('abcd44','eeff',1,1,0,0,0)")
                # Bootstrap must work without the large reception archive.
                db.execute('DROP TABLE packets')
            before = archive.map_nodes()
            self.assertEqual(len(before['items']), 1)
            result = archive.mesh_live_nodes()
            self.assertEqual(len(result['nodes']), 3)
            self.assertEqual(set(result['tokens']), {'abcd33', 'abcd44', 'eeff'})
            self.assertEqual(archive.map_nodes(), before)
            self.assertNotIn('tokens', before)
            self.assertTrue(all('advert_path' not in n for n in result['nodes']))

    def test_http_parameter_is_opt_in(self):
        async def run_endpoint(fn, **kwargs):
            return fn(**kwargs)

        async def get(query):
            messages = []
            async def receive():
                return {'type': 'http.request', 'body': b''}
            async def send(message):
                messages.append(message)
            await app({'type': 'http', 'method': 'GET', 'path': '/api/map-nodes',
                       'query_string': query, 'headers': [], 'scheme': 'http',
                       'server': ('test', 80), 'client': ('test', 1), 'http_version': '1.1',
                       'root_path': ''}, receive, send)
            return messages

        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(Path(folder) / 'test.db')
            archive.close()
            with patch.object(app.state, 'archive', archive, create=True), \
                    patch('fastapi.routing.run_in_threadpool', run_endpoint):
                old = asyncio.run(get(b''))
                self.assertEqual(old[0]['status'], 200)
                self.assertEqual(json.loads(old[1]['body']), {'items': [], 'inactive': 0, 'without_position': 0})
                mesh = asyncio.run(get(b'mesh_live=true'))
                self.assertEqual(mesh[0]['status'], 200)
                self.assertEqual(json.loads(mesh[1]['body']), {'nodes': [], 'tokens': []})
                self.assertEqual(asyncio.run(get(b'mesh_live=invalid'))[0]['status'], 422)
