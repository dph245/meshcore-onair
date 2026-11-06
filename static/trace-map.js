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

// Historical observations have their own map and view; no fetch on map movement.
let traceMap;
(() => {
  let layer, cursor, query, version = 0, controller;
  const selected = new Map();
  let activeGroup, receptionPage = 0;
  const el = id => document.getElementById(`map-trace-${id}`);
  const position = hop => hop.position && [hop.position.latitude, hop.position.longitude];
  const routes = new Map(), labelViews = new WeakMap();
  let drawFrame = null;
  function scheduleDraw() {
    if (drawFrame === null) drawFrame = requestAnimationFrame(() => {
      drawFrame = null;
      draw();
    });
  }
  // Observe actual border-box changes (fonts, CSS, etc.), not marker movement.
  // This also invalidates sizes safely when a detached label is shown again.
  const labelObserver = new ResizeObserver(entries => {
    let changed = false;
    for (const entry of entries) {
      const view = labelViews.get(entry.target);
      if (!view || !view.marker || !layer.hasLayer(view.marker)) continue;
      const box = entry.borderBoxSize?.[0];
      if (box) {
        const size = [Math.round(box.inlineSize), Math.round(box.blockSize)];
        if (!size[0] || !size[1]) continue;
        if (view.size?.every((value, i) => value === size[i])) continue;
        view.size = size;
      } else view.size = null;
      changed = true;
    }
    if (changed) scheduleDraw();
  });
  function removeRoute(view) {
    for (const marker of view.markers) layer.removeLayer(marker);
    for (const segment of view.segments) {
      layer.removeLayer(segment.line);
      if (segment.arrow) layer.removeLayer(segment.arrow);
    }
    for (const label of view.labels) {
      if (label.marker) {
        layer.removeLayer(label.marker);
        labelObserver.unobserve(label.box);
      }
      if (label.leader) layer.removeLayer(label.leader);
    }
  }
  function routeView(item) {
    const view = {item, markers: [], segments: [], labels: []};
    item.hops.forEach((hop, i) => {
      const point = position(hop);
      if (!point) return;
      view.markers.push(L.circleMarker(point, {radius: 7}).bindTooltip(text('span',
        `#${item.id} · Hop ${i + 1}: ${traceNode(hop)} · SNR ${hop.snr_min ?? 'unbekannt'}`)).addTo(layer));
      const previous = i > 0 && position(item.hops[i - 1]);
      if (previous && hop.snr_min != null && item.hops[i - 1].snr_min != null) {
        view.segments.push({from: previous, to: point, line: L.polyline([previous, point], {weight: 3}).addTo(layer)});
      }
    });
    view.labels = traceMapSnrSegments(item.hops).map(section => ({section, route: view}));
    return view;
  }
  function draw() {
    if (!traceMap) return;
    if (document.getElementById('panel-trace').hidden || document.getElementById('map-traces').hidden) return;
    if (!layer) layer = L.layerGroup().addTo(traceMap);
    for (const [id, view] of routes) {
      if (selected.get(id) === view.item) continue;
      removeRoute(view);
      routes.delete(id);
    }
    const labels = [];
    [...selected.values()].forEach((item, index) => {
      const color = ['#3388ff', '#d97706'][index];
      let view = routes.get(item.id);
      if (!view) { view = routeView(item); routes.set(item.id, view); }
      const recolor = view.color !== color;
      view.index = index;
      view.color = color;
      if (recolor) for (const marker of view.markers) marker.setStyle({color});
      for (const segment of view.segments) {
        if (recolor) segment.line.setStyle({color});
        if (view.zoom !== traceMap.getZoom()) {
          const points = neighborArrowPoints(segment.from, segment.to, .6, traceMap);
          if (!points) {
            if (segment.arrow) layer.removeLayer(segment.arrow);
            segment.arrow = null;
          } else if (segment.arrow) segment.arrow.setLatLngs(points);
          else segment.arrow = L.polyline(points, {color, weight: 3, opacity: 1, interactive: false}).addTo(layer);
        }
        if (recolor && segment.arrow) segment.arrow.setStyle({color});
      }
      view.zoom = traceMap.getZoom();
      labels.push(...view.labels);
    });
    drawLabels(labels);
  }
  function drawLabels(labels) {
    const occupied = [], size = traceMap.getSize();
    const visible = [];
    for (const view of labels) {
      const {section, route} = view, {item, color} = route;
      const from = position(section.from), to = position(section.to);
      const a = traceMap.latLngToContainerPoint(from), b = traceMap.latLngToContainerPoint(to);
      const midpoint = L.point((a.x + b.x) / 2, (a.y + b.y) / 2);
      // Include labels near the edge, including tall repeated-traversal labels.
      const padding = Math.max(256, view.size?.[1] / 2 || (section.samples.length + 1) * 12 + 32);
      if (midpoint.x < -padding || midpoint.y < -padding || midpoint.x > size.x + padding || midpoint.y > size.y + padding) {
        if (view.marker && layer.hasLayer(view.marker)) {
          layer.removeLayer(view.marker);
          labelObserver.unobserve(view.box);
        }
        if (view.leader) layer.removeLayer(view.leader);
        continue;
      }
      if (!view.marker) {
        const box = view.box = text('div', '', 'trace-snr-label');
        box.dataset.traceId = item.id;
        box.append(text('span', `#${item.id} · ${section.from.hash} → ${section.to.hash}`, 'trace-snr-heading'));
        // Keep every chronological traversal, including repeated equal values.
        for (const sample of section.samples) {
          const row = text('span', `${sample.forward ? '→' : '←'} ${traceMapSnrText(sample.snr)}`, 'trace-snr-value');
          row.setAttribute('aria-label', `${sample.forward ? section.from.hash + ' → ' + section.to.hash : section.to.hash + ' → ' + section.from.hash}: ${traceMapSnrText(sample.snr)}, Hop ${sample.hop}`);
          box.append(row);
        }
        view.marker = L.marker(traceMap.containerPointToLatLng(midpoint), {
          icon: L.divIcon({html: box, className: 'trace-snr-icon', iconSize: [0, 0], iconAnchor: [0, 0]}),
          interactive: false, keyboard: false, zIndexOffset: 1000
        });
        labelViews.set(box, view);
      }
      if (view.color !== color) { view.box.style.borderColor = color; view.color = color; }
      if (!layer.hasLayer(view.marker)) {
        view.marker.addTo(layer);
        view.size = null;
        labelObserver.observe(view.box, {box: 'border-box'});
      }
      visible.push({view, midpoint});
    }
    // Batch initial/invalidated reads after DOM insertion; normal pan/zoom uses
    // the cached size. ResizeObserver supplies subsequent border-box changes.
    for (const {view} of visible) {
      if (!view.size) view.size = [view.box.offsetWidth, view.box.offsetHeight];
    }
    for (const {view, midpoint} of visible) {
      const {color, index} = view.route;
      const [width, height] = view.size;
      if (midpoint.x < 0 || midpoint.y < 0 || midpoint.x > size.x || midpoint.y > size.y) {
        const point = traceMap.containerPointToLatLng(midpoint);
        if (!view.marker.getLatLng().equals(point)) view.marker.setLatLng(point);
        if (view.leader) layer.removeLayer(view.leader);
        continue;
      }
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
      const displayed = traceMap.containerPointToLatLng(best.center);
      if (!view.marker.getLatLng().equals(displayed)) view.marker.setLatLng(displayed);
      // A subtle leader preserves the association when collision avoidance shifts a label.
      const origin = traceMap.containerPointToLatLng(midpoint);
      if (!view.leader) view.leader = L.polyline([origin, displayed], {
        color, weight: 1, opacity: .65, interactive: false, className: 'trace-snr-leader'
      });
      else {
        const points = view.leader.getLatLngs();
        if (!points[0].equals(origin) || !points[1].equals(displayed)) view.leader.setLatLngs([origin, displayed]);
        if (view.leader.options.color !== color) view.leader.setStyle({color});
      }
      if (!layer.hasLayer(view.leader)) view.leader.addTo(layer);
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
    scheduleDraw();
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
      if (points.length) traceMap.fitBounds(L.latLngBounds(points), {padding: [35, 35], maxZoom: 13, animate: false});
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
    mapButton.addEventListener('click', () => document.getElementById('trace-map').scrollIntoView({block: 'center'}));
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
          const button = text('button', '', 'trace-group-choice');
          button.append(text('strong', `${new Date(item.first_seen * 1000).toLocaleString('de-DE')} · Tag ${item.tag}`),
            text('span', item.hops.map(traceNode).join(' → ') || 'Leere Route'),
            text('span', `${item.receptions} Empfänge · ${item.observers.length} Observer · ${item.observed_hops}/${item.hops.length} SNR · Min. ${item.weakest_snr ?? '—'} dB`, 'muted'));
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
  el('form').addEventListener('submit', event => { event.preventDefault(); search(); });
  el('next').addEventListener('click', () => search(true));
  el('period').addEventListener('change', () => {
    for (const field of ['start', 'end']) el(field).disabled = el('period').value !== 'custom';
  });
  el('start').disabled = el('end').disabled = true;
  window.showTraceMap = function() {
    if (!window.L) {
      el('status').textContent = 'Kartenbibliothek konnte nicht geladen werden. Bitte Seite neu laden.';
      return;
    }
    if (!traceMap) {
      traceMap = L.map('trace-map').setView([52.1, 10.1], 7);
      const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      }).addTo(traceMap);
      tiles.on('tileerror', () => { document.getElementById('trace-tiles-status').hidden = false; });
      traceMap.on('zoomend moveend resize', scheduleDraw);
      new ResizeObserver(() => {
        if (!document.getElementById('panel-trace').hidden && !document.getElementById('map-traces').hidden) traceMap.invalidateSize({pan: false});
      }).observe(traceMap.getContainer());
    }
    traceMap.invalidateSize({pan: false}); scheduleDraw();
  };
})();
