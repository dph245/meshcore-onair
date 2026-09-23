import json
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from starlette.requests import Request

from onair_archive import Archive
from onair_neighbors import neighbor_map, neighbor_page
from onair_web import app, conditional_neighbors


def link(i, distance=None):
    return dict(source=dict(id=f'{i:064x}', name=f'Node{i}', resolved=True, ambiguous=False),
                target=dict(id='f' * 64, name='Ziel', resolved=True, ambiguous=False),
                count=i, forward_count=i, reverse_count=0 if i % 2 else i,
                first_seen=1, last_seen=i, distance_km=distance)


class NeighborApiTests(unittest.TestCase):
    def test_http_routes_validate_queries_and_honor_etags(self):
        async def run_endpoint(fn, **kwargs):
            return fn(**kwargs)

        async def get(path, query=b'', headers=None):
            messages = []
            async def receive():
                return {'type': 'http.request', 'body': b''}
            async def send(message):
                messages.append(message)
            await app({'type': 'http', 'method': 'GET', 'path': path,
                       'query_string': query, 'headers': headers or [],
                       'scheme': 'http', 'server': ('test', 80), 'client': ('test', 1),
                       'http_version': '1.1', 'root_path': ''}, receive, send)
            return messages

        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(Path(folder) / 'test.db')
            archive.close()
            with patch.object(app.state, 'archive', archive, create=True), \
                    patch.object(archive, 'neighbors', return_value={'items': [link(1, 12)]}), \
                    patch('fastapi.routing.run_in_threadpool', run_endpoint):
                for path in ('/api/repeater-neighbors/table', '/api/repeater-neighbors/map'):
                    messages = asyncio.run(get(path))
                    self.assertEqual(messages[0]['status'], 200)
                    etag = dict(messages[0]['headers'])[b'etag']
                    messages = asyncio.run(get(path, headers=[(b'if-none-match', etag)]))
                    self.assertEqual(messages[0]['status'], 304)
                    self.assertEqual(messages[1]['body'], b'')
                for query in (b'limit=101', b'limit=0', b'page=-1', b'sort=bad', b'q=' + b'a' * 201):
                    self.assertEqual(asyncio.run(get('/api/repeater-neighbors/table', query))[0]['status'], 422)

    def test_filter_sort_and_pagination(self):
        items = [link(i, float(i) if i % 3 else None) for i in range(1, 202)]
        page = neighbor_page(items)
        self.assertEqual(len(page['items']), 100)
        self.assertEqual(page['items'][0]['count'], 201)
        self.assertEqual(page['total'], 201)
        self.assertEqual(neighbor_page(items, page=99)['page'], 2)
        self.assertEqual(len(neighbor_page(items, page=2)['items']), 1)
        self.assertEqual(neighbor_page(items, q='nOdE20')['total'], 3)
        self.assertEqual(neighbor_page(items, q='absent', page=10)['page'], 0)
        self.assertEqual(neighbor_page(items, q='f' * 64)['total'], 201)
        self.assertEqual(neighbor_page(items, one_way=True)['total'], 101)
        self.assertEqual([x['count'] for x in neighbor_page([link(10), link(2)], sort='source', descending=False)['items']], [2, 10])
        for descending in (True, False):
            result = neighbor_page([link(1, 0), link(2, 10), link(3)], sort='distance_km', descending=descending)
            self.assertIsNone(result['items'][-1]['distance_km'])
            self.assertEqual(result['items'][0]['distance_km'], 10 if descending else 0)
        for sort in ('count', 'forward_count', 'reverse_count', 'last_seen'):
            self.assertEqual(neighbor_page([link(2), link(10)], sort=sort)['items'][0]['count'], 10)

    def test_compact_map_preserves_values_and_deduplicates_nodes(self):
        items = [link(1, 0), link(2, 12.3), link(3)]
        result = neighbor_map(items)
        self.assertEqual(result['total'], 3)
        self.assertEqual(len(result['nodes']), 3)
        self.assertEqual(len(result['links']), 2)
        self.assertEqual(result['links'][0][2:], [1, 1, 0, 1, 0])
        self.assertEqual(result['links'][0][1], result['links'][1][1])

    def test_shared_snapshot_etag_and_bounded_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(Path(folder) / 'test.db')
            archive.close()
            with patch.object(archive, 'neighbors', return_value={'items':[link(1, 12)]}) as compute, \
                    patch('onair_archive.time.monotonic', return_value=100) as clock, \
                    patch.object(app.state, 'archive', archive, create=True):
                request = Request({'type':'http', 'headers':[]})
                first = conditional_neighbors(request, 'map')
                etag = first.headers['etag']
                conditional = Request({'type':'http', 'headers':[(b'if-none-match', etag.encode())]})
                repeated = conditional_neighbors(conditional, 'map')
                self.assertEqual(repeated.status_code, 304)
                self.assertEqual(repeated.body, b'')
                archive.neighbor_response('table', page=0)
                archive.neighbors_json()
                self.assertEqual(compute.call_count, 1)
                clock.return_value = 131
                self.assertEqual(conditional_neighbors(conditional, 'map').status_code, 304)
                compute.return_value = {'items':[link(2, 12)]}
                clock.return_value = 162
                self.assertEqual(conditional_neighbors(conditional, 'map').status_code, 200)
                for i in range(70):
                    archive.neighbor_response('table', q=str(i))
                self.assertLessEqual(len(archive._neighbors_responses), 64)
