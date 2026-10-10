import asyncio
import contextlib
import io
import json
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

import onair_mqtt as mqtt
import onair_web as web
from node_fixtures import node_database


NODE_NAMES = {'6f33a9' + '0' * 58: 'Test-Repeater',
              'b317ac' + '0' * 58: 'Brocken'}


def packet(raw='15416f33abcd', **fields):
    return mqtt.build_packet({'raw': raw, 'direction': 'rx', 'hash': 'AABB', **fields})


class DecoderTests(unittest.TestCase):
    def setUp(self):
        self.archive = self.enterContext(node_database(NODE_NAMES))
        mqtt.seen_hashes.clear()
        mqtt.packet_number = 0

    def test_routes_and_hash_widths(self):
        for route in range(4):
            for width in (1, 2, 3):
                with self.subTest(route=route, width=width):
                    hops = [bytes.fromhex('8dbc81')[:width], bytes.fromhex('6f33a9')[:width]]
                    raw = bytes([0x14 | route])
                    if route in (0, 3):
                        raw += bytes.fromhex('11223344')
                    raw += bytes([((width - 1) << 6) | 2]) + b''.join(hops) + b'\xaa\xbb'
                    d = mqtt.decode_raw_packet(raw.hex())
                    self.assertEqual(d['hops'], [hop.hex() for hop in hops])
                    self.assertEqual(d['hash_size'], width)
                    self.assertEqual(d['payload_name'], 'GRP_TXT')
                    self.assertEqual(d['route_type'], route)
                    self.assertEqual(d['payload_hex'], 'aabb')
                    self.assertEqual(d['transport_code'], '11223344' if route in (0, 3) else None)

    def test_bad_packets(self):
        for raw in ('', 'zz', '15', '140000', '15c0', '15426f33'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                mqtt.decode_raw_packet(raw)

    def test_direct_path_is_not_last_sender(self):
        for route in (2, 3):
            for width in (1, 2, 3):
                for count in (0, 2):
                    with self.subTest(route=route, width=width, count=count):
                        hashes = [bytes.fromhex(h)[:width] for h in ('6f33a9', 'b317ac')][:count]
                        raw = bytes([0x14 | route])
                        if route == 3:
                            raw += bytes.fromhex('11223344')
                        raw += bytes([((width - 1) << 6) | count]) + b''.join(hashes) + b'\xaa\xbb'
                        p = packet(raw.hex())
                        self.assertEqual(p.last_hop, 'Unbekannt')
                        self.assertEqual(p.decoded['hops'], [h.hex() for h in hashes])
                        self.assertEqual(p.path, mqtt.format_path(p.decoded['hops']))

    def test_names_from_database(self):
        for short in ('8d', '6f', 'b3', 'dd'):
            self.assertEqual(mqtt.node_label(short), short)
        self.assertEqual(mqtt.ALIASES, {})
        self.assertEqual(self.archive.resolve('6f33'), 'Test-Repeater')
        self.assertEqual(mqtt.node_label('6f33a9'), 'Test-Repeater[6f33a9]')
        self.assertEqual(packet().last_hop, 'Test-Repeater[6f33]')
        self.assertEqual(packet().decoded['hop_labels'], ['Test-Repeater[6f33]'])
        self.assertEqual(mqtt.node_label('ffff'), 'ffff')

    def test_repeats_and_terminal(self):
        first, second = packet(), packet('1581b317acabcd', hash='aabb')
        self.assertEqual(first.group_id, second.group_id)
        self.assertEqual(second.repeat_count, 2)
        self.assertEqual(second.first_number, first.number)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            mqtt.print_packet(second)
        for expected in ('REPEAT x2', 'Brocken[b317ac]', 'GRP_TXT', '3 byte'):
            self.assertIn(expected, output.getvalue())

    def test_missing_hash_and_nonfinite_metadata(self):
        self.assertNotEqual(packet(hash=None).group_id, packet(hash=None).group_id)
        p = packet(SNR='NaN', RSSI=float('inf'))
        self.assertIsNone(p.snr)
        self.assertIsNone(p.rssi)
        json.dumps(p.to_dict(), allow_nan=False)

    def test_mqtt_rx_only_and_malformed_json(self):
        sink = Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            for payload in (b'[]', b'null', b'{', b'{"direction":"tx","raw":"1500"}', b'{"stats":null}'):
                mqtt.on_message(None, {'packet_sink': sink}, SimpleNamespace(topic='meshcore/test/packets', payload=payload))
            mqtt.on_message(None, {'packet_sink': sink}, SimpleNamespace(topic='meshcore/test/packets', payload=b'{"direction":"rx","raw":"1500"}'))
        self.assertEqual(sink.call_count, 1)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(node_database(NODE_NAMES))

    def test_raw_noise_validation_and_bounded_history(self):
        dashboard = web.Dashboard()
        for value in (None, True, False, 'NaN', float('inf'), -112.5, {}, []):
            dashboard.accept_status({'stats': {'noise_floor': value}})
        dashboard.accept_status({'stats': None})
        dashboard.accept_status({})
        self.assertEqual(dashboard.status()['noise_history'], [])
        for i in range(502):
            dashboard.accept_status({'stats': {'noise_floor': -112 if i < 501 else -114}})
        history = dashboard.status()['noise_history']
        self.assertEqual(len(history), 500)
        self.assertEqual([s['noise_floor'] for s in history], [-112] * 499 + [-114])
        self.assertTrue(all(type(s['noise_floor']) is int for s in history))
        self.assertIsNotNone(mqtt.datetime.fromisoformat(history[0]['received_at']).tzinfo)
        dashboard.accept_status({'stats': {'noise_floor': -113}})
        self.assertEqual(history[-1]['noise_floor'], -114)  # Snapshot stays immutable.

    def test_group_variants_and_limits(self):
        store = web.PacketStore()
        with patch.object(web, 'MAX_GROUPS', 2), patch.object(web, 'MAX_RECEPTIONS', 2):
            store.add(packet())
            store.add(packet('1581b317acabcd'))
            group, _ = store.add(packet())
            self.assertEqual(group['count'], 3)
            self.assertEqual(len(group['receptions']), 2)
            self.assertEqual(group['receptions'][0]['last_hop'], 'Brocken[b317ac]')
            store.add(packet(hash='B'))
            _, removed = store.add(packet(hash='C'))
            self.assertEqual(removed, 'AABB')
            self.assertEqual(len(store.groups), 2)


class WebTests(unittest.IsolatedAsyncioTestCase):
    async def test_websocket_rejects_client_data_without_side_effects(self):
        client = Mock()
        with tempfile.TemporaryDirectory() as folder, patch.object(web, 'create_client', return_value=client), patch.object(web, 'Archive', side_effect=lambda: __import__('onair_archive').Archive(folder + '/test.sqlite3')):
            async with web.lifespan(web.app):
                for payload in ({'text': '{"command":"publish","topic":"meshcore/tx","raw":"1500"}'},
                                {'text': ''}, {'bytes': b'\x15\x00'}, {'bytes': b''}):
                    with self.subTest(payload=payload):
                        incoming, outgoing = asyncio.Queue(), asyncio.Queue()
                        await incoming.put({'type': 'websocket.connect'})
                        scope = {'type': 'websocket', 'path': '/ws', 'root_path': '',
                                 'query_string': b'', 'headers': [], 'scheme': 'ws', 'subprotocols': []}
                        task = asyncio.create_task(web.app(scope, incoming.get, outgoing.put))
                        try:
                            self.assertEqual((await asyncio.wait_for(outgoing.get(), 2))['type'], 'websocket.accept')
                            snapshot = await asyncio.wait_for(outgoing.get(), 2)
                            self.assertEqual(json.loads(snapshot['text'])['type'], 'snapshot')
                            calls_before = list(client.mock_calls)
                            await incoming.put({'type': 'websocket.receive', **payload})
                            while True:
                                message = await asyncio.wait_for(outgoing.get(), 2)
                                if message['type'] == 'websocket.close':
                                    break
                            self.assertEqual(message['code'], 1008)
                            await asyncio.wait_for(task, 2)
                            self.assertEqual(client.mock_calls, calls_before)
                            self.assertFalse(web.app.state.dashboard.listeners)
                            self.assertEqual(web.app.state.dashboard.store.received, 0)
                            self.assertTrue(web.app.state.dashboard.incoming.empty())
                            self.assertTrue(web.app.state.archive.queue.empty())
                            self.assertEqual(web.app.state.archive.search()['items'], [])
                        finally:
                            task.cancel()
                            await asyncio.gather(task, return_exceptions=True)
                client.publish.assert_not_called()

    async def test_http_write_methods_are_rejected(self):
        for path in ('/', '/api/archive', '/api/nodes', '/api/channels', '/api/repeaters', '/ws', '/static/app.js'):
            for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
                with self.subTest(path=path, method=method):
                    sent = []
                    async def receive_http():
                        return {'type': 'http.request', 'body': b'{"command":"publish"}'}
                    async def send_http(message):
                        sent.append(message)
                    await web.app({'type': 'http', 'method': method, 'path': path,
                                   'root_path': '', 'query_string': b'', 'headers': [],
                                   'http_version': '1.1', 'scheme': 'http'}, receive_http, send_http)
                    self.assertIn(sent[0]['status'], (404, 405))

    async def test_repeated_noise_readings_are_pushed_without_packets(self):
        dashboard = web.Dashboard()
        listener = asyncio.Queue(maxsize=8)
        dashboard.listeners.add(listener)
        task = asyncio.create_task(dashboard.pump())
        try:
            await asyncio.wait_for(listener.get(), 2)
            for count in (1, 2):
                dashboard.accept_status({'stats': {'noise_floor': -113}})
                event = await asyncio.wait_for(listener.get(), 2)
                self.assertEqual(len(event['status']['noise_history']), count)
                self.assertEqual(event['status']['noise_history'][-1]['noise_floor'], -113)
                self.assertEqual(event['groups'], [])
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_http_websocket_snapshot_update_and_shutdown(self):
        client = Mock()
        with tempfile.TemporaryDirectory() as folder, patch.object(web, 'create_client', return_value=client), patch.object(web, 'Archive', side_effect=lambda: __import__('onair_archive').Archive(folder + '/test.sqlite3')):
            async with web.lifespan(web.app):
                for path in ('/', '/static/app.js', '/static/noise.js', '/static/style.css'):
                    sent = []
                    async def receive_http():
                        return {'type': 'http.request', 'body': b''}
                    async def send_http(message):
                        sent.append(message)
                    await web.app({'type': 'http', 'method': 'GET', 'path': path,
                                   'root_path': '', 'query_string': b'', 'headers': [],
                                   'http_version': '1.1', 'scheme': 'http'}, receive_http, send_http)
                    self.assertEqual(sent[0]['status'], 200)
                    self.assertTrue(any(message.get('body') for message in sent))
                incoming, outgoing = asyncio.Queue(), asyncio.Queue()
                await incoming.put({'type': 'websocket.connect'})
                scope = {'type': 'websocket', 'path': '/ws', 'root_path': '',
                         'query_string': b'', 'headers': [], 'scheme': 'ws', 'subprotocols': []}
                task = asyncio.create_task(web.app(scope, incoming.get, outgoing.put))
                self.assertEqual((await asyncio.wait_for(outgoing.get(), 2))['type'], 'websocket.accept')
                snapshot = json.loads((await asyncio.wait_for(outgoing.get(), 2))['text'])
                self.assertEqual(snapshot['type'], 'snapshot')
                web.app.state.dashboard.accept_packet(packet())
                while True:
                    update = json.loads((await asyncio.wait_for(outgoing.get(), 2))['text'])
                    if update['groups']:
                        break
                self.assertEqual(update['groups'][0]['latest']['decoded']['hops'], ['6f33'])
                await incoming.put({'type': 'websocket.disconnect', 'code': 1000})
                await asyncio.wait_for(task, 2)
                self.assertFalse(web.app.state.dashboard.listeners)
            client.connect_async.assert_called_once_with(mqtt.BROKER_HOST, mqtt.BROKER_PORT, keepalive=60)
            client.disconnect.assert_called_once()
            client.loop_stop.assert_called_once()

    async def test_slow_client_resynchronizes(self):
        dashboard = web.Dashboard()
        listener = asyncio.Queue(maxsize=1)
        listener.put_nowait({'type': 'obsolete'})
        dashboard.listeners.add(listener)
        dashboard.accept_packet(packet())
        task = asyncio.create_task(dashboard.pump())
        await asyncio.sleep(0.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        event = listener.get_nowait()
        self.assertEqual(event['type'], 'snapshot')
        self.assertEqual(len(event['groups']), 1)


if __name__ == '__main__':
    unittest.main()
