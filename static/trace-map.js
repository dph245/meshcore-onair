// SNR[i] was measured at route[i], on reception from route[i - 1].
// Repeated route entries preserve return measurements; min/max are NOT directions.
function traceMapSnrSegments(hops) {
  const sections = new Map();
  const valid = hop => hop && !hop.ambiguous && hop.position &&
    Number.isFinite(hop.position.latitude) && Number.isFinite(hop.position.longitude);
  const identity = hop => hop.public_key || hop.hash;
  for (let i = 1; i < hops.length; i++) {
    const from = hops[i - 1], to = hops[i];
    if (!valid(from) || !valid(to) || !identity(from) || !identity(to) ||
        identity(from) === identity(to) || !Number.isFinite(from.snr_min) ||
        !Number.isFinite(to.snr_min) || (to.snr_max != null && to.snr_max !== to.snr_min)) continue;
    // Include historical coordinates: never combine geographically different sections.
    const endpoint = hop => JSON.stringify([identity(hop), hop.position.latitude, hop.position.longitude]);
    const a = endpoint(from), b = endpoint(to), key = JSON.stringify([a, b].sort());
    if (!sections.has(key)) sections.set(key, {from, to, first: a, samples: []});
    const section = sections.get(key);
    section.samples.push({snr: to.snr_min, forward: section.first === a, hop: i + 1});
  }
  return [...sections.values()];
}

function traceMapSnrText(value) {
  const number = Math.abs(value).toLocaleString('de-DE', {minimumFractionDigits: 1, maximumFractionDigits: 2});
  return `${value < 0 ? '−' : '+'}${number} dB`;
}

