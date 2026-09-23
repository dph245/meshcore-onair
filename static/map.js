let nodeMap, mapLoading = false;
let neighborLayer, neighborLinks = [], neighborSignature;
let neighborPage = 0;
let neighborSortKey = 'count', neighborSortDirection = -1;
const neighborColumns = [
  ['source', 'Repeater A', link => neighborLabel(link.source)],
  ['target', 'Nachbar B', link => neighborLabel(link.target)],
  ['forward_count', 'A → B', link => link.forward_count],
  ['reverse_count', 'B → A', link => link.reverse_count],
  ['direction', 'Beobachtung', link => neighborDirection(link)],
  ['count', 'Empfänge gesamt', link => link.count],
  ['last_seen', 'Zuletzt beobachtet', link => link.last_seen],
  ['distance_km', 'Entfernung (Luftlinie)', link => link.distance_km],
];
let neighborsLoading = false;
let selectedMapRepeater = null;
const mapMarkers = new Map();
const mapTypes = {1: ['Companion', 'companion'], 2: ['Repeater', 'repeater'],
  3: ['RoomServer', 'room']};
const mapSymbolPaths = {
  companion: '<path d="M8 10V2m8 8V7"/><rect x="6" y="10" width="13" height="19" rx="3"/><path d="M10 15h5m-5 4h5m-5 4h5"/>',
  repeater: '<circle cx="16" cy="9" r="2"/><path d="M16 11L9 29m7-18 7 18M12 23h8m-10 6h12M11 5a6 6 0 0 0 0 8m10-8a6 6 0 0 1 0 8M7 2a10 10 0 0 0 0 14M25 2a10 10 0 0 1 0 14"/>',
  room: '<circle cx="16" cy="9" r="3"/><circle cx="6" cy="12" r="2.5"/><circle cx="26" cy="12" r="2.5"/><path d="M11 28v-8a5 5 0 0 1 10 0v8ZM3 26v-6a3 3 0 0 1 6 0v6Zm20 0v-6a3 3 0 0 1 6 0v6Z"/>',
  other: '<path d="m16 4 12 12-12 12L4 16Z"/><circle cx="16" cy="16" r="2"/>'
};

function mapNodeSymbol(style) {
  const badge = document.createElement('span');
  badge.className = `map-node-symbol ${style}`;
  badge.setAttribute('aria-hidden', 'true');
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 32 32');
  svg.setAttribute('focusable', 'false');
  // Only fixed, local SVG paths are used here, never node data.
  svg.innerHTML = mapSymbolPaths[style] || mapSymbolPaths.other;
  badge.append(svg);
  return badge;
}

// Recompute pixel spacing at every zoom; stored coordinates remain untouched.
function layoutMapNodes() {
  if (!nodeMap) return;
  const positions = new Map();
  for (const [key, view] of mapMarkers) {
    const positionKey = JSON.stringify(view.position);
    if (!positions.has(positionKey)) positions.set(positionKey, []);
    positions.get(positionKey).push({key, view});
  }
  for (const group of positions.values()) {
    group.sort((a, b) => a.key.localeCompare(b.key));
    const origin = group[0].view.position;
    const center = nodeMap.project(origin);
    group.forEach(({view}, index) => {
      const offset = group.length > 1 ? L.point(40, (index - (group.length - 1) / 2) * 46) : L.point(0, 0);
      const displayed = group.length > 1 ? nodeMap.unproject(center.add(offset)) : origin;
      view.marker.setLatLng(displayed);
      if (group.length > 1) {
        if (!view.line) {
          view.line = L.polyline([origin, displayed], {
            className: 'map-position-link', weight: 1.5, opacity: 0.8, interactive: false
          }).addTo(nodeMap);
        } else view.line.setLatLngs([origin, displayed]);
      } else if (view.line) {
        view.line.remove();
        view.line = null;
      }
    });
  }
  drawMapNeighbors();
}

function neighborLabel(node) {
  return `${node.name === node.id ? node.id : `${node.name} [${node.id.slice(0, 6)}]`}${node.ambiguous ? ' (mehrdeutig)' : node.resolved ? '' : ' (unaufgelöst)'}`;
}

