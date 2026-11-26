"""Local, subscribe-only dashboard. Run one Uvicorn worker."""
import asyncio
import json
import sqlite3
from collections import OrderedDict, deque
from datetime import datetime
from threading import Lock
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from queue import Empty, Full, Queue
import time

from typing import Literal

from fastapi import Request, FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
import onair_mqtt
import onair_channels
from onair_archive import Archive
from onair_replay import ReplayLimitError
from onair_distance import AnalysisLimitError, MAX_PAIR_RECEPTIONS
from onair_neighbors import MAX_LINK_DISTANCE_KM
from onair_routes import route_nodes, plan_routes
from fastapi.responses import JSONResponse, Response
from onair_assets import VersionedStaticFiles, index_response
import onair_rf_neighbor_view as rf_neighbor_view

from onair_mqtt import BROKER_HOST, BROKER_PORT, create_client, noise_sample
from onair_observer_radio import (MAX_CLOCK_LEAD, observer_identity, radio_report,
                                  status_origin_id, status_reported_time)

MAX_RAW_PACKETS = 500
MAX_GROUPS = 500
MAX_RECEPTIONS = 50
STATIC = Path(__file__).parent / "static"


def contact_time(reported_at, received_at, retained=False):
    if reported_at is None:
        return None if retained else received_at
    if reported_at <= received_at + MAX_CLOCK_LEAD:
        return min(reported_at, received_at)
    return None


def _encode_websocket_message(message) -> str | Exception:
    try:
        # Match Starlette's send_json text frames.
        return json.dumps(message, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError, RecursionError, OverflowError) as error:
        # Leave encoding failures with the affected senders, without retaining the message.
        return error.with_traceback(None)