// Historical observations use the existing Leaflet instance; no fetch on map movement.
(() => {
  let mode = 'paths', layer, cursor, query, version = 0, controller;
  const selected = new Map();
  let activeGroup, receptionPage = 0;
  const el = id => document.getElementById(`map-trace-${id}`);
  window.traceMapActive = () => mode === 'traces';
  const position = hop => hop.position && [hop.position.latitude, hop.position.longitude];
  function draw() {
    if (!nodeMap) return;
    if (!layer) layer = L.layerGroup().addTo(nodeMap);
    layer.clearLayers();
    if (mode !== 'traces') return;
    const labels = [];
    [...selected.values()].forEach((item, index) => {
      const color = ['#3388ff', '#d97706'][index];
      item.hops.forEach((hop, i) => {
        const point = position(hop);
        if (!point) return;
        L.circleMarker(point, {color, radius: 7}).bindTooltip(text('span',
          `#${item.id} · Hop ${i + 1}: ${traceNode(hop)} · SNR ${hop.snr_min ?? 'unbekannt'}`)).addTo(layer);
        const previous = i > 0 && position(item.hops[i - 1]);
        if (previous && hop.snr_min != null && item.hops[i - 1].snr_min != null) {
          L.polyline([previous, point], {color, weight: 3}).addTo(layer);
          drawNeighborArrow(previous, point, .6, color, layer);
        }
      });
      for (const section of traceMapSnrSegments(item.hops)) labels.push({section, item, color, index});
    });
    drawLabels(labels);
  }
  function drawLabels(labels) {
    const occupied = [], size = nodeMap.getSize();
    for (const {section, item, color, index} of labels) {
      const from = position(section.from), to = position(section.to);
      const a = nodeMap.latLngToContainerPoint(from), b = nodeMap.latLngToContainerPoint(to);
      const midpoint = L.point((a.x + b.x) / 2, (a.y + b.y) / 2);
      const box = text('div', '', 'trace-snr-label');
      box.style.borderColor = color;
      box.dataset.traceId = item.id;
      const endpoints = `${section.from.hash} → ${section.to.hash}`;
      box.append(text('span', `#${item.id} · ${endpoints}`, 'trace-snr-heading'));
      // Chronological first traversal is above its return; retain every later traversal too.
      for (const sample of section.samples) {
        const row = text('span', `${sample.forward ? '→' : '←'} ${traceMapSnrText(sample.snr)}`, 'trace-snr-value');
        row.setAttribute('aria-label', `${sample.forward ? section.from.hash + ' → ' + section.to.hash : section.to.hash + ' → ' + section.from.hash}: ${traceMapSnrText(sample.snr)}, Hop ${sample.hop}`);
        box.append(row);
      }
      const marker = L.marker(nodeMap.containerPointToLatLng(midpoint), {
        icon: L.divIcon({html: box, className: 'trace-snr-icon', iconSize: [0, 0], iconAnchor: [0, 0]}),
        interactive: false, keyboard: false, zIndexOffset: 1000
      }).addTo(layer);
      const width = box.offsetWidth, height = box.offsetHeight;
      // Lay out visible sections only. Offscreen labels stay with their own section.
      if (midpoint.x < 0 || midpoint.y < 0 || midpoint.x > size.x || midpoint.y > size.y) continue;
      const clamp = (v, low, high) => Math.max(low, Math.min(high, v));
      let best, bestScore = Infinity;
      for (let ring = 0; ring <= 8; ring++) {
        for (const side of [index ? -1 : 1, index ? 1 : -1]) {
          for (const horizontal of [0, -1, 1]) {
            const center = L.point(
              clamp(midpoint.x + horizontal * ring * 28, width / 2 + 4, size.x - width / 2 - 4),
              clamp(midpoint.y + side * (18 + ring * 22), height / 2 + 4, size.y - height / 2 - 4));
            const rect = {x: center.x - width / 2, y: center.y - height / 2, width, height};
            const overlap = occupied.reduce((sum, r) => sum + Math.max(0, Math.min(rect.x + width + 4, r.x + r.width) - Math.max(rect.x - 4, r.x)) *
              Math.max(0, Math.min(rect.y + height + 4, r.y + r.height) - Math.max(rect.y - 4, r.y)), 0);
            const score = overlap * 1000 + center.distanceTo(midpoint);
            if (score < bestScore) { bestScore = score; best = {center, rect, overlap}; }
          }
        }
        if (best.overlap === 0) break;
      }
      occupied.push(best.rect);
      const displayed = nodeMap.containerPointToLatLng(best.center);
      marker.setLatLng(displayed);
      // A subtle leader preserves the association when collision avoidance shifts a label.
      L.polyline([nodeMap.containerPointToLatLng(midpoint), displayed], {
        color, weight: 1, opacity: .65, interactive: false, className: 'trace-snr-leader'
      }).addTo(layer);
    }
  }
  function details() {
    el('detail').replaceChildren(...[...selected.values()].map((item, index) => {
      const card = text('section', '', 'trace-map-card');
      card.append(text('h3', `${index ? 'Orange' : 'Blau'} · #${item.id} · ${new Date(item.first_seen * 1000).toLocaleString('de-DE')}`),
        text('p', `Quelle: unbekannt · Ziel: nicht gesichert · ${item.hops.length} Routen-Hops · ${item.observed_hops} mit SNR`));
      const list = text('ol', '');
      item.hops.forEach(hop => list.append(text('li', `${traceNode(hop)} · ${hop.position ? 'Position aus früherem ADVERT' : 'Historische Position unbekannt'} · SNR: ${hop.snr_min == null ? 'nicht mitgehört' : hop.snr_min + ' dB'}`)));
      const remove = text('button', 'Auswahl entfernen');
      remove.type = 'button';
      remove.addEventListener('click', () => { selected.delete(item.id); details();
        for (const checkbox of el('list').querySelectorAll('input')) checkbox.checked = selected.has(Number(checkbox.dataset.id));
      });
      card.append(list, remove);
      return card;
    }));
    if (activeGroup) renderReceptions();
    draw();
  }
  async function select(item, checkbox) {
    if (!checkbox.checked) { selected.delete(item.id); details(); return; }
    if (selected.size >= 2) { checkbox.checked = false; el('status').textContent = 'Zuerst eine der zwei Beobachtungen abwählen.'; return; }
    const current = version;
    checkbox.disabled = true;
    try {
      const response = await fetch(`/api/map-traces/${item.id}`, {signal: controller?.signal});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result = await response.json();
      if (current !== version) return;
      if (selected.size >= 2) { checkbox.checked = false; return; }
      selected.set(item.id, result); details();
      const points = [...selected.values()].flatMap(v => v.hops.map(position).filter(Boolean));
      if (points.length) nodeMap.fitBounds(L.latLngBounds(points), {padding: [35, 35], maxZoom: 13});
    } catch (error) {
      if (current === version && error.name !== 'AbortError') { checkbox.checked = false; el('status').textContent = `Details nicht verfügbar: ${error.message}`; }
    } finally { checkbox.disabled = false; }
  }

  function groupLabel(item) {
    const missing = item.hops.filter(h => !h.public_key).length;
    const ambiguous = item.hops.filter(h => h.ambiguous).length;
    return `${new Date(item.first_seen * 1000).toLocaleString('de-DE')} · Tag ${item.tag} · ${item.hops.map(traceNode).join(' → ') || 'Leere Route'} · ${item.receptions} Empfänge · ${item.observers.length} Observer · Beste Einzelabdeckung ${item.observed_hops}/${item.hops.length} SNR · Gruppenminimum ${item.weakest_snr == null ? 'unbekannt' : item.weakest_snr + ' dB'} · ${missing} unaufgelöste Hops (davon ${ambiguous} mehrdeutig) · ${item.scope} · Auth ${item.auth_code} · Flags ${item.flags}`;
  }
  function renderReceptions() {
    const container = el('receptions');
    container.replaceChildren();
    if (!activeGroup) return;
    container.append(text('h3', 'Einzelne Empfangspakete'));
    const table = text('table', ''), head = text('tr', '');
    for (const title of ['Empfang / Zeit', 'Observer', 'SNR', 'Karte (max. 2)']) head.append(text('th', title));
    table.append(head);
    for (const packet of activeGroup.packets.slice(receptionPage * 50, (receptionPage + 1) * 50)) {
      const row = text('tr', '');
      row.append(text('td', `#${packet.id} · ${new Date(packet.received * 1000).toLocaleString('de-DE')}`),
        text('td', `${packet.observer}${packet.observer_id ? ' [' + packet.observer_id + ']' : ''}`),
        text('td', `${packet.observed_hops}/${activeGroup.hops.length} · Min. ${packet.weakest_snr ?? '—'} dB`));
      const action = text('td', ''), label = text('label', '');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox'; checkbox.dataset.id = packet.id;
      checkbox.checked = selected.has(packet.id);
      checkbox.addEventListener('change', () => select(packet, checkbox));
      const color = [...selected.keys()].indexOf(packet.id);
      label.append(checkbox, text('span', color < 0 ? 'Auf Karte' : color ? 'Orange' : 'Blau'));
      action.append(label); row.append(action); table.append(row);
    }
    container.append(table);
    const pages = Math.ceil(activeGroup.packets.length / 50);
    if (pages > 1) {
      const prev = text('button', 'Vorherige Empfänge'), next = text('button', 'Weitere Empfänge');
      prev.type = next.type = 'button';
      prev.disabled = receptionPage === 0; next.disabled = receptionPage + 1 === pages;
      prev.addEventListener('click', () => { receptionPage--; renderReceptions(); });
      next.addEventListener('click', () => { receptionPage++; renderReceptions(); });
      container.append(prev, text('span', ` Seite ${receptionPage + 1}/${pages} `), next);
    }
  }
  async function chooseGroup(item) {
    activeGroup = item; receptionPage = 0;
    for (const button of el('list').querySelectorAll('.trace-group-choice')) {
      button.setAttribute('aria-pressed', String(button.dataset.id === String(item.id)));
    }
    const summary = el('summary');
    summary.replaceChildren(text('h3', 'TRACE-Ergebnis'), text('p', groupLabel(item)),
      text('p', `Gruppenminimum und Observerzahl sind aggregiert. Karte und Messwerte zeigen einzelne Empfänge. Empfohlener Einzelempfang: #${item.representative_id} mit größter SNR-Abdeckung; bei Gleichstand neuester Empfang, dann höchste ID.`));
    const mapButton = text('button', 'Zur TRACE-Karte');
    mapButton.type = 'button';
    mapButton.addEventListener('click', () => document.getElementById('node-map').scrollIntoView({block: 'center'}));
    summary.append(mapButton);
    // A second group can join the comparison; never silently replace either color.
    renderReceptions();
    const packet = item.packets.find(p => p.id === item.representative_id);
    if (!selected.has(packet.id) && selected.size < 2) await select(packet, {checked: true});
    else if (!selected.has(packet.id)) el('status').textContent = 'Messgruppe geöffnet. Für ihren Empfang zuerst eine der zwei Kartenbeobachtungen abwählen.';
    summary.scrollIntoView({block: 'nearest'});
  }
  async function search(next = false) {
    if (!next) {
      ++version; controller?.abort(); controller = new AbortController();
      details(); el('list').replaceChildren();
      const hours = el('period').value, end = Date.now() / 1000;
      const start = hours === 'custom' ? new Date(el('start').value).getTime() / 1000 : end - Number(hours) * 3600;
      const until = hours === 'custom' ? new Date(el('end').value).getTime() / 1000 : end;
      if (!Number.isFinite(start) || !Number.isFinite(until) || start >= until || until - start > 31 * 86400) {
        el('status').textContent = 'Gültigen Zeitraum von höchstens 31 Tagen wählen.'; el('next').hidden = true; return;
      }
      query = new URLSearchParams({grouped: 'true', start, end: until, first: el('first').value.toLowerCase(), last: el('last').value.toLowerCase()});
      if (el('hops').value !== '') query.set('hops', el('hops').value);
    } else query.set('before', cursor);
    const current = version;
    el('next').disabled = true; el('status').textContent = 'TRACE-Messgruppen werden geladen …';
    try {
      const response = await fetch(`/api/map-traces?${query}`, {signal: controller.signal});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result = await response.json();
      if (current !== version) return;
      // Keep the DOM bounded; selected comparison details survive page changes.
      el('list').replaceChildren(...result.items.map(item => {
        if (result.grouped) {
          const button = text('button', groupLabel(item), 'trace-group-choice');
          button.type = 'button'; button.dataset.id = item.id;
          button.setAttribute('aria-pressed', String(activeGroup?.id === item.id));
          button.addEventListener('click', () => chooseGroup(item));
          return button;
        }
        const label = text('label', '', 'trace-map-choice'), checkbox = document.createElement('input');
        checkbox.type = 'checkbox'; checkbox.dataset.id = item.id; checkbox.checked = selected.has(item.id);
        checkbox.addEventListener('change', () => select(item, checkbox));
        label.append(checkbox, text('span', `#${item.id} · ${new Date(item.received * 1000).toLocaleString('de-DE')} · ${item.route.join(' → ') || 'Leere Route'} · ${item.observed_hops}/${item.route.length} SNR`));
        return label;
      }));
      cursor = result.before; el('next').hidden = cursor == null;
      el('status').textContent = `${result.items.length} ${result.grouped ? 'Messgruppen' : 'Treffer'} · ${result.scanned} Empfänge geprüft${cursor ? ' · Weitere Archivseite verfügbar (auch bei leerer Trefferliste).' : ' · Ende des geladenen Bestands.'}`;
      if (result.truncated) el('status').textContent += ' · Auf 5000 Empfänge begrenzt; Messgruppen können an Zeitraum-/Bestandsgrenzen unvollständig sein.';
    } catch (error) {
      if (current === version && error.name !== 'AbortError') el('status').textContent = `Suche fehlgeschlagen: ${error.message}`;
    } finally { if (current === version) el('next').disabled = false; }
  }
  document.querySelectorAll('#map-modes button').forEach(button => button.addEventListener('click', () => {
    mode = button.dataset.mode;
    document.querySelectorAll('#map-modes button').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
    document.getElementById('map-traces').hidden = mode !== 'traces';
    for (const id of ['map-node-tools', 'map-status', 'map-neighbors-status', 'map-node-help']) document.getElementById(id).hidden = mode === 'traces';
    if (mode === 'nodes') setMapLinkMode('none');
    else if (mode === 'paths' && mapLinkMode === 'none') setMapLinkMode('selected');
    drawMapNeighbors(); draw(); nodeMap?.invalidateSize();
  }));
  document.querySelectorAll('#map-modes button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
  document.getElementById('map-link-mode').addEventListener('change', () => {
    if (mode === 'traces') return;
    mode = mapLinkMode === 'none' ? 'nodes' : 'paths';
    document.querySelectorAll('#map-modes button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
  });
  el('form').addEventListener('submit', event => { event.preventDefault(); search(); });
  el('next').addEventListener('click', () => search(true));
  el('period').addEventListener('change', () => {
    for (const field of ['start', 'end']) el(field).disabled = el('period').value !== 'custom';
  });
  el('start').disabled = el('end').disabled = true;
  // Register after initMap has created the map, without polling or additional requests.
  const originalInit = showNodeMap;
  showNodeMap = function() { originalInit(); nodeMap.off('zoomend moveend resize', draw).on('zoomend moveend resize', draw); draw(); };
})();