function neighborDirection(link) {
  if (link.forward_count && link.reverse_count) return 'Beide Richtungen beobachtet';
  return `Nur ${link.forward_count ? 'A → B' : 'B → A'} beobachtet`;
}

function neighborDistance(link) {
  return Number.isFinite(link.distance_km)
    ? `${link.distance_km.toLocaleString('de-DE', {minimumFractionDigits: 1, maximumFractionDigits: 1})} km`
    : '—';
}

function drawNeighborArrow(from, to, fraction, color) {
  const a = nodeMap.project(from), b = nodeMap.project(to);
  const dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy);
  if (length < 24) return;
  const ux = dx / length, uy = dy / length;
  const x = a.x + dx * fraction, y = a.y + dy * fraction;
  const points = [[x - ux * 9 - uy * 5, y - uy * 9 + ux * 5], [x, y],
    [x - ux * 9 + uy * 5, y - uy * 9 - ux * 5]].map(point => nodeMap.unproject(point));
  L.polyline(points, {color, weight: 3, opacity: 1, interactive: false}).addTo(neighborLayer);
}

function selectMapRepeater(identity) {
  selectedMapRepeater = identity;
  drawMapNeighbors();
}

function drawMapNeighbors() {
  if (!nodeMap) return;
  if (selectedMapRepeater && !mapMarkers.has(selectedMapRepeater)) selectedMapRepeater = null;
  const showLinks = document.getElementById('map-neighbors-toggle').checked;
  const focused = showLinks && selectedMapRepeater !== null;
  const visibleNodes = new Set(focused ? [selectedMapRepeater] : []);
  nodeMap.getContainer().classList.toggle('map-neighbor-focus', focused);
  document.getElementById('map-neighbors-reset').hidden = !selectedMapRepeater;
  if (!neighborLayer) neighborLayer = L.layerGroup().addTo(nodeMap);
  neighborLayer.clearLayers();
  let mapped = 0;
  for (const link of neighborLinks) {
    if (selectedMapRepeater && link.source.id !== selectedMapRepeater && link.target.id !== selectedMapRepeater) continue;
    const a = mapMarkers.get(link.source.id), b = mapMarkers.get(link.target.id);
    if (!link.source.resolved || !link.target.resolved || !a || !b) continue;
    mapped++;
    if (!showLinks) continue;
    visibleNodes.add(link.source.id);
    visibleNodes.add(link.target.id);
    const label = `A: ${neighborLabel(link.source)} · B: ${neighborLabel(link.target)} · A → B: ${link.forward_count} · B → A: ${link.reverse_count} · Luftlinie: ${neighborDistance(link)}`;
    const info = text('div', label);
    info.append(text('div', `${neighborDirection(link)} · ${link.count} Empfänge insgesamt`));
    info.append(text('div', `Zuletzt beobachtet: ${new Date(link.last_seen * 1000).toLocaleString('de-DE')}`));
    const color = link.forward_count && link.reverse_count ? '#3388ff' : '#d97706';
    const start = a.marker.getLatLng(), end = b.marker.getLatLng();
    const line = L.polyline([start, end], {
      color, weight: Math.min(8, 1 + Math.log2(1 + link.count)), opacity: 0.65,
      bubblingMouseEvents: false
    }).bindTooltip(text('span', label)).addTo(neighborLayer);
    line.on('click', event => {
      line.closeTooltip();
      // Keep the clicked values as a snapshot, independent of redrawn layers.
      // Leaflet closes this popup on another map/marker click as usual.
      L.popup().setLatLng(event.latlng).setContent(info).openOn(nodeMap);
    });
    if (link.forward_count) drawNeighborArrow(start, end, 0.65, color);
    if (link.reverse_count) drawNeighborArrow(end, start, 0.65, color);
  }
  for (const [key, view] of mapMarkers) {
    const visible = !focused || visibleNodes.has(key);
    // Removing the layer also removes its label, tooltip and popup.
    for (const layer of [view.marker, view.line]) {
      if (!layer) continue;
      if (visible && !nodeMap.hasLayer(layer)) layer.addTo(nodeMap);
      else if (!visible && nodeMap.hasLayer(layer)) layer.remove();
    }
  }
  const selected = mapMarkers.get(selectedMapRepeater);
  document.getElementById('map-neighbors-status').textContent = selected
    ? `Nachbarn von ${selected.label || selectedMapRepeater} · ${mapped} Verbindungen auf der Karte zuordenbar · Klick auf die freie Karte hebt den Filter auf`
    : `${neighborLinks.length} beobachtete Verbindungen · ${mapped} auf der Karte zuordenbar · Repeater anklicken, um seine Nachbarn zu sehen`;
}

