/* Historical link aggregation on the same Leaflet map as TRACE comparison. */
window.TraceLinks = (() => {
  const el = id => document.getElementById(`trace-links-${id}`);
  const selected = () => !document.getElementById('panel-trace').hidden &&
    !document.getElementById('map-traces').hidden && !el('controls').hidden;
  const active = () => selected() && !paused;
  const labels = new Map();
  const views = new Map();
  const REFRESH_INTERVAL_MS = 10000;
  let layer, renderer, result, query, filters, controller, detailsController, frame, timer;
  let choice = '', boundsSet = false, dirty = true, visible = false, revision, lastRequest = 0;
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

  function scheduleLabels() {
    if (!visible || frame != null) return;
    frame = requestAnimationFrame(() => {
      frame = null;
      if (!visible) return;
      const bounds = traceMap.getBounds();
      const zoom = traceMap.getZoom();
      for (const [id, view] of views) {
        const open = zoom >= 9 && bounds.contains(view.center);
        if (open && !labels.has(id)) {
          const label = L.tooltip({direction: 'center', permanent: true, className: 'trace-link-tooltip',
            interactive: false}).setLatLng(view.center).setContent(labelContent(view.link)).addTo(layer);
          labels.set(id, label);
        } else if (!open && labels.has(id)) {
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

  function labelContent(link) {
    const box = text('div', '');
    const [a, b] = link.endpoints.map(name);
    box.append(text('strong', `${a} ↔ ${b}`));
    const groups = profilesOnMap(link);
    for (const group of groups) {
      const stat = el('stat').value;
      const sf = group.profile.spreading_factor;
      const title = groups.filter(other => other.profile.spreading_factor === sf).length > 1 ?
        profileName(group.profile) : sf == null ? 'Unbekannt' : `SF${sf}`;
      const describe = direction => direction ? traceMapSnrText(direction[stat]) : 'fehlt';
      box.append(text('div', `${title} · → ${describe(group.forward)} · ← ${describe(group.reverse)}`));
    }
    return box;
  }

  function style(link, id) {
    const groups = profilesOnMap(link);
    const forward = groups.some(group => group.forward), reverse = groups.some(group => group.reverse);
    return {color: forward ? '#3388ff' : '#d97706', weight: id === choice ? 6 : 4,
      opacity: .9, dashArray: forward && reverse ? null : '7 5'};
  }

  function reconcile() {
    if (!result || !visible) return;
    const available = new Map(result.links.filter(link => !link.endpoints.some((endpoint, i) =>
      repeaterMapVisibility.hidden(endpoint.public_key, 2, link.prefix_bytes[i]))).map(link => [key(link), link]));
    for (const [id, view] of views) {
      if (available.has(id)) continue;
      layer.removeLayer(view.line);
      if (labels.has(id)) layer.removeLayer(labels.get(id));
      labels.delete(id);
      views.delete(id);
    }
    if (!available.has(choice)) choice = '';
    for (const [id, link] of available) {
      if (views.get(id)?.link === link) continue;
      const points = link.positions.map(p => L.latLng(p.latitude, p.longitude));
      const center = L.latLng((points[0].lat + points[1].lat) / 2, (points[0].lng + points[1].lng) / 2);
      let old = views.get(id);
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
        .on('click', () => choose(id, true)).addTo(layer);
      if (labels.has(id)) labels.get(id).setLatLng(center).setContent(labelContent(link));
      views.set(id, {line, center, link, colocated});
    }
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
    const table = text('table', '', 'trace-link-table'), head = text('tr', '');
    for (const title of ['Observer-Funkprofil', 'Richtung', 'Anzahl', 'Zuletzt', 'Min.', 'Median', 'Max.', 'Erste / letzte Messung', 'Zuordnung']) {
      head.append(text('th', title));
    }
    const header = table.createTHead();
    header.append(head);
    const body = table.createTBody();
    for (const {profile, forward, reverse} of link.profiles) {
      const [a, b] = link.endpoints.map(name);
      for (const [direction, values] of [[`${a} → ${b}`, forward], [`${b} → ${a}`, reverse]]) {
        const row = body.insertRow();
        row.append(text('td', profileName(profile)), text('td', direction));
        if (!values) {
          const cell = text('td', 'Keine Messung');
          cell.colSpan = 7;
          row.append(cell);
          continue;
        }
        row.append(text('td', values.count), ...['last', 'min', 'median', 'max'].map(stat =>
          text('td', traceMapSnrText(values[stat]))), text('td', `${time(values.first_at)} / ${time(values.last_at)}`),
          text('td', Object.entries(values.quality).map(([quality, count]) => `${count} × ${qualityText[quality]}`).join(' · ')));
      }
    }
    const scroll = text('div', '', 'trace-link-scroll');
    scroll.append(table);
    const button = text('button', 'Einzelmessungen laden');
    button.type = 'button';
    button.onclick = () => loadSamples(items);
    panel.append(scroll, button, items);
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

  function choose(id, scroll = false) {
    const previous = choice;
    choice = id;
    el('pair').value = choice;
    for (const id of new Set([previous, choice])) {
      const view = views.get(id);
      if (view) view.line.setStyle(style(view.link, id));
    }
    renderDetails();
    if (scroll) el('detail').scrollIntoView({block: 'nearest'});
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
      const {summary, backfill} = result;
      const unmapped = Object.values(summary.unmapped_samples).reduce((total, n) => total + n, 0);
      const reasons = Object.entries(summary.unmapped_samples).map(([reason, n]) => `${locationIssues[reason]} ${n}`).join(', ');
      el('status').textContent = [
        `${result.links.length} Linkstrecken · ${summary.visible_samples} gerichtete Messwerte`,
        unmapped ? `${unmapped} Messwerte ohne Karte (${reasons})` : '',
        `Im Zeitraum ${summary.measurements} TRACE-Messungen, davon ${summary.partial} teilweise mitgehört`,
        summary.without_visible_links !== undefined ? `${summary.without_visible_links} ohne darstellbare Strecke` : '',
        summary.undecodable ? `${summary.undecodable} Empfänge nicht dekodierbar` : '',
        backfill.done ? '' : `Archivaufarbeitung läuft · ${backfill.scanned} TRACE-Empfänge gelesen`
      ].filter(Boolean).join(' · ');
      const previous = choice;
      repeaterMapVisibility.addKeys(result.links.flatMap(link => link.endpoints.map(node => node.public_key)));
      reconcile();
      renderDetails(!manual && choice === previous);
    } catch (error) {
      if (error.name !== 'AbortError') {
        dirty = true;
        el('status').textContent = `Linkstrecken konnten nicht geladen werden (${error.message}).`;
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
      renderer = L.canvas({padding: .25});
      layer = L.layerGroup();
      traceMap.on('zoomend moveend resize', scheduleLabels);
    }
    if (!visible) {
      visible = true;
      layer.addTo(traceMap);
      scheduleLabels();
    }
    if (paused) {
      if (controller || timer != null) dirty = true;
      controller?.abort();
      clearTimeout(timer); timer = null;
    } else if (dirty && !controller) refresh();
  }

  el('form').onsubmit = event => { event.preventDefault(); refresh(true); };
  el('period').onchange = () => {
    el('start').disabled = el('end').disabled = el('period').value !== 'custom';
    if (el('period').value !== 'custom' || el('start').value && el('end').value) refresh(true);
  };
  el('sf').onchange = () => refresh(true);
  el('stat').onchange = () => {
    for (const [id, label] of labels) label.setContent(labelContent(views.get(id).link));
  };
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
