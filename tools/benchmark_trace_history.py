"""Backfill real TRACE rows into a separate, disposable projection database."""
import argparse
from collections import Counter
from contextlib import closing, contextmanager
from gzip import compress
import json
from math import isfinite
from pathlib import Path
import signal
import sqlite3
from statistics import median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter, sleep

from onair_trace_history import backfill_batch, links, measurement, migrate, status
from onair_trace_positions import TracePositionCache

DEFAULT_TIMEOUT = 60
REPEATS = 5
SAMPLE_SQL = '''SELECT measurement_id,hop,source,target,snr_qdb,event_at FROM trace_sample
    WHERE event_at>=? AND event_at<?
    ORDER BY event_at DESC,measurement_id DESC,hop DESC'''


class Run:
    def __init__(self, timeout):
        self.start = perf_counter()
        self.deadline = self.start + timeout
        self.next_heartbeat = self.start + 5
        self.phase = 'start'
        self.detail = ''
        self.timings = {}
        self.terminated = False

    def log(self, message):
        print(f'[{perf_counter() - self.start:7.2f} s] {self.phase}: {message}',
              file=sys.stderr, flush=True)

    def check(self):
        if perf_counter() >= self.deadline:
            raise TimeoutError

    def sqlite_progress(self):
        now = perf_counter()
        if now >= self.deadline:
            return 1
        if now >= self.next_heartbeat:
            self.log(f'SQLite arbeitet weiter (bislang {now - self.phase_start:.1f} s in diesem Abschnitt). '
                     f'{self.detail}'.rstrip())
            self.next_heartbeat = now + 5
        return 0

    @contextmanager
    def section(self, name, description):
        self.phase, self.detail = name, ''
        self.phase_start = perf_counter()
        self.check()
        self.next_heartbeat = self.phase_start + 5
        self.log(description)
        yield
        self.check()
        elapsed = perf_counter() - self.phase_start
        self.timings[name] = round(elapsed, 4)
        self.log(f'Fertig in {elapsed:.3f} s.')

    @contextmanager
    def signals(self):
        def stop(signum, _frame):
            if signum == signal.SIGALRM:
                raise TimeoutError
            self.terminated = True
            raise KeyboardInterrupt

        previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGALRM)}
        try:
            remaining = self.deadline - perf_counter()
            if remaining <= 0:
                raise TimeoutError
            signal.setitimer(signal.ITIMER_REAL, remaining)
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def connect_source(db, path):
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('ATTACH DATABASE ? AS source', (path.resolve().as_uri() + '?mode=ro',))
    db.execute('BEGIN')
    for name in ('packets', 'nodes', 'manual_nodes', 'observer_radio_history',
                 'observer_radio_conflicts', 'position_state', 'position_identity',
                 'position_generation', 'position_active'):
        db.execute(f'CREATE TEMP VIEW {name} AS SELECT * FROM source.{name}')


def build_projection(db):
    migrate(db)
    db.commit()


def timed_backfill(db, total, run):
    durations = []
    progress = status(db)
    while not progress['done']:
        run.check()
        previous = progress['scanned']
        # Match the writer's 100 ms wait for live packets on an idle queue.
        sleep(.1)
        start = perf_counter()
        progress = backfill_batch(db)
        durations.append(perf_counter() - start)
        scanned = progress['scanned']
        if progress['done'] or not previous or scanned // 1000 != previous // 1000:
            run.log(f'{scanned:,}/{total:,} TRACE-Empfänge'.replace(',', '.'))
    return progress, durations


def measure_window(db, start, end, days, run, position_cache):
    times = []
    sql_times = []
    for index in range(1, REPEATS + 1):
        run.detail = f'Aggregation {index}/{REPEATS}'
        before = perf_counter()
        result = links(db, start, end, position_cache=position_cache)
        times.append((perf_counter() - before) * 1000)
        run.detail = f'SQL-Stichprobe {index}/{REPEATS}'
        before = perf_counter()
        db.execute(SAMPLE_SQL, (start, end)).fetchall()
        sql_times.append((perf_counter() - before) * 1000)
        run.log(f'{index}/{REPEATS} · Aggregation {times[-1]:.2f} ms · SQL {sql_times[-1]:.2f} ms')
        run.check()
    run.detail = 'JSON kodieren'
    before = perf_counter()
    payload = json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode()
    json_ms = round((perf_counter() - before) * 1000, 2)
    before = perf_counter()
    gzip_bytes = len(compress(payload, compresslevel=3, mtime=0))
    gzip_ms = round((perf_counter() - before) * 1000, 2)
    categories = {mode: dict(Counter(link['analysis'][mode]['category'] for link in result['links']))
                  for mode in ('reserve', 'asymmetry', 'coverage', 'sf7')}
    profile_directions = [group[direction] for link in result['links'] for group in link['profiles']
                          for direction in ('forward', 'reverse') if group[direction]]
    return result['links'], payload, dict(days=days, median_ms=round(median(times), 2),
        first_ms=round(times[0], 2), sample_sql_median_ms=round(median(sql_times), 2),
        json_ms=json_ms, json_bytes=len(payload), gzip_ms=gzip_ms, gzip_bytes=gzip_bytes,
        analysis_categories=categories,
        profile_directions=len(profile_directions),
        profile_direction_readings=sum(values['count'] for values in profile_directions),
        links=len(result['links']), **result['summary'])


def publish_fixtures(folder, output, filenames, run):
    # Stage on the destination filesystem. A new fixture directory is published
    # with one rename. Existing directories keep other files and each JSON is
    # replaced atomically, only once all measurements have completed.
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.onair-trace-fixtures-', dir=output.parent) as staging:
        staged = Path(staging) / 'results'
        staged.mkdir()
        for name in filenames:
            run.check()
            (staged / name).write_bytes((folder / name).read_bytes())
        run.check()
        if not output.exists():
            staged.rename(output)
        else:
            for name in filenames:
                (staged / name).replace(output / name)


