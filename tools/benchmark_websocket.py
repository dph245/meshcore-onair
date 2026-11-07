"""Offline P2a/P2b WebSocket benchmark. Run once per revision and client count."""
import argparse
import asyncio
from collections import deque
from dataclasses import replace
import json
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import tempfile
from time import process_time_ns
from types import SimpleNamespace, coroutine
from unittest.mock import patch

from benchmark_prefixes import reference_module

ROOT = Path(__file__).resolve().parents[1]
import onair_mqtt
import onair_web

STAMP = '2026-11-07T12:00:00+00:00'
OBSERVERS = [(str(n) * 64, f'Observer {n} · Funk') for n in range(1, 4)]


def reception(group):
    observer, label = OBSERVERS[onair_mqtt.packet_number % len(OBSERVERS)]
    packet = onair_mqtt.build_packet({
        'raw': '1582aabbccddeeff0123456789', 'hash': f'H{group:06d}', 'direction': 'rx',
        'origin_id': observer, 'origin': label, 'RSSI': -97, 'SNR': -3, 'time': '12:00:00',
    })
    return replace(packet, received_at=STAMP)


@coroutine
def next_tick(delay):
    assert delay == 0.25
    yield


def run_server(web, delta, args, trace):
    dashboard = web.Dashboard()
    dashboard.connected = True
    # Put frequently updated groups at the recent end of the initial LRU.
    for ids, count in ((range(152, 500), 1), (range(24, 152), 8), (range(24), 50)):
        for group in ids:
            for _ in range(count):
                dashboard.store.add(reception(group))
    for observer, label in OBSERVERS:
        dashboard.noise_history[observer] = deque([
            dict(origin_id=observer, origin=label, noise_floor=-110 + i % 3,
                 received_at=STAMP, status_at=STAMP) for i in range(args.noise)
        ], maxlen=500)
    queues = [asyncio.Queue(maxsize=8) for _ in range(args.clients)]
    for queue in queues:
        if delta:
            dashboard.listeners[queue] = True
        else:
            dashboard.listeners.add(queue)

    def record(target, payload):
        wire = payload.encode()
        trace.write(target + wire + b'\n')
        return len(wire)

    encode = web._encode_websocket_message
    encoding_ns = encoding_count = 0

    def timed_encode(message):
        nonlocal encoding_ns, encoding_count
        start = process_time_ns()
        result = encode(message)
        encoding_ns += process_time_ns() - start
        encoding_count += 1
        return result

    pump = dashboard.pump()
    ticks = []

    def advance(i):
        groups = [(i * 4 + n) % 24 for n in range(4)]
        groups += [24 + (i * 2 + n) % 128 for n in range(2)]
        packets = [reception(group) for group in groups + [500 + i]]
        start = process_time_ns()
        for packet in packets:
            dashboard.accept_packet(packet)
        pump.send(None)
        ticks.append(process_time_ns() - start)

    def drain(target, peers):
        if not peers:
            return 0
        payload = peers[0].get_nowait()
        for peer in peers[1:]:
            assert peer.get_nowait() is payload
        return record(target, payload)

    with patch.object(web, 'asyncio', SimpleNamespace(sleep=next_tick)), \
            patch.object(web, '_encode_websocket_message', timed_encode):
        for queue in queues:
            queue.put_nowait(dashboard.snapshot_payload(dashboard.status()))
        initial_bytes = drain(b'A', queues)
        initial_encode_ns = encoding_ns
        sizes = []
        for i in range(args.ticks):
            advance(i)
            sizes.append(drain(b'A', queues))
        normal_ns = sum(ticks)
        normal_encode_ns = encoding_ns - initial_encode_ns
        assert encoding_count == args.ticks + 1

        # Keep the final client blocked for 11 ticks. Other peers drain normally.
        max_depth = max_pending = 0
        for i in range(args.ticks, args.ticks + 11):
            advance(i)
            drain(b'F', queues[:-1])
            slow = queues[-1]
            max_depth = max(max_depth, slow.qsize())
            max_pending = max(max_pending, sum(len(frame.encode()) for frame in slow._queue))
        snapshot, *pending = [slow.get_nowait() for _ in range(slow.qsize())]
        assert json.loads(snapshot)['type'] == 'snapshot' and len(pending) == 2
        if delta:
            seq = json.loads(snapshot)['seq']
            assert [json.loads(frame)['seq'] for frame in pending] == [seq + 1, seq + 2]
        recovery_bytes = record(b'B', snapshot)
        for payload in pending:
            record(b'S', payload)
        advance(args.ticks + 11)
        drain(b'A', queues)
    pump.close()
    record(b'R', encode({**dashboard.store.snapshot(), 'status': dashboard.status()}))
    assert not dashboard.dropped
    return {
        'clients': args.clients, 'ticks': args.ticks, 'receptions_per_tick': 7,
        'noise_samples_per_observer': args.noise,
        'mean_update_bytes': round(statistics.mean(sizes)),
        'p95_update_bytes': sorted(sizes)[int(len(sizes) * .95) - 1],
        'initial_snapshot_bytes': initial_bytes,
        'total_bytes_including_initial_snapshots': args.clients * (sum(sizes) + initial_bytes),
        'server_cpu_ms': round(normal_ns / 1e6, 2),
        'server_encode_cpu_ms': round(normal_encode_ns / 1e6, 2),
        'server_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'overflow_snapshot_bytes': recovery_bytes, 'max_slow_queue_depth': max_depth,
        'max_slow_queue_payload_bytes': max_pending,
        'overflow_tick_cpu_ms': round(ticks[args.ticks + 8] / 1e6, 2),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', help='P2a Git ref. Omit for the current P2b tree.')
    parser.add_argument('--clients', type=int, choices=(1, 10, 30), required=True)
    parser.add_argument('--ticks', type=int, default=2400)
    parser.add_argument('--noise', type=int, choices=range(1, 501), metavar='[1-500]', default=100)
    args = parser.parse_args()
    if args.ticks < 1:
        parser.error('--ticks must be positive')
    web = reference_module(args.ref, 'onair_web') if args.ref else onair_web

    with tempfile.TemporaryDirectory(prefix='onair-websocket-') as temp:
        trace = Path(temp) / 'frames'
        frontend_sources = Path(temp) / 'sources.json'
        paths = ('static/app.js', 'static/meshlive-effects.js', 'static/meshlive.js')
        sources = [subprocess.check_output(['git', 'show', f'{args.ref}:{path}'], cwd=ROOT, text=True)
                   if args.ref else (ROOT / path).read_text() for path in paths]
        frontend_sources.write_text(json.dumps(sources))
        with trace.open('wb') as out:
            result = run_server(web, args.ref is None, args, out)
        frontend = subprocess.check_output([
            'node', str(ROOT / 'tools/benchmark_websocket.mjs'), str(trace),
            str(args.clients), str(args.ticks), str(frontend_sources),
        ], cwd=ROOT)
    print(json.dumps({'version': args.ref or 'P2b', **result, **json.loads(frontend)}, indent=2))


if __name__ == '__main__':
    main()
