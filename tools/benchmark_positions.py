"""Local-only migration/parity benchmark. Never opens the source for writing."""
import argparse
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import time
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from onair_distance import Positions, analyze
from onair_positions import (NormalizedPositions, backup_before_migration, evaluate,
                             migrate, current_generation)
from onair_trace_map import detail


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def packet_digest(db):
    result = hashlib.sha256()
    count = 0
    for row in db.execute('SELECT * FROM packets ORDER BY id'):
        raw = json.dumps(row, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        result.update(len(raw).to_bytes(8, 'little'))
        result.update(raw)
        count += 1
    return dict(rows=count, sha256=result.hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True,
                        help='New directory on disk with room for two SQLite copies')
    parser.add_argument('--runs', type=int, default=3)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error('--runs must be positive')
    source = args.source.resolve(strict=True)
    directory = args.directory.resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    working = directory / 'working.sqlite3'
    working.touch(mode=0o600)
    report = dict(source=str(source), working=str(working), sqlite=sqlite3.sqlite_version,
                  runs={}, timezone='Europe/Berlin')
    print('Creating local SQLite working copy', flush=True)
    t = time.perf_counter()
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src, \
            closing(sqlite3.connect(working)) as target:
        src.execute('PRAGMA query_only=ON')
        src.backup(target)
    report['copy_seconds'] = time.perf_counter() - t
    print('Creating additional pre-migration SQLite backup', flush=True)
    t = time.perf_counter()
    report['backup'] = str(backup_before_migration(working))
    if report['backup'] == 'None':
        raise RuntimeError('Source must be an unmigrated archive (schema <16)')
    report['backup_seconds'] = time.perf_counter() - t
    with closing(sqlite3.connect(working)) as db:
        print('Hashing all raw packet columns before migration', flush=True)
        before = packet_digest(db)
        print('Migrating and backfilling local working copy', flush=True)
        t = time.perf_counter()
        migrate(db)
        report['migration_and_backfill_seconds'] = time.perf_counter() - t
        # Measure a repeatable generation rebuild independently of schema/index work.
        from onair_positions import rebuild
        t = time.perf_counter()
        rebuild(db)
        report['backfill_seconds'] = time.perf_counter() - t
        print('Hashing all raw packet columns after migration', flush=True)
        after = packet_digest(db)
        report['raw_before'], report['raw_after'] = before, after
        if before != after:
            raise RuntimeError('Raw archive changed; stopping')
        generation = current_generation(db)
        report['generation'] = generation
        report['table_rows'] = {table: db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
            for table in ('position_identity', 'position_generation', 'position_active',
                          'position_state', 'position_head')}
        report['active_rows'] = {table: db.execute('SELECT count(*) FROM ' + table +
            ' WHERE generation=?', (generation,)).fetchone()[0]
            for table in ('position_state', 'position_head')}
        report['storage_bytes'] = dict(db.execute("""SELECT name,sum(pgsize) FROM dbstat
            WHERE name LIKE 'position_%' OR name='packets_advert_key_received'
            OR name LIKE 'sqlite_autoindex_position_%' GROUP BY name"""))
        zone = ZoneInfo('Europe/Berlin')
        start, end = [datetime(2026, 11, day, 18, 16, tzinfo=zone).timestamp() for day in (3, 6)]
        report.update(start=start, end=end, minimum_km=200)
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        expected = None
        # Alternate order, one warm-up per implementation; no Archive/result cache.
        for mode in ('legacy', 'normalized'):
            print('Warm-up ' + mode, flush=True)
            factory = Positions if mode == 'legacy' else NormalizedPositions
            result = analyze(db, start, end, 200, positions_factory=factory)
            checksum = digest(result)
            if expected is not None and checksum != expected:
                raise RuntimeError('Unresolved DX comparison mismatch; stopping')
            expected = checksum
        for iteration in range(args.runs):
            for mode in (('legacy', 'normalized') if iteration % 2 == 0 else ('normalized', 'legacy')):
                factory = Positions if mode == 'legacy' else NormalizedPositions
                t = time.perf_counter()
                result = analyze(db, start, end, 200, positions_factory=factory)
                elapsed = time.perf_counter() - t
                checksum = digest(result)
                if checksum != expected:
                    raise RuntimeError('Unresolved DX comparison mismatch; stopping')
                t = time.perf_counter()
                positions = factory(db, start, end)
                position_elapsed = time.perf_counter() - t
                report['runs'].setdefault(mode, []).append(dict(seconds=elapsed,
                    positions_seconds=position_elapsed, sha256=checksum))
                print(mode, iteration + 1, elapsed, checksum, flush=True)
        report['dx_sha256'] = expected
        report['links'] = len(result['items'])
        report['candidate_receptions'] = result['candidate_receptions']
        report['packets'] = result['packet_count']
        report['medians_seconds'] = {mode: statistics.median(r['seconds'] for r in runs)
                                    for mode, runs in report['runs'].items()}
        report['position_medians_seconds'] = {mode: statistics.median(r['positions_seconds'] for r in runs)
                                             for mode, runs in report['runs'].items()}
        print('Comparing all TRACE details on the same snapshot', flush=True)
        ids = [row[0] for row in db.execute("SELECT id FROM packets WHERE kind='TRACE' ORDER BY id")]
        cutoff = db.execute('SELECT max(received)+1 FROM packets').fetchone()[0]
        legacy, normalized = Positions(db, 0, cutoff), NormalizedPositions(db, 0, cutoff)
        trace_hash = hashlib.sha256()
        for ident in ids:
            old, new = detail(db, ident, legacy), detail(db, ident, normalized)
            if old != new or digest(old) != digest(new):
                raise RuntimeError('Unresolved TRACE comparison mismatch at ' + str(ident))
            trace_hash.update(bytes.fromhex(digest(old)))
        report['trace'] = dict(receptions=len(ids), sha256=trace_hash.hexdigest())
        # Exercise the production comparison orchestrator as well.
        failures = []
        compared = evaluate(db, 'compare', lambda factory:
            analyze(db, start, end, 200, positions_factory=factory), failures.append)
        if failures or digest(compared) != expected:
            raise RuntimeError('Production compare mode failed; stopping')
        db.rollback()
    output = directory / 'report.json'
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print('Report: ' + str(output), flush=True)


if __name__ == '__main__':
    main()
