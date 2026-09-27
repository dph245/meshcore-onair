import asyncio
import json
import random
import unittest
from unittest.mock import patch

from onair_routes import plan_routes, route_nodes, shortest_routes
from onair_web import app


def link(a, b, forward=3, reverse=1, ambiguous=False):
    return dict(source=dict(id=a, name='Node ' + a, resolved=True, ambiguous=ambiguous),
                target=dict(id=b, name='Node ' + b, resolved=True, ambiguous=False),
                forward_count=forward, reverse_count=reverse, last_seen=123,
                distance_km=2)


class RouteTests(unittest.TestCase):
    def test_shortest_alternatives_and_direction_counts(self):
        items = [link('aa', 'bb', reverse=0), link('bb', 'dd'),
                 link('aa', 'cc'), link('cc', 'dd'), link('bb', 'cc')]
        result = plan_routes(items, 'NODE AA', 'dd')
        self.assertEqual([r['hops'] for r in result['routes']], [2, 2, 3, 3])
        first = result['routes'][0]
        self.assertEqual(first['distance_km'], 4)
        self.assertEqual(first['one_way_steps'], 1)
        self.assertEqual(first['unobserved_steps'], 0)
        reverse = plan_routes(items, 'bb', 'aa')['routes'][0]
        self.assertEqual(reverse['unobserved_steps'], 1)
        self.assertEqual(reverse['steps'][0]['forward_count'], 0)
        self.assertEqual(reverse['steps'][0]['reverse_count'], 3)
        directed = plan_routes(items, 'bb', 'aa', observed_only=True)['routes']
        self.assertEqual(directed[0]['hops'], 2)
        self.assertTrue(all(r['unobserved_steps'] == 0 for r in directed))

    def test_disconnected_same_node_limits_and_unknown_distance(self):
        items = [link('aa', 'bb'), link('bb', 'cc'), link('dd', 'ee')]
        self.assertEqual(plan_routes(items, 'aa', 'dd')['routes'], [])
        self.assertEqual(plan_routes(items, 'aa', 'cc', max_hops=1)['routes'], [])
        self.assertEqual(plan_routes(items, 'aa', 'aa')['routes'][0]['hops'], 0)
        items[0]['distance_km'] = None
        self.assertIsNone(plan_routes(items, 'aa', 'cc')['routes'][0]['distance_km'])
        self.assertEqual(len(plan_routes(items, 'aa', 'bb', limit=1)['routes']), 1)

    def test_ambiguous_nodes_cannot_create_routes(self):
        items = [link('aa', 'bb'), link('ff', 'bb', ambiguous=True),
                 link('ff', 'cc', ambiguous=True), link('cc', 'dd')]
        self.assertEqual(plan_routes(items, 'aa', 'dd')['routes'], [])
        self.assertEqual(route_nodes(items)['excluded_links'], 2)
        self.assertNotIn('ff', [n['id'] for n in route_nodes(items)['items']])
        for query in ('', '  ', 'unknown', 'node'):
            with self.assertRaises(ValueError):
                plan_routes(items, query, 'dd')
        # Unresolved but unambiguous hashes remain usable without claiming identity.
        items[0]['source']['resolved'] = False
        self.assertFalse(plan_routes(items, 'aa', 'bb')['routes'][0]['nodes'][0]['resolved'])

    def test_yen_matches_exhaustive_simple_paths(self):
        rng = random.Random(12)
        for _ in range(80):
            graph = {str(i): [] for i in range(7)}
            for a in graph:
                graph[a] = [b for b in graph if a != b and rng.random() < .35]
            max_hops = rng.randrange(1, 7)
            all_paths = []

            def visit(path):
                if path[-1] == '6':
                    all_paths.append(tuple(path))
                elif len(path) <= max_hops:
                    for b in graph[path[-1]]:
                        if b not in path:
                            visit(path + [b])
            visit(['0'])
            result = shortest_routes(graph, '0', '6', 5, max_hops)
            self.assertEqual([len(p) for p in result], sorted(len(p) for p in all_paths)[:5])
            self.assertEqual(len(result), len(set(result)))
            self.assertTrue(all(p in all_paths and len(p) == len(set(p)) for p in result))

    def test_http_validation_and_errors(self):
        async def run_endpoint(fn, **kwargs):
            return fn(**kwargs)

        async def get(path, query=b''):
            messages = []
            async def receive():
                return {'type': 'http.request', 'body': b''}
            async def send(message):
                messages.append(message)
            await app({'type': 'http', 'method': 'GET', 'path': path,
                       'query_string': query, 'headers': [], 'scheme': 'http',
                       'server': ('test', 80), 'client': ('test', 1),
                       'http_version': '1.1', 'root_path': ''}, receive, send)
            return messages[0]['status'], json.loads(messages[1]['body'])

        with patch.object(app.state, 'archive', create=True) as archive, \
                patch('fastapi.routing.run_in_threadpool', run_endpoint):
            archive.route_snapshot.return_value = [link('aa', 'bb', reverse=0)]
            self.assertEqual(asyncio.run(get('/api/routes/nodes'))[0], 200)
            status, body = asyncio.run(get('/api/routes', b'start=bb&target=aa'))
            self.assertEqual(status, 200)
            self.assertEqual(body['routes'][0]['unobserved_steps'], 1)
            status, body = asyncio.run(get('/api/routes', b'start=bb&target=aa&observed_only=true'))
            self.assertEqual(body['routes'], [])
            self.assertEqual(asyncio.run(get('/api/routes', b'start=unknown&target=aa'))[0], 400)
            for query in (b'', b'start=&target=aa', b'start=bb&target=aa&limit=6',
                          b'start=bb&target=aa&max_hops=65', b'start=bb&target=aa&max_hops=0'):
                self.assertEqual(asyncio.run(get('/api/routes', query))[0], 422)


if __name__ == '__main__':
    unittest.main()
