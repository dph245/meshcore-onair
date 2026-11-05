"""Read-only browsing of Schema 15 RF snapshots; no ingestion or migrations."""
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
import time


@contextmanager
def snapshot(path):
    # Never create a missing DB or enter Archive's migration/writer lifecycle.
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro',
                                 uri=True, timeout=3)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        deadline = time.monotonic() + 5
        db.set_progress_handler(lambda: time.monotonic() > deadline, 10000)
        db.execute('BEGIN')
        yield db


def _names(db, keys):
    keys = sorted(set(keys))
    if not keys:
        return {}
    slots = ','.join('?' for _ in keys)
    # Both stores use full canonical keys. Never guess from a short prefix.
    return dict(db.execute(f'''SELECT public_key, name FROM nodes
        WHERE public_key IN ({slots}) AND name IS NOT NULL AND name != ''
        UNION ALL SELECT public_key, name FROM manual_nodes
        WHERE public_key IN ({slots}) AND NOT EXISTS
          (SELECT 1 FROM nodes n WHERE n.public_key=manual_nodes.public_key
           AND n.name IS NOT NULL AND n.name != '')''', keys + keys))


def observers(path, limit=500):
    with snapshot(path) as db:
        rows = db.execute('''SELECT g.observer_key,g.reports,r.origin,r.reported_at,
                r.message_id,m.received_at
            FROM (SELECT observer_key,COUNT(*) AS reports FROM rf_neighbor_reports
                  GROUP BY observer_key ORDER BY observer_key LIMIT ?) g
            JOIN rf_neighbor_reports r ON r.message_id=(
                SELECT message_id FROM rf_neighbor_reports recent
                WHERE recent.observer_key=g.observer_key
                ORDER BY reported_at DESC,message_id DESC LIMIT 1)
            JOIN rf_neighbor_messages m ON m.id=r.message_id
            ORDER BY g.observer_key''', (limit + 1,)).fetchall()
        items = [dict(row) for row in rows[:limit]]
        names = _names(db, [r['observer_key'] for r in items])
        for item in items:
            item['name'] = names.get(item['observer_key']) or item['origin'] or None
        return dict(items=items, more=len(rows) > limit)


def history(path, observer, before=None, limit=20):
    observer = observer.lower()
    with snapshot(path) as db:
        where, params = 'r.observer_key=?', [observer]
        if before is not None:
            cursor = db.execute('''SELECT reported_at FROM rf_neighbor_reports
                WHERE observer_key=? AND message_id=?''', (observer, before)).fetchone()
            if cursor is None:
                return None
            if cursor['reported_at'] is None:
                where += ' AND r.reported_at IS NULL AND r.message_id<?'
                params.append(before)
            else:
                where += ''' AND (r.reported_at<? OR (r.reported_at=? AND r.message_id<?)
                             OR r.reported_at IS NULL)'''
                params.extend((cursor['reported_at'], cursor['reported_at'], before))
        rows = db.execute(f'''SELECT r.message_id,r.reported_at,r.source_timestamp,
                r.total_neighbors,r.queried_neighbors,r.truncated,m.received_at,m.retain
            FROM rf_neighbor_reports r JOIN rf_neighbor_messages m ON m.id=r.message_id
            WHERE {where} ORDER BY r.reported_at DESC,r.message_id DESC LIMIT ?''',
                          params + [limit + 1]).fetchall()
        items = [dict(row) for row in rows[:limit]]
        return dict(items=items, next_before=items[-1]['message_id'] if len(rows) > limit else None)


def detail(path, observer, message_id):
    with snapshot(path) as db:
        row = db.execute('''SELECT r.*,m.received_at,m.retain,m.dup,m.qos
            FROM rf_neighbor_reports r JOIN rf_neighbor_messages m ON m.id=r.message_id
            WHERE r.observer_key=? AND r.message_id=?''', (observer.lower(), message_id)).fetchone()
        if row is None:
            return None
        report = dict(row)
        # Firmware snapshots are small; keep responses bounded even for imported
        # oversized data. This display bound is distinct from firmware truncated.
        rows = db.execute('''SELECT position,pubkey,snr,heard_secs_ago,heard_at,scopes,status
            FROM rf_neighbor_entries WHERE message_id=? ORDER BY position LIMIT 1001''',
                          (message_id,)).fetchall()
        entries = [dict(e) for e in rows[:1000]]
        names = _names(db, [report['observer_key']] + [e['pubkey'] for e in entries])
        report['name'] = names.get(report['observer_key']) or report['origin'] or None
        for entry in entries:
            entry['name'] = names.get(entry['pubkey'])
        return dict(report=report, entries=entries, entries_more=len(rows) > 1000)
