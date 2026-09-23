"""Observed adjacency in received flood paths, retaining ambiguous raw hashes."""
import json
from datetime import datetime


def record_path(db, packet):
    decoded = packet['decoded']
    hops = decoded['hops']
    if packet.get('direction') != 'rx' or decoded['route_type'] not in (0, 1) or len(hops) < 2:
        return
    received = datetime.fromisoformat(packet['received_at']).timestamp()
    db.execute('''INSERT INTO repeater_paths VALUES(?,1,?,?)
        ON CONFLICT(path) DO UPDATE SET count=count+1,
        first_seen=MIN(first_seen,excluded.first_seen),
        last_seen=MAX(last_seen,excluded.last_seen)''',
        (json.dumps(hops), received, received))


def neighbor_summary(db):
    nodes = {row[0]: {'id': row[0], 'name': row[1] or row[0], 'node_type': row[2]}
             for row in db.execute('SELECT public_key,name,node_type FROM nodes')}
    paths = [(json.loads(path), count, first, last) for path, count, first, last
             in db.execute('SELECT * FROM repeater_paths')]
    tokens = {token for hops, *_ in paths for token in hops}
    # Include all known node types: a Companion sharing a prefix is a collision too.
    candidates = tokens | set(nodes) | {row[0] for row in db.execute('SELECT token FROM repeater_receptions')}
    # Each terminal identity contributes its prefixes once. Avoid scanning all
    # identities for every token (quadratic with a large server archive).
    prefixes = {}
    for token in sorted(candidates, key=lambda value: (-len(value), value)):
        if token in prefixes:
            continue
        for length in range(2, len(token) + 1, 2):
            prefix = token[:length]
            prefixes[prefix] = None if prefix in prefixes else token
    resolved = {}
    for token in tokens:
        match = prefixes[token]
        identity = match or token
        node = nodes.get(identity)
        resolved[token] = dict(id=identity, name=node['name'] if node else identity,
                               resolved=bool(node and node['node_type'] == 2),
                               ambiguous=match is None,
                               excluded=bool(node and node['node_type'] != 2))
    links = {}
    for hops, count, first, last in paths:
        seen = set()
        directions = set()
        for left, right in zip(hops, hops[1:]):
            a, b = sorted((resolved[left], resolved[right]), key=lambda item: item['id'])
            key = (a['id'], b['id'])
            if a['excluded'] or b['excluded'] or key[0] == key[1]:
                continue
            if key not in links:
                links[key] = dict(source=a, target=b, count=0, forward_count=0,
                                  reverse_count=0, first_seen=first, last_seen=last)
            link = links[key]
            if key not in seen:
                link['count'] += count
                seen.add(key)
            direction = 'forward_count' if resolved[left]['id'] == a['id'] else 'reverse_count'
            directed_key = (*key, direction)
            if directed_key not in directions:
                link[direction] += count
                directions.add(directed_key)
            link['first_seen'] = min(link['first_seen'], first)
            link['last_seen'] = max(link['last_seen'], last)
    return {'items': sorted(links.values(), key=lambda item: (-item['count'], item['source']['id'], item['target']['id']))}
