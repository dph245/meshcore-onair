"""Backfill real TRACE rows into a separate, disposable projection database."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter, sleep

from onair_trace_history import ADVERT_POSITIONS, backfill_batch, links, measurement, migrate, status


def benchmark(path, fixture_dir=None, sample_id=None):
    with TemporaryDirectory(prefix='onair-trace-') as folder, closing(
            sqlite3.connect(Path(folder) / 'projection.sqlite3')) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('ATTACH DATABASE ? AS source', (path.resolve().as_uri() + '?mode=ro',))
        db.execute('BEGIN')
        count, last = db.execute('''SELECT (SELECT COUNT(*) FROM source.packets INDEXED BY packets_received),
            (SELECT MAX(received) FROM source.packets)''').fetchone()
        for name in ('packets', 'nodes', 'manual_nodes', 'observer_radio_history',
                     'observer_radio_conflicts', 'position_state', 'position_identity',
                     'position_generation', 'position_active'):
            db.execute(f'CREATE TEMP VIEW {name} AS SELECT * FROM source.{name}')
        migrate(db)
        db.execute('CREATE TEMP VIEW trace_advert_positions AS ' +
                   ADVERT_POSITIONS.replace('FROM packets', 'FROM source.packets'))
        db.commit()
        durations = []
        total_start = perf_counter()
        progress = status(db)
        while not progress['done']:
            # Match the writer's 100 ms wait for live packets on an idle queue.
            sleep(.1)
            batch_start = perf_counter()
            progress = backfill_batch(db)
            durations.append(perf_counter() - batch_start)
            if progress['done'] or progress['scanned'] % 1000 == 0:
                print(f"TRACE: {progress['scanned']} Empfänge", flush=True)
        backfill_seconds = perf_counter() - total_start
        db.execute('PRAGMA main.wal_checkpoint(TRUNCATE)')
        size = (Path(folder) / 'projection.sqlite3').stat().st_size
        # A single source snapshot bounds the performance comparison.
        db.execute('BEGIN')
        results = []
        for days in (1, 7, 30, 0):
            end = last + 1
            start = end - days * 86400 if days else 0
            times = []
            sql_times = []
            for _ in range(5):
                query_start = perf_counter()
                result = links(db, start, end)
                times.append((perf_counter() - query_start) * 1000)
                query_start = perf_counter()
                db.execute('''SELECT measurement_id,hop,source,target,snr_qdb,event_at FROM trace_sample
                    WHERE event_at>=? AND event_at<?
                    ORDER BY event_at DESC,measurement_id DESC,hop DESC''', (start, end)).fetchall()
                sql_times.append((perf_counter() - query_start) * 1000)
            payload = json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode()
            results.append(dict(days=days, median_ms=round(median(times), 2), first_ms=round(times[0], 2),
                sample_sql_median_ms=round(median(sql_times), 2), json_bytes=len(payload),
                links=len(result['links']), **result['summary']))
            if fixture_dir:
                (fixture_dir / f'trace-links-{days}.json').write_bytes(payload)
        if result['links']:
            pair = tuple(node['public_key'] for node in result['links'][0]['endpoints'])
            begin = perf_counter()
            page = links(db, 0, end, 'all', pair)
            results[0]['sample_query_all_ms'] = round((perf_counter() - begin) * 1000, 2)
            results[0]['sample_query_json_bytes'] = len(json.dumps(page, ensure_ascii=False, separators=(',', ':')).encode())
        if sample_id is not None:
            ident = db.execute('SELECT measurement_id FROM trace_observation WHERE packet_id=?', (sample_id,)).fetchone()
            example = measurement(db, ident[0]) if ident and ident[0] else None
            if fixture_dir and example:
                (fixture_dir / 'trace-example.json').write_text(json.dumps(example, ensure_ascii=False, indent=2))
        return dict(archive_packets=count, source_schema=db.execute('PRAGMA source.user_version').fetchone()[0],
                    sqlite=sqlite3.sqlite_version, trace_receptions=progress['scanned'], extra_bytes=size,
                    backfill_seconds=round(backfill_seconds, 2), active_seconds=round(sum(durations), 2),
                    max_batch_ms=round(max(durations, default=0) * 1000, 2),
                    windows=results)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--fixture-dir', type=Path)
    parser.add_argument('--sample-id', type=int)
    args = parser.parse_args()
    if args.fixture_dir:
        args.fixture_dir.mkdir(parents=True, exist_ok=True)
    print(json.dumps(benchmark(args.archive, args.fixture_dir, args.sample_id), indent=2))