function renderMapNeighbors(result) {
  const signature = JSON.stringify(result.items);
  if (signature === neighborSignature) return;
  neighborSignature = signature;
  neighborLinks = result.items;
  renderNeighborTable();
}

async function loadNeighbors() {
  if (neighborsLoading || paused) return;
  neighborsLoading = true;
  const message = document.getElementById('neighbors-status');
  try {
    const response = await fetch('/api/repeater-neighbors');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    if (paused) return;
    renderMapNeighbors(result);
    drawMapNeighbors();
    const oneWay = neighborLinks.filter(link => !link.forward_count || !link.reverse_count).length;
    message.textContent = `${neighborLinks.length} beobachtete Verbindungen · ${oneWay} nur in einer Richtung beobachtet · Stand: ${new Date().toLocaleTimeString('de-DE')}`;
  } catch (error) {
    message.textContent = `Verbindungen konnten nicht geladen werden: ${error.message}. Erneuter Versuch in 30 Sekunden; bisherige Daten bleiben stehen.`;
    document.getElementById('map-neighbors-status').textContent = message.textContent;
  } finally {
    neighborsLoading = false;
  }
}

function renderNeighborTable() {
  const query = document.getElementById('map-neighbors-search').value.trim().toLocaleLowerCase();
  const onlyOneWay = document.getElementById('neighbors-one-way').checked;
  const links = neighborLinks.filter(link => (!onlyOneWay || !link.forward_count || !link.reverse_count) && [link.source, link.target].some(node =>
    `${node.name} ${node.id}`.toLocaleLowerCase().includes(query)));
  const sortValue = neighborColumns.find(([key]) => key === neighborSortKey)[2];
  links.sort((a, b) => {
    const left = sortValue(a), right = sortValue(b);
    if (left == null || right == null) return (left == null) - (right == null);
    const order = typeof left === 'number' ? left - right
      : left.localeCompare(right, 'de', {numeric: true, sensitivity: 'base'});
    return order * neighborSortDirection || a.source.id.localeCompare(b.source.id)
      || a.target.id.localeCompare(b.target.id);
  });
  const pages = Math.max(1, Math.ceil(links.length / 100));
  neighborPage = Math.max(0, Math.min(neighborPage, pages - 1));
  document.getElementById('map-neighbors-page').textContent = `Seite ${neighborPage + 1} / ${pages} · ${links.length} Verbindungen`;
  document.getElementById('map-neighbors-prev').disabled = neighborPage === 0;
  document.getElementById('map-neighbors-next').disabled = neighborPage === pages - 1;
  const table = text('table', '');
  const head = text('tr', '');
  for (const [key, label] of neighborColumns) {
    const active = key === neighborSortKey;
    const cell = text('th', '');
    cell.scope = 'col';
    cell.setAttribute('aria-sort', active ? (neighborSortDirection === 1 ? 'ascending' : 'descending') : 'none');
    const button = text('button', `${label} ${active ? (neighborSortDirection === 1 ? '↑' : '↓') : '↕'}`);
    button.type = 'button';
    button.id = `neighbors-sort-${key}`;
    button.addEventListener('click', () => {
      neighborSortDirection = active ? -neighborSortDirection : (['source', 'target', 'direction'].includes(key) ? 1 : -1);
      neighborSortKey = key;
      neighborPage = 0;
      renderNeighborTable();
    });
    cell.append(button);
    head.append(cell);
  }
  table.append(head);
  for (const link of links.slice(neighborPage * 100, (neighborPage + 1) * 100)) {
    const row = text('tr', '');
    for (const value of [neighborLabel(link.source), neighborLabel(link.target), link.forward_count,
      link.reverse_count, neighborDirection(link), link.count,
      new Date(link.last_seen * 1000).toLocaleString('de-DE'), neighborDistance(link)]) row.append(text('td', value));
    table.append(row);
  }
  const focusedSort = document.activeElement?.id;
  document.getElementById('map-neighbors-list').replaceChildren(table);
  if (focusedSort?.startsWith('neighbors-sort-')) document.getElementById(focusedSort)?.focus();
}

