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
  const modes = {
    reserve: {title: 'Linkqualität', categories: {good: 'Gute Reserve', watch: 'Geringe Reserve',
      low: 'Sehr geringe Reserve', unknown: 'Nicht beurteilbar'}},
    asymmetry: {title: 'Asymmetrie', categories: {good: 'Ähnliche Richtungen', watch: 'Merklicher Unterschied',
      low: 'Großer Unterschied', unknown: 'Nicht vergleichbar'}},
    coverage: {title: 'Messabdeckung', categories: {good: 'Breit vermessen', watch: 'Teilweise vermessen',
      low: 'Dünn vermessen'}},
    sf7: {title: 'SF7-Reserveprognose', categories: {good: 'Gute geschätzte Reserve', watch: 'Geringe geschätzte Reserve',
      low: 'Sehr geringe geschätzte Reserve', unknown: 'Keine Prognose'}}
  };
  const colors = {good: '#008060', watch: '#ac7100', low: '#c42c44', unknown: '#626b77'};
  const coverageColors = {good: '#2059a0', watch: '#307fc7', low: '#668eb1'};
  const compactCategories = {
    reserve: {good: 'Gut', watch: 'Gering', low: 'Sehr gering', unknown: 'Offen'},
    asymmetry: {good: 'Ähnlich', watch: 'Merklich', low: 'Große Differenz', unknown: 'Offen'},
    coverage: {good: 'Breit', watch: 'Teilweise', low: 'Dünn'},
    sf7: {good: 'Gut', watch: 'Gering', low: 'Sehr gering', unknown: 'Offen'}
  };
  const strokes = {good: [], watch: [12, 5], low: [5, 5], unknown: [1, 4]};
  const incompleteStrokes = {good: [19, 4, 2, 4], watch: [12, 4, 2, 4, 2, 4], low: [6, 3, 2, 4], unknown: [3, 3, 1, 4]};
  let layer, renderer, hoverTooltip, hovered, result, query, filters, controller, detailsController, frame, timer;
  let choice = '', boundsSet = false, dirty = true, visible = false, revision, lastRequest = 0;
  let pendingResult, geometryPending = false;
  let tooltipControls = [];
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(settingsKey)) || {}; } catch { /* Optional persistence. */ }
  let labelMode = ['snr', 'full'].includes(saved.labelMode) ? saved.labelMode : 'none';
  let mode = Object.hasOwn(modes, saved.mode) ? saved.mode : 'reserve';
  let category = 'all';
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
    conflicting_status: 'Widersprüchlicher Observer-Status',
    unassigned: 'Fehlendes oder unvollständiges Profil', mixed: 'Mehrere Profile in derselben Richtung'
  };

  function saveView() {
    try { localStorage.setItem(settingsKey, JSON.stringify({labelMode, detailsOpen, panelWidth, mode,
      sort: el('sort').value, priority: el('priority').checked, stat: el('stat').value,
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
        const open = view.shown && zoom >= labelZoom[labelMode] && bounds.contains(view.center);
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
    box.append(text('div', `${categoryName(link)}${incomplete(link) ? ' · Richtungsdaten fehlen' : ''}`));
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

  function assessment(link, selectedMode = mode) {
    return link.analysis[selectedMode];
  }

  function categoryName(link) {
    return modes[mode].categories[assessment(link).category];
  }

  function incomplete(link) {
    return !link.coverage.forward || !link.coverage.reverse || assessment(link).directions === 1;
  }

  function needsAttention(link) {
    return assessment(link).category !== 'good' || incomplete(link);
  }

  function strokeColor(group) {
    return (mode === 'coverage' ? coverageColors : colors)[group];
  }

  function style(link, id) {
    const group = assessment(link).category;
    const pattern = (incomplete(link) ? incompleteStrokes : strokes)[group];
    return {color: strokeColor(group), weight: id === choice ? 7 : 4, fill: false, lineCap: 'butt',
      opacity: choice && id !== choice ? .55 : .9, dashArray: pattern.join(' ') || null};
  }

  function swatch(color, pattern) {
    const line = text('span', '', 'trace-link-swatch');
    line.setAttribute('aria-hidden', 'true');
    let offset = 0;
    const stops = pattern.map((length, index) => {
      const start = offset;
      offset += length;
      return `${index % 2 ? 'transparent' : color} ${start}px ${offset}px`;
    });
    line.style.background = pattern.length ? `repeating-linear-gradient(90deg, ${stops.join(', ')})` : color;
    return line;
  }

  function renderLegend() {
    const counts = {};
    for (const {link} of views.values()) {
      const group = assessment(link).category;
      counts[group] = (counts[group] || 0) + 1;
    }
    const buttons = el('categories');
    const focus = buttons.contains(document.activeElement) ? document.activeElement.dataset.category : null;
    buttons.replaceChildren();
    for (const [id, label] of [['all', 'Alle Strecken'], ...Object.entries(modes[mode].categories)]) {
      const count = id === 'all' ? views.size : counts[id] || 0;
      const button = text('button', '', 'trace-link-category');
      button.type = 'button';
      button.dataset.category = id;
      button.setAttribute('aria-pressed', String(id === category && !el('priority').checked));
      button.setAttribute('aria-label', `${count} ${label}`);
      if (id !== 'all') button.append(swatch(strokeColor(id), strokes[id]));
      const apply = id === category && !el('priority').checked ? 'all' : id;
      button.append(text('span', `${count} ${label}`, 'trace-link-category-full'),
        text('span', `${count} ${id === 'all' ? 'Alle' : compactCategories[mode][id]}`, 'trace-link-category-compact'));
      button.onclick = () => {
        category = apply;
        el('priority').checked = false;
        saveView();
        updatePresentation();
      };
      buttons.append(button);
      if (id === focus) button.focus({preventScroll: true});
    }
    const shown = [...views.values()].filter(view => view.shown).length;
    const rules = result.analysis_rules;
    const bounds = {
      reserve: `Gut ≥ ${rules.reserve_good_db} dB · gering ≥ ${rules.reserve_watch_db} dB`,
      asymmetry: `Ähnlich ≤ ${rules.asymmetry_good_db} dB · merklich ≤ ${rules.asymmetry_watch_db} dB`,
      coverage: 'Anzahl, Streuung, Aktualität und Profilzuordnung je Richtung',
      sf7: `Theoretische Schätzung aus SF8 · SF7-Referenz ${db(rules.demodulation_db[7])}`
    };
    el('legend').replaceChildren(text('span', bounds[mode]),
      text('span', '', 'trace-link-legend-direction'));
    const direction = el('legend').lastChild;
    direction.append(swatch(colors.unknown, incompleteStrokes.good), ' Richtungsdaten fehlen');
    if (el('priority').checked || category !== 'all') {
      el('legend').append(text('span', `${shown} von ${views.size} sichtbar`));
    }
    const excluded = result.links.length - views.size;
    if (excluded) el('legend').append(text('span', `${excluded} wegen Präfixkollision ausgeblendet`));
    el('analysis').hidden = false;
  }

  function sortLinks(a, b) {
    const sort = el('sort').value;
    const metric = link => {
      if (sort === 'last') return -Math.max(...Object.values(link.coverage).map(values => values?.last_at ?? 0));
      if (sort === 'distance') return link.distance_km ?? Infinity;
      if (sort === 'coverage') {
        const count = Math.min(...Object.values(link.coverage).map(values => values?.count ?? 0));
        return assessment(link, sort).score + count / (1 + count);
      }
      const value = assessment(link, sort).db;
      return value == null ? Infinity : sort === 'asymmetry' ? -value : value;
    };
    return metric(a) - metric(b) || linkName(a).localeCompare(linkName(b), 'de') || key(a).localeCompare(key(b));
  }

  function present() {
    if (!visible || !result) return;
    closeHover();
    const priority = el('priority').checked;
    const shown = [];
    for (const view of views.values()) {
      view.shown = (category === 'all' || assessment(view.link).category === category) &&
        (!priority || needsAttention(view.link));
      if (view.shown) shown.push(view.link);
    }
    if (!views.get(choice)?.shown) choice = '';
    const select = el('pair');
    select.replaceChildren(new Option(shown.length ? 'Linkstrecke wählen' : 'Keine Linkstrecke im Filter', ''),
      ...shown.sort(sortLinks).map(link => {
        const label = `${linkName(link)} · ${categoryName(link)}${incomplete(link) ? ' · Richtung offen' : ''}`;
        return new Option(label, key(link));
      }));
    select.value = choice;
    renderLegend();
    geometryPending = true;
    syncViewport();
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
      if (view.shown && !layer.hasLayer(view.line)) addPath(view.line);
      else if (!view.shown) layer.removeLayer(view.line);
      if (!labels.has(id)) continue;
      if (view.shown) labels.get(id).setContent(labelContent(view.link, labelMode === 'snr'));
      else {
        layer.removeLayer(labels.get(id));
        labels.delete(id);
      }
    }
    reconcilePositions();
    views.get(choice)?.line.bringToFront();
  }

  function reconcilePositions() {
    const wanted = new Map();
    const shownPositions = new Set();
    for (const {points, shown} of views.values()) {
      for (const point of points) {
        const id = `${point.lat}/${point.lng}`;
        wanted.set(id, point);
        if (shown) shownPositions.add(id);
      }
    }
    for (const [id, marker] of positions) {
      if (wanted.has(id)) continue;
      layer.removeLayer(marker);
      positions.delete(id);
    }
    for (const [id, point] of wanted) {
      let marker = positions.get(id);
      if (!marker) {
        marker = L.circleMarker(point, {radius: 3, interactive: false,
          color: '#374151', weight: 1, fillColor: '#fff', fillOpacity: .9});
        positions.set(id, marker);
      }
      const shown = shownPositions.has(id);
      if (shown === layer.hasLayer(marker)) continue;
      if (shown) addPath(marker).bringToBack();
      else layer.removeLayer(marker);
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
    present();
  }

  const directionKeys = ['forward', 'reverse'];
  const statisticName = {p10: 'P10', median: 'Median'};

  function describe(link, rules) {
    const finding = assessment(link);
    const group = link.profiles[finding.profile_index];
    const observed = link.coverage.forward && link.coverage.reverse
      ? 'Die Strecke wurde in beiden Richtungen beobachtet.'
      : 'TRACE-Werte liegen nur für eine Richtung vor.';
    const remarks = [observed];
    if (mode === 'coverage') {
      const counts = directionKeys.map(direction => link.coverage[direction]?.count ?? 0);
      const days = directionKeys.map(direction => link.coverage[direction]?.days ?? 0);
      remarks.push(`Hin- und Rückrichtung umfassen ${counts.join(' und ')} eindeutige TRACE-Messungen an ${days.join(' und ')} Tagen.`);
      const limits = finding.score === 1 ? rules.coverage_watch : rules.coverage_good;
      if (finding.score < 3) {
        const directions = Object.values(link.coverage).filter(Boolean);
        const reasons = [
          ['zu wenige Messungen', values => values.count < limits.count],
          ['zu kurze zeitliche Streuung', values => values.days < limits.days || values.span_hours < limits.span_hours],
          ['die letzte Messung liegt zu weit zurück', values => values.age_days > limits.age_days],
          ['zu wenige eindeutig zugeordnete Funkprofile', values => values.assigned < limits.assigned]
        ].filter(([, check]) => directions.some(check)).map(([label]) => label);
        if (reasons.length) remarks.push(`Einschränkungen in den beobachteten Richtungen · ${reasons.join(' · ')}.`);
      }
      return remarks.join(' ');
    }
    if (mode === 'sf7') {
      remarks.push('Die SF7-Reserve ist eine theoretische Schätzung aus empfangenen SF8-Werten. Ob die Strecke unter SF7 erreichbar wäre, bleibt offen.');
    }
    if (group) {
      const [a, b] = link.endpoints.map(name);
      if (mode === 'asymmetry') {
        const comparison = group.asymmetry;
        remarks.push(`Die Richtungen unterscheiden sich im Profil SF${group.profile.spreading_factor} um ${number(comparison.db)} dB. Der Vergleich beruht auf ${comparison.windows} Stundenfenstern mit Messungen in beiden Richtungen.`);
      } else {
        const value = group[finding.direction][mode];
        const path = finding.direction === 'forward' ? `${a} → ${b}` : `${b} → ${a}`;
        const side = finding.directions === 1 ? 'Bewertbar ist nur' : 'Die kleinere Reserve hat';
        remarks.push(`${side} ${path} mit ${db(value.db)} im Observer-Profil SF${group.profile.spreading_factor}. Grundlage ist der ${statisticName[value.statistic]} aus ${group[finding.direction].count} TRACE-Messungen.`);
        if (directionKeys.some(direction => group[direction]?.[mode]?.statistic === 'median')) {
          remarks.push('Bei kleinen Stichproben bleibt die Einstufung vorläufig.');
        }
      }
      if (directionKeys.some(direction => group[direction]?.quality.last_known)) {
        remarks.push('Die Profilzuordnung stützt sich auch auf zuvor gemeldete Observer-Einstellungen.');
      }
      return remarks.join(' ');
    }
    const selected = profilesOnMap(link);
    const groups = selected.filter(group => mode !== 'sf7' || group.profile.spreading_factor === 8);
    const complete = groups.filter(({profile}) => ['frequency_hz', 'bandwidth_hz', 'spreading_factor', 'coding_rate']
      .every(field => profile[field] != null));
    const qualities = new Set(selected.flatMap(group => directionKeys.flatMap(direction => Object.keys(group[direction]?.quality || {}))));
    if (!complete.length) {
      if (mode === 'sf7' && !groups.length) remarks.push('Im gewählten Filter fehlen eindeutig zugeordnete SF8-Werte.');
      if (qualities.has('conflicting_profiles') || qualities.has('conflicting_status')) {
        remarks.push('Für einen Teil der Messwerte liegen widersprüchliche Profilmeldungen vor.');
      } else if (qualities.has('uncertain')) remarks.push('Das Funkprofil zum Messzeitpunkt ist unsicher.');
      else if (groups.length || mode !== 'sf7') remarks.push('Für die Messwerte fehlt ein vollständiges Observer-Funkprofil.');
    } else if (mode === 'asymmetry') {
      remarks.push('Es fehlen ausreichend zeitnahe, ähnlich große Stichproben in beiden Richtungen desselben Funkprofils.');
    } else {
      remarks.push(`Je Richtung und Funkprofil braucht die Bewertung mindestens ${rules.median_min} eindeutige TRACE-Messungen.`);
    }
    return remarks.join(' ');
  }

  function readout(entries) {
    const list = text('dl', '', 'trace-link-stats');
    for (const [title, value] of entries) {
      const entry = text('div', '');
      entry.append(text('dt', title), text('dd', String(value)));
      list.append(entry);
    }
    return list;
  }

  function qualitySummary(quality) {
    return Object.entries(quality).map(([match, count]) => `${count} × ${qualityText[match]}`).join(' · ');
  }

  function coverageDetails(panel, link, paths) {
    const cards = text('div', '', 'trace-link-directions');
    directionKeys.forEach((direction, i) => {
      const values = link.coverage[direction];
      const card = text('section', '', 'trace-link-direction');
      card.append(text('h5', paths[i]));
      if (values) {
        card.append(readout([
          ['Eindeutige TRACE', values.count], ['Messtage (UTC)', values.days],
          ['Zeitspanne', `${number(values.span_hours)} h`], ['Alter', `${number(values.age_days)} d`],
          ['Profil zugeordnet', `${number(100 * values.assigned, 0)} %`]
        ]), text('p', `Erste / letzte Messung · ${time(values.first_at)} / ${time(values.last_at)}`),
        text('p', qualitySummary(values.quality)));
      } else card.append(text('p', 'Keine Messung', 'muted'));
      cards.append(card);
    });
    panel.append(cards);
  }

  function directionDetails(profile, paths, expert) {
    const cards = text('div', '', 'trace-link-directions');
    directionKeys.forEach((direction, i) => {
      const values = profile[direction];
      const card = text('section', '', 'trace-link-direction');
      card.append(text('h5', paths[i]));
      if (values) {
        const fields = expert
          ? [['Min.', db(values.min)], ['P10', db(values.p10)], ['Median', db(values.median)],
            ['P90', db(values.p90)], ['Max.', db(values.max)], ['Stichprobe', values.count]]
          : [['Median-SNR', db(values.median)], ['Letzter SNR', db(values.last)], ['Stichprobe', values.count]];
        for (const [mode, label] of [['reserve', 'Nominelle Reserve'], ['sf7', 'SF7-Reserve (geschätzt)']]) {
          if (mode === 'sf7' && profile.profile.spreading_factor !== 8) continue;
          const estimate = values[mode];
          const evidence = estimate?.statistic === 'median' ? 'Median, vorläufig' : 'P10';
          fields.push([label, estimate ? `${db(estimate.db)} (${evidence})` : '—']);
        }
        card.append(readout(fields));
        if (!expert) card.append(text('p', `Erste / letzte Messung · ${time(values.first_at)} / ${time(values.last_at)}`),
          text('p', qualitySummary(values.quality)));
      } else card.append(text('p', 'Keine Messung', 'muted'));
      cards.append(card);
    });
    return cards;
  }

  function rulesText(rules) {
    const coverage = ['good', 'watch'].map(group => {
      const cutoffs = rules[`coverage_${group}`];
      return `${group === 'good' ? 'Breit' : 'Teilweise'} ab ${cutoffs.count} TRACE an ${cutoffs.days} UTC-Tagen, mindestens ${cutoffs.span_hours} h Zeitspanne, letzte Messung höchstens ${cutoffs.age_days} Tage alt, mindestens ${number(100 * cutoffs.assigned)} % Profilzuordnung je Richtung.`;
    });
    return [
      'Jeder korrelierte TRACE zählt je Richtung und exakt gemeldetem Observer-Profil einmal. Bei mehrfach durchlaufener Richtung zählt der kleinste SNR. P10, Median und P90 werden linear an Rang (n − 1) × p interpoliert.',
      `Die Reserve ist SNR minus nominelle Referenz. Median ab ${rules.median_min} TRACE je Richtung, P10 ab ${rules.p10_min}. Grün ab ${rules.reserve_good_db} dB, Gelb ab ${rules.reserve_watch_db} dB. Rot liegt darunter. Maßgeblich ist die kleinste berechenbare Reserve eines einzelnen Profils.`,
      `LoRa-Referenzen in dB · ${Object.entries(rules.demodulation_db).map(([sf, value]) => `SF${sf} ${db(value)}`).join(' · ')}`,
      `Asymmetrie ist der Betrag der medianen Richtungsdifferenz aus mindestens ${rules.asymmetry_windows_min} gemeinsamen Zeitfenstern zu je ${rules.asymmetry_window_hours} h (UTC). Pro Fenster darf das Stichprobenverhältnis höchstens ${rules.asymmetry_max_ratio}:1 betragen. Insgesamt braucht es mindestens ${rules.asymmetry_min} TRACE je Richtung. Grün bis ${rules.asymmetry_good_db} dB, Gelb bis ${rules.asymmetry_watch_db} dB, darüber Rot. Maßgeblich ist die größte vergleichbare Differenz eines Profils.`,
      ...coverage,
      'Die Profile stammen aus den Statusmeldungen der beteiligten Observer. Die Funkeinstellungen der TRACE-Sender bleiben offen. Hardware, Firmware und Coding Rate können die nominelle Reserve und die SF7-Schätzung beeinflussen. Die Stichproben beschreiben empfangene TRACE-Werte. Die Zustellwahrscheinlichkeit bleibt offen.'
    ];
  }

  function chart(title, series, xLabel, formatX, connect = false) {
    const canvas = text('canvas', '', 'trace-link-chart');
    canvas.width = 430;
    canvas.height = 180;
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', title);
    const wrap = text('figure', '');
    wrap.append(canvas, text('figcaption', `${title} · ${xLabel} · SNR in dB · ○ Hinrichtung · × Rückrichtung`));
    const draw = () => {
      const context = canvas.getContext('2d');
      const theme = getComputedStyle(document.documentElement);
      const points = series.flat();
      const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
      const left = 48, right = 403, top = 16, bottom = 148;
      const xMin = Math.min(...xs), xMax = Math.max(...xs), xSpan = xMax - xMin;
      const yMin = Math.floor(Math.min(...ys)) - 1, yMax = Math.ceil(Math.max(...ys)) + 1;
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
      for (const value of ticks) {
        context.textAlign = !xSpan ? 'center' : value === xMin ? 'left' : 'right';
        context.fillText(formatX(value), x(value), bottom + 20);
      }
      series.forEach((readings, i) => {
        context.strokeStyle = theme.getPropertyValue(i ? '--purple' : '--blue');
        context.lineWidth = 2;
        if (connect && readings.length) {
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

  function quantileChart(group) {
    const collapse = text('details', '');
    collapse.append(text('summary', 'SNR-Verteilung anzeigen'));
    collapse.addEventListener('toggle', () => {
      if (!collapse.open || collapse.childNodes.length > 1) return;
      const series = directionKeys.map(direction => group[direction] ? [
        [0, 'min'], [10, 'p10'], [50, 'median'], [90, 'p90'], [100, 'max']
      ].map(([part, label]) => [part, group[direction][label]]) : []);
      collapse.replaceChildren(collapse.firstChild,
        chart('SNR-Verteilung', series, 'Perzentil', value => `${value} %`, true));
    });
    return collapse;
  }

  function renderDetails(preserveSamples = false) {
    if (!preserveSamples) detailsController?.abort();
    const panel = el('detail');
    const link = views.get(choice)?.link;
    const expertOpen = panel.querySelector('.trace-link-expert')?.open;
    const items = (preserveSamples && panel.querySelector('.trace-link-samples')) || text('div', '', 'trace-link-samples');
    panel.replaceChildren();
    if (!link) return;
    const rules = result.analysis_rules;
    const [a, b] = link.endpoints.map(name);
    const paths = [`${a} → ${b}`, `${b} → ${a}`];
    const verdict = text('section', '', 'trace-link-verdict');
    verdict.append(text('strong', categoryName(link)), text('p', describe(link, rules)));
    panel.append(text('h3', linkName(link)), verdict);

    const technical = text('section', '', 'trace-link-technical');
    technical.append(text('h4', 'Messübersicht'),
      text('p', link.distance_km == null ? 'Entfernung unbekannt' :
        `Luftlinie ${number(link.distance_km)} km · Standortbeleg ${time(link.position_at)}`));
    const identities = text('ul', '', 'trace-link-identities');
    for (const endpoint of link.endpoints) {
      const item = text('li', `${name(endpoint)} · `);
      item.append(text('code', endpoint.public_key));
      identities.append(item);
    }
    const identityDetails = text('details', '', 'trace-link-identity-details');
    identityDetails.append(text('summary', 'Repeater-IDs'), identities);
    technical.append(identityDetails);
    coverageDetails(technical, link, paths);
    const driver = link.profiles[assessment(link).profile_index];
    for (const group of profilesOnMap(link)) {
      const section = text('section', '', 'trace-link-profile');
      section.append(text('h4', profileName(group.profile) + (group === driver ? ' · Maßgeblich' : '')),
        directionDetails(group, paths, false));
      technical.append(section);
    }
    panel.append(technical);

    const expert = text('details', '', 'trace-link-expert');
    expert.open = preserveSamples && Boolean(expertOpen);
    expert.append(text('summary', 'Expertenansicht'));
    const methods = text('details', '', 'trace-link-methods');
    methods.append(text('summary', 'Bewertungsverfahren und Schwellen'),
      ...rulesText(rules).map(line => text('p', line)));
    expert.append(methods, text('p', `Kürzeste kartierbare Präfixe in Endpunktreihenfolge · ${link.prefix_bytes.join(' / ')} Byte`));
    const selectedProfiles = new Set(profilesOnMap(link));
    for (const group of link.profiles) {
      const section = text('section', '', 'trace-link-profile');
      section.append(text('h4', profileName(group.profile) + (selectedProfiles.has(group) ? '' : ' · Außerhalb des Profilfilters')));
      const asym = group.asymmetry;
      let comparison = 'Für dieses Profil fehlen vergleichbare Richtungsdaten.';
      if (asym) {
        comparison = `Asymmetrie ${number(asym.db)} dB · Hinrichtung minus Rückrichtung ${db(asym.signed_db)} · ${asym.windows} gemeinsame Fenster · ${asym.counts.join(' / ')} TRACE`;
      }
      section.append(text('p', comparison), directionDetails(group, paths, true), quantileChart(group));
      expert.append(section);
    }
    const button = text('button', 'Einzelmessungen laden');
    button.type = 'button';
    button.onclick = () => loadSamples(items);
    expert.append(button, items);
    panel.append(expert);
  }

  function historyChart(items, firstKey) {
    const details = text('details', '');
    details.append(text('summary', 'SNR-Verlauf dieser Seite anzeigen'));
    details.addEventListener('toggle', () => {
      if (!details.open || details.childNodes.length > 1) return;
      const profiles = new Map();
      for (const item of items) {
        const id = JSON.stringify(item.profile);
        if (!profiles.has(id)) profiles.set(id, [[], []]);
        profiles.get(id)[item.source === firstKey ? 0 : 1].push([item.time, item.snr]);
      }
      const select = text('select', '');
      for (const id of profiles.keys()) select.add(new Option(profileName(JSON.parse(id)), id));
      const label = text('label', 'Diagrammprofil ');
      label.append(select);
      const plot = text('div', '');
      const stamp = value => new Date(value * 1000).toLocaleString('de-DE', {dateStyle: 'short', timeStyle: 'short'});
      select.onchange = () => plot.replaceChildren(chart('SNR-Verlauf', profiles.get(select.value), 'Ereigniszeit', stamp));
      details.append(label, plot);
      select.onchange();
    });
    return details;
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
      panel.replaceChildren(text('p', `${data.total} gerichtete Hop-Werte im gewählten Funkprofilfilter`));
      if (data.observers?.length) {
        const observers = text('details', '');
        observers.append(text('summary', `${data.observers.length} beteiligte Observer mit bekannter ID`));
        const ids = text('ul', '');
        ids.append(...data.observers.map(id => text('li', id)));
        observers.append(ids);
        panel.append(observers);
      }
      if (data.items.length) panel.append(historyChart(data.items, a), list);
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

  function updatePresentation(explain = false) {
    const previous = choice;
    present();
    if (explain || previous !== choice) renderDetails(previous === choice);
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
    el('status').dataset.state = backfill.done ? 'ready' : 'backfill';
    el('status').textContent = [
      `${linkCount} · ${summary.visible_samples} gerichtete Messwerte · ${summary.measurements} TRACE-Messungen`,
      backfill.done ? '' : `Archivaufarbeitung läuft · ${backfill.scanned} TRACE-Empfänge gelesen`
    ].filter(Boolean).join(' · ');
    const unmapped = Object.values(summary.unmapped_samples).reduce((total, n) => total + n, 0);
    const notes = [
      summary.unmapped_measurements ? `${summary.unmapped_measurements} TRACE mit gerichteten Werten im Profilfilter ohne kartierbare Strecke` : '',
      summary.partial ? `${summary.partial} TRACE-Messungen teilweise mitgehört` : '',
      summary.without_visible_links ? `${summary.without_visible_links} TRACE ohne darstellbare Linkstrecke im gesamten Zeitraum` : '',
      summary.undecodable ? `${summary.undecodable} TRACE-Empfänge nicht dekodierbar` : '',
      ...Object.entries(summary.unmapped_samples).map(([reason, n]) => `${traceLocationIssues[reason]} · ${n}`)
    ].filter(Boolean);
    el('coverage-title').textContent = unmapped ? `${unmapped} Messwert${unmapped === 1 ? '' : 'e'} ohne Karte` : 'Zum Messbestand';
    el('coverage-list').replaceChildren(...notes.map(note => text('li', note)));
    el('coverage').hidden = !notes.length;
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
    renderStatus(result);
    const previous = choice;
    repeaterMapVisibility.addKeys(result.links.flatMap(link => link.endpoints.map(node => node.public_key)));
    pendingResult = null;
    reconcile();
    renderDetails(!manual && choice === previous);
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
      el('coverage').hidden = true;
      return;
    }
    controller?.abort();
    const request = controller = new AbortController();
    const params = new URLSearchParams({start, end, sf});
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
        detailsController?.abort();
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
      traceMap.on('resize', sizeTooltips);
      traceMap.on('zoomend moveend resize', scheduleLabels);
      traceMap.on('zoomstart movestart resize', closeHover);
    }
    const opening = !visible;
    visible = true;
    if (pendingResult && !paused) applyResult();
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
  for (const id of ['period', 'sf', 'stat', 'sort']) {
    if (id === 'sf' && ![...el(id).options].some(option => option.value === saved.sf) && /^(?:[5-9]|1[0-2])$/.test(saved.sf)) {
      el(id).add(new Option(`SF${saved.sf}`, saved.sf));
    }
    if ([...el(id).options].some(option => option.value === saved[id])) el(id).value = saved[id];
  }
  for (const id of ['start', 'end']) el(id).value = saved[id] || '';
  el('mode').value = mode;
  el('mode').onchange = () => {
    mode = el('mode').value;
    category = 'all';
    saveView();
    updatePresentation(true);
  };
  el('priority').checked = saved.priority === true;
  el('priority').onchange = () => {
    category = 'all';
    saveView();
    updatePresentation();
  };
  el('sort').onchange = () => {
    saveView();
    updatePresentation();
  };
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
    if (visible && result && !pendingResult) {
      const previous = choice;
      reconcile();
      if (previous !== choice) renderDetails();
    }
  });
  return {sync, resize: () => syncViewport(true), receive(value, snapshot) {
    if (value == null || value === revision && !snapshot) return;
    const first = revision == null;
    revision = value;
    if (first && !result && !controller) return;
    dirty = true;
    scheduleRefresh();
  }};
})();
