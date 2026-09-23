"""SQLite reception archive; one writer, bounded batches, independent readers."""
import json
import logging
import os
from pathlib import Path
from queue import Queue, Empty, Full
import sqlite3
from threading import Thread, Event, Lock
import time
from datetime import datetime
from onair_repeaters import record_repeater, repeater_summary, repeater_token
from onair_scopes import scope_label
from onair_observers import record_observer, observer_comparison
from onair_neighbors import record_path, neighbor_summary


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
        self._neighbors_expires = 0
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

    def map_nodes(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute('SELECT * FROM nodes ORDER BY public_key').fetchall()
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
                items.append(dict(row))
        return {'items': items, 'without_position': without_position, 'inactive': inactive}

    def neighbors(self):
        with self.connect() as db, db:
            db.execute('BEGIN')
            return neighbor_summary(db)

    def neighbors_json(self):
        # Share both computation and JSON serialization across concurrent clients.
        # Keep a bounded refresh rate even when receptions arrive continuously.
        with self._neighbors_lock:
            if self._neighbors_json is None or time.monotonic() >= self._neighbors_expires:
                result = json.dumps(self.neighbors(), ensure_ascii=False,
                                    separators=(',', ':')).encode('utf-8')
                self._neighbors_json = result
                self._neighbors_expires = time.monotonic() + 30
            return self._neighbors_json

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

    def repeaters(self, hours=8):
        from onair_mqtt import node_label
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute('SELECT * FROM repeater_receptions').fetchall()
            names = dict(db.execute('SELECT public_key,name FROM nodes'))
        items = repeater_summary(rows, names, node_label)
        # Resolve identities using all known tokens before filtering activity.
        if hours:
            since = time.time() - hours * 3600
            items = [item for item in items if item['last_seen'] >= since]
        return {'items': items}

    def repeater_history(self, identity, hours=24, limit=500):
        item = next((item for item in self.repeaters(hours=0)['items'] if item['id'] == identity), None)
        if item is None:
            return {'items': [], 'has_more': False}
        tokens = item['tokens']
        placeholders = ','.join('?' for _ in tokens)
        since = time.time() - hours * 3600 if hours else 0
        with self.connect() as db:
            rows = db.execute(f'''SELECT received, json_extract(packet_json, '$.rssi'),
                json_extract(packet_json, '$.origin_id'), json_extract(packet_json, '$.origin')
                FROM packets WHERE repeater_token IN ({placeholders}) AND received >= ?
                AND json_extract(packet_json, '$.rssi') IS NOT NULL
                ORDER BY received DESC,id DESC LIMIT ?''', tokens + [since, limit + 1]).fetchall()
        return {'items': [{'received': row[0], 'rssi': row[1],
                           'origin_id': row[2], 'origin': row[3]} for row in reversed(rows[:limit])],
                'has_more': len(rows) > limit}

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
        return {'items': items, 'next_before': items[-1]['id'] if len(rows) > limit else None}
