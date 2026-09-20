const tabs = [...document.querySelectorAll('[role="tab"]')];
function selectTab(selected) {
  for (const tab of tabs) {
    const active = tab === selected;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    document.getElementById(tab.getAttribute('aria-controls')).hidden = !active;
  }
  if (selected.id === 'tab-channels' && !channelsReady) loadChannelMessages();
  if (selected.id === 'tab-observers') loadObservers();
  if (selected.id === 'tab-repeaters') loadRepeaters();
  if (selected.id === 'tab-map') showNodeMap();
}
for (const [index, tab] of tabs.entries()) {
  tab.addEventListener('click', () => selectTab(tab));
  tab.addEventListener('keydown', event => {
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else return;
    event.preventDefault();
    selectTab(tabs[next]);
    tabs[next].focus();
  });
}

const groups = new Map(), expanded = new Set();
let paused = false, status = {}, socket;
const body = document.getElementById('packets');
const text = (tag, value, className) => {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
};
const measurement = (value, unit) => value == null ? '—' : `${value} ${unit}`;
// Central thresholds for the live SNR indicator; values are in dB.
const snrThresholds = { low: -2, high: 0 };
function snrMeasurement(value) {
  const display = text('span', '', 'snr-reading');
  display.append(text('span', measurement(Number.isFinite(value) ? value : null, 'dB')));
  if (!Number.isFinite(value)) return display;
  const level = value < snrThresholds.low ? 1 : value <= snrThresholds.high ? 2 : 3;
  const bars = text('span', '', `snr-bars snr-level-${level}`);
  bars.setAttribute('aria-hidden', 'true');
  display.title = `SNR: ${value} dB · ${level} von 3 Balken`;
  for (let index = 1; index <= 3; index++) {
    bars.append(text('span', '', index <= level ? 'active' : ''));
  }
  display.append(bars);
  return display;
}
function scopeLabel(decoded) {
  if (decoded.scope_label) return decoded.scope_label;
  if (![0, 3].includes(decoded.route_type)) return 'Kein Scope';
  // Transport code 1 is a packet-dependent uint16 in little-endian order.
  // Derive this from the existing field so archived receptions work as well.
  const raw = decoded.transport_code;
  if (typeof raw !== 'string' || !/^[0-9a-f]{8}$/i.test(raw)) return 'Unbekannt';
  return `Unbekannt (0x${(raw.slice(2, 4) + raw.slice(0, 2)).toUpperCase()})`;
}
const liveFilter = document.getElementById('live-repeater');
let displayedGroups = [], displayedStatus = {};
function matchesRepeater(packet, query) {
  const d = packet.decoded;
  // DIRECT paths describe destinations, not the transmitting repeater.
  if (packet.direction !== 'rx' || ![0, 1].includes(d.route_type)) return false;
  if (d.hops.length) {
    return [d.hops[d.hops.length - 1], packet.last_hop]
      .some(value => value.toLowerCase().includes(query));
  }
  const a = d.advert;
  return Boolean(a && !d.advert_status && a.node_type === 2 && a.signature_status === 'Gültig'
    && [a.public_key, a.name || ''].some(value => value.toLowerCase().includes(query)));
}
function filteredLiveGroups(source, query) {
  return source.flatMap(group => {
    if (!query) return [group];
    const receptions = group.receptions.filter(packet => matchesRepeater(packet, query));
    if (!receptions.length) return [];
    return [{...group, receptions, latest: receptions[receptions.length - 1]}];
  }).sort((a, b) => b.latest.number - a.latest.number);
}
function receptionsBySnr(receptions) {
  return [...receptions].sort((a, b) => {
    const aSnr = Number.isFinite(a.snr) ? a.snr : -Infinity;
    const bSnr = Number.isFinite(b.snr) ? b.snr : -Infinity;
    return aSnr === bSnr ? b.number - a.number : bSnr - aSnr;
  });
}
function render(force = false) {
  if (paused && !force) return;
  if (!paused) {
    displayedGroups = [...groups.values()];
    displayedStatus = status;
    renderNoise(status.noise_history || []);
  }
  const query = liveFilter.value.trim().toLowerCase();
  const fragment = document.createDocumentFragment();
  const sorted = filteredLiveGroups(displayedGroups, query);
  for (const group of sorted) {
    const p = group.latest, d = p.decoded, open = expanded.has(group.id);
    const receptions = receptionsBySnr(group.receptions);
    const row = text('tr', '', 'packet');
    const time = text('td', '');
    const toggle = text('button', `${open ? '▾' : '▸'} ${p.time}`, 'expand');
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', `Paket ${p.observer_hash || p.number}: Details`);
    toggle.onclick = () => { open ? expanded.delete(group.id) : expanded.add(group.id); render(true); };
    time.append(toggle); row.append(time);
    for (const value of [d.payload_name, d.route_name]) row.append(text('td', value));
    row.append(text('td', scopeLabel(d)));
    const content = text('td', '', 'message');
    if (d.payload_name === 'GRP_TXT') {
      if (d.group_text != null) {
        content.append(text('div', d.group_channel, 'muted'));
        content.append(text('div', d.group_text));
      } else {
        content.append(text('span', d.group_text_status || 'Nicht entschlüsselbar', 'muted'));
      }
    } else if (d.payload_name === 'ADVERT') {
      const advert = d.advert;
      if (advert) {
        content.append(text('div', `${advert.name || 'Ohne Namen'} · ${advert.node_type_name}`));
        if (advert.latitude != null) {
          content.append(text('div', `${advert.latitude.toFixed(6)}, ${advert.longitude.toFixed(6)}`, 'muted'));
        }
      }
      if (d.advert_status) content.append(text('div', d.advert_status, 'muted'));
    }
    row.append(content);
    row.append(text('td', p.last_hop));
    const rssiCell = text('td', '');
    rssiCell.append(text('div', measurement(p.rssi, 'dBm'), 'live-reception-line'));
    const snrCell = text('td', '');
    const latestSnr = text('div', '', 'live-reception-line');
    latestSnr.append(snrMeasurement(p.snr));
    snrCell.append(latestSnr);
    row.append(rssiCell, snrCell, text('td', d.hop_count));
    const repeats = text('td', '');
    const hashLabel = text('div', `${p.observer_hash?.slice(0, 6) || 'ohne Hash'} · ${group.count} ${group.count === 1 ? 'Empfang' : 'Empfänge'}`, 'live-reception-line');
    hashLabel.title = `${p.observer_hash || 'ohne Hash'} · Empfangsbeobachtungen über alle Observer, keine Anzahl von Weiterleitungen`;
    repeats.append(hashLabel);
    if (query) {
      repeats.append(text('div', `${group.receptions.length} passende gespeicherte Empfänge`, 'muted live-reception-line'));
      for (const cell of [rssiCell, snrCell]) cell.append(text('div', '', 'live-reception-line'));
    }
    if (group.count > 1) {
      const hopList = text('div', '', 'muted');
      hopList.title = 'Empfänge nach SNR absteigend (maximal 50); Messwerte in den RSSI- und SNR-Spalten';
      for (const reception of receptions) {
        const hop = text('div', `${reception.last_hop} via Observer ${observerLabel(reception, true)}`, 'live-reception-line');
        rssiCell.append(text('div', measurement(reception.rssi, 'dBm'), 'live-reception-line'));
        const snr = text('div', '', 'live-reception-line');
        snr.append(snrMeasurement(reception.snr));
        snrCell.append(snr);
        hop.title = observerLabel(reception);
        hopList.append(hop);
      }
      repeats.append(hopList);
    }
    row.append(repeats);
    fragment.append(row);
    if (open) {
      const detail = text('tr', '', 'detail'), cell = text('td', ''); cell.colSpan = 10;
      cell.append(text('div', `${group.count} Empfänge in dieser Gruppe · ${group.receptions.length} ${query ? 'passende gespeichert' : 'gespeichert'} · zuerst lokal: ${group.first_seen}`, 'muted'));
      for (const reception of receptions) {
        const decoded = reception.decoded, block = text('section', '', 'reception');
        const receptionSummary = text('div', `#${reception.number} · ${reception.time} · ${decoded.route_name} · ${measurement(reception.rssi, 'dBm')} · `);
        receptionSummary.append(snrMeasurement(reception.snr));
        block.append(receptionSummary);
        const observer = text('div', `Observer: ${observerLabel(reception, true)}`);
        observer.title = observerLabel(reception);
        block.append(observer);
        block.append(text('div', `Pfad: ${reception.path}`));
        block.append(text('div', `Scope: ${scopeLabel(decoded)}`));
        if (decoded.advert) {
          const a = decoded.advert;
          block.append(text('div', `Advert: ${a.name || 'Ohne Namen'} · ${a.node_type_name}`));
          if (a.latitude != null) block.append(text('div', `Position: ${a.latitude.toFixed(6)}, ${a.longitude.toFixed(6)}`));
          block.append(text('pre', `Public Key: ${a.public_key}\nAdvert-Zeit: ${new Date(a.timestamp * 1000).toISOString()} (Unix: ${a.timestamp})\nFlags: ${a.flags == null ? '—' : '0x' + a.flags.toString(16).padStart(2, '0')} · Feature 1: ${a.feature_1 ?? '—'} · Feature 2: ${a.feature_2 ?? '—'}\nSignatur (${a.signature_status}): ${a.signature}`));
        }
        if (decoded.advert_status) block.append(text('div', decoded.advert_status, 'muted'));
        block.append(text('div', `Transport-Code: ${decoded.transport_code || '—'} · Hashgröße: ${decoded.hash_size} Byte · Länge: ${measurement(reception.length, 'B')}`));
        block.append(text('pre', `Raw: ${reception.raw_hex}\nPayload: ${decoded.payload_hex}\nHeader: 0x${decoded.header.toString(16).padStart(2, '0')} · Payload-Typ: ${decoded.payload_type} · Version: ${decoded.payload_ver} · Path-Length: 0x${decoded.path_len_raw.toString(16).padStart(2, '0')}\nHop-Hashes: ${decoded.hops.join(' → ') || '—'}\nLokal empfangen: ${reception.received_at}`));
        cell.append(block);
      }
      detail.append(cell); fragment.append(detail);
    }
  }
  body.replaceChildren(fragment);
  document.getElementById('empty').hidden = sorted.length > 0;
  document.getElementById('empty').textContent = query
    ? 'Keine passenden Empfänge im Live-Puffer. Filter ändern oder zurücksetzen.'
    : 'Noch keine RX-Pakete empfangen. Die Ansicht aktualisiert sich automatisch.';
  document.getElementById('live-filter-status').textContent = query
    ? `${sorted.length} von ${displayedGroups.length} Paketgruppen · nur passende gespeicherte Empfänge${paused ? ' · Ansicht pausiert' : ''}` : '';
  document.getElementById('counts').textContent = `${displayedGroups.length} Paketgruppen · ${displayedStatus.received || 0} RX seit Start · ${displayedStatus.dropped || 0} bei Überlast verworfen`;
  if (displayedStatus.archive) {
    document.getElementById('counts').textContent += ` · ${displayedStatus.archive.saved} archiviert seit Start`;
    if (displayedStatus.archive.error || displayedStatus.archive.dropped) {
      document.getElementById('counts').textContent += ` · Archivproblem: ${displayedStatus.archive.error || ''} · ${displayedStatus.archive.dropped} verworfen`;
    }
  }
}
liveFilter.addEventListener('input', () => render(true));
document.getElementById('live-filter-reset').onclick = () => {
  liveFilter.value = '';
  render(true);
  liveFilter.focus();
};
function connection() {
  const online = socket.readyState === WebSocket.OPEN;
  const node = document.getElementById('connection');
  node.textContent = online ? (status.connected ? '● MQTT verbunden · Live' : '● MQTT getrennt · warte auf Verbindung') : '● WebSocket getrennt · verbinde erneut …';
  node.className = online && status.connected ? 'online' : 'offline';
  const noise = document.getElementById('noise-floor');
  noise.replaceChildren();
  for (const observer of status.noise_observers || []) {
    if (!noiseObserverActive(observer)) continue;
    const reading = text('span', `Noise Floor ${observerLabel(observer, true)}: ${measurement(online && status.connected ? observer.noise_floor : null, 'dBm')}`);
    reading.title = `${observerLabel(observer)} · Letzter Status: ${new Date(observer.status_at || observer.received_at).toLocaleString('de-DE')}`;
    noise.append(reading);
  }
  if (!noise.children.length) noise.textContent = 'Noise Floor: —';
}
function connect() {
  socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`);
  socket.onopen = connection;
  socket.onmessage = event => {
    const data = JSON.parse(event.data);
    if (data.type === 'snapshot') groups.clear();
    for (const id of data.removed || []) groups.delete(id);
    for (const group of data.groups || []) groups.set(group.id, group);
    for (const id of expanded) if (!groups.has(id)) expanded.delete(id);
    status = data.status || status;
    connection(); render();
  };
  socket.onclose = () => { connection(); setTimeout(connect, 2000); };
  socket.onerror = () => socket.close();
}
document.getElementById('pause').onclick = event => {
  paused = !paused;
  event.target.textContent = paused ? 'Live fortsetzen' : 'Ansicht pausieren';
  event.target.setAttribute('aria-pressed', String(paused));
  if (!paused) {
    render();
    if (!document.getElementById('panel-observers').hidden) loadObservers();
    if (!document.getElementById('panel-repeaters').hidden) loadRepeaters();
    if (!document.getElementById('panel-map').hidden) loadMapNodes();
  }
};
connect();
// Expire silent observers even without MQTT/WebSocket updates. While paused,
// keep the displayed measurements frozen but still hide expired observers.
setInterval(() => {
  connection();
  renderNoise((paused ? displayedStatus : status).noise_history || []);
}, 1000);

let repeatersLoading = false;
async function loadRepeaters() {
  if (repeatersLoading || paused) return;
  repeatersLoading = true;
  const message = document.getElementById('repeaters-status');
  try {
    const response = await fetch('/api/repeaters');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const {items} = await response.json();
    if (paused) return;
    const results = document.getElementById('repeaters-results');
    const position = value => `${Math.max(0, Math.min(100, (value + 140) / 120 * 100))}%`;
    for (const item of items) {
      const view = repeaterView(item);
      const row = view.summary;
      row.replaceChildren();
      const identity = text('div', '', 'repeater-identity');
      identity.append(text('strong', item.name));
      identity.append(text('div', item.id, 'muted'));
      identity.title = `Empfangene Kennungen: ${item.tokens.join(', ')}`;
      const signal = text('div', '', 'repeater-signal');
      signal.append(text('div', `RSSI ${measurement(item.rssi, 'dBm')}`, 'repeater-reading'));
      const track = text('div', '', 'signal-track');
      track.setAttribute('role', 'img');
      track.setAttribute('aria-label', `RSSI ${measurement(item.rssi, 'dBm')}, Minimum ${measurement(item.min_rssi, 'dBm')}, Maximum ${measurement(item.max_rssi, 'dBm')}`);
      if (item.rssi != null) {
        const fill = text('span', '', 'signal-fill');
        fill.style.width = position(item.rssi);
        track.append(fill);
      }
      for (const [field, title] of [['min_rssi', 'Minimum'], ['max_rssi', 'Maximum']]) {
        if (item[field] == null) continue;
        const marker = text('span', '', `signal-marker ${field}`);
        marker.style.left = position(item[field]);
        marker.title = `${title}: ${measurement(item[field], 'dBm')}`;
        track.append(marker);
      }
      signal.append(track);
      signal.append(text('div', `Min ${measurement(item.min_rssi, 'dBm')} · Max ${measurement(item.max_rssi, 'dBm')}`, 'muted'));
      const details = text('div', '', 'repeater-details');
      details.append(text('div', `${item.count.toLocaleString('de-DE')} Empfänge gesamt`));
      details.append(text('div', `Zuletzt: ${new Date(item.last_seen * 1000).toLocaleString('de-DE')}`, 'muted'));
      row.append(identity, signal, details);
    }
    for (const [id, view] of repeaterViews) {
      if (!items.some(item => item.id === id)) {
        view.element.remove();
        repeaterViews.delete(id);
      }
    }
    items.forEach((item, index) => {
      const view = repeaterViews.get(item.id);
      if (results.children[index] !== view.element) results.insertBefore(view.element, results.children[index] || null);
      loadRepeaterHistory(view);
    });
    message.textContent = items.length
      ? `${items.length} Repeater / Hop-Kennungen · Stand: ${new Date().toLocaleTimeString('de-DE')}`
      : 'Keine direkten Repeater-Empfänge in den letzten 8 Stunden.';
  } catch (error) {
    message.textContent = `Repeater konnten nicht geladen werden: ${error.message}. Erneuter Versuch in 5 Sekunden; vorhandene Werte bleiben stehen.`;
  } finally {
    repeatersLoading = false;
  }
}
setInterval(() => {
  if (!document.getElementById('panel-repeaters').hidden) loadRepeaters();
}, 5000);

const archiveForm = document.getElementById('archive-search');
const archiveResults = document.getElementById('archive-results');
const archiveStatus = document.getElementById('archive-status');
const archiveMore = document.getElementById('archive-more');
let archiveQuery = new URLSearchParams(), archiveBefore = null, archiveLoading = false;
async function searchArchive(more = false) {
  if (archiveLoading) return;
  archiveLoading = true;
  archiveMore.disabled = true;
  archiveForm.querySelector('button').disabled = true;
  if (!more) {
    archiveQuery = new URLSearchParams();
    for (const [key, value] of new FormData(archiveForm)) {
      if (value) archiveQuery.set(key, key === 'since' || key === 'until' ? String(new Date(value).getTime() / 1000) : key === 'kind' ? value.toUpperCase() : value);
    }
    archiveBefore = null;
    archiveMore.hidden = true;
    archiveResults.replaceChildren();
  }
  const query = new URLSearchParams(archiveQuery);
  if (archiveBefore != null) query.set('before', archiveBefore);
  archiveStatus.textContent = 'Archiv wird durchsucht …';
  try {
    const response = await fetch(`/api/archive?${query}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    for (const item of result.items) {
      const p = item.packet, d = p.decoded, a = d.advert;
      const entry = text('details', '', 'reception');
      const content = d.payload_name === 'GRP_TXT'
        ? (d.group_text ?? d.group_text_status ?? 'Nicht entschlüsselbar')
        : ((a && a.name) || d.advert_status || '');
      entry.append(text('summary', `${new Date(p.received_at).toLocaleString()} · ${d.payload_name} · ${d.group_channel || ''} · Scope: ${scopeLabel(d)} · ${content} · ${p.last_hop}`));
      entry.append(text('div', `Pfad: ${p.path} · RSSI: ${measurement(p.rssi, 'dBm')} · SNR: ${measurement(p.snr, 'dB')} · Hash: ${p.observer_hash || '—'}`));
      entry.append(text('div', `Observer: ${observerLabel(p)}`));
      entry.append(text('pre', JSON.stringify(p, null, 2)));
      archiveResults.append(entry);
    }
    archiveBefore = result.next_before;
    archiveMore.hidden = archiveBefore == null;
    archiveStatus.textContent = `${archiveResults.children.length} Empfänge geladen${archiveBefore == null ? ' · Ende der Treffer' : ''}`;
  } catch (error) {
    archiveStatus.textContent = `Archiv konnte nicht geladen werden: ${error.message}. Bitte erneut versuchen.`;
  } finally {
    archiveLoading = false;
    archiveMore.disabled = false;
    archiveForm.querySelector('button').disabled = false;
  }
}
archiveForm.onsubmit = event => { event.preventDefault(); searchArchive(); };
archiveMore.onclick = () => searchArchive(true);

