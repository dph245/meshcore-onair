/* MeshLive consumes the existing server-only stream; it never changes packet groups. */
const MESH_LIVE = Object.freeze({
  TRAVEL_MS: 300, TOTAL_MS: 1000, MAX_ACTIVE: 64,
  DEDUP_WINDOW_MS: 10000, MAX_DEDUP_ENTRIES: 5000,
  MAX_DPR: 2, ACTIVE_DAYS: 28, COLOR: '#087f92',
});
const MESH_REPLAY = Object.freeze({SPEED: 10, WINDOW_MS: 600000, MAX_EVENTS: 5000,
  MAX_PER_FRAME: 200, FRAME_BUDGET_MS: 8});

class MeshLiveModel {
  constructor() {
    this.nodes = new Map();
    this.prefixes = new Map();
    this.terminals = new Set();
    this.seen = new Map();
    this.active = [];
    this.observed = true;
    this.reconstructed = true;
    this.limited = 0;
    this.unmapped = 0;
  }

  identity(value) {
    const id = typeof value === 'string' ? value.toLowerCase() : '';
    if (!/^(?:[0-9a-f]{2}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{64})$/.test(id)) return;
    if (this.terminals.has(id) || (id.length < 64 && this.prefixes.has(id))) return;
    // A longer identity replaces its unresolved ancestor, not another descendant.
    for (const length of [2, 4, 6]) {
      const ancestor = id.slice(0, length);
      if (length >= id.length || !this.terminals.delete(ancestor)) continue;
      for (const size of [2, 4, 6]) {
        if (size > ancestor.length) break;
        const prefix = ancestor.slice(0, size), bucket = this.prefixes.get(prefix);
        bucket?.delete(ancestor);
        if (!bucket?.size) this.prefixes.delete(prefix);
      }
    }
    this.terminals.add(id);
    for (const length of [2, 4, 6]) {
      if (length > id.length) break;
      const prefix = id.slice(0, length);
      if (!this.prefixes.has(prefix)) this.prefixes.set(prefix, new Set());
      this.prefixes.get(prefix).add(id);
    }
  }

  mergeNode(item) {
    const key = item.public_key?.toLowerCase();
    if (!/^[0-9a-f]{64}$/.test(key || '')) return;
    this.identity(key);
    const old = this.nodes.get(key);
    const node = {...item, public_key: key};
    if (old) {
      if (old.advert_time >= node.advert_time) node.name = old.name;
      if (old.advert_time > node.advert_time) node.node_type = old.node_type;
      node.advert_time = Math.max(old.advert_time, node.advert_time);
      node.first_seen = Math.min(old.first_seen, node.first_seen);
      node.last_seen = Math.max(old.last_seen, node.last_seen);
      if (old.position_time != null && (node.position_time == null || old.position_time > node.position_time)) {
        for (const field of ['latitude', 'longitude', 'position_time']) node[field] = old[field];
      }
    }
    this.nodes.set(key, node);
    return key;
  }

  bootstrap(data) {
    // Merge instead of replacing: ADVERTs can arrive while the HTTP request runs.
    for (const node of data.nodes || []) this.mergeNode(node);
    for (const token of data.tokens || []) this.identity(token);
    for (const packet of data.seed_packets || []) this.learn(packet);
  }

  learn(packet) {
    const d = packet.decoded || {};
    if (packet.direction !== 'rx') return;
    if ([0, 1].includes(d.route_type) && d.payload_type !== 9) {
      for (const token of d.hops || []) this.identity(token);
    }
    const advert = d.advert, received = Date.parse(packet.received_at) / 1000;
    if (!advert || d.advert_status || advert.signature_status !== 'Gültig' || !Number.isFinite(received)) return;
    return this.mergeNode({...advert, advert_time: advert.timestamp,
      position_time: advert.latitude != null && advert.longitude != null ? advert.timestamp : null,
      first_seen: received, last_seen: received});
  }

  position(key, wallTime) {
    const node = this.nodes.get(key);
    if (!node || !Number.isFinite(node.latitude) || !Number.isFinite(node.longitude) ||
        Math.abs(node.latitude) > 90 || Math.abs(node.longitude) > 180 ||
        (node.latitude === 0 && node.longitude === 0) ||
        !(node.last_seen > wallTime / 1000 - MESH_LIVE.ACTIVE_DAYS * 86400)) return;
    return [node.latitude, node.longitude];
  }

