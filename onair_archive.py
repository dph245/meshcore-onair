"""SQLite reception archive; one writer, bounded batches, independent readers."""
import json
import logging
import os
from pathlib import Path
from queue import Queue, Empty, Full
import sqlite3
from threading import Thread, Event
import time
from datetime import datetime
from onair_repeaters import record_repeater, repeater_summary


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
                if db.execute('PRAGMA user_version').fetchone()[0] < 3:
                    db.execute('''CREATE TABLE IF NOT EXISTS repeater_receptions (
                        token TEXT PRIMARY KEY, count INTEGER NOT NULL,
                        rssi INTEGER, min_rssi INTEGER, max_rssi INTEGER,
                        last_seen REAL NOT NULL)''')
                    db.execute('DELETE FROM repeater_receptions')
                    for (raw,) in db.execute('SELECT packet_json FROM packets ORDER BY id'):
                        record_repeater(db, json.loads(raw))
                    db.execute('PRAGMA user_version=3')
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
                    db.execute('INSERT INTO noise_samples(received_at,noise_floor) VALUES(?,?)',
                               (sample['received_at'], sample['noise_floor']))
                    continue
                d = p['decoded']
                record_repeater(db, p)
                a = d.get('advert')
                received = datetime.fromisoformat(p['received_at']).timestamp()
                search = ' '.join(str(v) for v in (p['observer_hash'] or '', p['path'],
                    ' '.join(d['hops']), d.get('group_text') or '', d.get('group_channel') or '',
                    a.get('name') or '' if a else '', a.get('public_key') or '' if a else '')).casefold()
                db.execute('INSERT INTO packets(received,kind,channel,observer_hash,search_text,packet_json) VALUES(?,?,?,?,?,?)',
                    (received, d['payload_name'], d.get('group_channel'), p['observer_hash'], search,
                     json.dumps(p, ensure_ascii=False)))
                if a and not d.get('advert_status') and a.get('signature_status') == 'Gültig':
                    db.execute('''INSERT INTO nodes VALUES(?,?,?,?,?) ON CONFLICT(public_key) DO UPDATE SET
                        name=CASE WHEN excluded.advert_time > nodes.advert_time THEN excluded.name ELSE nodes.name END,
                        advert_time=MAX(nodes.advert_time,excluded.advert_time),
                        last_seen=MAX(nodes.last_seen,excluded.last_seen)''',
                        (a['public_key'], a['name'], a['timestamp'], received, received))
            names = dict(db.execute('SELECT public_key, name FROM nodes'))
        self.saved += sum('noise_sample' not in p for p in batch)
        self.names = names

    def noise_history(self, limit=500):
        with self.connect() as db:
            rows = db.execute('SELECT received_at,noise_floor FROM noise_samples ORDER BY id DESC LIMIT ?',
                              (limit,)).fetchall()
        return [{'received_at': row[0], 'noise_floor': row[1]} for row in reversed(rows)]

    def repeaters(self):
        from onair_mqtt import node_label
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute('SELECT * FROM repeater_receptions').fetchall()
            names = dict(db.execute('SELECT public_key,name FROM nodes'))
        return {'items': repeater_summary(rows, names, node_label)}

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
        return {'items': items, 'next_before': items[-1]['id'] if len(rows) > limit else None}
