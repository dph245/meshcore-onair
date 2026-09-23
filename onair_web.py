"""Local, subscribe-only dashboard. Run one Uvicorn worker."""
import asyncio
from collections import OrderedDict, deque
from threading import Lock
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from queue import Empty, Full, Queue

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
import onair_mqtt
import onair_channels
from onair_archive import Archive
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from onair_mqtt import BROKER_HOST, BROKER_PORT, create_client, noise_sample

MAX_RAW_PACKETS = 500
MAX_GROUPS = 500
MAX_RECEPTIONS = 50
STATIC = Path(__file__).parent / "static"


class PacketStore:
    def __init__(self):
        self.groups = OrderedDict()
        self.received = 0
        self.raw_packets = deque(maxlen=MAX_RAW_PACKETS)

    def add(self, packet):
        item = packet.to_dict()
        self.raw_packets.append(onair_mqtt.format_packet(packet))
        key = packet.group_id
        group = self.groups.get(key)
        if group is None:
            group = {"id": key, "count": 0, "first_seen": packet.received_at, "receptions": []}
        group["count"] += 1
        group["latest"] = item
        group["receptions"].append(item)
        group["receptions"] = group["receptions"][-MAX_RECEPTIONS:]
        self.groups[key] = group
        self.groups.move_to_end(key)
        removed = None
        if len(self.groups) > MAX_GROUPS:
            removed, _ = self.groups.popitem(last=False)
        self.received += 1
        return group, removed

    def snapshot(self):
        return {"type": "snapshot", "groups": list(self.groups.values()),
                "raw_packets": list(self.raw_packets)}


class Dashboard:
    def __init__(self, archive=None):
        self.archive = archive
        self.noise_lock = Lock()
        self.noise_history = {}
        for sample in archive.noise_history() if archive else []:
            self.noise_history.setdefault(sample.get('origin_id'), deque(maxlen=500)).append(sample)
        self.store = PacketStore()
        self.incoming = Queue(maxsize=2048)
        self.listeners = set()
        self.dropped = 0
        self.connected = False
        self.noise_floor = None

    def accept_status(self, data):
        sample = noise_sample(data)
        if sample is not None:
            with self.noise_lock:
                self.noise_history.setdefault(sample.get('origin_id'), deque(maxlen=500)).append(sample)
                self.noise_floor = sample['noise_floor'] if len(self.noise_history) == 1 else None
            if self.archive is not None:
                self.archive.accept_noise(sample)

    def accept_packet(self, packet):
        # Called from the MQTT thread; no event-loop or browser work here.
        try:
            self.incoming.put_nowait(packet)
        except Full:
            self.dropped += 1

    def status(self):
        with self.noise_lock:
            history = [sample for series in self.noise_history.values() for sample in series]
            observers = [dict(series[-1]) for series in self.noise_history.values()]
        return {"connected": self.connected, "received": self.store.received,
                "archive": self.archive_status() if hasattr(self, 'archive_status') else None,
                "noise_floor": self.noise_floor,
                "noise_history": history,
                "noise_observers": observers,
                "dropped": self.dropped, "max_groups": MAX_GROUPS,
                "max_receptions": MAX_RECEPTIONS}

    async def pump(self):
        previous_status = None
        while True:
            changed, removed, raw_packets = {}, [], []
            for _ in range(200):
                try:
                    packet = self.incoming.get_nowait()
                except Empty:
                    break
                group, evicted = self.store.add(packet)
                raw_packets.append(self.store.raw_packets[-1])
                changed[group["id"]] = group
                if evicted:
                    removed.append(evicted)
                    changed.pop(evicted, None)
            status = self.status()
            if changed or status != previous_status:
                event = {"type": "update", "groups": list(changed.values()),
                         "removed": removed, "status": status, "raw_packets": raw_packets}
                for queue in tuple(self.listeners):
                    if queue.full():
                        while not queue.empty():
                            queue.get_nowait()
                        queue.put_nowait({**self.store.snapshot(), "status": status})
                    else:
                        queue.put_nowait(event)
                previous_status = status
            await asyncio.sleep(0.25)


