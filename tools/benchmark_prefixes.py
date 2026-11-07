"""Compare prefix resolution with a Git revision using a fixed local SQLite snapshot."""
import argparse
from contextlib import closing, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import itertools
import json
from pathlib import Path
import random
import sqlite3
import statistics
import subprocess
import sys
from threading import Lock
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import onair_archive
import onair_mqtt
import onair_repeaters
import onair_web


def reference_module(revision, name):
    # Execute the unchanged reference in a separate module namespace.
    filename = name + '.py'
    source = subprocess.check_output(['git', 'show', f'{revision}:{filename}'], cwd=ROOT)
    module = ModuleType('reference_' + name)
    module.__file__ = str(ROOT / filename)
    sys.modules[module.__name__] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module


def snapshot_inputs(path):
    wal = path.with_name(path.name + '-wal')
    if wal.exists() and wal.stat().st_size:
        raise ValueError('Use a fixed snapshot with no pending WAL frames')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        db.row_factory = sqlite3.Row
        names = dict(db.execute('SELECT public_key,name FROM nodes'))
        rows = [dict(row) for row in db.execute('SELECT * FROM repeater_receptions ORDER BY rowid')]
        packets = db.execute('SELECT id,kind,packet_json FROM packets ORDER BY id DESC LIMIT 200').fetchall()
    if len(packets) != 200 or len(names) != 2790:
        raise ValueError('Expected 2,790 known nodes and at least 200 archived packets')
    packets.reverse()
    messages, hops = [], set()
    for row in packets:
        packet = json.loads(row['packet_json'])
        messages.append(dict(raw=packet['raw_hex'], direction=packet['direction'],
                             hash=packet['observer_hash'], time=packet['time'],
                             RSSI=packet['rssi'], SNR=packet['snr'], len=packet['length'],
                             origin_id=packet.get('origin_id'), origin=packet.get('origin')))
        hops.update(packet['decoded']['hops'])
    return names, rows, messages, sorted(hops), (packets[0]['id'], packets[-1]['id'])


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 6, 12, tzinfo=tz or timezone.utc)


def assert_equal(label, before, after):
    if before != after:
        raise AssertionError(f'Output differs: {label}')


def build_workloads(archive_module, mqtt, repeaters, web, names, rows, messages, tokens):
    # Prepare resolver state only. Never instantiate an Archive on the snapshot.
    archive = archive_module.Archive.__new__(archive_module.Archive)
    archive._names_lock = Lock()
    archive.names = names
    mqtt.learned_alias = archive.resolve

    def build():
        mqtt.packet_number = 0
        mqtt.seen_hashes.clear()
        return [mqtt.build_packet(message) for message in messages]

    def dashboard():
        mqtt.packet_number = 0
        mqtt.seen_hashes.clear()
        store = web.PacketStore()
        with redirect_stdout(io.StringIO()) as output:
            for message in messages:
                mqtt.handle_packet(message, store.add)
        return output.getvalue(), store.snapshot()

    def resolve():
        return [archive.resolve(token) for token in tokens]

    return archive, dict(resolve=resolve, build_packet=build, console_and_dashboard=dashboard,
                         repeater_summary=lambda: repeaters.repeater_summary(rows, names, mqtt.node_label))


def check_parity(workloads, mqtt):
    counter = itertools.count()
    with patch.multiple(mqtt, datetime=FixedClock,
                        uuid=SimpleNamespace(uuid4=lambda: SimpleNamespace(hex=f'{next(counter):032x}'))):
        result = {name: run() for name, run in workloads.items()}
    result['build_packet'] = [packet.to_dict() for packet in result['build_packet']]
    return result


def measure(reference, current, runs):
    results = {}
    for name, before in reference.items():
        after = current[name]
        timings = [[], []]
        for iteration in range(runs):
            order = (0, 1) if iteration % 2 == 0 else (1, 0)
            for variant in order:
                start = time.process_time_ns()
                result = (before, after)[variant]()
                elapsed = time.process_time_ns() - start
                timings[variant].append(elapsed / 1_000_000)
                del result
        results[name] = {
            label: dict(median=round(statistics.median(values), 3),
                        min=round(min(values), 3), max=round(max(values), 3))
            for label, values in zip(('before_ms', 'after_ms'), timings)
        }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--baseline', required=True, help='Git revision before Sprint P1')
    parser.add_argument('--runs', type=int, default=9)
    args = parser.parse_args()
    if args.runs < 2:
        parser.error('--runs must be at least 2')
    path = args.source.resolve(strict=True)
    names, rows, messages, hops, packet_ids = snapshot_inputs(path)
    baseline = subprocess.check_output(
        ['git', 'rev-parse', '--verify', args.baseline + '^{commit}'], cwd=ROOT, text=True).strip()
    before = tuple(reference_module(baseline, module.__name__) for module in
                   (onair_archive, onair_mqtt, onair_repeaters, onair_web))
    before[3].onair_mqtt = before[1]  # The reference dashboard uses its own MQTT formatter.
    after = onair_archive, onair_mqtt, onair_repeaters, onair_web

    # Validate the reference behavior with same-name collisions, observed extensions
    # and an unnamed identity as well as the unmodified snapshot.
    collision_names = {'aabb01'.ljust(64, '0'): 'Same', 'aabb02'.ljust(64, '0'): 'Same',
                       'aabb01': None, 'ffff': ''}
    collision_tokens = ['aa', 'aabb', 'aabb01', 'aabb02', 'AA', 'ffff', 'ff00', 'ff0011', 'zzzz']
    collision_rows = [dict(token=token, count=1, rssi=-100, min_rssi=None, max_rssi=-100, last_seen=1)
                      for token in collision_tokens]
    _, ref = build_workloads(*before, collision_names, collision_rows, messages, collision_tokens)
    _, new = build_workloads(*after, collision_names, collision_rows, messages, collision_tokens)
    assert_equal('synthetic collisions', check_parity(ref, before[1]), check_parity(new, after[1]))

    report = dict(baseline=baseline, python=sys.version.split()[0], source=str(path),
                  runs=args.runs, packet_ids=packet_ids, packet_count=len(messages),
                  repeater_rows=len(rows), workloads={})
    extra = {hashlib.sha256(('P1:' + key).encode()).hexdigest(): name for key, name in names.items()}
    for nodes in (names, names | extra):
        keys = random.Random(1).sample(sorted(nodes), 100)
        queries = [key[:width] for key in keys for width in (2, 4, 5, 6, 8, 64)]
        queries += hops + ['FFFF', 'unknown']
        tokens = (queries * (1000 // len(queries) + 1))[:1000]
        _, ref = build_workloads(*before, nodes, rows, messages, tokens)
        resolver, new = build_workloads(*after, nodes, rows, messages, tokens)
        expected, actual = check_parity(ref, before[1]), check_parity(new, after[1])
        for name in ref:
            assert_equal(f'{len(nodes)} nodes, {name}', expected[name], actual[name])
        report['workloads'][len(nodes)] = dict(queries=len(tokens),
            index_bytes=sys.getsizeof(resolver._name_keys) + sys.getsizeof(resolver._names_lock),
            timings=measure(ref, new, args.runs))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
