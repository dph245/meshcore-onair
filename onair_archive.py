"""SQLite reception archive; one writer, bounded batches, independent readers."""
import json
import hashlib
from collections import OrderedDict
import logging
import os
from pathlib import Path
from queue import Queue, Empty, Full
import sqlite3
from threading import Thread, Event, Lock
import time
from datetime import datetime
from onair_repeaters import (record_repeater, repeater_summary, repeater_token,
                             record_repeater_observer, attach_observer_signals)
from onair_scopes import scope_label
from onair_payload import decode_payload_details
from onair_discovery import discovery_sessions
from onair_trace import trace_sessions, WINDOW_SECONDS as TRACE_WINDOW_SECONDS
from onair_observers import record_observer, observer_comparison
from onair_neighbors import (record_path, record_path_pairs, rebuild_path_pairs,
                             neighbor_summary, neighbor_page, neighbor_map)
from onair_distance import INDEX_SQL, analyze as analyze_distance, response as distance_response


def database_path():
    return Path(os.environ.get('ONAIR_DB_PATH', str(Path(__file__).with_name('onair.sqlite3')))).expanduser().resolve()


class Archive:
    def __init__(self, path=None, interval=5):
        self.path = Path(path) if path is not None else database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.interval = interval
        self.queue = Queue(maxsize=10000)
        self.stopping = Event()
        self.error = None
        self.dropped = 0
        self.saved = 0
        self.names = {}
        self._neighbors_lock = Lock()
        self._neighbors_json = None
        self._neighbors_items = None
        self._neighbors_responses = OrderedDict()
        self._neighbors_expires = 0
        self._distance_lock = Lock()
        self._distance_cache = OrderedDict()
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS packets (
                    id INTEGER PRIMARY KEY, received REAL NOT NULL,
                    kind TEXT NOT NULL, channel TEXT, observer_hash TEXT,
                    search_text TEXT NOT NULL, packet_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS packets_received ON packets(received);
                CREATE INDEX IF NOT EXISTS packets_kind_id ON packets(kind, id);
                CREATE INDEX IF NOT EXISTS packets_channel_id ON packets(channel, id);
                CREATE INDEX IF NOT EXISTS packets_hash_id ON packets(observer_hash, id);
                CREATE TABLE IF NOT EXISTS nodes (
                    public_key TEXT PRIMARY KEY, name TEXT, advert_time INTEGER NOT NULL,
                    first_seen REAL NOT NULL, last_seen REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS noise_samples (
                    id INTEGER PRIMARY KEY, received_at TEXT NOT NULL,
                    noise_floor INTEGER NOT NULL);
            ''')
            with db:
                db.execute('BEGIN')
                if db.execute('PRAGMA user_version').fetchone()[0] < 3:
                    db.execute('''CREATE TABLE IF NOT EXISTS repeater_receptions (
                        token TEXT PRIMARY KEY, count INTEGER NOT NULL,
                        rssi INTEGER, min_rssi INTEGER, max_rssi INTEGER,
                        last_seen REAL NOT NULL)''')
                    db.execute('DELETE FROM repeater_receptions')
                    for (raw,) in db.execute('SELECT packet_json FROM packets ORDER BY id'):
                        record_repeater(db, json.loads(raw))
                    db.execute('PRAGMA user_version=3')
                if db.execute('PRAGMA user_version').fetchone()[0] < 4:
                    db.execute('ALTER TABLE packets ADD COLUMN repeater_token TEXT')
                    for packet_id, raw in db.execute('SELECT id,packet_json FROM packets'):
                        db.execute('UPDATE packets SET repeater_token=? WHERE id=?',
                                   (repeater_token(json.loads(raw)), packet_id))
                    db.execute('CREATE INDEX packets_repeater_received ON packets(repeater_token,received,id)')
                    db.execute('PRAGMA user_version=4')
                if db.execute('PRAGMA user_version').fetchone()[0] < 5:
                    columns = {row[1] for row in db.execute('PRAGMA table_info(nodes)')}
                    for column in ('node_type INTEGER', 'latitude REAL', 'longitude REAL', 'position_time INTEGER'):
                        if column.split()[0] not in columns:
                            db.execute('ALTER TABLE nodes ADD COLUMN ' + column)
                    for (raw,) in db.execute("SELECT packet_json FROM packets WHERE kind='ADVERT' ORDER BY id"):
                        self._record_node(db, json.loads(raw))
                    db.execute('PRAGMA user_version=5')
                if db.execute('PRAGMA user_version').fetchone()[0] < 6:
                    columns = {row[1] for row in db.execute('PRAGMA table_info(packets)')}
                    for column in ('origin_id', 'origin'):
                        if column not in columns:
                            db.execute('ALTER TABLE packets ADD COLUMN ' + column + ' TEXT')
                    db.execute('CREATE TABLE IF NOT EXISTS observers (origin_id TEXT PRIMARY KEY, origin TEXT, last_seen REAL NOT NULL, count INTEGER NOT NULL)')
                    db.execute('CREATE TABLE IF NOT EXISTS observer_receptions (token TEXT NOT NULL, origin_id TEXT NOT NULL, count INTEGER NOT NULL, best_rssi INTEGER, best_snr REAL, last_seen REAL NOT NULL, PRIMARY KEY(token,origin_id))')
                    db.execute('DELETE FROM observers')
                    db.execute('DELETE FROM observer_receptions')
                    for packet_id, raw in db.execute('SELECT id,packet_json FROM packets ORDER BY id'):
                        packet = json.loads(raw)
                        db.execute('UPDATE packets SET origin_id=?,origin=? WHERE id=?',
                                   (packet.get('origin_id'), packet.get('origin'), packet_id))
                        record_observer(db, packet)
                    db.execute('CREATE INDEX IF NOT EXISTS packets_origin_id ON packets(origin_id,id)')
                    db.execute('PRAGMA user_version=6')
                if db.execute('PRAGMA user_version').fetchone()[0] < 7:
                    columns = {row[1] for row in db.execute('PRAGMA table_info(noise_samples)')}
                    for column in ('origin_id', 'origin'):
                        if column not in columns:
                            db.execute('ALTER TABLE noise_samples ADD COLUMN ' + column + ' TEXT')
                    db.execute('CREATE INDEX IF NOT EXISTS noise_origin_id ON noise_samples(origin_id,id)')
                    db.execute('PRAGMA user_version=7')
                if db.execute('PRAGMA user_version').fetchone()[0] < 8:
                    columns = {row[1] for row in db.execute('PRAGMA table_info(noise_samples)')}
                    if 'status_at' not in columns:
                        db.execute('ALTER TABLE noise_samples ADD COLUMN status_at TEXT')
                    db.execute('PRAGMA user_version=8')
                if db.execute('PRAGMA user_version').fetchone()[0] < 9:
                    db.execute('''CREATE TABLE IF NOT EXISTS repeater_paths (
                        path TEXT PRIMARY KEY, count INTEGER NOT NULL,
                        first_seen REAL NOT NULL, last_seen REAL NOT NULL)''')
                    db.execute('DELETE FROM repeater_paths')
                    for (raw,) in db.execute('SELECT packet_json FROM packets ORDER BY id'):
                        record_path(db, json.loads(raw))
                    db.execute('PRAGMA user_version=9')
                if db.execute('PRAGMA user_version').fetchone()[0] < 10:
                    db.execute('''CREATE TABLE IF NOT EXISTS node_advert_paths (
                        public_key TEXT PRIMARY KEY, received REAL NOT NULL, reception TEXT NOT NULL)''')
                    for (raw,) in db.execute("SELECT packet_json FROM packets WHERE kind='ADVERT' ORDER BY id"):
                        self._record_advert_path(db, json.loads(raw))
                    db.execute('PRAGMA user_version=10')
                if db.execute('PRAGMA user_version').fetchone()[0] < 11:
                    db.execute('''CREATE TABLE IF NOT EXISTS repeater_pairs (
                        source TEXT NOT NULL, target TEXT NOT NULL, count INTEGER NOT NULL,
                        forward_count INTEGER NOT NULL, reverse_count INTEGER NOT NULL,
                        first_seen REAL NOT NULL, last_seen REAL NOT NULL,
                        PRIMARY KEY(source,target)) WITHOUT ROWID''')
                    rebuild_path_pairs(db)
                    db.execute('PRAGMA user_version=11')
                if db.execute('PRAGMA user_version').fetchone()[0] < 12:
                    db.execute('''CREATE TABLE IF NOT EXISTS manual_nodes (
                        public_key TEXT PRIMARY KEY CHECK(length(public_key)=64
                            AND public_key NOT GLOB '*[^0-9a-f]*'),
                        name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 128),
                        latitude REAL NOT NULL CHECK(latitude BETWEEN -90 AND 90),
                        longitude REAL NOT NULL CHECK(longitude BETWEEN -180 AND 180),
                        source TEXT NOT NULL CHECK(length(trim(source)) BETWEEN 1 AND 512),
                        created_at REAL NOT NULL, updated_at REAL NOT NULL,
                        CHECK(latitude != 0 OR longitude != 0))''')
                    db.execute('PRAGMA user_version=12')
                if db.execute('PRAGMA user_version').fetchone()[0] < 13:
                    # One historical index build; no duplicated event archive.
                    db.execute(INDEX_SQL)
                    db.execute('PRAGMA user_version=13')
                if db.execute('PRAGMA user_version').fetchone()[0] < 14:
                    db.execute('''CREATE TABLE IF NOT EXISTS repeater_observer_signals (
                        token TEXT NOT NULL, origin_id TEXT NOT NULL, origin TEXT,
                        rssi INTEGER, min_rssi INTEGER, max_rssi INTEGER,
                        last_seen REAL NOT NULL, PRIMARY KEY(token,origin_id))''')
                    db.execute('DELETE FROM repeater_observer_signals')
                    for (raw,) in db.execute('SELECT packet_json FROM packets WHERE repeater_token IS NOT NULL ORDER BY id'):
                        record_repeater_observer(db, json.loads(raw))
                    db.execute('PRAGMA user_version=14')
            self._load_names(db)
        self.worker = Thread(target=self._run, name='onair-archive', daemon=True)
        self.worker.start()

    def connect(self):
        # Connections are owned by their calling thread and explicitly closed below.
        from contextlib import closing
        return closing(sqlite3.connect(self.path, timeout=5))

    def _load_names(self, db):
        self.names = dict(db.execute('SELECT public_key, name FROM nodes'))

    def resolve(self, token):
        if len(token) < 4:
            return None
        matches = [name for key, name in self.names.items() if key.startswith(token)]
        return matches[0] if len(matches) == 1 else None

    def discovery(self, hours=24, limit=100):
        cutoff = time.time() - hours * 3600
        with self.connect() as db:
            rows = db.execute('''SELECT id,received,packet_json FROM packets
                WHERE kind='CONTROL' AND received>=? ORDER BY id DESC LIMIT 5001''',
                              (cutoff,)).fetchall()
            names = dict(db.execute('SELECT public_key,name FROM nodes'))
        sessions, ignored = discovery_sessions(
            [(row_id, received, json.loads(raw)) for row_id, received, raw in rows[:5000]], names)
        return dict(items=sessions[:limit], hours=hours, window_seconds=60,
                    scanned=min(len(rows), 5000), ignored=ignored,
                    truncated=len(rows) > 5000, more_sessions=len(sessions) > limit)

    def traces(self, hours=24, limit=100):
        cutoff = time.time() - hours * 3600
        with self.connect() as db:
            rows = db.execute('''SELECT id,received,packet_json FROM packets
                WHERE kind='TRACE' AND received>=? ORDER BY id DESC LIMIT 5001''',
                              (cutoff,)).fetchall()
            names = dict(db.execute('SELECT public_key,name FROM nodes'))
        sessions, histories, ignored = trace_sessions(
            [(row_id, received, json.loads(raw)) for row_id, received, raw in rows[:5000]], names)
        return dict(items=sessions[:limit], histories=histories[:100], hours=hours,
                    window_seconds=TRACE_WINDOW_SECONDS, scanned=min(len(rows), 5000),
                    ignored=ignored, truncated=len(rows) > 5000,
                    more_sessions=len(sessions) > limit, more_routes=len(histories) > 100)

    def trace_map(self, start, end, before, first, last, hops, grouped=False):
        from onair_trace_map import browse, grouped_snapshot, grouped_page
        if grouped:
            # Small bounded cache: page/group clicks never recompute correlation.
            key = (start, end, first, last, hops)
            with self._distance_lock, self.connect() as db:
                cache = getattr(self, '_trace_groups', None)
                if cache is None:
                    cache = self._trace_groups = OrderedDict()
                entry = cache.get(key)
                if entry is None or time.monotonic() >= entry[0]:
                    entry = (time.monotonic() + 120, grouped_snapshot(db, start, end, first, last, hops))
                    cache[key] = entry
                    while len(cache) > 2:
                        cache.popitem(last=False)
                cache.move_to_end(key)
                return grouped_page(entry[1], before)
        with self.connect() as db:
            return browse(db, start, end, before, first, last, hops)

    def trace_map_detail(self, identity):
        from onair_trace_map import detail
        from onair_distance import Positions
        # Shared lock bounds concurrent historical work; cache independent of map motion.
        with self._distance_lock, self.connect() as db:
            if db.execute("SELECT 1 FROM packets WHERE id=? AND kind='TRACE'", (identity,)).fetchone() is None:
                return None
            now = time.monotonic()
            cache = getattr(self, '_trace_positions', None)
            if cache is None or now - cache[0] > 60:
                deadline = now + 10
                db.set_progress_handler(lambda: time.monotonic() > deadline, 10000)
                try:
                    positions = Positions(db, 0, time.time() + 1)
                finally:
                    db.set_progress_handler(None, 0)
                self._trace_positions = (time.monotonic(), positions)
            return detail(db, identity, self._trace_positions[1])

    def accept(self, packet):
        self._enqueue(packet.to_dict())

    def accept_noise(self, sample):
        self._enqueue({'noise_sample': dict(sample)})

    def _enqueue(self, item):
        try:
            self.queue.put_nowait(item)
        except Full:
            self.dropped += 1
            logging.error('Archiv-Warteschlange voll: Empfang verworfen (%s)', self.dropped)

    def _write(self, db, batch):
        with db:
            for p in batch:
                if 'noise_sample' in p:
                    sample = p['noise_sample']
                    db.execute('INSERT INTO noise_samples(received_at,noise_floor,origin_id,origin,status_at) VALUES(?,?,?,?,?)',
                               (sample['received_at'], sample['noise_floor'],
                                sample.get('origin_id'), sample.get('origin'), sample.get('status_at')))
                    continue
                d = p['decoded']
                record_repeater(db, p)
                record_repeater_observer(db, p)
                record_observer(db, p)
                record_path(db, p)
                a = d.get('advert')
                received = datetime.fromisoformat(p['received_at']).timestamp()
                search = ' '.join(str(v) for v in (p['observer_hash'] or '', p['path'],
                    ' '.join(d['hops']), d.get('group_text') or '', d.get('group_channel') or '',
                    a.get('name') or '' if a else '', a.get('public_key') or '' if a else '')).casefold()
                db.execute('INSERT INTO packets(received,kind,channel,observer_hash,search_text,packet_json,repeater_token,origin_id,origin) VALUES(?,?,?,?,?,?,?,?,?)',
                    (received, d['payload_name'], d.get('group_channel'), p['observer_hash'], search,
                     json.dumps(p, ensure_ascii=False), repeater_token(p), p.get('origin_id'), p.get('origin')))
                self._record_node(db, p)
                self._record_advert_path(db, p)
            record_path_pairs(db, batch)
            names = dict(db.execute('SELECT public_key, name FROM nodes'))
        self.saved += sum('noise_sample' not in p for p in batch)
        self.names = names

    @staticmethod
    def _record_node(db, packet):
        decoded = packet['decoded']
        a = decoded.get('advert')
        if not a or decoded.get('advert_status') or a.get('signature_status') != 'Gültig':
            return
        received = datetime.fromisoformat(packet['received_at']).timestamp()
        position_time = a['timestamp'] if a.get('latitude') is not None and a.get('longitude') is not None else None
        db.execute('''INSERT INTO nodes
            (public_key,name,advert_time,first_seen,last_seen,node_type,latitude,longitude,position_time)
            VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(public_key) DO UPDATE SET
            name=CASE WHEN excluded.advert_time > nodes.advert_time THEN excluded.name ELSE nodes.name END,
            node_type=CASE WHEN excluded.advert_time >= nodes.advert_time THEN excluded.node_type ELSE nodes.node_type END,
            advert_time=MAX(nodes.advert_time,excluded.advert_time),
            first_seen=MIN(nodes.first_seen,excluded.first_seen),
            last_seen=MAX(nodes.last_seen,excluded.last_seen),
            latitude=CASE WHEN excluded.position_time >= COALESCE(nodes.position_time,-1) THEN excluded.latitude ELSE nodes.latitude END,
            longitude=CASE WHEN excluded.position_time >= COALESCE(nodes.position_time,-1) THEN excluded.longitude ELSE nodes.longitude END,
            position_time=CASE WHEN excluded.position_time >= COALESCE(nodes.position_time,-1) THEN excluded.position_time ELSE nodes.position_time END''',
            (a['public_key'], a.get('name'), a['timestamp'], received, received,
             a.get('node_type'), a.get('latitude'), a.get('longitude'), position_time))

    @staticmethod
    def _record_advert_path(db, packet):
        decoded = packet['decoded']
        advert = decoded.get('advert')
        if (packet.get('direction') != 'rx' or not advert or decoded.get('advert_status')
                or advert.get('signature_status') != 'Gültig'):
            return
        received = datetime.fromisoformat(packet['received_at']).timestamp()
        reception = dict(received=received, origin=packet.get('origin'),
                         origin_id=packet.get('origin_id'),
                         hops=decoded.get('hops', []) if decoded.get('route_type') in (0, 1) else None)
        db.execute('''INSERT INTO node_advert_paths VALUES(?,?,?)
            ON CONFLICT(public_key) DO UPDATE SET received=excluded.received, reception=excluded.reception
            WHERE excluded.received >= node_advert_paths.received''',
            (advert['public_key'], received, json.dumps(reception, ensure_ascii=False)))

    def mesh_live_nodes(self):
        """On-demand bootstrap only; include invisible identities for collision checks."""
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN')
            nodes = [dict(row) for row in db.execute('''SELECT public_key,name,node_type,
                advert_time,latitude,longitude,position_time,first_seen,last_seen FROM nodes''')]
            tokens = [row[0] for row in db.execute('''SELECT token FROM repeater_receptions
                UNION SELECT source FROM repeater_pairs UNION SELECT target FROM repeater_pairs''')]
            manual = [dict(row) for row in db.execute('SELECT * FROM manual_nodes ORDER BY public_key')]
        return {'nodes': nodes, 'tokens': tokens, 'manual_nodes': manual}

    def mesh_live_replay(self):
        from onair_replay import replay_response
        return replay_response(self.connect)

    def map_nodes(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute('''SELECT nodes.*, reception FROM nodes
                LEFT JOIN node_advert_paths USING(public_key) ORDER BY public_key''').fetchall()
        prefixes = {}
        for row in rows:
            for length in range(2, len(row['public_key']) + 1, 2):
                token = row['public_key'][:length]
                prefixes[token] = None if token in prefixes else row
        cutoff = time.time() - 28 * 24 * 60 * 60
        items = []
        without_position = inactive = 0
        for row in rows:
            if row['last_seen'] <= cutoff:
                inactive += 1
            elif (row['latitude'] is None or row['longitude'] is None or
                  (row['latitude'] == 0 and row['longitude'] == 0)):
                without_position += 1
            else:
                item = dict(row)
                raw = item.pop('reception')
                item['advert_path'] = reception = json.loads(raw) if raw else None
                if reception and reception['hops'] is not None:
                    hops = []
                    for token in reception['hops']:
                        match = prefixes.get(token)
                        hops.append(dict(token=token, name=match['name'] if match else None,
                                         resolved=match is not None,
                                         ambiguous=token in prefixes and match is None))
                    reception['hops'] = hops
                items.append(item)
        # Reuse the already loaded rows: search must expose every repeater candidate,
        # including identities excluded from marker display by the existing rules.
        visible = {item['public_key'] for item in items}
        repeaters = [dict(public_key=row['public_key'], name=row['name'],
                          unavailable=None if row['public_key'] in visible else
                          'Seit mindestens 4 Wochen nicht gehört' if row['last_seen'] <= cutoff else
                          'Keine bekannte Kartenposition')
                     for row in rows if row['node_type'] == 2]
        return {'items': items, 'repeaters': repeaters,
                'without_position': without_position, 'inactive': inactive}

    def neighbors(self):
        with self.connect() as db, db:
            db.execute('BEGIN')
            return neighbor_summary(db)

    def distance_analysis(self, start, end, minimum=200, source='', target='', offset=0):
        key = (start, end, minimum)
        # Keep expensive requests out of the existing neighbor snapshot lock.
        with self._distance_lock:
            cached = self._distance_cache.get(key)
            if cached is None or time.monotonic() >= cached[0]:
                with self.connect() as db, db:
                    db.execute('BEGIN')
                    result = analyze_distance(db, start, end, minimum)
                cached = (time.monotonic() + 120, result)
                self._distance_cache[key] = cached
                while len(self._distance_cache) > 2:
                    self._distance_cache.popitem(last=False)
            self._distance_cache.move_to_end(key)
            return distance_response(cached[1], source, target, offset)

    def _refresh_neighbors(self):
        # Caller owns the lock; all clients and representations share one snapshot.
        if self._neighbors_items is None or time.monotonic() >= self._neighbors_expires:
            items = self.neighbors()['items']
            self._neighbors_items = items
            self._neighbors_json = None
            self._neighbors_responses.clear()
            self._neighbors_expires = time.monotonic() + 30

    def neighbors_json(self):
        with self._neighbors_lock:
            self._refresh_neighbors()
            if self._neighbors_json is None:
                self._neighbors_json = json.dumps({'items': self._neighbors_items}, ensure_ascii=False,
                                                 separators=(',', ':')).encode('utf-8')
            return self._neighbors_json

    def route_snapshot(self):
        # Snapshots are replaced, never mutated. Search outside the shared lock.
        with self._neighbors_lock:
            self._refresh_neighbors()
            return self._neighbors_items

    def neighbor_response(self, mode, **options):
        with self._neighbors_lock:
            self._refresh_neighbors()
            key = (mode, tuple(sorted(options.items())))
            if key not in self._neighbors_responses:
                result = (neighbor_map(self._neighbors_items) if mode == 'map'
                          else neighbor_page(self._neighbors_items, **options))
                body = json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                etag = '"' + hashlib.sha256(body).hexdigest() + '"'
                self._neighbors_responses[key] = (body, etag)
                if len(self._neighbors_responses) > 64:
                    self._neighbors_responses.popitem(last=False)
            self._neighbors_responses.move_to_end(key)
            return self._neighbors_responses[key]

    def observer_comparison(self):
        with self.connect() as db, db:
            db.execute('BEGIN')
            return observer_comparison(db)

    def noise_history(self, limit=500):
        """Latest readings per observer, in receipt order (legacy IDs stay NULL)."""
        with self.connect() as db:
            rows = db.execute('''SELECT received_at,noise_floor,origin_id,origin,status_at FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY origin_id ORDER BY id DESC) AS rank
                FROM noise_samples) WHERE rank <= ? ORDER BY id''',
                              (limit,)).fetchall()
        return [dict(received_at=row[0], noise_floor=row[1],
                     **{key: value for key, value in zip(('origin_id', 'origin', 'status_at'), row[2:])
                        if value is not None}) for row in rows]

    def repeaters(self, hours=8, include_observers=True):
        from onair_mqtt import node_label
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN')
            rows = db.execute('SELECT * FROM repeater_receptions').fetchall()
            signals = db.execute('SELECT * FROM repeater_observer_signals').fetchall() if include_observers else []
            names = dict(db.execute('SELECT public_key,name FROM nodes'))
        items = repeater_summary(rows, names, node_label)
        # Resolve identities using all known tokens before filtering activity.
        if hours:
            since = time.time() - hours * 3600
            items = [item for item in items if item['last_seen'] >= since]
        if include_observers:
            attach_observer_signals(items, signals)
            if hours:
                for item in items:
                    item['observers'] = [signal for signal in item['observers']
                                         if signal['last_seen'] >= since]
        return {'items': items}

    def repeater_history(self, identity, hours=24, limit=500):
        item = next((item for item in self.repeaters(hours=0, include_observers=False)['items'] if item['id'] == identity), None)
        empty = {'items': [], 'has_more': False, 'total': 0, 'sampled': False}
        if item is None:
            return empty
        tokens = item['tokens']
        placeholders = ','.join('?' for _ in tokens)
        since = time.time() - hours * 3600 if hours else 0
        where = f"""FROM packets WHERE repeater_token IN ({placeholders}) AND received >= ?
            AND json_extract(packet_json, '$.rssi') IS NOT NULL"""
        with self.connect() as db:
            # Bounds and readings must come from the same snapshot during live ingestion.
            db.execute('BEGIN')
            total, start, end = db.execute(
                'SELECT COUNT(*), MIN(received), MAX(received) ' + where,
                tokens + [since]).fetchone()
            if not total:
                return empty
            rows = db.execute("""SELECT received, json_extract(packet_json, '$.rssi'),
                json_extract(packet_json, '$.origin_id'), json_extract(packet_json, '$.origin'), id
                """ + where + ' ORDER BY received,id', tokens + [since])
            if total <= limit:
                selected = list(rows)
            else:
                # Keep real first/last/min/max readings per time bucket and observer.
                # Stream the full interval without loading the archive into memory.
                buckets = {}
                bucket_count = max(1, limit // 4)
                for row in rows:
                    bucket = min(bucket_count - 1, int((row[0] - start) / (end - start) * bucket_count)) if end > start else 0
                    key = (row[2] or None, bucket)
                    if key not in buckets:
                        buckets[key] = [row, row, row, row]
                    else:
                        values = buckets[key]
                        values[1] = row
                        if row[1] < values[2][1]:
                            values[2] = row
                        if row[1] > values[3][1]:
                            values[3] = row
                selected = sorted({row[4]: row for values in buckets.values() for row in values}.values(),
                                  key=lambda row: (row[0], row[4]))
        return {'items': [{'received': row[0], 'rssi': row[1],
                           'origin_id': row[2], 'origin': row[3]} for row in selected],
                'has_more': False, 'total': total, 'sampled': len(selected) < total}

    def _run(self):
        batch = []
        deadline = time.monotonic() + self.interval
        with self.connect() as db:
            while not self.stopping.is_set() or batch or not self.queue.empty():
                if len(batch) < 100:
                    try:
                        batch.append(self.queue.get(timeout=0.1))
                    except Empty:
                        pass
                while len(batch) < 100:
                    try:
                        batch.append(self.queue.get_nowait())
                    except Empty:
                        break
                if batch and (len(batch) >= 100 or time.monotonic() >= deadline or self.stopping.is_set()):
                    try:
                        self._write(db, batch)
                    except sqlite3.Error as exc:
                        self.error = str(exc)
                        logging.exception('Archiv konnte nicht geschrieben werden')
                        if self.stopping.wait(self.interval):
                            return
                        continue
                    batch.clear()
                    self.error = None
                    deadline = time.monotonic() + self.interval

    def close(self):
        self.stopping.set()
        self.worker.join()
        if self.error:
            raise RuntimeError(f'Archiv nicht vollständig gespeichert: {self.error}')

    def search_nodes(self, q='', after=None, limit=50):
        clauses, args = [], []
        if q:
            clauses.append('(instr(casefold(COALESCE(name, \'\')), ?) > 0 OR instr(casefold(public_key), ?) > 0)')
            args.extend([q.casefold(), q.casefold()])
        if after is not None:
            clauses.append('public_key > ?')
            args.append(after)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with self.connect() as db:
            db.create_function('casefold', 1, str.casefold, deterministic=True)
            db.row_factory = sqlite3.Row
            rows = db.execute('SELECT public_key,name,advert_time,first_seen,last_seen FROM nodes' +
                              where + ' ORDER BY public_key LIMIT ?', args + [limit + 1]).fetchall()
        items = [dict(row) for row in rows[:limit]]
        return {'items': items, 'next_after': items[-1]['public_key'] if len(rows) > limit else None}

    def search(self, q='', kind='', channel='', observer_hash='', since=None, until=None, before=None, limit=50):
        clauses, args = [], []
        for column, value in (('kind', kind), ('channel', channel), ('observer_hash', observer_hash.upper())):
            if value:
                clauses.append(f'{column} = ?')
                args.append(value)
        if q:
            clauses.append('instr(search_text, ?) > 0')
            args.append(q.casefold())
        for column, op, value in (('received', '>=', since), ('received', '<=', until), ('id', '<', before)):
            if value is not None:
                clauses.append(f'{column} {op} ?')
                args.append(value)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with self.connect() as db:
            rows = db.execute('SELECT id,packet_json FROM packets' + where + ' ORDER BY id DESC LIMIT ?', args + [limit + 1]).fetchall()
        items = [dict(id=row[0], packet=json.loads(row[1])) for row in rows[:limit]]
        for item in items:
            decoded = item['packet']['decoded']
            decoded['scope_label'] = scope_label(decoded)
            decoded.update(decode_payload_details(decoded))
            if decoded.get('payload_type') == 9:
                item['packet'].update(path='TRACE (SNR-Pfad)', last_hop='Unbekannt')
        return {'items': items, 'next_before': items[-1]['id'] if len(rows) > limit else None}