class PacketStore:
    def __init__(self):
        self.groups = OrderedDict()
        self.received = 0
        self.raw_packets = deque(maxlen=MAX_RAW_PACKETS)

    def add(self, packet):
        item = packet.to_dict()
        self.raw_packets.append(packet.raw_text)
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
        self.status_lock = Lock()
        self.noise_history = {}
        self.latest_noise = {}
        self.observer_activity = {}
        self._activity_snapshot = None
        for sample in archive.noise_history() if archive else []:
            received = status_reported_time({'timestamp': sample['received_at']})
            reported = status_reported_time({'timestamp': sample.get('status_at')})
            # Legacy rows have no retain flag. Only a known source time can
            # restore activity without mistaking a replay for a new contact.
            observed = contact_time(reported, received, retained=True) if received is not None else None
            identity = self._record_noise(sample, observed)
            self._record_contact(identity, sample.get('origin'), observed)
        for radio in archive.observer_radio_status() if archive else []:
            self._record_contact(radio['origin_id'], radio.get('origin'), radio['last_confirmed_at'])
        self.store = PacketStore()
        self.incoming = Queue(maxsize=2048)
        self.listeners = {}  # Queue -> whether the client requested reception deltas
        self.sequence = 0
        self._websocket_snapshot = None
        self.dropped = 0
        self.connected = False
        self.noise_floor = None

    def accept_status(self, data):
        sample = noise_sample(data)
        received = data.get('_mqtt_received_at')
        if received is None:
            received = time.time()
        observed = contact_time(status_reported_time(data), received, data.get('_mqtt_retained'))
        identity = status_origin_id(data)
        with self.status_lock:
            if sample is not None:
                self._record_noise(sample, observed)
                self.noise_floor = sample['noise_floor'] if len(self.noise_history) == 1 else None
            if data.get('status') != 'offline' and (
                    identity is not None or sample is not None and not sample.get('origin_id')):
                self._record_contact(identity or '', data.get('origin'), observed)
        if self.archive is not None:
            self.archive.accept_observer_status(sample, radio_report(data))

    def _record_noise(self, sample, observed):
        origin_id = sample.get('origin_id')
        self.noise_history.setdefault(origin_id, deque(maxlen=500)).append(sample)
        identity = observer_identity(origin_id) or ''
        previous = self.latest_noise.get(identity)
        if previous is None or previous[0] is None or (observed is not None and observed >= previous[0]):
            self.latest_noise[identity] = (observed, sample)
        return identity

    def _record_contact(self, identity, origin, observed):
        if observed is None:
            return
        # Second resolution matches the age check and coalesces busy RX streams.
        observed = int(observed)
        previous = self.observer_activity.get(identity)
        if previous is not None and observed <= previous['last_contact']:
            return
        if isinstance(origin, str) and origin.strip():
            origin = origin.encode('utf-8', errors='replace').decode('utf-8')
        else:
            origin = previous['origin'] if previous else None
        self.observer_activity[identity] = dict(origin=origin, last_contact=observed)
        self._activity_snapshot = None

    def accept_reception_contact(self, packet, data):
        identity = observer_identity(packet.origin_id)
        if identity is not None:
            received = datetime.fromisoformat(packet.received_at).timestamp()
            observed = contact_time(status_reported_time(data), received)
            with self.status_lock:
                self._record_contact(identity, packet.origin, observed)

    def accept_packet(self, packet):
        # Called from the MQTT thread; no event-loop or browser work here.
        try:
            self.incoming.put_nowait(packet)
        except Full:
            self.dropped += 1

    def status(self):
        with self.status_lock:
            history = [sample for series in self.noise_history.values() for sample in series]
            observers = [sample for _, sample in self.latest_noise.values()]
            if self._activity_snapshot is None:
                self._activity_snapshot = self.observer_activity.copy()
            activity = self._activity_snapshot
        return {"connected": self.connected, "received": self.store.received,
                "archive": self.archive_status() if hasattr(self, 'archive_status') else None,
                "noise_floor": self.noise_floor,
                "noise_history": history,
                "noise_observers": observers,
                "radio_observers": self.archive.observer_radio_status() if self.archive else (),
                "observer_activity": activity,
                "dropped": self.dropped, "max_groups": MAX_GROUPS,
                "max_receptions": MAX_RECEPTIONS}

    def snapshot_payload(self, status):
        # Status includes the store's monotonically increasing reception count.
        if self._websocket_snapshot is None or self._websocket_snapshot[0] != status:
            payload = _encode_websocket_message({
                **self.store.snapshot(), "seq": self.sequence, "status": status,
            })
            self._websocket_snapshot = (status, payload)
        return self._websocket_snapshot[1]

    def remove_listener(self, queue):
        self.listeners.pop(queue, None)
        if not self.listeners:
            self._websocket_snapshot = None

    def _broadcast(self, receptions, changed, evictions, status, raw_packets, previous_status):
        # The pump publishes the entire batch without yielding. A snapshot at seq N
        # includes this batch, so the first update following it must be N + 1.
        self.sequence += 1
        self._websocket_snapshot = None
        if not self.listeners:
            return
        updates = {}
        update_status = status.copy()
        if previous_status is not None:
            if status["radio_observers"] is previous_status["radio_observers"]:
                update_status.pop("radio_observers")
            previous_activity = previous_status["observer_activity"]
            activity = status["observer_activity"]
            changed_activity = ({key: entry for key, entry in activity.items()
                                 if entry is not previous_activity.get(key)}
                                if activity is not previous_activity else {})
            if changed_activity:
                update_status["observer_activity"] = changed_activity
            else:
                update_status.pop("observer_activity")
        for queue, delta in self.listeners.items():
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(self.snapshot_payload(status))
            else:
                if delta not in updates:
                    if delta:
                        body = {"type": "delta", "receptions": receptions}
                        if evictions:
                            body["evictions"] = evictions
                    else:
                        body = {"type": "update", "groups": list(changed.values()),
                                "removed": list(evictions.values())}
                    updates[delta] = _encode_websocket_message({
                        **body, "seq": self.sequence, "status": update_status,
                        "raw_packets": raw_packets,
                    })
                queue.put_nowait(updates[delta])

    async def pump(self):
        previous_status = None
        while True:
            receptions, changed, evictions, raw_packets = [], {}, {}, []
            for _ in range(200):
                try:
                    packet = self.incoming.get_nowait()
                except Empty:
                    break
                group, evicted = self.store.add(packet)
                receptions.append(group["latest"])
                raw_packets.append(self.store.raw_packets[-1])
                changed[group["id"]] = group
                if evicted is not None:
                    # Apply eviction at this reception, even if the same ID returns
                    # later in the batch and starts a new group.
                    evictions[len(receptions) - 1] = evicted
                    changed.pop(evicted, None)
            status = self.status()
            if receptions or status != previous_status:
                self._broadcast(receptions, changed, evictions, status, raw_packets, previous_status)
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
        client = create_client(accept_packet, status_sink=dashboard.accept_status,
                               rf_neighbor_sink=archive.accept_rf_neighbors,
                               reception_contact_sink=dashboard.accept_reception_contact)
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
app.mount("/static", VersionedStaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return index_response(STATIC)


@app.get("/api/archive")
def search_archive(q: str = Query('', max_length=200), kind: str = '', channel: str = '',
                   observer_hash: str = '', since: float | None = None, until: float | None = None,
                   before: int | None = Query(None, ge=1), limit: int = Query(50, ge=1, le=100)):
    return app.state.archive.search(q, kind, channel, observer_hash, since, until, before, limit)


@app.get('/api/archive/stats')
def archive_stats():
    return JSONResponse(app.state.archive.archive_stats(), headers={'Cache-Control': 'no-store'})


@app.get("/api/channels")
def list_channels():
    return {'channels': list(onair_channels.CHANNELS)}


@app.get('/api/discovery')
def discovery(hours: int = Query(24, ge=1, le=168),
              limit: int = Query(100, ge=1, le=100)):
    return app.state.archive.discovery(hours, limit)


def rf_neighbor_query(query, *args):
    try:
        result = query(app.state.archive.path, *args)
    except sqlite3.Error:
        raise HTTPException(503, 'RF-Nachbarschaftsarchiv momentan nicht lesbar') from None
    if result is None:
        raise HTTPException(404, 'RF-Nachbarschaftsreport nicht gefunden')
    return result


@app.get('/api/rf-neighbors/observers')
def rf_neighbor_observers(limit: int = Query(500, ge=1, le=500)):
    return rf_neighbor_query(rf_neighbor_view.observers, limit)


@app.get('/api/rf-neighbors/reports')
def rf_neighbor_reports(observer: str = Query(..., pattern=r'^[0-9A-Fa-f]{64}$'),
                        before: int | None = Query(None, ge=1),
                        limit: int = Query(20, ge=1, le=100)):
    return rf_neighbor_query(rf_neighbor_view.history, observer, before, limit)


@app.get('/api/rf-neighbors/reports/{message_id}')
def rf_neighbor_report(message_id: int, observer: str = Query(..., pattern=r'^[0-9A-Fa-f]{64}$')):
    return rf_neighbor_query(rf_neighbor_view.detail, observer, message_id)


@app.get("/api/observer-comparison")
def compare_observers():
    return app.state.archive.observer_comparison()


@app.get('/api/traces')
def traces(hours: int = Query(24, ge=1, le=168),
           limit: int = Query(100, ge=1, le=100)):
    return app.state.archive.traces(hours, limit)


@app.get('/api/map-traces')
def map_traces(start: float = Query(..., ge=0, le=4102444800),
               end: float = Query(..., ge=0, le=4102444800),
               before: int = Query(9223372036854775807, ge=1, le=9223372036854775807),
               first: str = Query('', pattern=r'^(?:[0-9a-f]{2}|[0-9a-f]{4}|[0-9a-f]{8}|[0-9a-f]{16})?$'),
               last: str = Query('', pattern=r'^(?:[0-9a-f]{2}|[0-9a-f]{4}|[0-9a-f]{8}|[0-9a-f]{16})?$'),
               hops: int | None = Query(None, ge=0, le=255),
               grouped: bool = False):
    if end <= start or end - start > 31 * 86400:
        raise HTTPException(422, 'Zeitraum muss positiv sein und darf höchstens 31 Tage umfassen.')
    return app.state.archive.trace_map(start, end, before, first, last, hops, grouped=grouped)


@app.get('/api/map-traces/{identity}')
def map_trace_detail(identity: int):
    if not 1 <= identity <= 9223372036854775807:
        raise HTTPException(422, 'Ungültige Empfangs-ID.')
    try:
        item = app.state.archive.trace_map_detail(identity)
    except sqlite3.OperationalError as exc:
        raise HTTPException(503, 'Historische Positionen momentan nicht verfügbar. Bitte erneut versuchen.') from exc
    if item is None:
        raise HTTPException(404, 'Keine auswertbare TRACE-Beobachtung.')
    return item


@app.get("/api/repeaters")
def list_repeaters():
    return app.state.archive.repeaters()


@app.get("/api/repeater-history")
def repeater_history(identity: str = Query(..., pattern='^(?:[0-9a-fA-F]{2}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{64})$'),
                     hours: int = Query(24, ge=0, le=8760), compact: bool = False):
    if not compact:
        return app.state.archive.repeater_history(identity.lower(), hours)

    now = time.time()
    result = app.state.archive.repeater_history(identity.lower(), hours, now=now)
    observers = {}
    points = []
    items = result.pop('items')
    for item in items:
        observer = (item['origin_id'], item['origin'])
        points.append((item['received'], item['rssi'], observers.setdefault(observer, len(observers))))
    # The oldest reading survives sampling and is the first one to expire.
    valid_for = max(0, items[0]['received'] + hours * 3600 - now) if items and hours else None
    return JSONResponse(dict(result, points=points, observers=list(observers), valid_for=valid_for),
                        headers={'Cache-Control': 'no-store'})


@app.get('/api/prefix-explorer')
def prefix_explorer(days: int = 30,
                    prefix: str = Query('', max_length=6),
                    reference: str = Query('', max_length=64),
                    reference_q: str = Query('', max_length=128),
                    radius: int = 0,
                    sort: Literal['prefix', 'count', 'distance'] = 'prefix',
                    offset: int = Query(0, ge=0, le=10000000)):
    try:
        return JSONResponse(app.state.archive.prefix_explorer.query(
            days, prefix, reference, radius, sort, offset, reference_q=reference_q), headers={'Cache-Control': 'no-store'})
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.get("/api/nodes")
def search_nodes(q: str = Query('', max_length=200),
                 after: str | None = Query(None, min_length=64, max_length=64, pattern='^[0-9a-fA-F]{64}$'),
                 limit: int = Query(50, ge=1, le=100)):
    return app.state.archive.search_nodes(q.strip(), after.lower() if after else None, limit)


@app.get("/api/map-nodes")
def map_nodes(mesh_live: bool = False):
    if mesh_live:
        return app.state.archive.mesh_live_nodes()
    return app.state.archive.map_nodes()


@app.get('/api/meshlive/replay')
def mesh_live_replay():
    try:
        return Response(content=app.state.archive.mesh_live_replay(), media_type='application/json',
                        headers={'Cache-Control': 'no-store'})
    except ReplayLimitError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except (sqlite3.Error, ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=503, detail='Replay-Archiv momentan nicht lesbar. Bitte erneut versuchen.') from error


@app.get("/api/repeater-neighbors")
def repeater_neighbors():
    return Response(content=app.state.archive.neighbors_json(), media_type='application/json')


def conditional_neighbors(request, mode, **options):
    body, etag = app.state.archive.neighbor_response(mode, **options)
    headers = {'ETag': etag, 'Cache-Control': 'private, no-cache'}
    matches = [tag.strip().removeprefix('W/') for tag in request.headers.get('if-none-match', '').split(',')]
    if etag in matches or '*' in matches:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type='application/json', headers=headers)