def benchmark(path, fixture_dir=None, sample_id=None, *, run=None):
    run = run or Run(DEFAULT_TIMEOUT)
    with TemporaryDirectory(prefix='onair-trace-') as temp:
        folder = Path(temp)
        projection = folder / 'projection.sqlite3'
        with closing(sqlite3.connect(projection, timeout=5)) as db:
            db.set_progress_handler(run.sqlite_progress, 10000)
            with run.section('source_attach', 'Quellarchiv lesend anbinden'):
                connect_source(db, path)
            with run.section('source_inventory', 'Pakete und TRACE-Empfänge über die vorhandenen Indizes zählen'):
                count, last, trace_count = db.execute('''SELECT
                    (SELECT COUNT(*) FROM source.packets INDEXED BY packets_received),
                    COALESCE((SELECT MAX(received) FROM source.packets), 0),
                    (SELECT COUNT(*) FROM source.packets WHERE kind='TRACE')''').fetchone()
                schema = db.execute('PRAGMA source.user_version').fetchone()[0]
                run.log(f'{count:,} Pakete, {trace_count:,} TRACE, Schema {schema}'.replace(',', '.'))
            with run.section('projection_schema', 'Temporäre Projektion anlegen'):
                build_projection(db)
            with run.section('backfill', f'{trace_count} TRACE-Empfänge in Batches aufarbeiten'):
                progress, durations = timed_backfill(db, trace_count, run)
            with run.section('checkpoint', 'Temporäre Datenbank sichern und Größe erfassen'):
                db.execute('PRAGMA main.wal_checkpoint(TRUNCATE)')
                size = projection.stat().st_size

            # A single source snapshot bounds the performance comparison.
            db.execute('BEGIN')
            results = []
            filenames = []
            end = last + 1
            position_cache = TracePositionCache(attached_source=True)
            for days in (1, 7, 30, 0):
                with run.section(f'window_{days}d' if days else 'window_all',
                                 f'{days} Tage auswerten' if days else 'Gesamten Bestand auswerten'):
                    start = max(0, end - days * 86400) if days else 0
                    map_links, payload, summary = measure_window(db, start, end, days, run, position_cache)
                    results.append(summary)
                    if fixture_dir:
                        name = f'trace-links-{days}.json'
                        (folder / name).write_bytes(payload)
                        filenames.append(name)
            if map_links:
                with run.section('single_link', 'Eine Seite Einzelwerte für die erste Linkstrecke laden'):
                    pair = tuple(node['public_key'] for node in map_links[0]['endpoints'])
                    before = perf_counter()
                    page = links(db, 0, end, 'all', pair, position_cache=position_cache)
                    results[-1]['sample_query_all_ms'] = round((perf_counter() - before) * 1000, 2)
                    results[-1]['sample_query_json_bytes'] = len(json.dumps(
                        page, ensure_ascii=False, separators=(',', ':')).encode())
            if sample_id is not None:
                with run.section('sample', f'TRACE-Rohpaket #{sample_id} zuordnen'):
                    ident = db.execute('SELECT measurement_id FROM trace_observation WHERE packet_id=?',
                                       (sample_id,)).fetchone()
                    example = measurement(db, ident[0], position_cache=position_cache) if ident and ident[0] else None
                    if fixture_dir and example:
                        (folder / 'trace-example.json').write_text(json.dumps(example, ensure_ascii=False, indent=2))
                        filenames.append('trace-example.json')
                    if example is None:
                        run.log('Keine dekodierbare Messung für diese Rohpaket-ID.')
        if fixture_dir:
            with run.section('fixtures', 'Vollständige JSON-Fixtures veröffentlichen'):
                publish_fixtures(folder, fixture_dir, filenames, run)
    return dict(archive_packets=count, source_schema=schema, sqlite=sqlite3.sqlite_version,
                trace_receptions=progress['scanned'], extra_bytes=size,
                backfill_seconds=round(run.timings['backfill'], 2), active_seconds=round(sum(durations), 2),
                max_batch_ms=round(max(durations, default=0) * 1000, 2),
                total_seconds=round(perf_counter() - run.start, 3), section_seconds=run.timings, windows=results)


def timeout_seconds(value):
    try:
        seconds = float(value)
    except ValueError:
        seconds = 0
    if not isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError('Eine positive, endliche Sekundenzahl angeben.')
    return seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--fixture-dir', type=Path)
    parser.add_argument('--sample-id', type=int)
    parser.add_argument('--timeout', type=timeout_seconds, default=DEFAULT_TIMEOUT, metavar='SEKUNDEN',
                        help='Zeitlimit für den gesamten Lauf (Standard: %(default)s Sekunden)')
    args = parser.parse_args()
    run = Run(args.timeout)
    try:
        with run.signals():
            result = benchmark(args.archive, args.fixture_dir, args.sample_id, run=run)
        print(json.dumps(result, indent=2))
        return 0
    except (KeyboardInterrupt, TimeoutError, OSError, sqlite3.Error) as exc:
        if run.terminated or isinstance(exc, KeyboardInterrupt):
            run.log(f'Abgebrochen. {run.detail}'.rstrip())
            return 143 if run.terminated else 130
        if isinstance(exc, TimeoutError) or perf_counter() >= run.deadline:
            run.log(f'Zeitlimit von {args.timeout:g} s erreicht. {run.detail}'.rstrip())
            return 124
        run.log(f'Fehler: {exc}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
