"""Benchmark the production lookup with temporary profiles on a read-only archive."""
import argparse
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from statistics import median, quantiles
from time import perf_counter

from onair_observer_radio import (
    CONFLICTS_SQL, HISTORY_SQL, RadioReport, observer_identity, radio_profile_at, record_radio,
    _AT, _CONFLICT_AT, _NEXT,
)


def benchmark(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA temp_store=FILE')
        for statement in (HISTORY_SQL, CONFLICTS_SQL):
            db.execute(statement.replace('CREATE TABLE', 'CREATE TEMP TABLE', 1))
        db.execute('''CREATE UNIQUE INDEX temp.observer_radio_open_conflict
            ON observer_radio_conflicts (origin_id) WHERE resolved_at IS NULL''')
        packet_count = db.execute('SELECT COUNT(*) FROM main.packets INDEXED BY packets_received').fetchone()[0]
        recent = [(key, received) for origin_id, received in db.execute(
            'SELECT origin_id, received FROM main.packets ORDER BY id DESC LIMIT 5000')
            if (key := observer_identity(origin_id)) is not None]
        if not recent:
            raise ValueError('Im Stichprobenfenster fehlt ein Empfang mit Observer-ID')
        identities = list(dict.fromkeys(key for key, _ in recent))
        end = int(recent[0][1])
        versions = 2000
        start = end - versions * 300
        with db:
            for origin_id in identities:
                for version in range(versions):
                    observed = start + version * 300
                    profile = dict(frequency_hz=869618000, bandwidth_hz=62500,
                                   spreading_factor=7 + version % 2, coding_rate=8)
                    for time in (observed, observed + 100):
                        record_radio(db, RadioReport(origin_id, None, time, time + 1, False, profile))
        query_times = []
        matches = Counter()
        # Include archived reception timestamps and controlled lookup points for
        # exact matches, preceding observations, and known transition gaps.
        probes = recent + [(identities[i % len(identities)], start + i * 300 + offset)
                           for i in range(versions) for offset in (0, 50, 150)]
        for origin_id, received in probes:
            begin = perf_counter()
            result = radio_profile_at(db, origin_id, received)
            query_times.append((perf_counter() - begin) * 1e6)
            matches[result['match']] += 1
        return dict(sqlite=sqlite3.sqlite_version,
                    source_schema=db.execute('PRAGMA main.user_version').fetchone()[0],
                    archive_packets=packet_count, source_bytes=path.stat().st_size,
                    observers=len(identities), status_reports=2 * versions * len(identities),
                    profile_rows=db.execute('SELECT COUNT(*) FROM observer_radio_history').fetchone()[0],
                    queries=len(probes), matches=matches, median_us=round(median(query_times), 2),
                    p95_us=round(quantiles(query_times, n=100)[94], 2),
                    plans=[db.execute('EXPLAIN QUERY PLAN ' + sql, probes[0]).fetchone()[3]
                           for sql in (_AT, _CONFLICT_AT, _NEXT)])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    print(json.dumps(benchmark(args.archive), indent=2))