  resolve(token) {
    if (typeof token !== 'string') return;
    token = token.toLowerCase();
    if (token.length === 64) return this.nodes.has(token) ? token : undefined;
    const candidates = this.prefixes.get(token);
    if (candidates?.size !== 1) return;
    const key = candidates.values().next().value;
    return this.nodes.has(key) ? key : undefined;
  }

  edges(packet) {
    const d = packet.decoded || {};
    if (packet.direction !== 'rx' || ![0, 1].includes(d.route_type) || d.payload_type === 9 || !Array.isArray(d.hops)) return [];
    const edges = [];
    // Resolve adjacent ORIGINAL entries: never filter out a gap before pairing.
    for (let i = 1; i < d.hops.length; i++) {
      edges.push({source: this.resolve(d.hops[i - 1]), target: this.resolve(d.hops[i]), reconstructed: true});
    }
    const advert = d.advert;
    const sender = d.hops.length ? this.resolve(d.hops[d.hops.length - 1]) :
      advert?.signature_status === 'Gültig' && !d.advert_status ? this.resolve(advert.public_key) : undefined;
    const observer = typeof packet.origin_id === 'string' ? packet.origin_id.toLowerCase() : '';
    edges.push({source: sender, target: this.nodes.has(observer) ? observer : undefined, observed: true});
    return edges;
  }

  style(event) {
    if (this.observed && event.observed) return 'observed';
    if (this.reconstructed && event.reconstructed) return 'reconstructed';
  }

  expireAnimations(now) {
    this.active = this.active.filter(event => now - event.started < MESH_LIVE.TOTAL_MS && this.style(event));
  }

  expire(now, eventTime = now) {
    this.expireAnimations(now);
    // Map insertion order is the fixed window's start order (duplicates never extend it).
    for (const [key, entry] of this.seen) {
      if (eventTime - entry.seenAt < MESH_LIVE.DEDUP_WINDOW_MS) break;
      this.seen.delete(key);
    }
  }

  ingest(packet, now, wallTime, animate = true, timing = {}) {
    const {eventTime = now, started = now} = timing;
    this.expire(now, eventTime);
    const d = packet.decoded || {};
    if (typeof d.payload_hex !== 'string') return;
    const identity = JSON.stringify([packet.observer_hash?.toUpperCase() || null,
      d.payload_type, d.payload_ver, d.payload_hex.toLowerCase(), d.transport_code?.toLowerCase() || null]);
    for (const edge of this.edges(packet)) {
      const {source, target} = edge;
      if (!source || !target) { this.unmapped++; continue; }
      if (source === target) continue;
      const from = this.position(source, wallTime), to = this.position(target, wallTime);
      if (!from || !to) { this.unmapped++; continue; }
      // Coincident real coordinates cannot produce a meaningful directional trail.
      if (from[0] === to[0] && from[1] === to[1]) continue;
      const key = JSON.stringify([identity, source, target]);
      const previous = this.seen.get(key);
      if (previous) {
        previous.observed ||= Boolean(edge.observed);
        previous.reconstructed ||= Boolean(edge.reconstructed);
        continue;
      }
      const event = {...edge, from, to, started, seenAt: eventTime};
      this.seen.set(key, event);
      while (this.seen.size > MESH_LIVE.MAX_DEDUP_ENTRIES) this.seen.delete(this.seen.keys().next().value);
      if (!animate || !this.style(event)) continue;
      if (this.active.length >= MESH_LIVE.MAX_ACTIVE) { this.limited++; continue; }
      this.active.push(event);
    }
  }
}

class MeshLiveReplay {
  constructor(data, now) {
    if (!Number.isFinite(data.window_start) || !Number.isFinite(data.window_end) ||
        Math.abs((data.window_end - data.window_start) * 1000 - MESH_REPLAY.WINDOW_MS) > 1 ||
        data.speed !== MESH_REPLAY.SPEED || !Array.isArray(data.events) ||
        data.events.length > MESH_REPLAY.MAX_EVENTS || !data.bootstrap) throw Error('Ungültige Replay-Daten.');
    let previous = -Infinity, previousId = -1;
    for (const event of data.events) {
      if (!Number.isFinite(event.received) || event.received < data.window_start || event.received >= data.window_end ||
          event.received < previous || !Number.isSafeInteger(event.id) || event.id < 1 ||
          (event.received === previous && event.id <= previousId) || !event.packet?.decoded) throw Error('Ungültige Replay-Reihenfolge.');
      previous = event.received; previousId = event.id;
    }
    this.data = data;
    this.model = new MeshLiveModel();
    this.model.bootstrap(data.bootstrap);
    this.anchor = now;
    this.elapsed = 0;
    this.paused = false;
    this.index = 0;
    this.late = 0;
    this.duration = MESH_REPLAY.WINDOW_MS / MESH_REPLAY.SPEED;
  }

