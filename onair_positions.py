"""Rebuildable ADVERT position projection; the raw archive remains authoritative."""
from collections import defaultdict
from contextlib import contextmanager, closing
import json
import logging
from pathlib import Path
import sqlite3
import uuid

from onair_distance import Positions
from onair_neighbors import distance_km

SEMANTICS_VERSION = 1
MODES = ('legacy', 'compare', 'normalized')
ADVERT_WHERE = "kind='ADVERT' AND json_extract(packet_json,'$.decoded.advert_status') IS NULL"
KEY_EXPR = "json_extract(packet_json,'$.decoded.advert.public_key')"


class PositionUnavailable(ValueError):
    pass


class PositionMismatch(PositionUnavailable):
    pass


@contextmanager
def atomic(db):
    # Unlike executescript(), SAVEPOINT never commits a caller's transaction.
    name = 'positions_' + uuid.uuid4().hex
    db.execute('SAVEPOINT ' + name)
    try:
        yield
    except BaseException:
        db.execute('ROLLBACK TO ' + name)
        raise
    finally:
        db.execute('RELEASE ' + name)


def backup_before_migration(path, force=False):
    """SQLite backup before any schema-16 writes, including on older archives."""
    path = Path(path).resolve()
    if not path.exists() or not path.stat().st_size:
        return None
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as source:
        if not force and source.execute('PRAGMA user_version').fetchone()[0] >= 16:
            return None
        backup = path.with_name(path.stem + '.pre-position-v16-' + uuid.uuid4().hex + '.sqlite3')
        backup.touch(mode=0o600, exist_ok=False)
        with closing(sqlite3.connect(backup)) as target:
            source.backup(target)
    logging.info('SQLite-Sicherung vor Positionsmigration: %s', backup)
    return backup


def migrate(db, progress=None):
    """Atomic, retryable schema and initial generation. Caller owns the backup."""
    with atomic(db):
        for sql in (
            '''CREATE TABLE IF NOT EXISTS position_identity (
                node_id INTEGER PRIMARY KEY, public_key TEXT NOT NULL UNIQUE
                CHECK(length(public_key)=64 AND public_key NOT GLOB '*[^0-9a-f]*'))''',
            '''CREATE TABLE IF NOT EXISTS position_generation (
                generation INTEGER PRIMARY KEY, semantics_version INTEGER NOT NULL,
                archive_epoch TEXT NOT NULL, source_revision INTEGER NOT NULL,
                source_high_id INTEGER NOT NULL, position_revision INTEGER NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('building','ready','invalid')))''',
            '''CREATE TABLE IF NOT EXISTS position_active (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                generation INTEGER NOT NULL REFERENCES position_generation(generation),
                archive_epoch TEXT NOT NULL, source_revision INTEGER NOT NULL DEFAULT 0)''',
            '''CREATE TABLE IF NOT EXISTS position_state (
                generation INTEGER NOT NULL REFERENCES position_generation(generation),
                node_id INTEGER NOT NULL REFERENCES position_identity(node_id),
                received REAL NOT NULL, packet_id INTEGER NOT NULL,
                advert_timestamp INTEGER NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL,
                PRIMARY KEY(generation,node_id,received,packet_id)) WITHOUT ROWID''',
            '''CREATE INDEX IF NOT EXISTS position_state_window
                ON position_state(generation,received,packet_id,node_id)''',
            '''CREATE TABLE IF NOT EXISTS position_head (
                generation INTEGER NOT NULL REFERENCES position_generation(generation),
                node_id INTEGER NOT NULL REFERENCES position_identity(node_id),
                max_position_timestamp INTEGER NOT NULL,
                last_order_received REAL NOT NULL, last_order_packet_id INTEGER NOT NULL,
                PRIMARY KEY(generation,node_id)) WITHOUT ROWID''',
            f'''CREATE INDEX IF NOT EXISTS packets_advert_key_received
                ON packets({KEY_EXPR},received,id) WHERE {ADVERT_WHERE}''',
            # Raw corrections/deletions invalidate even if MAX(id) is unchanged.
            '''CREATE TRIGGER IF NOT EXISTS position_packets_update AFTER UPDATE ON packets
                WHEN OLD.kind='ADVERT' OR NEW.kind='ADVERT' BEGIN
                UPDATE position_active SET source_revision=source_revision+1;
                UPDATE position_generation SET status='invalid'; END''',
            '''CREATE TRIGGER IF NOT EXISTS position_packets_delete AFTER DELETE ON packets
                WHEN OLD.kind='ADVERT' BEGIN
                UPDATE position_active SET source_revision=source_revision+1;
                UPDATE position_generation SET status='invalid'; END''',
            '''CREATE TRIGGER IF NOT EXISTS position_packets_insert AFTER INSERT ON packets
                WHEN NEW.id <= COALESCE((SELECT source_high_id FROM position_generation
                    JOIN position_active USING(generation)), -1) BEGIN
                UPDATE position_active SET source_revision=source_revision+1;
                UPDATE position_generation SET status='invalid'; END''',
        ):
            db.execute(sql)
        try:
            current_generation(db)
        except PositionUnavailable:
            rebuild(db, progress=progress)
        db.execute('PRAGMA user_version=16')


