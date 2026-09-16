let nodeMap, mapLoading = false;
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
}

function fitMapNodes() {
  if (!nodeMap || !mapMarkers.size) return;
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
          title: `${type}: ${label}`, alt: `${type}: ${label}`, riseOnHover: true}).addTo(nodeMap);
        marker.bindTooltip(mapNodeInfo(item), {direction: 'top', offset: [0, -18]});
        marker.bindPopup(mapNodeInfo(item));
        view = {marker};
        mapMarkers.set(item.public_key, view);
      } else {
        view.marker.setLatLng([item.latitude, item.longitude]).setIcon(markerIcon);
        view.marker.getElement().title = `${type}: ${label}`;
        view.marker.setTooltipContent(mapNodeInfo(item)).setPopupContent(mapNodeInfo(item));
      }
      view.position = [item.latitude, item.longitude];
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
setInterval(() => {
  if (!document.getElementById('panel-map').hidden) loadMapNodes();
}, 5000);