  time(now) { return this.elapsed + (this.paused ? 0 : Math.max(0, now - this.anchor)); }
  sourceTime(now) { return this.data.window_start * 1000 + Math.min(this.duration, this.time(now)) * MESH_REPLAY.SPEED; }
  pause(now) { this.elapsed = this.time(now); this.paused = true; }
  resume(now) { if (this.paused) { this.anchor = now; this.paused = false; } }

  advance(now) {
    const changed = new Set(), visualTime = this.time(now), deadline = performance.now() + MESH_REPLAY.FRAME_BUDGET_MS;
    let processed = 0;
    if (!this.paused) while (this.index < this.data.events.length && processed < MESH_REPLAY.MAX_PER_FRAME) {
      const event = this.data.events[this.index];
      const due = (event.received - this.data.window_start) * 1000 / MESH_REPLAY.SPEED;
      if (due > visualTime || performance.now() >= deadline) break;
      const key = this.model.learn(event.packet);
      if (key) changed.add(key);
      const animate = visualTime - due < MESH_LIVE.TOTAL_MS;
      if (!animate) this.late++;
      this.model.ingest(event.packet, visualTime, event.received * 1000, animate,
        {eventTime: event.received * 1000, started: due});
      this.index++; processed++;
    }
    this.model.expireAnimations(visualTime);
    return changed;
  }

  finished(now) {
    return this.index === this.data.events.length && this.time(now) >= this.duration && !this.model.active.length;
  }
}

function meshLivePhase(age) {
  if (age < 0 || age >= MESH_LIVE.TOTAL_MS) return null;
  return {progress: Math.min(1, age / MESH_LIVE.TRAVEL_MS),
    alpha: age <= MESH_LIVE.TRAVEL_MS ? 1 :
      (MESH_LIVE.TOTAL_MS - age) / (MESH_LIVE.TOTAL_MS - MESH_LIVE.TRAVEL_MS),
    moving: age < MESH_LIVE.TRAVEL_MS};
}