def _candidate(raw):
    a = json.loads(raw) if raw else None
    if (not a or not a.get('public_key') or a.get('timestamp') is None
            or a.get('signature_status') != 'Gültig'
            or a.get('latitude') is None or a.get('longitude') is None):
        return None
    return a


def _rows(db, high, key=None, after=None):
    extra = f' AND {KEY_EXPR}=?' if key is not None else ''
    lower = ' AND id>?' if after is not None else ''
    args = [high]
    if after is not None:
        args.append(after)
    if key is not None:
        args.append(key)
    return db.execute(f'''SELECT id,received,json_extract(packet_json,'$.decoded.advert')
        FROM packets WHERE {ADVERT_WHERE} AND id<=? {lower} {extra}
        ORDER BY received,id''', args)


def _load_heads(db, generation, keys):
    heads = {}
    if not keys:
        return heads
    placeholders = ','.join('?' for _ in keys)
    for node, key, stamp, received, ident in db.execute(f'''SELECT h.node_id,i.public_key,
            h.max_position_timestamp,h.last_order_received,h.last_order_packet_id
            FROM position_head h JOIN position_identity i USING(node_id)
            WHERE h.generation=? AND i.public_key IN ({placeholders})''', (generation, *keys)):
        state = db.execute('''SELECT latitude,longitude FROM position_state
            WHERE generation=? AND node_id=? ORDER BY received DESC,packet_id DESC LIMIT 1''',
                           (generation, node)).fetchone()
        heads[key] = [node, stamp, (received, ident), state]
    return heads


def _apply(db, generation, heads, ident, received, a):
    key, stamp = a['public_key'], a['timestamp']
    head = heads.get(key)
    if head is None:
        db.execute('INSERT OR IGNORE INTO position_identity(public_key) VALUES(?)', (key,))
        node = db.execute('SELECT node_id FROM position_identity WHERE public_key=?', (key,)).fetchone()[0]
        head = heads[key] = [node, -1, (received, ident), None]
    head[2] = (received, ident)
    if stamp < head[1]:
        return
    head[1] = stamp
    point = (a['latitude'], a['longitude'])
    if head[3] != point:
        db.execute('INSERT INTO position_state VALUES(?,?,?,?,?,?,?)',
                   (generation, head[0], received, ident, stamp, *point))
        head[3] = point


def _save_heads(db, generation, heads):
    db.executemany('''INSERT INTO position_head VALUES(?,?,?,?,?)
        ON CONFLICT(generation,node_id) DO UPDATE SET
        max_position_timestamp=excluded.max_position_timestamp,
        last_order_received=excluded.last_order_received,
        last_order_packet_id=excluded.last_order_packet_id''',
        ((generation, h[0], h[1], *h[2]) for h in heads.values()))


