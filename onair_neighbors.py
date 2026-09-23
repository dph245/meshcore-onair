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
    identities = []
    for token in sorted(candidates, key=lambda value: (-len(value), value)):
        if not any(identity.startswith(token) for identity in identities):
            identities.append(token)
    resolved = {}
    for token in tokens:
        matches = [identity for identity in identities if identity.startswith(token)]
        identity = matches[0] if len(matches) == 1 else token
        node = nodes.get(identity)
        resolved[token] = dict(id=identity, name=node['name'] if node else identity,
                               resolved=bool(node and node['node_type'] == 2),
                               ambiguous=len(matches) > 1,
                               excluded=bool(node and node['node_type'] != 2))
    links = {}
    for hops, count, first, last in paths:
        seen = set()
        for left, right in zip(hops, hops[1:]):
            a, b = sorted((resolved[left], resolved[right]), key=lambda item: item['id'])
            key = (a['id'], b['id'])
            if a['excluded'] or b['excluded'] or key[0] == key[1] or key in seen:
                continue
            seen.add(key)
            if key not in links:
                links[key] = dict(source=a, target=b, count=0, first_seen=first, last_seen=last)
            link = links[key]
            link['count'] += count
            link['first_seen'] = min(link['first_seen'], first)
            link['last_seen'] = max(link['last_seen'], last)
    return {'items': sorted(links.values(), key=lambda item: (-item['count'], item['source']['id'], item['target']['id']))}
