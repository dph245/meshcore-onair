/* Historical link aggregation on the same Leaflet map as TRACE comparison. */
window.TraceLinks = (() => {
  const el = id => document.getElementById(`trace-links-${id}`);
  const selected = () => !document.getElementById('panel-trace').hidden &&
    !document.getElementById('map-traces').hidden && !el('controls').hidden;
  const active = () => selected() && !paused;
  const labels = new Map();
  const views = new Map();
  const positions = new Map();
  const chartDraw = new WeakMap();
  const workspace = document.getElementById('map-traces');
  const hoverCapability = matchMedia('(any-hover: hover)');
  const wide = matchMedia('(min-width: 901px)');
  const settingsKey = 'onair-trace-links-view';
  const labelZoom = {snr: 11, full: 9};
  const tooltipPadding = 8;
  const REFRESH_INTERVAL_MS = 10000;
  const snrColors = ['#c62828', '#b45309', '#15803d'];
  let layer, renderer, hoverTooltip, hovered, result, query, filters, controller, detailsController, frame, timer;
  let choice = '', boundsSet = false, dirty = true, visible = false, revision, lastRequest = 0;
  let pendingResult, geometryPending = false, visibilityVersion;
  let tooltipControls = [];
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(settingsKey)) || {}; } catch { /* Optional persistence. */ }
  let labelMode = ['snr', 'full'].includes(saved.labelMode) ? saved.labelMode : 'none';
  let detailsOpen = saved.detailsOpen !== false;
  let panelWidth = Number.isInteger(saved.panelWidth) && saved.panelWidth >= 28 && saved.panelWidth <= 54 ?
    saved.panelWidth : 36;
  const time = value => new Date(value * 1000).toLocaleString('de-DE');
  const number = (value, maximumFractionDigits = 2) => value.toLocaleString('de-DE', {maximumFractionDigits});
  const db = value => value == null ? '—' : traceMapSnrText(value);
  const name = endpoint => endpoint.name || endpoint.public_key.slice(0, 8);
  const linkName = link => link.endpoints.map(name).join(' ↔ ');
  const key = link => link.endpoints.map(node => node.public_key).join('/');
  const profileName = profile => !Object.keys(profile).length ? 'Unbekannt' : [
    profile.spreading_factor == null ? 'SF unbekannt' : `SF${profile.spreading_factor}`,
    profile.frequency_hz != null ? `${(profile.frequency_hz / 1e6).toLocaleString('de-DE')} MHz` : null,
    profile.bandwidth_hz != null ? `${(profile.bandwidth_hz / 1000).toLocaleString('de-DE')} kHz` : null,
    profile.coding_rate != null ? `CR 4/${profile.coding_rate}` : null,
    profile.tx_power_dbm != null ? `${profile.tx_power_dbm} dBm TX` : null,
    profile.preamble_length != null ? `Präambel ${profile.preamble_length}` : null,
    profile.sync_word != null ? `Sync 0x${profile.sync_word.toString(16)}` : null,
    profile.radio_ic
  ].filter(Boolean).join(' · ');
  const qualityText = {
    confirmed: 'Observer-Meldung bestätigt', last_known: 'Zuletzt gemeldet', unknown: 'Profil unbekannt',
    uncertain: 'Profilzeitraum unsicher', conflicting_profiles: 'Widersprüchliche Observer-Profile',
    conflicting_status: 'Widersprüchlicher Observer-Status'
  };

  function saveView() {
    try { localStorage.setItem(settingsKey, JSON.stringify({labelMode, detailsOpen, panelWidth, stat: el('stat').value,
      period: el('period').value, sf: el('sf').value, start: el('start').value, end: el('end').value})); }
    catch { /* Optional persistence. */ }
  }

  function updateDetailsToggle() {
    workspace.dataset.detailsOpen = detailsOpen;
    const button = el('toggle-details');
    button.setAttribute('aria-expanded', String(detailsOpen));
    const action = detailsOpen ? 'ausblenden' : 'einblenden';
    button.setAttribute('aria-label', `Details ${action}`);
    el('toggle-verb').textContent = ` ${action}`;
  }

  function updatePanelWidth() {
    workspace.style.setProperty('--trace-links-panel-width', `${panelWidth}%`);
    el('panel-width').setAttribute('aria-valuetext', `${panelWidth} Prozent`);
  }

  function sizeTooltips() {
    if (!visible) return;
    const map = traceMap.getContainer();
    const width = Math.max(0, traceMap.getSize().x - 2 * tooltipPadding);
    map.style.setProperty('--trace-link-tooltip-space', `${width}px`);
    const bounds = map.getBoundingClientRect();
    const left = bounds.left + map.clientLeft, top = bounds.top + map.clientTop;
    tooltipControls = [...map.querySelectorAll('.leaflet-control-zoom, .leaflet-control-attribution')].map(control => {
      const rect = control.getBoundingClientRect();
      return {left: rect.left - left, right: rect.right - left, top: rect.top - top, bottom: rect.bottom - top};
    });
  }

  function positionTooltip(tooltip) {
    const element = tooltip.getElement();
    const {offsetWidth: width, offsetHeight: height} = element;
    const size = traceMap.getSize();
    const point = traceMap.latLngToContainerPoint(tooltip.getLatLng());
    let x = point.x - width / 2;
    let y = point.y - height / 2;
    if (!tooltip.options.permanent) {
      const gap = 10;
      if (point.x + gap + width <= size.x - tooltipPadding) x = point.x + gap;
      else if (point.x - gap - width >= tooltipPadding) x = point.x - gap - width;
      else y = point.y < size.y / 2 ? point.y + gap : point.y - gap - height;
    }
    const clamp = (value, min, max) => Math.max(min, Math.min(value, max));
    x = clamp(x, tooltipPadding, size.x - width - tooltipPadding);
    let top = tooltipPadding, bottom = size.y - tooltipPadding;
    for (const control of tooltipControls) {
      if (x >= control.right || x + width <= control.left) continue;
      if (control.top < size.y / 2) top = Math.max(top, control.bottom + 3);
      else bottom = Math.min(bottom, control.top - 3);
    }
    y = top + height <= bottom ? clamp(y, top, bottom - height) :
      clamp(y, tooltipPadding, size.y - height - tooltipPadding);
    const position = L.point(x, y).round();
    L.DomUtil.setPosition(element, traceMap.containerPointToLayerPoint(position));
  }

  function scheduleLabels() {
    if (!visible || !traceMap.hasLayer(layer) || labelMode === 'none' || frame != null) return;
    frame = requestAnimationFrame(() => {
      frame = null;
      if (!visible || labelMode === 'none') return;
      const bounds = traceMap.getBounds();
      const zoom = traceMap.getZoom();
      const compact = labelMode === 'snr';
      for (const [id, view] of views) {
        const open = zoom >= labelZoom[labelMode] && bounds.contains(view.center);
        if (open && !labels.has(id)) {
          const className = compact ? 'trace-link-tooltip trace-link-compact' : 'trace-link-tooltip';
          const label = L.tooltip({direction: 'center', permanent: true, className})
            .setLatLng(view.center).setContent(labelContent(view.link, compact)).addTo(layer);
          labels.set(id, label);
        }
        if (open) positionTooltip(labels.get(id));
        else if (labels.has(id)) {
          layer.removeLayer(labels.get(id));
          labels.delete(id);
        }
      }
    });
  }

  function labelContent(link, compact = false) {
    const stat = el('stat').value;
    const {forward, reverse} = link.snr;
    const readings = [
      text('span', `→ ${db(forward?.[stat])}`, 'trace-link-reading'), ' · ',
      text('span', `← ${db(reverse?.[stat])}`, 'trace-link-reading')
    ];
    const box = text('div', '');
    if (!compact) box.append(text('strong', linkName(link)));
    const row = text('div', '');
    row.append(...readings);
    box.append(row);
    return box;
  }

  function closeHover() {
    hoverTooltip?.remove();
    hovered = null;
  }

  function hover(id, event) {
    if (!hoverCapability.matches || event.originalEvent?.sourceCapabilities?.firesTouchEvents ||
        labelMode === 'full' && labels.has(id)) return;
    if (!hoverTooltip) hoverTooltip = L.tooltip({direction: 'center', opacity: 1,
      className: 'trace-link-tooltip trace-link-hover'});
    if (hovered !== id) {
      hovered = id;
      hoverTooltip.setContent(labelContent(views.get(id).link)).setLatLng(event.latlng).addTo(traceMap);
    } else hoverTooltip.setLatLng(event.latlng);
    positionTooltip(hoverTooltip);
  }

  function style(link, id) {
    const stat = el('stat').value;
    const {forward, reverse} = link.snr;
    const snr = Math.min(forward?.[stat] ?? Infinity, reverse?.[stat] ?? Infinity);
    const color = snrColors[snr < snrThresholds.low ? 0 : snr <= snrThresholds.high ? 1 : 2];
    return {color, weight: id === choice ? 7 : 4, fill: false, lineCap: 'butt',
      opacity: choice && id !== choice ? .55 : .9, dashArray: forward && reverse ? null : '7 5'};
  }

  function renderLegend() {
    const ranges = [`< ${snrThresholds.low} dB`,
      `${snrThresholds.low} bis ${snrThresholds.high} dB`, `> ${snrThresholds.high} dB`];
    el('legend').replaceChildren(...ranges.map((range, i) => {
      const entry = text('span', '', 'trace-link-legend-entry');
      const line = text('span', '', 'trace-link-swatch');
      line.style.backgroundColor = snrColors[i];
      line.setAttribute('aria-hidden', 'true');
      entry.append(line, range);
      return entry;
    }), text('span', 'Schwächerer Richtungswert · gestrichelt bei nur einer Richtung'));
  }

  function addPath(path) {
    path.options.renderer = renderer;
    return path.addTo(layer);
  }

  function syncViewport(sized = false) {
    if (!visible || !selected() || (!sized && !resizeTraceMap())) return;
    if (!boundsSet && views.size) {
      boundsSet = true;
      traceMap.fitBounds(L.latLngBounds([...views.values()].flatMap(view => view.points)),
        {padding: [32, 32], maxZoom: 12, animate: false});
    }
    if (!traceMap.hasLayer(layer)) {
      // Leaflet 1.9.4 cancels Canvas's queued redraw on removal but retains its frame ID.
      // Reattach the existing paths with a renderer whose frame queue is empty.
      renderer = L.canvas({padding: .25, tolerance: 4});
      layer.eachLayer(path => { if (path instanceof L.Path) path.options.renderer = renderer; });
      layer.addTo(traceMap);
      sizeTooltips();
    }
    if (geometryPending) {
      geometryPending = false;
      paintLayers();
    }
    scheduleLabels();
  }

  function paintLayers() {
    for (const [id, view] of views) {
      view.line.setStyle(style(view.link, id));
      if (!layer.hasLayer(view.line)) addPath(view.line);
      labels.get(id)?.setContent(labelContent(view.link, labelMode === 'snr'));
    }
    reconcilePositions();
    views.get(choice)?.line.bringToFront();
  }

  function reconcilePositions() {
    const wanted = new Map();
    for (const {points} of views.values()) {
      for (const point of points) {
        const id = `${point.lat}/${point.lng}`;
        wanted.set(id, point);
      }
    }
    for (const [id, marker] of positions) {
      if (wanted.has(id)) continue;
      layer.removeLayer(marker);
      positions.delete(id);
    }
    for (const [id, point] of wanted) {
      if (positions.has(id)) continue;
      const marker = L.circleMarker(point, {radius: 3, interactive: false,
        color: '#374151', weight: 1, fillColor: '#fff', fillOpacity: .9});
      positions.set(id, marker);
      addPath(marker).bringToBack();
    }
  }

  function reconcile() {
    if (!result || !visible) return;
    closeHover();
    visibilityVersion = repeaterMapVisibility.version;
    const available = new Map(result.links.filter(link => !link.endpoints.some((endpoint, i) =>
      repeaterMapVisibility.hidden(endpoint.public_key, 2, link.prefix_bytes[i]))).map(link => [key(link), link]));
    for (const [id, view] of views) {
      if (available.has(id)) continue;
      layer.removeLayer(view.line);
      if (labels.has(id)) layer.removeLayer(labels.get(id));
      labels.delete(id);
      views.delete(id);
    }
    for (const [id, link] of available) {
      const view = views.get(id);
      if (view?.link === link) continue;
      const points = link.positions.map(p => L.latLng(p.latitude, p.longitude));
      const center = L.latLng((points[0].lat + points[1].lat) / 2, (points[0].lng + points[1].lng) / 2);
      let old = view;
      const colocated = points[0].equals(points[1]);
      if (old && old.colocated !== colocated) {
        layer.removeLayer(old.line);
        old = null;
      }
      if (old) {
        if (colocated) {
          if (!old.line.getLatLng().equals(center)) old.line.setLatLng(center);
        } else {
          const oldPoints = old.line.getLatLngs();
          if (!points.every((point, i) => point.equals(oldPoints[i]))) old.line.setLatLngs(points);
        }
      }
      const options = style(link, id);
      const line = old?.line || (colocated ? L.circleMarker(center, {...options, radius: 5}) : L.polyline(points, options))
        .on('click', () => choose(id, true))
        .on('mouseover mousemove', event => hover(id, event))
        .on('mouseout', () => { if (hovered === id) closeHover(); });
      if (labels.has(id)) labels.get(id).setLatLng(center);
      views.set(id, {line, center, points, link, colocated});
    }
    if (!views.has(choice)) choice = '';
    const select = el('pair');
    select.replaceChildren(new Option(views.size ? 'Linkstrecke wählen' : 'Keine Linkstrecke im Filter', ''),
      ...[...available].sort((a, b) => linkName(a[1]).localeCompare(linkName(b[1]), 'de'))
        .map(([id, link]) => new Option(linkName(link), id)));
    select.value = choice;
    renderStatus();
    geometryPending = true;
    syncViewport();
  }

  function historyChart(series, paths) {
    const canvas = text('canvas', '', 'trace-link-chart');
    canvas.width = 430;
    canvas.height = 180;
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', `SNR-Verlauf in dB · ${paths.join(' und ')}`);
    const wrap = text('figure', '');
    const caption = text('figcaption', '', 'trace-link-chart-caption');
    paths.forEach((path, i) => caption.append(text('span',
      `${i ? '×' : '○'} ${path}${series[i].length ? '' : ' (keine Messung)'}`, i ? 'reverse' : 'forward')));
    wrap.append(caption, canvas);
    const draw = () => {
      const context = canvas.getContext('2d');
      const theme = getComputedStyle(document.documentElement);
      const left = 48, right = 403, top = 16, bottom = 148;
      let xMin = Infinity, xMax = -Infinity, min = Infinity, max = -Infinity;
      for (const direction of series) {
        if (!direction.length) continue;
        xMin = Math.min(xMin, direction[0][0]);
        xMax = Math.max(xMax, direction.at(-1)[0]);
        for (const [, snr] of direction) {
          min = Math.min(min, snr);
          max = Math.max(max, snr);
        }
      }
      const xSpan = xMax - xMin;
      const yMin = Math.floor(min) - 1, yMax = Math.ceil(max) + 1;
      const x = value => xSpan ? left + (right - left) * (value - xMin) / xSpan : (left + right) / 2;
      const y = value => bottom - (bottom - top) * (value - yMin) / (yMax - yMin);
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.font = '12px monospace';
      context.fillStyle = theme.getPropertyValue('--fg');
      context.strokeStyle = theme.getPropertyValue('--control-border');
      context.lineWidth = 1;
      for (const value of [yMin, (yMin + yMax) / 2, yMax]) {
        context.textAlign = 'right';
        context.fillText(number(value), left - 6, y(value) + 4);
        context.beginPath();
        context.moveTo(left, y(value));
        context.lineTo(right, y(value));
        context.stroke();
      }
      const ticks = xSpan ? [xMin, xMax] : [xMin];
      const timestampFormat = {dateStyle: 'short', timeStyle: xSpan < 60 ? 'medium' : 'short'};
      for (const value of ticks) {
        context.textAlign = !xSpan ? 'center' : value === xMin ? 'left' : 'right';
        const stamp = new Date(value * 1000).toLocaleString('de-DE', timestampFormat);
        context.fillText(stamp, x(value), bottom + 20);
      }
      series.forEach((readings, i) => {
        context.strokeStyle = theme.getPropertyValue(i ? '--purple' : '--blue');
        context.lineWidth = 2;
        if (readings.length > 1) {
          context.setLineDash(i ? [5, 3] : []);
          context.beginPath();
          readings.forEach(([stamp, snr], index) => index ? context.lineTo(x(stamp), y(snr)) : context.moveTo(x(stamp), y(snr)));
          context.stroke();
          context.setLineDash([]);
        }
        for (const [stamp, snr] of readings) {
          const px = x(stamp), py = y(snr);
          context.beginPath();
          if (i) {
            context.moveTo(px - 3, py - 3); context.lineTo(px + 3, py + 3);
            context.moveTo(px + 3, py - 3); context.lineTo(px - 3, py + 3);
          } else context.arc(px, py, 3, 0, 2 * Math.PI);
          context.stroke();
        }
      });
    };
    chartDraw.set(canvas, draw);
    draw();
    return wrap;
  }

  function renderDetails() {
    detailsController?.abort();
    const panel = el('detail');
    const link = views.get(choice)?.link;
    panel.replaceChildren();
    if (!link) return;
    const request = detailsController = new AbortController();
    const [a, b] = choice.split('/');
    const params = new URLSearchParams(query);
    params.set('a', a); params.set('b', b);
    const names = Object.fromEntries(link.endpoints.map(endpoint => [endpoint.public_key, name(endpoint)]));
    const plot = text('div', '', 'trace-link-history');
    plot.append(text('h4', 'SNR-Verlauf in dB'));
    const readings = text('div', '');
    plot.append(readings);
    const samples = text('details', '', 'trace-link-samples');
    const list = text('div', '');
    samples.hidden = true;
    samples.append(text('summary', 'Einzelmessungen'), list);
    panel.append(text('h3', linkName(link)), plot, samples);
    loadSamples({params, request, names, readings, samples, list});
  }

  async function loadSamples(detail, offset = 0) {
    const {params, request, names, readings, samples, list: panel} = detail;
    const page = new URLSearchParams(params);
    page.set('offset', offset);
    const status = offset === 0 ? readings : panel;
    status.replaceChildren(text('p', 'Messungen werden geladen …'));
    try {
      const response = await fetch(`/api/trace-links?${page}`, {signal: request.signal});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (request.signal.aborted) return;
      if (offset === 0) {
        const {forward, reverse} = data.history;
        const [a, b] = Object.values(names);
        readings.replaceChildren(forward.length || reverse.length ?
          historyChart([forward, reverse], [`${a} → ${b}`, `${b} → ${a}`]) :
          text('p', 'Keine geografisch auflösbaren Messwerte im gewählten Zeitraum.'));
        samples.hidden = !data.total;
      }
      const list = text('ol', '');
      list.start = offset + 1;
      for (const item of data.items) {
        const row = text('li', `${time(item.time)} · ${names[item.source]} → ${names[item.target]} · ${traceMapSnrText(item.snr)} · ${profileName(item.profile)} · ${qualityText[item.quality]}`);
        if (item.location_issue) row.append(text('span', ` · ${traceLocationIssues[item.location_issue]}`));
        const evidence = text('details', '');
        let loading = false;
        evidence.append(text('summary', `TRACE #${item.measurement_id} · Hop ${item.hop} · Empfänge ${item.observations.map(id => '#' + id).join(', ')}`));
        evidence.addEventListener('toggle', async () => {
          if (!evidence.open || loading || evidence.childNodes.length > 1) return;
          loading = true;
          try {
            const r = await fetch(`/api/trace-measurements/${item.measurement_id}`, {signal: request.signal});
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const measurement = await r.json();
            if (request.signal.aborted) return;
            evidence.append(text('p',
              `${measurement.prefix_bytes} Byte · ${measurement.complete ? 'Vollständig' : 'Teilweise mitgehört'} · ${measurement.hops.map(hop => {
                const snr = hop.snr == null ? 'SNR fehlt' : traceMapSnrText(hop.snr);
                const source = traceLocationIssues[hop.from_location_issue];
                const issues = [snr, traceLocationIssues[hop.location_issue || hop.state],
                  source && `sendender Hop: ${source}`].filter(Boolean);
                return `${hop.name || hop.hash} (${issues.join(', ')})`;
              }).join(' → ')}`));
            const observers = text('ul', '');
            for (const reception of measurement.observations) {
              observers.append(text('li', [
                `#${reception.packet_id} · ${reception.observer_name || reception.observer_id || 'Observer unbekannt'}`,
                reception.observer_name && reception.observer_id ? reception.observer_id : '',
                `MQTT-Empfang ${time(reception.received)}`,
                reception.source_at == null ? 'Quellzeit fehlt' : `Quellzeit ${time(reception.source_at)}`,
                reception.observer_rssi == null ? '' : `Observer-RSSI ${reception.observer_rssi} dBm`,
                reception.observer_snr == null ? '' : `Observer-SNR ${traceMapSnrText(reception.observer_snr)}`,
                profileName(reception.radio.profile || {}),
                qualityText[reception.radio.match],
                reception.radio.observed_at == null ? '' : `Observer-Profilmeldung ${time(reception.radio.observed_at)}`
              ].filter(Boolean).join(' · ')));
            }
            evidence.append(observers);
          } catch (error) {
            if (error.name !== 'AbortError') evidence.append(text('p', `TRACE-Details konnten nicht geladen werden (${error.message}).`));
          } finally {
            loading = false;
          }
        });
        row.append(evidence);
        list.append(row);
      }
      panel.replaceChildren(text('p', `${data.total} gerichtete Messwerte`), list);
      for (const [label, target, enabled] of [['Vorherige', Math.max(0, offset - 50), offset > 0],
        ['Weitere', data.next, data.next != null]]) {
        if (!enabled) continue;
        const button = text('button', label);
        button.type = 'button';
        button.onclick = () => loadSamples(detail, target);
        panel.append(button);
      }
    } catch (error) {
      if (error.name !== 'AbortError') {
        const retry = text('button', 'Erneut laden');
        retry.type = 'button';
        retry.onclick = () => loadSamples(detail, offset);
        status.replaceChildren(text('p', `Messungen konnten nicht geladen werden (${error.message}).`), retry);
      }
    }
  }

  function choose(id, fromMap = false) {
    const previous = choice;
    choice = id;
    el('pair').value = choice;
    if (choice !== previous) {
      const changed = previous && choice ? [previous, choice] : views.keys();
      for (const id of changed) {
        const view = views.get(id);
        if (view) view.line.setStyle(style(view.link, id));
      }
      views.get(choice)?.line.bringToFront();
      renderDetails();
    }
    if (fromMap) {
      if (!detailsOpen) {
        detailsOpen = true;
        updateDetailsToggle();
        saveView();
      }
      el('details').scrollTop = 0;
      if (!wide.matches) el('details').scrollIntoView({block: 'start'});
    }
  }

  function renderStatus() {
    const {backfill} = result;
    const count = views.size;
    const status = el('status');
    status.dataset.state = backfill.done ? (count ? 'ready' : 'empty') : 'backfill';
    const linkCount = count ? `${count} Linkstrecke${count === 1 ? '' : 'n'}` : 'Keine Linkstrecken im Filter';
    status.textContent = linkCount +
      (backfill.done ? '' : ` · Archivaufarbeitung läuft · ${backfill.scanned} TRACE-Empfänge gelesen`);
    el('legend').hidden = !count;
  }

  function applyResult() {
    const {payload, params, manual} = pendingResult;
    result = payload;
    query = params;
    for (const sf of result.spreading_factors) {
      if (![...el('sf').options].some(option => Number(option.value) === sf)) {
        el('sf').add(new Option(`SF${sf}`, sf));
      }
    }
    const previous = choice;
    const previousSnr = views.get(choice)?.link.snr;
    repeaterMapVisibility.addKeys(result.links.flatMap(link => link.endpoints.map(node => node.public_key)));
    pendingResult = null;
    reconcile();
    if (manual || choice !== previous ||
        JSON.stringify(views.get(choice)?.link.snr) !== JSON.stringify(previousSnr)) renderDetails();
  }

  async function refresh(manual = false) {
    if (!active() || !traceMap) return;
    clearTimeout(timer); timer = null;
    const settings = manual || !filters ? {
      period: el('period').value, sf: el('sf').value,
      start: new Date(el('start').value).getTime() / 1000,
      end: new Date(el('end').value).getTime() / 1000
    } : filters;
    const {period, sf} = settings;
    const now = Date.now() / 1000;
    const end = period === 'custom' ? settings.end : now;
    const start = period === 'custom' ? settings.start :
      period === 'all' ? 0 : end - Number(period) * 3600;
    if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end || start < 0) {
      el('status').dataset.state = 'error';
      el('status').textContent = 'Bitte einen gültigen Von-/Bis-Zeitraum auswählen.';
      return;
    }
    controller?.abort();
    const request = controller = new AbortController();
    const params = new URLSearchParams({start, end, sf, compact: true});
    filters = settings;
    dirty = false;
    lastRequest = Date.now();
    if (!result) {
      el('status').dataset.state = 'loading';
      el('status').textContent = 'Linkstrecken werden geladen …';
    }
    try {
      const response = await fetch(`/api/trace-links?${params}`, {signal: request.signal});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (request.signal.aborted) return;
      pendingResult = {payload, params, manual};
      if (active()) applyResult();
    } catch (error) {
      if (error.name !== 'AbortError') {
        dirty = true;
        el('status').dataset.state = 'error';
        el('status').textContent = `Linkstrecken konnten nicht geladen werden (${error.message}).` +
          (result ? ' Die Karte zeigt den letzten geladenen Stand.' : '');
        }
    } finally {
      if (controller === request) controller = null;
      if (request.signal.aborted && dirty) scheduleRefresh();
    }
  }

  function scheduleRefresh() {
    if (!active() || !traceMap || timer != null) return;
    timer = setTimeout(() => {
      timer = null;
      if (dirty) refresh();
    }, Math.max(0, REFRESH_INTERVAL_MS - (Date.now() - lastRequest)));
  }

  function sync() {
    if (!selected() || !traceMap) {
      if (visible) {
        visible = false;
        closeHover();
        clearTimeout(timer); timer = null;
        if (frame != null) cancelAnimationFrame(frame);
        frame = null;
        layer.remove();
        renderer?.remove();
        renderer = null;
      }
      return;
    }
    if (!layer) {
      layer = L.layerGroup();
      renderLegend();
      traceMap.on('resize', sizeTooltips);
      traceMap.on('zoomend moveend resize', scheduleLabels);
      traceMap.on('zoomstart movestart resize', closeHover);
    }
    const opening = !visible;
    visible = true;
    if (pendingResult && !paused) applyResult();
    else if (opening && result && visibilityVersion !== repeaterMapVisibility.version) updateVisibility();
    else if (opening) syncViewport();
    if (opening && filters && !['all', 'custom'].includes(filters.period) &&
        Date.now() - lastRequest >= REFRESH_INTERVAL_MS) dirty = true;
    if (paused) {
      if (controller || timer != null) dirty = true;
      controller?.abort();
      clearTimeout(timer); timer = null;
    } else if (dirty && !controller) refresh();
  }

  function updateDates() {
    const custom = el('period').value === 'custom';
    for (const id of ['start', 'end']) el(id).parentElement.hidden = el(id).disabled = !custom;
    el('apply').hidden = !custom;
    return custom;
  }
  for (const id of ['period', 'sf', 'stat']) {
    if (id === 'sf' && ![...el(id).options].some(option => option.value === saved.sf) && /^(?:[5-9]|1[0-2])$/.test(saved.sf)) {
      el(id).add(new Option(`SF${saved.sf}`, saved.sf));
    }
    if ([...el(id).options].some(option => option.value === saved[id])) el(id).value = saved[id];
  }
  for (const id of ['start', 'end']) el(id).value = saved[id] || '';
  document.getElementById('theme-toggle').addEventListener('click', () => {
    if (!active()) return;
    requestAnimationFrame(() => {
      if (!active()) return;
      for (const canvas of el('detail').querySelectorAll('.trace-link-chart')) chartDraw.get(canvas)?.();
    });
  });
  updateDates();
  el('form').onsubmit = event => {
    event.preventDefault();
    el('options').open = false;
    saveView();
    refresh(true);
  };
  el('period').onchange = () => {
    saveView();
    if (!updateDates() || el('start').value && el('end').value) refresh(true);
  };
  el('sf').onchange = () => { saveView(); refresh(true); };
  el('stat').onchange = () => {
    saveView();
    for (const [id, view] of views) view.line.setStyle(style(view.link, id));
    for (const [id, label] of labels) label.setContent(labelContent(views.get(id).link, labelMode === 'snr'));
    scheduleLabels();
    if (hovered) {
      hoverTooltip.setContent(labelContent(views.get(hovered).link));
      positionTooltip(hoverTooltip);
    }
  };
  el('label-mode').value = labelMode;
  el('label-mode').onchange = () => {
    labelMode = el('label-mode').value;
    closeHover();
    for (const label of labels.values()) layer.removeLayer(label);
    labels.clear();
    saveView();
    scheduleLabels();
  };
  updateDetailsToggle();
  el('toggle-details').onclick = () => {
    detailsOpen = !detailsOpen;
    updateDetailsToggle();
    saveView();
  };
  el('panel-width').value = panelWidth;
  updatePanelWidth();
  el('panel-width').oninput = () => {
    panelWidth = el('panel-width').valueAsNumber;
    updatePanelWidth();
  };
  el('panel-width').onchange = saveView;
  el('pair').onchange = () => choose(el('pair').value);
  function updateVisibility() {
    if (!visible || !result || pendingResult) return;
    const previous = choice;
    reconcile();
    if (previous !== choice) renderDetails();
  }

  repeaterMapVisibility.listeners.add(updateVisibility);
  return {sync, resize: () => syncViewport(true), receive(value, snapshot) {
    if (value == null || value === revision && !snapshot) return;
    const first = revision == null;
    revision = value;
    if (first && !result && !controller) return;
    dirty = true;
    scheduleRefresh();
  }};
})();