def rebuild(db, progress=None):
    """Build beside the previous generation and atomically publish on success."""
    with atomic(db):
        old = db.execute('SELECT archive_epoch,source_revision FROM position_active').fetchone()
        epoch, revision = old if old else (uuid.uuid4().hex, 0)
        high = db.execute('SELECT COALESCE(MAX(id),0) FROM packets').fetchone()[0]
        cursor = db.execute('''INSERT INTO position_generation
            (semantics_version,archive_epoch,source_revision,source_high_id,position_revision,status)
            VALUES(?,?,?,?,0,'building')''', (SEMANTICS_VERSION, epoch, revision, high))
        generation = cursor.lastrowid
        heads = {}
        for count, (ident, received, raw) in enumerate(_rows(db, high), 1):
            a = _candidate(raw)
            if a:
                _apply(db, generation, heads, ident, received, a)
            if progress:
                progress(count)
        _save_heads(db, generation, heads)
        db.execute("UPDATE position_generation SET status='ready' WHERE generation=?", (generation,))
        db.execute('''INSERT INTO position_active VALUES(1,?,?,?) ON CONFLICT(singleton)
            DO UPDATE SET generation=excluded.generation''', (generation, epoch, revision))
        return generation


def current_generation(db):
    row = db.execute('''SELECT g.generation,g.source_high_id FROM position_generation g
        JOIN position_active a USING(generation) WHERE g.status='ready'
        AND g.semantics_version=? AND g.archive_epoch=a.archive_epoch
        AND g.source_revision=a.source_revision''', (SEMANTICS_VERSION,)).fetchone()
    if row is None or row[1] != db.execute('SELECT COALESCE(MAX(id),0) FROM packets').fetchone()[0]:
        raise PositionUnavailable('Positionshistorie fehlt, ist ungültig oder nicht aktuell')
    return row[0]


def synchronize(db):
    """Idempotent high-ID catch-up; backdated receptions rebuild the affected key."""
    with atomic(db):
        row = db.execute('''SELECT g.generation,g.source_high_id FROM position_generation g
            JOIN position_active a USING(generation) WHERE g.status='ready'
            AND g.semantics_version=? AND g.archive_epoch=a.archive_epoch
            AND g.source_revision=a.source_revision''', (SEMANTICS_VERSION,)).fetchone()
        if row is None:
            raise PositionUnavailable('Positionshistorie benötigt einen Wiederaufbau')
        generation, after = row
        high = db.execute('SELECT COALESCE(MAX(id),0) FROM packets').fetchone()[0]
        if high == after:
            return
        if high < after:
            raise PositionUnavailable('Archiv wurde ersetzt oder verkürzt')
        candidates = [(ident, received, a) for ident, received, raw in _rows(db, high, after=after)
                      if (a := _candidate(raw)) is not None]
        # Writer batches are bounded; unrelated receptions never load all heads.
        heads = _load_heads(db, generation, {a['public_key'] for _, _, a in candidates})
        late = set()
        changed = {}
        for ident, received, a in candidates:
            key = a['public_key']
            if key in late:
                continue
            if key in heads and (received, ident) <= heads[key][2]:
                late.add(key)
                continue
            _apply(db, generation, heads, ident, received, a)
            changed[key] = heads[key]
        for key in late:
            node = heads[key][0]
            db.execute('DELETE FROM position_state WHERE generation=? AND node_id=?', (generation, node))
            db.execute('DELETE FROM position_head WHERE generation=? AND node_id=?', (generation, node))
            del heads[key]
            for ident, received, raw in _rows(db, high, key=key):
                a = _candidate(raw)
                if a:
                    _apply(db, generation, heads, ident, received, a)
            changed[key] = heads[key]
        _save_heads(db, generation, changed)
        db.execute('''UPDATE position_generation SET source_high_id=?,
            position_revision=position_revision+1 WHERE generation=?''', (high, generation))


def maintain(db):
    """Projection errors cannot discard an otherwise archivable reception batch."""
    try:
        synchronize(db)
    except Exception:
        logging.exception('Positionshistorie ungültig; Legacy bleibt verfügbar')
        try:
            db.execute("UPDATE position_generation SET status='invalid' WHERE generation IN (SELECT generation FROM position_active)")
        except sqlite3.Error:
            # A missing projection schema is itself a safe read-side fallback.
            logging.exception('Positionsgeneration konnte nicht invalidiert werden')