window.MeshLive = (() => {
  let model, map, canvas, context, frame, resizeObserver, controller;
  let opened = false, ready = false, paused = false, highWater = 0, needsRefresh = true;
  let dropped = 0, resyncs = 0, error = '', packetTime = null;
  let mode = 'live', replay = null, pauseOnLoad = false;
  const markers = new Map();
  const element = id => document.getElementById(`meshlive-${id}`);
  const visible = () => opened && !document.hidden;
  const running = () => visible() && ready && (mode === 'replay' ? !replay.paused : mode === 'live' && !paused);
  const animationTime = () => replay ? replay.time(performance.now()) : performance.now();

  function status() {
    if (!model) return;
    const replayMode = mode !== 'live';
    element('replay-badge').hidden = !replayMode;
    element('replay-controls').hidden = !replayMode;
    element('replay-start').disabled = replayMode || !ready;
    element('refresh').disabled = replayMode;
    element('pause').hidden = replayMode;
    element('replay-pause').disabled = !replay;
    element('replay-pause').textContent = replay?.paused ? 'Replay fortsetzen' : 'Replay pausieren';
    element('replay-pause').setAttribute('aria-pressed', String(Boolean(replay?.paused)));
    const activity = mode === 'loading' ? 'Replay wird geladen …' : replay ?
      replay.paused ? 'Replay pausiert' : 'REPLAY · 10×' : !ready ? 'Knoten werden geladen …' : paused ? 'Animation pausiert' : 'Live';
    element('status').textContent = error || `${markers.size} Nodes · ${activity} · ${model.unmapped} Strecken nicht zuordenbar · ${model.limited} Spuren am Limit ausgelassen` +
      (replay ? ` · ${replay.late} verspätete Empfänge ohne Animation` : ` · ${dropped} RX vom Server verworfen · ${resyncs} Stream-Abgleiche ohne Nachspielen`);
    replayProgress();
  }

  function stopDrawing() {
    if (frame != null) cancelAnimationFrame(frame);
    frame = null;
    if (context) context.clearRect(0, 0, canvas.width, canvas.height);
  }

  function clear() {
    stopDrawing();
    if (model) model.active = [];
  }

  function resetMarkers() {
    for (const marker of markers.values()) marker.remove();
    markers.clear();
  }

  function replayProgress() {
    if (!replay) {
      element('replay-progress').value = 0;
      element('replay-position').textContent = mode === 'loading' ? 'Archiv wird gelesen …' : '';
      return;
    }
    const now = performance.now(), elapsed = Math.min(replay.duration, replay.time(now));
    element('replay-progress').value = elapsed / replay.duration;
    const range = `${new Date(replay.data.window_start * 1000).toLocaleTimeString('de-DE')}–${new Date(replay.data.window_end * 1000).toLocaleTimeString('de-DE')}`;
    const label = `${range} · ${new Date(replay.sourceTime(now)).toLocaleTimeString('de-DE')} · ${Math.floor(elapsed / 1000)} / 60 s · ${replay.index}/${replay.data.events.length} Empfänge${elapsed === replay.duration ? ' · Spuren klingen aus' : ''}`;
    // Do not rebuild or announce identical progress text on every frame.
    if (element('replay-position').textContent !== label) element('replay-position').textContent = label;
  }

  function pauseReplay() {
    pauseOnLoad = true;
    if (replay) replay.pause(performance.now());
    stopDrawing(); status(); schedule(true);
  }

  function endReplay(message = '') {
    controller?.abort(); controller = null;
    clear(); replay = null; mode = 'live'; pauseOnLoad = false;
    model = new MeshLiveModel();
    for (const kind of ['observed', 'reconstructed']) model[kind] = element(kind).checked;
    resetMarkers(); ready = false; needsRefresh = true; error = ''; packetTime = null;
    element('replay-message').textContent = message;
    status();
    if (visible()) refresh();
  }

  async function startReplay() {
    if (!visible() || !ready || mode !== 'live') return;
    controller?.abort();
    const request = controller = new AbortController();
    clear(); mode = 'loading'; ready = false; error = ''; pauseOnLoad = false;
    element('replay-message').textContent = ''; status();
    try {
      const response = await fetch('/api/meshlive/replay', {signal: request.signal, cache: 'no-store'});
      const data = await response.json();
      if (controller !== request || mode !== 'loading') return;
      if (!response.ok) throw Error(data.detail || `HTTP ${response.status}`);
      const next = new MeshLiveReplay(data, performance.now());
      if (!data.events.length) { endReplay('Keine archivierten Empfänge in den letzten zehn Minuten.'); return; }
      replay = next; model = replay.model; mode = 'replay'; ready = true;
      packetTime = null;
      for (const kind of ['observed', 'reconstructed']) model[kind] = element(kind).checked;
      replay.paused = true;
      resetMarkers();
      if (visible()) renderNodes();
      if (!pauseOnLoad && visible()) replay.resume(performance.now());
      const latest = data.archive_latest_received == null ? 'unbekannt' : new Date(data.archive_latest_received * 1000).toLocaleString('de-DE');
      element('replay-message').textContent = `Archivstand: ${latest}. Die letzten Sekunden können noch ungespeichert sein. Nur damals belegbare Positionen.${data.seed_scan_limited ? ' Positionssuche begrenzt; fehlende Positionen bleiben unsichtbar.' : ''}`;
      status(); schedule(true);
    } catch (cause) {
      if (controller !== request || cause.name === 'AbortError') return;
      endReplay(`Replay konnte nicht gestartet werden: ${cause.message}`);
    } finally {
      if (controller === request) controller = null;
    }
  }

  function resize() {
    if (!visible() || !canvas) return;
    map.invalidateSize({pan: false});
    const size = map.getSize(), dpr = Math.min(MESH_LIVE.MAX_DPR, window.devicePixelRatio || 1);
    canvas.width = Math.ceil(size.x * dpr);
    canvas.height = Math.ceil(size.y * dpr);
    canvas.style.width = `${size.x}px`;
    canvas.style.height = `${size.y}px`;
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    schedule(true);
  }

  function schedule(redraw = false) {
    if (frame == null && visible() && ready &&
        ((running() && (replay || model.active.length)) || (redraw && replay))) frame = requestAnimationFrame(draw);
  }

  function draw(now) {
    frame = null;
    context.clearRect(0, 0, canvas.width, canvas.height);
    if (!visible() || !ready || (mode === 'live' && !running())) return;
    if (replay) {
      const changed = replay.advance(now);
      if (changed.size) renderNodes(changed);
      replayProgress();
      if (replay.finished(now)) { endReplay('Replay beendet. Zurück zu Live, ohne Nachspielen.'); return; }
      now = replay.time(now);
      if (changed.size || packetTime == null || now - packetTime >= 1000) {
        // Historical inactivity is evaluated against the replay cursor, never today's clock.
        for (const [key, marker] of markers) if (!model.position(key, replay.sourceTime(performance.now()))) {
          marker.remove(); markers.delete(key);
        }
        status(); packetTime = now;
      }
    } else model.expire(now);
    const size = map.getSize();
    for (const event of model.active) {
      const phase = meshLivePhase(now - event.started);
      if (!phase) continue;
      const a = map.latLngToContainerPoint(event.from), b = map.latLngToContainerPoint(event.to);
      if (Math.max(a.x, b.x) < 0 || Math.min(a.x, b.x) > size.x ||
          Math.max(a.y, b.y) < 0 || Math.min(a.y, b.y) > size.y) continue;
      const x = a.x + (b.x - a.x) * phase.progress, y = a.y + (b.y - a.y) * phase.progress;
      const inferred = model.style(event) === 'reconstructed';
      context.strokeStyle = MESH_LIVE.COLOR;
      context.fillStyle = MESH_LIVE.COLOR;
      context.globalAlpha = phase.alpha * (inferred ? 0.42 : 0.68);
      context.lineWidth = inferred ? 1.4 : 1.8;
      context.lineCap = 'round';
      context.setLineDash(inferred ? [5, 5] : []);
      context.beginPath(); context.moveTo(a.x, a.y); context.lineTo(x, y); context.stroke();
      if (phase.moving) {
        context.globalAlpha = inferred ? 0.65 : 0.85;
        context.shadowColor = MESH_LIVE.COLOR; context.shadowBlur = 5;
        context.beginPath(); context.arc(x, y, 2.5, 0, Math.PI * 2); context.fill();
        context.shadowBlur = 0;
      }
    }
    context.globalAlpha = 1;
    schedule();
  }

  function renderNodes(keys = model.nodes.keys()) {
    const now = replay ? replay.sourceTime(performance.now()) : Date.now();
    for (const key of keys) {
      const node = model.nodes.get(key), position = model.position(key, now);
      if (!position) {
        markers.get(key)?.remove(); markers.delete(key); continue;
      }
      const label = `${node.name || 'Ohne Namen'} [${key.slice(0, 6)}]`;
      const content = document.createElement('div'); content.className = 'map-marker-content';
      content.append(mapNodeSymbol(mapTypes[node.node_type]?.[1] || 'other'));
      const icon = L.divIcon({html: content, className: 'map-marker', iconSize: [24, 24], iconAnchor: [12, 12]});
      let marker = markers.get(key);
      if (!marker) {
        marker = L.marker(position, {icon, title: label, keyboard: true}).addTo(map);
        markers.set(key, marker);
      } else marker.setLatLng(position).setIcon(icon);
      const info = document.createElement('div'); info.className = 'map-node-info';
      info.textContent = `${label} · ${key} · Position vom ${new Date(node.position_time * 1000).toLocaleString('de-DE')}`;
      marker.unbindTooltip().bindTooltip(document.createTextNode(label));
      marker.unbindPopup().bindPopup(info);
    }
  }

  async function refresh() {
    if (!visible() || !map || mode !== 'live') return;
    controller?.abort();
    const request = controller = new AbortController();
    ready = false; error = ''; clear(); status();
    try {
      const response = await fetch('/api/map-nodes?mesh_live=true', {signal: request.signal, cache: 'no-store'});
      if (!response.ok) throw Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (controller !== request || !visible() || mode !== 'live') return;
      model.bootstrap(data);
      renderNodes();
      ready = true; needsRefresh = false;
    } catch (cause) {
      if (controller !== request || cause.name === 'AbortError') return;
      error = `Knoten konnten nicht geladen werden: ${cause.message}. Bitte „Knoten aktualisieren“ wählen.`;
    } finally {
      if (controller === request) { controller = null; status(); }
    }
  }

  function initialize() {
    if (!window.L) throw Error('Kartenbibliothek konnte nicht geladen werden. Bitte Seite neu laden.');
    model = new MeshLiveModel();
    const view = savedMapView();
    map = L.map('meshlive-map', {zoomAnimation: false, fadeAnimation: false}).setView(view.center, view.zoom);
    const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
    let tileErrors = false;
    tiles.on('loading', () => { tileErrors = false; });
    tiles.on('tileerror', () => { tileErrors = true; element('tiles-status').hidden = false; });
    tiles.on('load', () => { element('tiles-status').hidden = !tileErrors; });
    canvas = document.createElement('canvas'); canvas.className = 'meshlive-canvas';
    canvas.setAttribute('aria-hidden', 'true');
    context = canvas.getContext('2d');
    if (!context) throw Error('Canvas wird von diesem Browser nicht unterstützt.');
    map.getContainer().append(canvas);
    map.on('move zoom resize', () => schedule(true));
    resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(map.getContainer());
    for (const kind of ['observed', 'reconstructed']) {
      element(kind).addEventListener('change', () => {
        model[kind] = element(kind).checked;
        if (replay) model.expireAnimations(animationTime());
        else model.expire(performance.now());
        context.clearRect(0, 0, canvas.width, canvas.height);
        schedule(true);
      });
    }
    element('pause').addEventListener('click', () => {
      paused = !paused; clear();
      element('pause').textContent = paused ? 'Animation fortsetzen' : 'Animation pausieren';
      element('pause').setAttribute('aria-pressed', String(paused)); status();
    });
    element('fit').addEventListener('click', () => {
      if (markers.size) map.fitBounds(L.latLngBounds([...markers.values()].map(marker => marker.getLatLng())), {padding: [30, 30], maxZoom: 14});
    });
    element('refresh').addEventListener('click', refresh);
    element('replay-start').addEventListener('click', startReplay);
    element('replay-end').addEventListener('click', () => endReplay());
    element('replay-pause').addEventListener('click', () => {
      if (!replay) return;
      if (replay.paused) { replay.resume(performance.now()); status(); schedule(); }
      else pauseReplay();
    });
    document.addEventListener('visibilitychange', () => {
      if (mode !== 'live') {
        if (!visible()) pauseReplay();
        else { resize(); if (replay) renderNodes(); }
        return;
      }
      if (!visible()) { clear(); controller?.abort(); needsRefresh = true; }
      else { resize(); refresh(); }
    });
  }

  function select(active) {
    opened = active;
    if (mode !== 'live') {
      if (!active) pauseReplay();
      else { resize(); if (replay) renderNodes(); status(); }
      return;
    }
    if (!active) { clear(); controller?.abort(); needsRefresh = true; return; }
    try {
      if (!map) initialize();
      resize();
      if (needsRefresh) refresh();
    } catch (cause) {
      element('status').textContent = cause.message;
    }
  }

  function receive(data) {
    // This lightweight watermark runs even before initialization. Hidden tabs never replay.
    const packets = (data.groups || []).flatMap(group => group.receptions || [])
      .filter(packet => Number.isSafeInteger(packet.number));
    const snapshot = data.type === 'snapshot';
    const fresh = packets.filter(packet => packet.number > highWater).sort((a, b) => a.number - b.number);
    if (snapshot) highWater = 0;
    for (const packet of packets) highWater = Math.max(highWater, packet.number);
    dropped = data.status?.dropped ?? dropped;
    // Keep the live watermark even across reconnects, but never learn, deduplicate,
    // refresh or draw live packets in the isolated replay model.
    if (mode !== 'live') { needsRefresh = true; return; }
    if (!model || !visible()) { needsRefresh = true; return; }
    try {
      if (snapshot) {
        resyncs++; clear(); model.expire(performance.now());
        // In-memory ADVERTs also cover the archive writer's commit delay.
        for (const packet of packets) model.learn(packet);
        refresh(); return;
      }
      const changed = new Set(), now = performance.now(), wallTime = Date.now();
      // Learn all identities first, so same-batch collisions cannot animate a false match.
      for (const packet of fresh) {
        const key = model.learn(packet);
        if (key) changed.add(key);
      }
      for (const packet of fresh) model.ingest(packet, now, wallTime, running());
      if (changed.size) renderNodes(changed);
      // Expire inactive nodes without a polling query or a permanent timer.
      if (packetTime == null || now - packetTime > 60000) { renderNodes(); packetTime = now; }
      status(); schedule();
    } catch (cause) {
      // An optional visualization must never interrupt the existing text view.
      clear(); error = `MeshLive: ${cause.message}`; status();
    }
  }
  return {select, receive};
})();
