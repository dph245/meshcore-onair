"""Local identity analysis. No packet reads, network access or durable projection."""
from bisect import bisect_left
from collections import Counter
import re
import sqlite3
import time
from threading import Lock

from onair_map_visibility import MapVisibility
from onair_neighbors import distance_km
from onair_prefixes import unique_prefix

WOLFENBUETTEL = dict(latitude=52.164, longitude=10.540)
KEY = re.compile(r'[0-9a-f]{64}')


class PrefixExplorer:
    def __init__(self, connect):
        self.connect = connect
        self.lock = Lock()
        self.cached = None
        self.expires = 0

    def snapshot(self):
        with self.lock:
            if self.cached is not None and time.monotonic() < self.expires:
                return self.cached
            with self.connect() as db:
                db.row_factory = sqlite3.Row
                db.execute('BEGIN')
                nodes = [dict(r) for r in db.execute('SELECT * FROM nodes ORDER BY last_seen,public_key')]
                manual = [dict(r) for r in db.execute('SELECT * FROM manual_nodes')]
                # SQL collapses case variants before resolving tokens. No packet JSON scans.
                receptions = list(db.execute('SELECT lower(token),MAX(last_seen) FROM repeater_receptions GROUP BY lower(token)'))
            policy = MapVisibility(nodes, manual)
            identities = {}
            for row in nodes:
                key = row['public_key'].lower()
                if KEY.fullmatch(key):
                    identities[key] = dict(row, public_key=key)
            # Manual entries provide identity/type/position, but creation is NOT a sighting.
            for row in manual:
                key = row['public_key'].lower()
                if KEY.fullmatch(key) and key not in identities:
                    identities[key] = dict(row, public_key=key, node_type=2, last_seen=None)
            keys = sorted(identities)
            heard = {}
            for token, seen in receptions:
                if not re.fullmatch(r'(?:[0-9a-f]{2}){1,32}', token):
                    continue
                key = unique_prefix(keys, token)
                if key and identities[key]['node_type'] == 2:
                    heard[key] = max(heard.get(key, seen), seen)
            rows = []
            for key in keys:
                row = identities[key]
                if row['node_type'] != 2:
                    continue
                seen = [v for v in (row['last_seen'], heard.get(key)) if v is not None]
                row['last_seen'] = max(seen) if seen else None
                row['hidden'] = policy.hidden(key)
                rows.append(row)
            self.cached = rows, time.time()
            self.expires = time.monotonic() + 30
            return self.cached

    def query(self, days=30, prefix='', reference='', radius=0, sort='prefix', offset=0, now=None, reference_q=''):
        if days not in (0, 7, 30, 60, 90):
            raise ValueError('Ungültiger Zeitraum')
        prefix, reference = prefix.lower().strip(), reference.lower().strip()
        if prefix and not re.fullmatch(r'(?:[0-9a-f]{2}){1,3}', prefix):
            raise ValueError('Prefix muss 2, 4 oder 6 Hex-Zeichen enthalten')
        if radius not in (0, 25, 50, 100, 250) or sort not in ('prefix', 'count', 'distance') or offset < 0:
            raise ValueError('Ungültiger Filter')
        rows, generated = self.snapshot()
        now = generated if now is None else now
        start = now - days * 86400 if days else float('-inf')
        active = [r for r in rows if r['last_seen'] is not None and start <= r['last_seen'] <= now]
        keys = sorted(r['public_key'] for r in active)
        counts = {length: Counter(k[:length] for k in keys) for length in (2, 4, 6)}
        references = [dict(public_key=r['public_key'], name=r['name']) for r in active
                      if not r['hidden'] and distance_km(r, r) is not None
                      and (reference_q.casefold() in (r['name'] or '').casefold()
                           or reference_q.lower() in r['public_key'] or r['public_key'] == reference)]
        references = sorted(references, key=lambda r: (r['public_key'] != reference, r['public_key']))[:100]
        point = WOLFENBUETTEL
        if reference:
            point = next((r for r in active if r['public_key'] == reference and not r['hidden']
                          and distance_km(r, r) is not None), None)
            if point is None:
                raise ValueError('Bezugspunkt nicht verfügbar; Wolfenbüttel wählen')
        # Drilldown always contains at most 256 cells, including empty children.
        parent = prefix if len(prefix) < 6 else prefix[:4]
        length = len(parent) + 2
        cells = [dict(prefix=parent + f'{i:02x}', count=counts[length][parent + f'{i:02x}']) for i in range(256)]
        if sort == 'count':
            cells.sort(key=lambda c: (-c['count'], c['prefix']))
        levels = [dict(prefix=prefix[:n], count=counts[n][prefix[:n]])
                  for n in (2, 4, 6) if n <= len(prefix)]
        items = []
        for row in active:
            key = row['public_key']
            if not prefix or not key.startswith(prefix):
                continue
            # Never return coordinates, even for visible rows. Hidden distances stay null.
            distance = None if row['hidden'] else distance_km(point, row)
            if radius and (distance is None or distance > radius):
                continue
            index = bisect_left(keys, key)
            neighbors = keys[max(0, index-1):index] + keys[index+1:index+2]
            common = 0
            for other in neighbors:
                size = next((i for i, (a, b) in enumerate(zip(key, other)) if a != b), 64)
                common = max(common, size)
            shortest = min(64, ((common // 2) + 1) * 2)
            items.append(dict(public_key=key, name=row['name'], last_seen=row['last_seen'],
                              distance_km=distance, position_status='Verborgen' if row['hidden'] else
                              ('Unbekannt' if distance is None else 'Bekannt'), unique_prefix=key[:shortest]))
        if sort == 'distance':
            items.sort(key=lambda r: (r['distance_km'] is None, r['distance_km'] or 0, r['public_key']))
        else:
            items.sort(key=lambda r: r['public_key'])
        return dict(days=days, generated_at=generated, total=len(keys), parent=parent, cells=cells,
                    levels=levels, statistics=[dict(bytes=n//2, possible=256**(n//2), occupied=len(counts[n]),
                    collisions=sum(v >= 2 for v in counts[n].values())) for n in (2,4,6)],
                    busiest=[dict(prefix=p, count=c) for p,c in counts[2].most_common(10)],
                    references=references, items=items[offset:offset+100], matched=len(items),
                    next_offset=offset+100 if offset+100 < len(items) else None)