class NormalizedPositions(Positions):
    def __init__(self, db, start, end, keys=()):
        generation = current_generation(db)
        self.times = defaultdict(list)
        self.values = defaultdict(list)
        key_filter = ' AND i.public_key IN (' + ','.join('?' for _ in keys) + ')' if keys else ''
        # One predecessor per key, followed by all changes in [start,end).
        seeds = db.execute(f'''SELECT i.public_key,s.received,s.latitude,s.longitude
            FROM position_head h JOIN position_identity i USING(node_id)
            JOIN position_state s ON s.generation=h.generation AND s.node_id=h.node_id
            AND (s.received,s.packet_id)=(SELECT p.received,p.packet_id FROM position_state p
                WHERE p.generation=h.generation AND p.node_id=h.node_id AND p.received<?
                ORDER BY p.received DESC,p.packet_id DESC LIMIT 1)
            WHERE h.generation=? {key_filter}''', (min(start, end), generation, *keys))
        for key, received, latitude, longitude in seeds:
            self.times[key].append(received)
            self.values[key].append(dict(latitude=latitude, longitude=longitude))
        for key, received, latitude, longitude in db.execute(f'''SELECT i.public_key,
                s.received,s.latitude,s.longitude FROM position_state s
                JOIN position_identity i USING(node_id)
                WHERE s.generation=? AND s.received>=? AND s.received<? {key_filter}
                ORDER BY s.received,s.packet_id''', (generation, start, end, *keys)):
            self.times[key].append(received)
            self.values[key].append(dict(latitude=latitude, longitude=longitude))
        self.bounds = {}
        for key, values in self.values.items():
            valid = [p for p in values if distance_km(p, p) is not None]
            if valid:
                anchor = valid[0]
                self.bounds[key] = (anchor, max(distance_km(anchor, p) for p in valid))


def evaluate(db, mode, operation, on_failure=None):
    """Compare complete results on one snapshot; always return Legacy on failure."""
    if mode not in MODES:
        raise ValueError('Unbekannter Positionsmodus: ' + mode)
    with atomic(db):
        if mode == 'legacy':
            return operation(Positions)
        snapshots = []
        compared = 0

        def legacy_factory(connection, start, end, keys=()):
            positions = Positions(connection, start, end, keys)
            snapshots.append((positions, start, end))
            return positions

        def normalized_factory(connection, start, end, keys=()):
            nonlocal compared
            positions = NormalizedPositions(connection, start, end, keys)
            if compared >= len(snapshots):
                raise PositionMismatch('Unterschiedliche Positionsabrufe')
            old, old_start, old_end = snapshots[compared]
            compared += 1
            if (start, end) != (old_start, old_end) or old.bounds != positions.bounds:
                raise PositionMismatch('Positionsfenster oder Bewegungsgrenzen weichen ab')
            for key in set(old.values) | set(positions.values):
                samples = {start} | {t for t in old.times[key] + positions.times[key] if start <= t < end}
                if any(old.at(key, t) != positions.at(key, t) for t in samples):
                    raise PositionMismatch('Positionszustände weichen ab: ' + key)
            return positions

        legacy = operation(legacy_factory) if mode == 'compare' else None
        try:
            normalized = operation(normalized_factory if mode == 'compare' else NormalizedPositions)
            if mode == 'compare' and (normalized != legacy or compared != len(snapshots)):
                raise PositionMismatch('Legacy und normalisierte Positionsauswertung weichen ab')
        except Exception as exc:
            logging.error('Positionsauswertung: vollständiger Legacy-Fallback: %s', exc)
            if on_failure:
                on_failure(exc)
            return legacy if mode == 'compare' else operation(Positions)
        return legacy if mode == 'compare' else normalized


def main():
    """Explicit offline administration: backup, then migrate or rebuild one DB."""
    import argparse
    import time
    parser = argparse.ArgumentParser(description='Lokaler Positions-Neuaufbau mit SQLite-Sicherung')
    parser.add_argument('--db', type=Path, required=True)
    args = parser.parse_args()
    path = args.db.resolve(strict=True)
    backup = backup_before_migration(path, force=True)
    started = time.perf_counter()
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)) as db:
        with db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('PRAGMA user_version').fetchone()[0] < 16:
                migrate(db)
            else:
                rebuild(db)
            generation = current_generation(db)
    print(json.dumps(dict(backup=str(backup), generation=generation,
                          seconds=time.perf_counter() - started)))


if __name__ == '__main__':
    main()
