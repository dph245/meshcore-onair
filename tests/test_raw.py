import asyncio
import contextlib
import io
import unittest
from unittest.mock import patch

import onair_mqtt as mqtt
import onair_web as web


def packet():
    return mqtt.build_packet({'raw': '15416f33abcd', 'direction': 'rx', 'hash': 'RAW-TEST'})


class RawTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_packets_stream_separately_and_resync(self):
        dashboard = web.Dashboard()
        listener = asyncio.Queue(maxsize=1)
        dashboard.listeners.add(listener)
        first, second = packet(), packet()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            mqtt.print_packet(first)
            mqtt.print_packet(second)
        dashboard.accept_packet(first)
        dashboard.accept_packet(second)
        task = asyncio.create_task(dashboard.pump())
        try:
            event = await asyncio.wait_for(listener.get(), 2)
            self.assertEqual(len(event['groups']), 1)
            self.assertEqual(len(event['raw_packets']), 2)
            self.assertEqual(''.join(event['raw_packets']), output.getvalue())
            self.assertEqual(dashboard.store.snapshot()['raw_packets'], event['raw_packets'])
            listener.put_nowait({'type': 'obsolete'})
            third = packet()
            dashboard.accept_packet(third)
            await asyncio.sleep(0.3)
            snapshot = listener.get_nowait()
            self.assertEqual(snapshot['type'], 'snapshot')
            self.assertEqual(snapshot['raw_packets'], event['raw_packets'] + [mqtt.format_packet(third)])
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def test_history_bounded_independently_of_groups(self):
        with patch.object(web, 'MAX_RAW_PACKETS', 2), patch.object(web, 'MAX_RECEPTIONS', 1):
            store = web.PacketStore()
            packets = [packet() for _ in range(3)]
            for item in packets:
                store.add(item)
            self.assertEqual(store.snapshot()['raw_packets'], [mqtt.format_packet(p) for p in packets[-2:]])
            self.assertEqual(len(store.snapshot()['groups']), 1)
