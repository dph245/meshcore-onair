let nodeMap, mapLoading = false, mapFitted = false;
const mapMarkers = new Map();
const mapTypes = {1: ['Companion', 'companion', '●'], 2: ['Repeater', 'repeater', '●'],
  3: ['Room', 'room', '■']};

function fitMapNodes() {
  if (!nodeMap || !mapMarkers.size) return;
  nodeMap.fitBounds(L.latLngBounds([...mapMarkers.values()].map(view => view.marker.getLatLng())),
    {padding: [45, 45], maxZoom: 14});
  mapFitted = true;
}

function showNodeMap() {
  if (!window.L) {
    document.getElementById('map-status').textContent = 'Kartenbibliothek konnte nicht geladen werden. Bitte Seite neu laden.';
    return;
  }
  if (!nodeMap) {
    nodeMap = L.map('node-map').setView([51, 10], 6);
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
      const [type, style, symbol] = mapTypes[item.node_type] || ['Weiterer Node', 'other', '◆'];
      const label = `${item.name || 'Ohne Namen'} [${item.public_key.slice(0, 6)}]`;
      const icon = text('div', '', 'map-marker-content');
      icon.append(text('span', symbol, `map-dot ${style}`));
      if (item.node_type === 2) icon.append(text('span', label, 'map-repeater-label'));
      const markerIcon = L.divIcon({html: icon, className: 'map-marker', iconSize: [20, 20], iconAnchor: [10, 10]});
      if (!view) {
        const marker = L.marker([item.latitude, item.longitude], {icon: markerIcon,
          title: `${type}: ${label}`, alt: `${type}: ${label}`, riseOnHover: true}).addTo(nodeMap);
        marker.bindTooltip(mapNodeInfo(item), {direction: 'top', offset: [0, -10]});
        marker.bindPopup(mapNodeInfo(item));
        view = {marker};
        mapMarkers.set(item.public_key, view);
      } else {
        view.marker.setLatLng([item.latitude, item.longitude]).setIcon(markerIcon);
        view.marker.getElement().title = `${type}: ${label}`;
        view.marker.setTooltipContent(mapNodeInfo(item)).setPopupContent(mapNodeInfo(item));
      }
      view.signature = signature;
    }
    for (const [key, view] of mapMarkers) {
      if (!keys.has(key)) { view.marker.remove(); mapMarkers.delete(key); }
    }
    if (!mapFitted) fitMapNodes();
    message.textContent = `${mapMarkers.size} Nodes auf der Karte · ${result.without_position} ohne bekannte Position · Stand: ${new Date().toLocaleTimeString('de-DE')}`;
  } catch (error) {
    message.textContent = `Nodes konnten nicht geladen werden: ${error.message}. Erneuter Versuch in 5 Sekunden; vorhandene Marker bleiben stehen.`;
  } finally {
    mapLoading = false;
  }
}

document.getElementById('map-fit').addEventListener('click', fitMapNodes);
setInterval(() => {
  if (!document.getElementById('panel-map').hidden) loadMapNodes();
}, 5000);