const nodesForm = document.getElementById('nodes-search');
const nodesResults = document.getElementById('nodes-results');
const nodesStatus = document.getElementById('nodes-status');
const nodesMore = document.getElementById('nodes-more');
let nodesQuery = '', nodesAfter = null, nodesLoading = false;
async function searchNodes(more = false) {
  if (nodesLoading) return;
  nodesLoading = true;
  nodesMore.disabled = true;
  nodesForm.querySelector('button').disabled = true;
  if (!more) {
    nodesQuery = new FormData(nodesForm).get('q').trim();
    nodesAfter = null;
    nodesMore.hidden = true;
    nodesResults.replaceChildren();
  }
  const query = new URLSearchParams({q: nodesQuery});
  if (nodesAfter != null) query.set('after', nodesAfter);
  nodesStatus.textContent = 'Nodes werden gesucht …';
  try {
    const response = await fetch(`/api/nodes?${query}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    for (const node of result.items) {
      const entry = text('div', '', 'reception');
      entry.append(text('strong', node.name || 'Ohne Namen'));
      entry.append(text('div', `Public Key: ${node.public_key}`));
      entry.append(text('div', `Erster ADVERT-Empfang: ${new Date(node.first_seen * 1000).toLocaleString()} · Letzter ADVERT-Empfang: ${new Date(node.last_seen * 1000).toLocaleString()}`));
      nodesResults.append(entry);
    }
    nodesAfter = result.next_after;
    nodesMore.hidden = nodesAfter == null;
    nodesStatus.textContent = nodesResults.children.length
      ? `${nodesResults.children.length} Nodes geladen${nodesAfter == null ? ' · Ende der Treffer' : ''}`
      : 'Keine passenden Nodes gespeichert.';
  } catch (error) {
    nodesStatus.textContent = `Nodes konnten nicht geladen werden: ${error.message}. Bitte erneut versuchen.`;
  } finally {
    nodesLoading = false;
    nodesMore.disabled = false;
    nodesForm.querySelector('button').disabled = false;
  }
}
nodesForm.onsubmit = event => { event.preventDefault(); searchNodes(); };
nodesMore.onclick = () => searchNodes(true);

const channelsForm = document.getElementById('channels-search');
const channelsSelect = document.getElementById('channels-select');
const channelsResults = document.getElementById('channels-results');
const channelsStatus = document.getElementById('channels-status');
const channelsMore = document.getElementById('channels-more');
let channelsReady = false, channelsLoading = false, channelsBefore = null;
const channelGroups = new Map(), channelReceptionIds = new Set();
function appendChannelReception(item) {
  if (channelReceptionIds.has(item.id)) return;
  channelReceptionIds.add(item.id);
  const p = item.packet;
  // Match the live view: group receptions by packet hash; missing hashes stay separate.
  const key = p.observer_hash ? `hash:${p.observer_hash.toUpperCase()}` : `id:${item.id}`;
  let group = channelGroups.get(key);
  if (!group) {
    const entry = text('article', '', 'reception');
    entry.append(text('div', new Date(p.received_at).toLocaleString(), 'muted'));
    entry.append(text('div', p.decoded.group_text ?? p.decoded.group_text_status ?? 'Nicht entschlüsselbar', 'channel-message'));
    const scopes = text('div', '', 'muted');
    entry.append(scopes);
    const details = text('details', '');
    const summary = text('summary', '');
    details.append(summary);
    entry.append(details);
    channelsResults.append(entry);
    group = {details, summary, scopes, scopeLabels: new Set(), count: 0};
    channelGroups.set(key, group);
  }
  group.count += 1;
  group.scopeLabels.add(scopeLabel(p.decoded));
  group.scopes.textContent = `Scope: ${[...group.scopeLabels].join(' · ')}`;
  group.summary.textContent = group.count === 1
    ? '1 Empfang · Details'
    : `${group.count} Empfänge · Details`;
  const reception = text('div', '', 'reception');
  reception.append(text('div', new Date(p.received_at).toLocaleString(), 'muted'));
  reception.append(text('div', `Observer: ${observerLabel(p)}`));
  reception.append(text('div', `Scope: ${scopeLabel(p.decoded)}`));
  reception.append(text('div', `Last Hop: ${p.last_hop} · Pfad: ${p.path} · RSSI: ${measurement(p.rssi, 'dBm')} · SNR: ${measurement(p.snr, 'dB')} · Hash: ${p.observer_hash || '—'}`));
  group.details.append(reception);
}
async function loadChannelMessages(more = false) {
  if (channelsLoading) return;
  channelsLoading = true;
  channelsSelect.disabled = true;
  channelsMore.disabled = true;
  channelsForm.querySelector('button').disabled = true;
  channelsStatus.textContent = 'Nachrichten werden geladen …';
  try {
    if (!channelsReady) {
      const response = await fetch('/api/channels');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result = await response.json();
      channelsSelect.replaceChildren();
      for (const name of result.channels) {
        const option = text('option', name);
        option.value = name;
        channelsSelect.append(option);
      }
      channelsReady = true;
    }
    if (!more) {
      channelsBefore = null;
      channelsMore.hidden = true;
      channelsResults.replaceChildren();
      channelGroups.clear();
      channelReceptionIds.clear();
    }
    if (!channelsSelect.value) {
      channelsStatus.textContent = 'Keine Kanäle konfiguriert.';
      return;
    }
    const query = new URLSearchParams({kind: 'GRP_TXT', channel: channelsSelect.value});
    if (channelsBefore != null) query.set('before', channelsBefore);
    const response = await fetch(`/api/archive?${query}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    for (const item of result.items) appendChannelReception(item);
    channelsBefore = result.next_before;
    channelsMore.hidden = channelsBefore == null;
    channelsStatus.textContent = channelsResults.children.length
      ? `${channelGroups.size} Nachrichten · ${channelReceptionIds.size} Empfänge in ${channelsSelect.value} geladen${channelsBefore == null ? ' · Ende der Treffer' : ''}`
      : `Noch keine Nachrichten in ${channelsSelect.value} gespeichert.`;
  } catch (error) {
    channelsStatus.textContent = `Nachrichten konnten nicht geladen werden: ${error.message}. Bitte „Aktualisieren“ versuchen.`;
  } finally {
    channelsLoading = false;
    channelsSelect.disabled = !channelsReady || !channelsSelect.options.length;
    channelsMore.disabled = false;
    channelsForm.querySelector('button').disabled = false;
  }
}
channelsForm.onsubmit = event => { event.preventDefault(); loadChannelMessages(); };
channelsSelect.onchange = () => loadChannelMessages();
channelsMore.onclick = () => loadChannelMessages(true);