@app.get('/api/repeater-neighbors/map')
def repeater_neighbors_map(request: Request):
    return conditional_neighbors(request, 'map')


@app.get('/api/repeater-neighbors/analysis')
def repeater_distance_analysis(
        start: float = Query(..., ge=0, le=4102444800),
        end: float = Query(..., ge=0, le=4102444800),
        minimum: float = Query(200, ge=0, le=MAX_LINK_DISTANCE_KM),
        source: str = Query('', pattern=r'^(?:[0-9a-f]{64})?$'),
        target: str = Query('', pattern=r'^(?:[0-9a-f]{64})?$'),
        offset: int = Query(0, ge=0, le=MAX_PAIR_RECEPTIONS)):
    if bool(source) != bool(target) or (source and source == target):
        raise HTTPException(422, 'Zwei unterschiedliche vollständige Repeater-IDs angeben.')
    if not source and minimum < 100:
        raise HTTPException(422, 'Für die Gesamtübersicht mindestens 100 km wählen.')
    try:
        return app.state.archive.distance_analysis(start, end, minimum, source, target, offset)
    except AnalysisLimitError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get('/api/repeater-neighbors/table')
def repeater_neighbors_table(request: Request, q: str = Query('', max_length=200),
                             one_way: bool = False,
                             sort: Literal['source', 'target', 'forward_count', 'reverse_count',
                                           'direction', 'count', 'last_seen', 'distance_km'] = 'count',
                             descending: bool = True, page: int = Query(0, ge=0),
                             limit: int = Query(100, ge=1, le=100)):
    return conditional_neighbors(request, 'table', q=q, one_way=one_way, sort=sort,
                                 descending=descending, page=page, limit=limit)