function fitMapNodes() {
  if (!nodeMap || !mapMarkers.size) return;
  selectMapRepeater(null);
  nodeMap.fitBounds(L.latLngBounds([...mapMarkers.values()].map(view => view.marker.getLatLng())),
    {padding: [45, 45], maxZoom: 14});
}

function savedMapView() {
  try {
    const view = JSON.parse(localStorage.getItem('onair-map-view'));
    if (Array.isArray(view?.center) && view.center.length === 2 &&
        view.center.every(Number.isFinite) && Math.abs(view.center[0]) <= 90 &&
        Number.isInteger(view.zoom) && view.zoom >= 0 && view.zoom <= 19) return view;
  } catch { /* Use the default view when storage is unavailable or invalid. */ }
  return {center: [52.163, 10.54], zoom: 10};
}

function saveMapView() {
  const center = nodeMap.getCenter();
  try {
    localStorage.setItem('onair-map-view', JSON.stringify({
      center: [center.lat, center.lng], zoom: nodeMap.getZoom()
    }));
  } catch { /* The map also works when browser storage is unavailable. */ }
}

function updateMapLabels() {
  const zoom = nodeMap.getZoom();
  const container = nodeMap.getContainer();
  container.classList.toggle('map-labels-small', zoom >= 10 && zoom < 12);
  container.classList.toggle('map-labels-hidden', zoom < 10);
}

function showNodeMap() {
  if (!window.L) {
    document.getElementById('map-status').textContent = 'Kartenbibliothek konnte nicht geladen werden. Bitte Seite neu laden.';
    return;
  }
  if (!nodeMap) {
    const view = savedMapView();
    nodeMap = L.map('node-map').setView(view.center, view.zoom);
    nodeMap.on('click', () => selectMapRepeater(null));
    // Flex layout also changes when headers or status messages wrap.
    const resizeObserver = new ResizeObserver(() => {
      if (!document.getElementById('panel-map').hidden) {
        nodeMap.invalidateSize({pan: false});
      }
    });
    resizeObserver.observe(nodeMap.getContainer());
    nodeMap.on('zoomend', layoutMapNodes);
    nodeMap.on('zoomend', updateMapLabels);
    updateMapLabels();
    nodeMap.on('moveend', saveMapView);
    const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(nodeMap);
    let tileErrors = false;
    tiles.on('loading', () => { tileErrors = false; });
    tiles.on('tileerror', () => {
      tileErrors = true;
      document.getElementById('map-tiles-status').hidden = false;
    });
    tiles.on('load', () => { document.getElementById('map-tiles-status').hidden = !tileErrors; });
  }
  nodeMap.invalidateSize();
  loadMapNodes();
  loadNeighbors();
}

function mapNodeInfo(item) {
  const info = text('div', '', 'map-node-info');
  const type = mapTypes[item.node_type]?.[0] || (item.node_type === 4 ? 'Sensor' : 'Unbekannt');
  info.append(text('strong', `${item.name || 'Ohne Namen'} [${item.public_key.slice(0, 6)}]`));
  for (const value of [type, `Public Key: ${item.public_key}`,
    `Position: ${item.latitude.toFixed(6)}, ${item.longitude.toFixed(6)}`,
    `Position vom: ${new Date(item.position_time * 1000).toLocaleString('de-DE')}`,
    `Zuerst empfangen: ${new Date(item.first_seen * 1000).toLocaleString('de-DE')}`,
    `Zuletzt empfangen: ${new Date(item.last_seen * 1000).toLocaleString('de-DE')}`]) {
    info.append(text('div', value));
  }
  return info;
}