@asynccontextmanager
async def lifespan(app):
    archive = Archive()
    app.state.archive = archive
    onair_mqtt.learned_alias = archive.resolve
    dashboard = Dashboard(archive)
    dashboard.archive_status = lambda: {"saved": archive.saved, "error": archive.error,
                                       "dropped": archive.dropped}
    app.state.dashboard = dashboard
    def accept_packet(packet):
        archive.accept(packet)
        dashboard.accept_packet(packet)
    client = None
    pump = None
    try:
        client = create_client(accept_packet, status_sink=dashboard.accept_status)
        original_connect, original_disconnect = client.on_connect, client.on_disconnect

        def connected(*args):
            dashboard.connected = args[3] == 0
            original_connect(*args)

        def disconnected(*args):
            dashboard.connected = False
            dashboard.noise_floor = None
            original_disconnect(*args)

        client.on_connect, client.on_disconnect = connected, disconnected
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.connect_async(BROKER_HOST, BROKER_PORT, keepalive=60)
        client.loop_start()
        pump = asyncio.create_task(dashboard.pump())
        yield
    finally:
        try:
            if client is not None:
                client.disconnect()
                await asyncio.to_thread(client.loop_stop)
        finally:
            if pump is not None:
                pump.cancel()
                with suppress(asyncio.CancelledError):
                    await pump
            try:
                await asyncio.to_thread(archive.close)
            finally:
                onair_mqtt.learned_alias = None


app = FastAPI(title="MeshCore OnAir", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/archive")
def search_archive(q: str = Query('', max_length=200), kind: str = '', channel: str = '',
                   observer_hash: str = '', since: float | None = None, until: float | None = None,
                   before: int | None = Query(None, ge=1), limit: int = Query(50, ge=1, le=100)):
    return app.state.archive.search(q, kind, channel, observer_hash, since, until, before, limit)


@app.get("/api/channels")
def list_channels():
    return {'channels': list(onair_channels.CHANNELS)}


@app.get("/api/observer-comparison")
def compare_observers():
    return app.state.archive.observer_comparison()


@app.get("/api/repeaters")
def list_repeaters():
    return app.state.archive.repeaters()


@app.get("/api/repeater-history")
def repeater_history(identity: str = Query(..., pattern='^(?:[0-9a-fA-F]{2}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{64})$'),
                     hours: int = Query(24, ge=0, le=8760)):
    return app.state.archive.repeater_history(identity.lower(), hours)


@app.get("/api/nodes")
def search_nodes(q: str = Query('', max_length=200),
                 after: str | None = Query(None, min_length=64, max_length=64, pattern='^[0-9a-fA-F]{64}$'),
                 limit: int = Query(50, ge=1, le=100)):
    return app.state.archive.search_nodes(q.strip(), after.lower() if after else None, limit)


@app.get("/api/map-nodes")
def map_nodes():
    return app.state.archive.map_nodes()


@app.get("/api/repeater-neighbors")
def repeater_neighbors():
    return Response(content=app.state.archive.neighbors_json(), media_type='application/json')


@app.websocket("/ws")
async def websocket(websocket: WebSocket):
    await websocket.accept()
    dashboard = websocket.app.state.dashboard
    queue = asyncio.Queue(maxsize=8)
    dashboard.listeners.add(queue)
    queue.put_nowait({**dashboard.store.snapshot(), "status": dashboard.status()})

    async def send():
        while True:
            await asyncio.wait_for(websocket.send_json(await queue.get()), timeout=10)

    async def monitor_client():
        # Observe disconnects, but never parse or dispatch client data.
        # Text and binary application messages (including empty ones) are forbidden.
        message = await websocket.receive()
        return 1008 if message['type'] == 'websocket.receive' else 1000

    client_task = asyncio.create_task(monitor_client())
    tasks = [asyncio.create_task(send()), client_task]
    close_code = 1000
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if client_task in done:
            close_code = client_task.result()
        for task in done:
            task.result()
    except (WebSocketDisconnect, TimeoutError, OSError):
        pass
    finally:
        dashboard.listeners.discard(queue)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with suppress(WebSocketDisconnect, RuntimeError, OSError):
            await websocket.close(code=close_code,
                                  reason='Server-only stream' if close_code == 1008 else '')