@app.get('/api/routes/nodes')
def routing_nodes():
    return route_nodes(app.state.archive.route_snapshot())


@app.get('/api/routes')
def routing_plan(start: str = Query(..., min_length=1, max_length=200),
                 target: str = Query(..., min_length=1, max_length=200),
                 observed_only: bool = False, limit: int = Query(5, ge=1, le=5),
                 max_hops: int = Query(32, ge=1, le=64)):
    try:
        return plan_routes(app.state.archive.route_snapshot(), start, target,
                           observed_only, limit, max_hops)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.websocket("/ws")
async def websocket(websocket: WebSocket):
    await websocket.accept()
    dashboard = websocket.app.state.dashboard
    queue = asyncio.Queue(maxsize=8)
    queue.put_nowait(dashboard.snapshot_payload(dashboard.status()))
    dashboard.listeners[queue] = websocket.query_params.get("stream") == "delta"

    async def send():
        while True:
            payload = await queue.get()
            if isinstance(payload, Exception):
                raise type(payload)(*payload.args)
            await asyncio.wait_for(websocket.send_text(payload), timeout=10)
            del payload  # An idle sender should not keep its last frame alive.

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
        dashboard.remove_listener(queue)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with suppress(WebSocketDisconnect, RuntimeError, OSError):
            await websocket.close(code=close_code,
                                  reason='Server-only stream' if close_code == 1008 else '')
