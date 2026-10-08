"""Observed adjacency in received flood paths, retaining ambiguous raw hashes."""
import json
import math
import re
from datetime import datetime


def distance_km(a, b):
    """Great-circle distance from known positions; (0, 0) means unset."""
    for node in (a, b):
        if not node:
            return None
        lat, lon = node['latitude'], node['longitude']
        if (lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180)
                or (lat == 0 and lon == 0)):
            return None
    lat_a, lat_b = math.radians(a['latitude']), math.radians(b['latitude'])
    delta_lon = math.radians(b['longitude'] - a['longitude'])
    h = math.sin((lat_b - lat_a) / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(max(0, min(1, h))))


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


def add_path_pairs(pairs, hops, count, first, last):
    """Aggregate raw pairs once per path and direction, including loop tokens.

    MeshCore uses one hash width per path. Distinct tokens within a path
    therefore cannot resolve to the same identity: deduplication before name
    resolution preserves the per-reception counts, even after new collisions.
    """
    directions = {}
    for left, right in zip(hops, hops[1:]):
        a, b = (left, right) if left <= right else (right, left)
        key = (a, b)
        directions[key] = directions.get(key, 0) | (1 if left == a else 2)
    for key, direction in directions.items():
        forward = count if direction & 1 else 0
        reverse = count if direction & 2 else 0
        if key not in pairs:
            pairs[key] = [count, forward, reverse, first, last]
        else:
            values = pairs[key]
            values[0] += count
            values[1] += forward
            values[2] += reverse
            values[3] = min(values[3], first)
            values[4] = max(values[4], last)


def write_path_pairs(db, pairs):
    db.executemany('''INSERT INTO repeater_pairs
        (source,target,count,forward_count,reverse_count,first_seen,last_seen)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(source,target) DO UPDATE SET
        count=count+excluded.count,
        forward_count=forward_count+excluded.forward_count,
        reverse_count=reverse_count+excluded.reverse_count,
        first_seen=MIN(first_seen,excluded.first_seen),
        last_seen=MAX(last_seen,excluded.last_seen)''',
        ((*key, *values) for key, values in pairs.items()))


def rebuild_path_pairs(db):
    """One-time upgrade from compact historical paths, without reading packets."""
    db.execute('DELETE FROM repeater_pairs')
    pairs = {}
    for path, count, first, last in db.execute('SELECT path,count,first_seen,last_seen FROM repeater_paths'):
        add_path_pairs(pairs, json.loads(path), count, first, last)
        if len(pairs) >= 10000:
            write_path_pairs(db, pairs)
            pairs.clear()
    write_path_pairs(db, pairs)


def record_path_pairs(db, batch):
    pairs = {}
    for packet in batch:
        if 'noise_sample' in packet:
            continue
        decoded = packet['decoded']
        hops = decoded['hops']
        if packet.get('direction') != 'rx' or decoded['route_type'] not in (0, 1) or len(hops) < 2:
            continue
        received = datetime.fromisoformat(packet['received_at']).timestamp()
        add_path_pairs(pairs, hops, 1, received, received)
    write_path_pairs(db, pairs)


def neighbor_summary(db):
    nodes = {row[0]: {'id': row[0], 'name': row[1] or row[0], 'node_type': row[2],
                      'latitude': row[3], 'longitude': row[4]}
             for row in db.execute('SELECT public_key,name,node_type,latitude,longitude FROM nodes')}
    pairs = db.execute('''SELECT source,target,count,forward_count,reverse_count,first_seen,last_seen
                          FROM repeater_pairs''').fetchall()
    tokens = {token for row in pairs for token in row[:2]}
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
    for left, right, count, forward, reverse, first, last in pairs:
        a, b = resolved[left], resolved[right]
        if a['id'] > b['id']:
            a, b = b, a
            forward, reverse = reverse, forward
        key = (a['id'], b['id'])
        if a['excluded'] or b['excluded'] or key[0] == key[1]:
            continue
        if key not in links:
            links[key] = dict(source=a, target=b, count=0, forward_count=0,
                              reverse_count=0, first_seen=first, last_seen=last,
                              distance_km=distance_km(nodes.get(a['id']), nodes.get(b['id']))
                              if a['resolved'] and b['resolved'] and not a['ambiguous'] and not b['ambiguous'] else None)
        link = links[key]
        link['count'] += count
        link['forward_count'] += forward
        link['reverse_count'] += reverse
        link['first_seen'] = min(link['first_seen'], first)
        link['last_seen'] = max(link['last_seen'], last)
    return {'items': sorted(links.values(), key=lambda item: (-item['count'], item['source']['id'], item['target']['id']))}


def neighbor_page(items, q='', one_way=False, sort='count', descending=True, page=0, limit=100):
    query = q.strip().casefold()
    filtered = [item for item in items
                if (not one_way or not item['forward_count'] or not item['reverse_count'])
                and (not query or any(query in (node['name'] + ' ' + node['id']).casefold()
                                      for node in (item['source'], item['target'])))]

    def value(item):
        if sort in ('source', 'target'):
            node = item[sort]
            label = node['name'] + ' ' + node['id']
            # Natural ordering, including names such as Node2 and Node10.
            folded = label.casefold().translate(str.maketrans({'ä': 'a', 'ö': 'o', 'ü': 'u'}))
            return tuple((1, int(part)) if part.isdigit() else (0, part)
                         for part in re.split(r'(\d+)', folded))
        if sort == 'direction':
            return 0 if item['forward_count'] and item['reverse_count'] else 1 if item['forward_count'] else 2
        return item[sort]

    filtered.sort(key=lambda item: (item['source']['id'], item['target']['id']))
    known = [item for item in filtered if value(item) is not None]
    missing = [item for item in filtered if value(item) is None]
    known.sort(key=value, reverse=descending)
    filtered = known + missing
    page = min(page, max(0, (len(filtered) - 1) // limit))
    return dict(items=filtered[page * limit:(page + 1) * limit], page=page,
                total=len(filtered), total_all=len(items),
                one_way_total=sum(not item['forward_count'] or not item['reverse_count'] for item in items))


def neighbor_map(items):
    nodes, indices, links = [], {}, []
    for item in items:
        if item['distance_km'] is None:
            continue
        pair = []
        for node in (item['source'], item['target']):
            if node['id'] not in indices:
                indices[node['id']] = len(nodes)
                nodes.append([node['id'], node['name']])
            pair.append(indices[node['id']])
        links.append(pair + [item[key] for key in
                            ('count', 'forward_count', 'reverse_count', 'last_seen', 'distance_km')])
    return dict(nodes=nodes, links=links, total=len(items))
