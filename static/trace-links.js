/* Historical link aggregation on the same Leaflet map as TRACE comparison. */
window.TraceLinks = (() => {
  const el = id => document.getElementById(`trace-links-${id}`);
  const selected = () => !document.getElementById('panel-trace').hidden &&
    !document.getElementById('map-traces').hidden && !el('controls').hidden;
  const active = () => selected() && !paused;
  const labels = new Map();
  const views = new Map();
  const positions = new Map();
  const workspace = document.getElementById('map-traces');
  const hoverCapability = matchMedia('(any-hover: hover)');
  const wide = matchMedia('(min-width: 901px)');
  const settingsKey = 'onair-trace-links-view';
  const labelZoom = {snr: 11, full: 9};
  const tooltipPadding = 8;
  const REFRESH_INTERVAL_MS = 10000;
  let layer, renderer, hoverTooltip, hovered, result, query, filters, controller, detailsController, frame, timer;
  let choice = '', boundsSet = false, dirty = true, visible = false, revision, lastRequest = 0;
  let tooltipControls = [];
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(settingsKey)) || {}; } catch { /* Optional persistence. */ }
  let labelMode = ['snr', 'full'].includes(saved.labelMode) ? saved.labelMode : 'none';
  let detailsOpen = saved.detailsOpen !== false;
  let panelWidth = Number.isInteger(saved.panelWidth) && saved.panelWidth >= 28 && saved.panelWidth <= 54 ?
    saved.panelWidth : 36;
  const time = value => new Date(value * 1000).toLocaleString('de-DE');
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
  const locationIssues = {
    unknown: 'Identität unbekannt', ambiguous: 'Präfix mehrdeutig', collision: 'Präfixkollision',
    non_repeater: 'Kein Repeater', missing_position: 'Position fehlt',
    uncertain_position: 'Position unsicher', same_identity: 'Gleiche Repeater-ID'
  };

  function saveView() {
    try { localStorage.setItem(settingsKey, JSON.stringify({labelMode, detailsOpen, panelWidth})); }
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
    if (!visible || labelMode === 'none' || frame != null) return;
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

  function profilesOnMap(link) {
    const sf = query.get('sf');
    return link.profiles.filter(group => sf === 'all' || sf === String(group.profile.spreading_factor ?? 'unknown'));
  }

  function labelContent(link, compact = false) {
    const groups = profilesOnMap(link);
    const stat = el('stat').value;
    const describe = (direction, missing) => direction ? traceMapSnrText(direction[stat]) : missing;
    const readings = (group, missing) => [
      text('span', `→ ${describe(group?.forward, missing)}`, 'trace-link-reading'), ' · ',
      text('span', `← ${describe(group?.reverse, missing)}`, 'trace-link-reading')
    ];
    if (compact) {
      // Keep both directions in one real profile, using the dataset's order for ties.
      const count = group => (group.forward?.count || 0) + (group.reverse?.count || 0);
      const group = groups.reduce((best, current) => !best || count(current) > count(best) ? current : best, null);
      const row = text('div', '');
      row.append(...readings(group, '—'));
      return row;
    }
    const box = text('div', '');
    const [a, b] = link.endpoints.map(name);
    box.append(text('strong', `${a} ↔ ${b}`));
    for (const group of groups) {
      const sf = group.profile.spreading_factor;
      const title = groups.filter(other => other.profile.spreading_factor === sf).length > 1 ?
        profileName(group.profile) : sf == null ? 'Unbekannt' : `SF${sf}`;
      const row = text('div', `${title} · `);
      row.append(...readings(group, 'fehlt'));
      box.append(row);
    }
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
    const groups = profilesOnMap(link);
    const forward = groups.some(group => group.forward), reverse = groups.some(group => group.reverse);
    return {color: forward ? '#3388ff' : '#d97706', weight: id === choice ? 7 : 4,
      opacity: choice && id !== choice ? .55 : .9, dashArray: forward && reverse ? null : '7 5'};
  }

  function reconcilePositions() {
    const wanted = new Map();
    for (const {points} of views.values()) {
      for (const point of points) wanted.set(`${point.lat}/${point.lng}`, point);
    }
    for (const [id, marker] of positions) {
      if (wanted.has(id)) continue;
      layer.removeLayer(marker);
      positions.delete(id);
    }
    for (const [id, point] of wanted) {
      if (positions.has(id)) continue;
      const marker = L.circleMarker(point, {renderer, radius: 3, interactive: false,
        color: '#374151', weight: 1, fillColor: '#fff', fillOpacity: .9}).addTo(layer).bringToBack();
      positions.set(id, marker);
    }
  }

  function reconcile() {
    if (!result || !visible) return;
    closeHover();
    const available = new Map(result.links.filter(link => !link.endpoints.some((endpoint, i) =>
      repeaterMapVisibility.hidden(endpoint.public_key, 2, link.prefix_bytes[i]))).map(link => [key(link), link]));
    for (const [id, view] of views) {
      if (available.has(id)) continue;
      layer.removeLayer(view.line);
      if (labels.has(id)) layer.removeLayer(labels.get(id));
      labels.delete(id);
      views.delete(id);
    }
    const selectionRemoved = choice && !available.has(choice);
    if (selectionRemoved) choice = '';
    for (const [id, link] of available) {
      const view = views.get(id);
      if (view?.link === link) {
        if (selectionRemoved) view.line.setStyle(style(link, id));
        continue;
      }
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
        old.line.setStyle(style(link, id));
      }
      const options = {...style(link, id), renderer};
      const line = old?.line || (colocated ? L.circleMarker(center, {...options, radius: 5}) : L.polyline(points, options))
        .on('click', () => choose(id, true))
        .on('mouseover mousemove', event => hover(id, event))
        .on('mouseout', () => { if (hovered === id) closeHover(); }).addTo(layer);
      if (labels.has(id)) labels.get(id).setLatLng(center).setContent(labelContent(link, labelMode === 'snr'));
      views.set(id, {line, center, points, link, colocated});
    }
    reconcilePositions();
    views.get(choice)?.line.bringToFront();
    const select = el('pair');
    select.replaceChildren(new Option('Linkstrecke wählen', ''),
      ...[...available].sort((a, b) => linkName(a[1]).localeCompare(linkName(b[1]), 'de'))
        .map(([id, link]) => new Option(linkName(link), id)));
    select.value = choice;
    if (!boundsSet && available.size) {
      boundsSet = true;
      traceMap.fitBounds(L.latLngBounds([...available.values()].flatMap(link => link.positions
        .map(p => [p.latitude, p.longitude]))), {padding: [32, 32], maxZoom: 12, animate: false});
    }
    scheduleLabels();
  }

  function renderDetails(preserveSamples = false) {
    if (!preserveSamples) detailsController?.abort();
    const panel = el('detail');
    const link = views.get(choice)?.link;
    const items = (preserveSamples && panel.querySelector('.trace-link-samples')) || text('div', '', 'trace-link-samples');
    panel.replaceChildren();
    if (!link) return;
    panel.append(text('h3', linkName(link)), text('p', `Kartengeometrie zum jüngsten darstellbaren Messpunkt · ${time(link.position_at)}`));
    const [a, b] = link.endpoints.map(name);
    for (const {profile, forward, reverse} of link.profiles) {
      const group = text('section', '', 'trace-link-profile');
      const directions = text('div', '', 'trace-link-directions');
      group.append(text('h4', profileName(profile)), directions);
      for (const [direction, values] of [[`${a} → ${b}`, forward], [`${b} → ${a}`, reverse]]) {
        const card = text('section', '', 'trace-link-direction');
        card.append(text('h5', direction));
        directions.append(card);
        if (!values) {
          card.append(text('p', 'Keine Messung', 'muted'));
          continue;
        }
        const stats = text('dl', '', 'trace-link-stats');
        for (const [label, value] of [
          ['Anzahl', values.count], ...[['Zuletzt', 'last'], ['Min.', 'min'], ['Median', 'median'], ['Max.', 'max']]
            .map(([title, stat]) => [title, traceMapSnrText(values[stat])])
        ]) {
          const entry = text('div', '');
          entry.append(text('dt', label), text('dd', value));
          stats.append(entry);
        }
        card.append(stats,
          text('p', `Erste / letzte Messung · ${time(values.first_at)} / ${time(values.last_at)}`),
          text('p', Object.entries(values.quality).map(([quality, count]) => `${count} × ${qualityText[quality]}`).join(' · ')));
      }
      panel.append(group);
    }
    const button = text('button', 'Einzelmessungen laden');
    button.type = 'button';
    button.onclick = () => loadSamples(items);
    panel.append(button, items);
  }

  async function loadSamples(panel, offset = 0) {
    detailsController?.abort();
    const request = detailsController = new AbortController();
    const [a, b] = choice.split('/');
    const params = new URLSearchParams(query);
    params.set('a', a); params.set('b', b); params.set('offset', offset);
    panel.replaceChildren(text('p', 'Einzelmessungen werden geladen …'));
    try {
      const response = await fetch(`/api/trace-links?${params}`, {signal: request.signal});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (request.signal.aborted || !visible) return;
      const list = text('ol', '');
      list.start = offset + 1;
      const names = Object.fromEntries(views.get(choice).link.endpoints.map(endpoint => [endpoint.public_key, name(endpoint)]));
      for (const item of data.items) {
        const row = text('li', `${time(item.time)} · ${names[item.source]} → ${names[item.target]} · ${traceMapSnrText(item.snr)} · ${profileName(item.profile)} · ${qualityText[item.quality]}`);
        if (item.location_issue) row.append(text('span', ` · ${locationIssues[item.location_issue]}`));
        const evidence = text('details', '');
        evidence.append(text('summary', `TRACE #${item.measurement_id} · Hop ${item.hop} · Empfänge ${item.observations.map(id => '#' + id).join(', ')}`));
        evidence.addEventListener('toggle', async () => {
          if (!evidence.open || evidence.childNodes.length > 1) return;
          try {
            const r = await fetch(`/api/trace-measurements/${item.measurement_id}`, {signal: request.signal});
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const measurement = await r.json();
            if (request.signal.aborted) return;
            evidence.append(text('p',
              `${measurement.prefix_bytes} Byte · ${measurement.complete ? 'Vollständig' : 'Teilweise mitgehört'} · ${measurement.hops.map(hop =>
                `${hop.name || hop.hash} (${hop.snr == null ? 'SNR fehlt' : traceMapSnrText(hop.snr)}${locationIssues[hop.state] ? ', ' + locationIssues[hop.state] : ''})`).join(' → ')}`));
            const observers = text('ul', '');
            for (const reception of measurement.observations) {
              observers.append(text('li', [
                `#${reception.packet_id} · ${reception.observer_name || reception.observer_id || 'Observer unbekannt'}`,
                `MQTT-Empfang ${time(reception.received)}`,
                reception.source_at == null ? 'Quellzeit fehlt' : `Quellzeit ${time(reception.source_at)}`,
                reception.observer_rssi == null ? '' : `Observer-RSSI ${reception.observer_rssi} dBm`,
                reception.observer_snr == null ? '' : `Observer-SNR ${traceMapSnrText(reception.observer_snr)}`,
                profileName(reception.radio.profile || {}),
                qualityText[reception.radio.match]
              ].filter(Boolean).join(' · ')));
            }
            evidence.append(observers);
          } catch (error) {
            if (error.name !== 'AbortError') evidence.append(text('p', `TRACE-Details konnten nicht geladen werden (${error.message}).`));
          }
        });
        row.append(evidence);
        list.append(row);
      }
      panel.replaceChildren(text('p', `${data.total} Einzelmessungen im gewählten Funkprofilfilter`), list);
      for (const [label, target, enabled] of [['Vorherige', Math.max(0, offset - 50), offset > 0],
        ['Weitere', data.next, data.next != null]]) {
        if (!enabled) continue;
        const button = text('button', label);
        button.type = 'button';
        button.onclick = () => loadSamples(panel, target);
        panel.append(button);
      }
    } catch (error) {
      if (error.name !== 'AbortError') panel.replaceChildren(text('p', `Einzelmessungen konnten nicht geladen werden (${error.message}).`));
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

  function renderStatus({links, summary, backfill}) {
    const linkCount = `${links.length} Linkstrecke${links.length === 1 ? '' : 'n'}`;
    el('status').textContent = [
      `${linkCount} · ${summary.visible_samples} gerichtete Messwerte · ${summary.measurements} TRACE-Messungen`,
      backfill.done ? '' : `Archivaufarbeitung läuft · ${backfill.scanned} TRACE-Empfänge gelesen`
    ].filter(Boolean).join(' · ');
    const unmapped = Object.values(summary.unmapped_samples).reduce((total, n) => total + n, 0);
    const notes = [
      summary.partial ? `${summary.partial} TRACE-Messungen teilweise mitgehört` : '',
      summary.without_visible_links ? `${summary.without_visible_links} TRACE-Messungen ohne darstellbare Linkstrecke` : '',
      summary.undecodable ? `${summary.undecodable} TRACE-Empfänge nicht dekodierbar` : '',
      ...Object.entries(summary.unmapped_samples).map(([reason, n]) => `${locationIssues[reason]} · ${n}`)
    ].filter(Boolean);
    el('coverage-title').textContent = unmapped ? `${unmapped} Messwert${unmapped === 1 ? '' : 'e'} ohne Karte` : 'Messabdeckung';
    el('coverage-list').replaceChildren(...notes.map(note => text('li', note)));
    el('coverage').hidden = !notes.length;
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
      el('status').textContent = 'Bitte einen gültigen Von-/Bis-Zeitraum auswählen.';
      el('coverage').hidden = true;
      return;
    }
    controller?.abort();
    const request = controller = new AbortController();
    const params = new URLSearchParams({start, end, sf});
    filters = settings;
    dirty = false;
    lastRequest = Date.now();
    if (!result) el('status').textContent = 'Linkstrecken werden geladen …';
    try {
      const response = await fetch(`/api/trace-links?${params}`, {signal: request.signal});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (request.signal.aborted || !active()) return;
      query = params;
      result = payload;
      for (const sf of result.spreading_factors) {
        if (![...el('sf').options].some(option => Number(option.value) === sf)) {
          el('sf').add(new Option(`SF${sf}`, sf));
        }
      }
      renderStatus(result);
      const previous = choice;
      repeaterMapVisibility.addKeys(result.links.flatMap(link => link.endpoints.map(node => node.public_key)));
      reconcile();
      renderDetails(!manual && choice === previous);
    } catch (error) {
      if (error.name !== 'AbortError') {
        dirty = true;
        el('status').textContent = `Linkstrecken konnten nicht geladen werden (${error.message}).`;
        el('coverage').hidden = true;
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
        controller?.abort();
        detailsController?.abort();
        clearTimeout(timer); timer = null;
        layer.remove();
        renderer.remove();
        dirty = true;
      }
      return;
    }
    if (!layer) {
      renderer = L.canvas({padding: .25, tolerance: 4});
      layer = L.layerGroup();
      traceMap.on('resize', sizeTooltips);
      traceMap.on('zoomend moveend resize', scheduleLabels);
      traceMap.on('zoomstart movestart resize', closeHover);
    }
    if (!visible) {
      visible = true;
      sizeTooltips();
      layer.addTo(traceMap);
      scheduleLabels();
    }
    if (paused) {
      if (controller || timer != null) dirty = true;
      controller?.abort();
      clearTimeout(timer); timer = null;
    } else if (dirty && !controller) refresh();
  }

  function updateDates() {
    const custom = el('period').value === 'custom';
    for (const id of ['start', 'end']) el(id).parentElement.hidden = el(id).disabled = !custom;
    return custom;
  }
  updateDates();
  el('form').onsubmit = event => { event.preventDefault(); refresh(true); };
  el('period').onchange = () => {
    if (!updateDates() || el('start').value && el('end').value) refresh(true);
  };
  el('sf').onchange = () => refresh(true);
  el('stat').onchange = () => {
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
  repeaterMapVisibility.listeners.add(() => {
    if (visible && result) {
      const previous = choice;
      reconcile();
      if (previous !== choice) renderDetails();
    }
  });
  return {sync, receive(value, snapshot) {
    if (value == null || value === revision && !snapshot) return;
    const first = revision == null;
    revision = value;
    if (first && !result && !controller) return;
    dirty = true;
    scheduleRefresh();
  }};
})();
