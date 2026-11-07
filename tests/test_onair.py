import asyncio
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import ssl
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from onair_archive import Archive
from onair_repeaters import repeater_summary
import onair_mqtt as mqtt
import onair_web as web
from node_fixtures import node_database, seed_nodes


NODE_NAMES = {'6f33a9' + '0' * 58: 'Test-Repeater',
              'b317ac' + '0' * 58: 'Brocken'}


class MqttConnectionTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.multiple(mqtt, MQTT_TLS='false', MQTT_USERNAME='',
                                         MQTT_PASSWORD='', MQTT_CA_CERTS=''))
        self.factory = self.enterContext(patch.object(mqtt.mqtt, 'Client'))
        self.client = self.factory.return_value

    def test_existing_plain_tcp_defaults(self):
        self.assertIs(mqtt.create_client(), self.client)
        self.client.username_pw_set.assert_not_called()
        self.client.tls_set_context.assert_not_called()
        self.client.connect.assert_not_called()
        self.client.publish.assert_not_called()

    def test_tls_and_credentials_with_verified_server(self):
        with patch.multiple(mqtt, MQTT_TLS='true', MQTT_USERNAME='reader',
                            MQTT_PASSWORD='  secret!$  '):
            mqtt.create_client()
        self.client.username_pw_set.assert_called_once_with('reader', '  secret!$  ')
        context = self.client.tls_set_context.call_args.args[0]
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.client.connect.assert_not_called()
        self.client.publish.assert_not_called()

    def test_custom_ca_is_loaded(self):
        with patch.multiple(mqtt, MQTT_TLS='on', MQTT_CA_CERTS='/certs/broker.pem'), \
                patch.object(mqtt.ssl, 'create_default_context') as create_context:
            mqtt.create_client()
        create_context.assert_called_once_with(cafile='/certs/broker.pem')
        self.client.tls_set_context.assert_called_once_with(create_context.return_value)

    def test_unreadable_ca_fails_without_plaintext_fallback(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.multiple(mqtt, MQTT_TLS='true', MQTT_CA_CERTS=folder + '/missing.pem'):
            with self.assertRaises(FileNotFoundError):
                mqtt.create_client()
        self.client.connect.assert_not_called()
        self.client.tls_set_context.assert_not_called()

    def test_credentials_without_tls_remain_supported(self):
        with patch.multiple(mqtt, MQTT_USERNAME='reader', MQTT_PASSWORD='secret'):
            mqtt.create_client()
        self.client.username_pw_set.assert_called_once_with('reader', 'secret')
        self.client.tls_set_context.assert_not_called()

    def test_invalid_configuration_is_rejected_before_client_creation(self):
        for settings, variable in [({'MQTT_TLS': 'treu'}, 'ONAIR_MQTT_TLS'),
                                   ({'MQTT_PASSWORD': 'secret'}, 'ONAIR_MQTT_PASSWORD'),
                                   ({'MQTT_CA_CERTS': '/ca.pem'}, 'ONAIR_MQTT_CA_CERTS')]:
            with self.subTest(settings=list(settings)), patch.multiple(mqtt, **settings):
                with self.assertRaisesRegex(ValueError, variable):
                    mqtt.create_client()
        self.factory.assert_not_called()


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

    def test_packet_resolves_each_distinct_hop_once(self):
        with patch.object(mqtt, 'learned_alias', wraps=self.archive.resolve) as resolve:
            p = packet('15836f33a9b317ac6f33a9abcd')
        self.assertEqual([call.args[0] for call in resolve.call_args_list], ['6f33a9', 'b317ac'])
        labels = ['Test-Repeater[6f33a9]', 'Brocken[b317ac]', 'Test-Repeater[6f33a9]']
        self.assertEqual(p.decoded['hop_labels'], labels)
        self.assertEqual(p.path, ' → '.join(labels))
        self.assertEqual(p.last_hop, labels[-1])

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


class PrefixTests(unittest.TestCase):
    def test_learned_names_match_linear_reference_and_alias_order(self):
        a = 'aabb0011'.ljust(64, '0')
        b = 'aabb0022'.ljust(64, '0')
        c = 'aacc'.ljust(64, '0')
        d = 'aadd'.ljust(64, '0')
        names = {a: 'Same', b: 'Same', c: None, d: ''}
        with node_database(names) as archive:
            queries = [key[:width] for key in names for width in (0, 2, 4, 5, 6, 7, 8, 63, 64)]
            queries += [a.upper(), a + '0', 'ffff', 'unknown']
            for token in queries:
                with self.subTest(token=token):
                    matches = [name for key, name in names.items() if key.startswith(token)]
                    expected = matches[0] if len(token) >= 4 and len(matches) == 1 else None
                    self.assertEqual(archive.resolve(token), expected)
            with patch.object(mqtt, 'ALIASES', {'AABB': 'First', 'aabb0011': 'Second', 'aa': 'Short'}):
                self.assertEqual(mqtt.node_label('AABB0011'), 'First[aabb0011]')
                self.assertEqual(mqtt.node_label('aabb00'), 'First[aabb00]')
                self.assertEqual(mqtt.node_label('AA'), 'aa')

    def test_signed_adverts_update_live_after_commit_and_retry(self):
        key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        public_key = key.public_key().public_bytes_raw()
        token = public_key.hex()[:6]
        shared_prefix = token[:4]
        sibling = shared_prefix + ('ff' if token[4:] != 'ff' else '00') + '0' * 58

        def advert(name, timestamp, valid=True):
            prefix = public_key + timestamp.to_bytes(4, 'little')
            appdata = b'\x82' + name.encode()
            signature = key.sign(prefix + appdata) if valid else bytes(64)
            return mqtt.build_packet(dict(raw='1100' + (prefix + signature + appdata).hex(),
                                          direction='rx')).to_dict()

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.sqlite3'
            seed_nodes(path, {sibling: 'Sibling'})
            archive = Archive(path)
            try:
                with archive.connect() as db, patch.multiple(mqtt, learned_alias=archive.resolve, ALIASES={}):
                    self.assertEqual(archive.resolve(shared_prefix), 'Sibling')
                    batch = [advert('Old', 100), advert('Current', 200), advert('Replay', 150)]
                    with patch('onair_archive.maintain_positions', side_effect=sqlite3.OperationalError):
                        with self.assertRaises(sqlite3.OperationalError):
                            archive._write(db, batch)
                    self.assertEqual(mqtt.node_label(token), token)
                    self.assertEqual(archive.resolve(shared_prefix), 'Sibling')
                    self.assertIsNone(db.execute('SELECT name FROM nodes WHERE public_key=?',
                                                 (public_key.hex(),)).fetchone())
                    archive._write(db, batch)
                    self.assertEqual(mqtt.node_label(token), f'Current[{token}]')
                    self.assertIsNone(archive.resolve(shared_prefix))
                    archive._write(db, [advert('Same timestamp', 200), advert('Invalid', 300, False)])
                    self.assertEqual(archive.resolve(public_key.hex()), 'Current')
                    archive._write(db, [advert('Renamed', 300)])
                    self.assertEqual(mqtt.node_label(token), f'Renamed[{token}]')
            finally:
                archive.close()

    def test_repeater_collisions_and_observed_only_extensions(self):
        a = 'aabb01'.ljust(64, '0')
        b = 'aabb02'.ljust(64, '0')
        names = {a: 'A', b: 'B', 'aabb01': 'Short', 'ee11': 'Named'}
        tokens = ('aabb', 'aabb01', a, 'ff', 'ff00', 'ff0001', 'ee', 'ee11')
        rows = [dict(token=token, count=1, rssi=-100 + n, min_rssi=-100 + n,
                     max_rssi=-100 + n, last_seen=n) for n, token in enumerate(tokens)]
        items = {item['id']: item for item in repeater_summary(iter(rows), names, str)}
        self.assertEqual(set(items), {'aabb', a, 'ff0001', 'ee11'})
        self.assertEqual(items['aabb']['tokens'], ['aabb'])
        self.assertEqual(items[a]['tokens'], ['aabb01', a])
        self.assertEqual(items[a]['name'], 'A')
        self.assertEqual(items['ff0001']['tokens'], ['ff', 'ff00', 'ff0001'])
        self.assertEqual(items['ff0001']['count'], 3)
        self.assertEqual(items['ff0001']['min_rssi'], -97)
        self.assertEqual(items['ff0001']['rssi'], -95)
        self.assertEqual(items['ee11']['tokens'], ['ee', 'ee11'])


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
    async def open_stream(self, dashboard, before_send=None):
        incoming, outgoing = asyncio.Queue(), asyncio.Queue()
        incoming.put_nowait({'type': 'websocket.connect'})

        async def send(message):
            if before_send is not None and message['type'] == 'websocket.send':
                await before_send(message['text'])
            outgoing.put_nowait(message)

        scope = {'type': 'websocket', 'app': SimpleNamespace(state=SimpleNamespace(dashboard=dashboard))}
        task = asyncio.create_task(web.websocket(web.WebSocket(scope, incoming.get, send)))

        async def cleanup():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        self.addAsyncCleanup(cleanup)
        self.assertEqual(await asyncio.wait_for(outgoing.get(), 2),
                         {'type': 'websocket.accept', 'subprotocol': None, 'headers': []})
        return incoming, outgoing, task

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
                event = json.loads(await asyncio.wait_for(listener.get(), 2))
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
        event = json.loads(listener.get_nowait())
        self.assertEqual(event['type'], 'snapshot')
        self.assertEqual(len(event['groups']), 1)

    async def test_fanout_preserves_text_order_and_queue_snapshots_under_backpressure(self):
        dashboard = web.Dashboard()
        release_slow = asyncio.Event()
        blocked = asyncio.Queue()

        async def slow_send(text):
            if json.loads(text)['status']['received'] == 1:
                blocked.put_nowait(text)
                await release_slow.wait()

        async def next_text(outgoing):
            frame = await asyncio.wait_for(outgoing.get(), 2)
            self.assertEqual(frame['type'], 'websocket.send')
            return frame['text']

        def legacy_json(message):
            return json.dumps(message, separators=(',', ':'), ensure_ascii=False)

        with patch.object(web, 'MAX_GROUPS', 1):
            _, fast, _ = await self.open_stream(dashboard)
            _, other_fast, _ = await self.open_stream(dashboard)
            _, slow, _ = await self.open_stream(dashboard, slow_send)
            slow_incoming, other_slow, slow_task = await self.open_stream(dashboard, slow_send)
            initial = await next_text(fast)
            self.assertEqual(initial, legacy_json({**dashboard.store.snapshot(), 'status': dashboard.status()}))
            for outgoing in (other_fast, slow, other_slow):
                self.assertIs(await next_text(outgoing), initial)

            pump = asyncio.create_task(dashboard.pump())
            try:
                # First tick has only status. Subsequent ticks mutate the same group in place.
                self.assertIs(await next_text(fast), await next_text(other_fast))
                self.assertIs(await next_text(slow), await next_text(other_slow))
                updates = []
                for count in range(1, 13):
                    item = packet(hash='AABB' if count < 12 else 'CCDD', origin='Funk 🔊')
                    dashboard.accept_packet(item)
                    text = await next_text(fast)
                    self.assertIs(await next_text(other_fast), text)
                    self.assertEqual(text, legacy_json({
                        'type': 'update', 'groups': list(dashboard.store.groups.values()),
                        'removed': ['AABB'] if count == 12 else [], 'status': dashboard.status(),
                        'raw_packets': [item.raw_text],
                    }))
                    updates.append(text)
                    if count == 1:
                        for _ in range(2):
                            self.assertIs(await asyncio.wait_for(blocked.get(), 2), text)
                    if count == 10:
                        # Both blocked queues overflow here. A new connection sees the same snapshot.
                        _, late, _ = await self.open_stream(dashboard)
                        fallback = await next_text(late)
                        self.assertEqual(fallback, legacy_json({**dashboard.store.snapshot(),
                                                               'status': dashboard.status()}))

                # Disconnect one slow peer while its send is blocked.
                slow_incoming.put_nowait({'type': 'websocket.disconnect', 'code': 1000})
                self.assertEqual((await asyncio.wait_for(other_slow.get(), 2))['code'], 1000)
                await asyncio.wait_for(slow_task, 2)
                self.assertEqual(len(dashboard.listeners), 4)

                release_slow.set()
                for expected in (updates[0], fallback, updates[10], updates[11]):
                    self.assertIs(await next_text(slow), expected)
                self.assertTrue(slow.empty())
            finally:
                pump.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pump

    async def test_encoding_failure_cleans_up_sender_without_stopping_pump(self):
        dashboard = web.Dashboard()
        _, outgoing, task = await self.open_stream(dashboard)
        await asyncio.wait_for(outgoing.get(), 2)  # Initial snapshot.
        status = dashboard.status()
        with patch.object(dashboard, 'status', return_value={**status, 'archive': object()}):
            pump = asyncio.create_task(dashboard.pump())
            try:
                self.assertEqual((await asyncio.wait_for(outgoing.get(), 2))['code'], 1000)
                with self.assertRaisesRegex(TypeError, 'not JSON serializable'):
                    await asyncio.wait_for(task, 2)
                self.assertFalse(dashboard.listeners)
                self.assertFalse(pump.done())
            finally:
                pump.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pump

    async def test_websocket_send_timeout_cleans_up_listener(self):
        dashboard = web.Dashboard()
        cancelled = asyncio.Event()

        async def blocked_send(_):
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        def short_timeout(send, timeout):
            self.assertEqual(timeout, 10)
            return asyncio.wait_for(send, 0.01)

        with patch.object(web, 'asyncio', Mock(wraps=asyncio, wait_for=short_timeout,
                                               FIRST_COMPLETED=asyncio.FIRST_COMPLETED)):
            _, outgoing, task = await self.open_stream(dashboard, blocked_send)
            self.assertEqual((await asyncio.wait_for(outgoing.get(), 2))['code'], 1000)
            await asyncio.wait_for(task, 2)
            self.assertTrue(cancelled.is_set())
            self.assertFalse(dashboard.listeners)
            self.assertIsNone(dashboard._websocket_snapshot)


if __name__ == '__main__':
    unittest.main()