async function loadMapNodes() {
  if (!nodeMap || mapLoading || paused) return;
  mapLoading = true;
  const message = document.getElementById('map-status');
  try {
    const response = await fetch('/api/map-nodes');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    if (paused) return;
    const keys = new Set();
    for (const item of result.items) {
      keys.add(item.public_key);
      let view = mapMarkers.get(item.public_key);
      const signature = JSON.stringify(item);
      if (view?.signature === signature) continue;
      const [type, style] = mapTypes[item.node_type] || ['Weiterer Node', 'other'];
      const label = `${item.name || 'Ohne Namen'} [${item.public_key.slice(0, 6)}]`;
      const icon = text('div', '', 'map-marker-content');
      icon.append(mapNodeSymbol(style));
      if (item.node_type === 2) {
        const nodeLabel = text('span', '', 'map-repeater-label');
        nodeLabel.append(text('span', item.name || 'Ohne Namen'),
          text('span', `[${item.public_key.slice(0, 6)}]`));
        icon.append(nodeLabel);
      }
      const markerIcon = L.divIcon({html: icon, className: 'map-marker', iconSize: [36, 36], iconAnchor: [18, 18], popupAnchor: [0, -18]});
      if (!view) {
        const marker = L.marker([item.latitude, item.longitude], {icon: markerIcon,
          title: `${type}: ${label}`, alt: `${type}: ${label}`, riseOnHover: true,
          bubblingMouseEvents: false}).addTo(nodeMap);
        marker.bindTooltip(mapNodeInfo(item), {direction: 'top', offset: [0, -18]});
        marker.bindPopup(mapNodeInfo(item));
        view = {marker};
        mapMarkers.set(item.public_key, view);
        marker.on('click', () => {
          if (view.nodeType === 2) selectMapRepeater(item.public_key);
        });
      } else {
        view.marker.setLatLng([item.latitude, item.longitude]).setIcon(markerIcon);
        view.marker.options.title = `${type}: ${label}`;
        const markerElement = view.marker.getElement();
        if (markerElement) markerElement.title = `${type}: ${label}`;
        view.marker.setTooltipContent(mapNodeInfo(item)).setPopupContent(mapNodeInfo(item));
      }
      view.position = [item.latitude, item.longitude];
      view.label = label;
      view.nodeType = item.node_type;
      view.signature = signature;
    }
    for (const [key, view] of mapMarkers) {
      if (!keys.has(key)) { view.marker.remove(); view.line?.remove(); mapMarkers.delete(key); }
    }
    layoutMapNodes();
    message.textContent = `${mapMarkers.size} Nodes auf der Karte · ${result.without_position} ohne bekannte Position · ${result.inactive} seit mindestens 4 Wochen nicht gehört · Stand: ${new Date().toLocaleTimeString('de-DE')}`;
  } catch (error) {
    message.textContent = `Nodes konnten nicht geladen werden: ${error.message}. Erneuter Versuch in 5 Sekunden; vorhandene Marker bleiben stehen.`;
  } finally {
    mapLoading = false;
  }
}

for (const legend of document.querySelectorAll('.map-legend[data-node-style]')) {
  legend.prepend(mapNodeSymbol(legend.dataset.nodeStyle));
}
document.getElementById('map-fit').addEventListener('click', fitMapNodes);
document.getElementById('map-neighbors-reset').addEventListener('click', () => selectMapRepeater(null));
const neighborsToggle = document.getElementById('map-neighbors-toggle');
neighborsToggle.checked = true;
try {
  neighborsToggle.checked = localStorage.getItem('onair-map-neighbors') !== 'false';
} catch { /* Default to visible when browser storage is unavailable. */ }
neighborsToggle.addEventListener('change', () => {
  try {
    localStorage.setItem('onair-map-neighbors', String(neighborsToggle.checked));
  } catch { /* The toggle still works without persistent storage. */ }
  drawMapNeighbors();
});
document.getElementById('map-neighbors-search').addEventListener('input', () => { neighborPage = 0; renderNeighborTable(); });
document.getElementById('neighbors-one-way').addEventListener('change', () => { neighborPage = 0; renderNeighborTable(); });
document.getElementById('map-neighbors-prev').addEventListener('click', () => { neighborPage--; renderNeighborTable(); });
document.getElementById('map-neighbors-next').addEventListener('click', () => { neighborPage++; renderNeighborTable(); });
setInterval(() => {
  if (!document.getElementById('panel-map').hidden) loadMapNodes();
}, 5000);
setInterval(() => {
  if (!document.getElementById('panel-map').hidden || !document.getElementById('panel-neighbors').hidden) loadNeighbors();
}, 30000);
