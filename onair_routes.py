"""Shortest loop-free candidate routes through observed repeater adjacencies."""
from collections import deque
import heapq


def route_graph(items, observed_only=False):
    nodes, graph, edges = {}, {}, {}
    excluded = 0
    for item in items:
        a, b = item['source'], item['target']
        if any(node.get('ambiguous') or node.get('excluded') for node in (a, b)):
            excluded += 1
            continue
        for node in (a, b):
            nodes[node['id']] = node
            graph.setdefault(node['id'], set())
        for source, target, forward, reverse in (
                (a, b, item['forward_count'], item['reverse_count']),
                (b, a, item['reverse_count'], item['forward_count'])):
            if source['id'] == target['id'] or not (forward or reverse):
                continue
            if observed_only and not forward:
                continue
            graph[source['id']].add(target['id'])
            edges[source['id'], target['id']] = dict(
                source=source['id'], target=target['id'], forward_count=forward,
                reverse_count=reverse, last_seen=item['last_seen'],
                distance_km=item['distance_km'])
    return nodes, {key: sorted(value) for key, value in graph.items()}, edges, excluded


def route_nodes(items):
    nodes, _, _, excluded = route_graph(items)
    return dict(items=sorted(nodes.values(), key=lambda n: (n['name'].casefold(), n['id'])),
                excluded_links=excluded)


def resolve_node(nodes, query):
    query = query.strip().casefold()
    if not query:
        raise ValueError('Bitte Start und Ziel auswählen.')
    exact = [key for key in nodes if key.casefold() == query]
    matches = exact or [key for key, node in nodes.items()
                        if query in key.casefold() or query in node['name'].casefold()]
    if not matches:
        raise ValueError('Node nicht im Nachbargraph gefunden: ' + query)
    if len(matches) != 1:
        raise ValueError('Mehrere Nodes passen zu „' + query + '“. Bitte einen vollständigen Hash auswählen.')
    return matches[0]


def shortest_path(graph, start, target, blocked_nodes, blocked_edges, max_hops):
    """BFS uses one parent per node, rather than expanding all simple paths."""
    queue = deque([(start, 0)])
    parents = {start: None}
    while queue:
        node, depth = queue.popleft()
        if node == target:
            path = []
            while node is not None:
                path.append(node)
                node = parents[node]
            return tuple(reversed(path))
        if depth >= max_hops:
            continue
        for neighbor in graph[node]:
            if (neighbor not in parents and neighbor not in blocked_nodes
                    and (node, neighbor) not in blocked_edges):
                parents[neighbor] = node
                queue.append((neighbor, depth + 1))
    return None


def shortest_routes(graph, start, target, limit, max_hops):
    """Yen's algorithm: up to k shortest distinct simple paths, ordered by hops."""
    first = shortest_path(graph, start, target, set(), set(), max_hops)
    if first is None:
        return []
    paths, candidates, queued = [first], [], {first}
    while len(paths) < limit:
        previous = paths[-1]
        for index in range(len(previous) - 1):
            root = previous[:index + 1]
            blocked = {(path[index], path[index + 1]) for path in paths
                       if len(path) > index + 1 and path[:index + 1] == root}
            spur = shortest_path(graph, root[-1], target, set(root[:-1]), blocked,
                                 max_hops - index)
            if spur is not None:
                candidate = root[:-1] + spur
                if candidate not in queued:
                    queued.add(candidate)
                    heapq.heappush(candidates, (len(candidate), candidate))
        if not candidates:
            break
        paths.append(heapq.heappop(candidates)[1])
    return paths


def plan_routes(items, start, target, observed_only=False, limit=5, max_hops=32):
    nodes, graph, edges, excluded = route_graph(items, observed_only)
    start, target = resolve_node(nodes, start), resolve_node(nodes, target)
    routes = []
    for path in shortest_routes(graph, start, target, limit, max_hops):
        steps = [edges[a, b] for a, b in zip(path, path[1:])]
        distances = [step['distance_km'] for step in steps]
        routes.append(dict(nodes=[nodes[key] for key in path], steps=steps,
                           hops=len(steps),
                           unobserved_steps=sum(not step['forward_count'] for step in steps),
                           one_way_steps=sum(not step['forward_count'] or not step['reverse_count']
                                             for step in steps),
                           distance_km=sum(distances) if all(d is not None for d in distances) else None))
    return dict(routes=routes, start=nodes[start], target=nodes[target],
                max_hops=max_hops, limit=limit, observed_only=observed_only,
                excluded_links=excluded)
