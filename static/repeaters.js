const repeaterViews = new Map();

function repeaterView(item) {
  let view = repeaterViews.get(item.id);
  if (!view) {
    const element = text('details', '', 'repeater-entry');
    const summary = text('summary', '', 'repeater-row');
    const history = text('div', '', 'repeater-history');
    const label = text('label', 'RSSI-Verlauf · Zeitraum ');
    const select = document.createElement('select');
    for (const [value, title] of [[1, 'Letzte Stunde'], [3, '3 Stunden'], [24, '24 Stunden'], [168, '7 Tage'], [0, 'Gesamtes Archiv']]) {
      const option = text('option', title);
      option.value = value;
      select.append(option);
    }
    select.value = '24';
    label.append(select);
    const message = text('p', '', 'muted');
    message.setAttribute('role', 'status');
    const plot = text('div', '', 'noise-scroll');
    const tooltip = text('p', 'Messpunkt berühren, mit der Maus zeigen oder per Tab auswählen.', 'muted');
    history.append(label, message, plot, tooltip);
    element.append(summary, history);
    view = {element, summary, select, message, plot, tooltip, item, version: 0};
    repeaterViews.set(item.id, view);
    element.addEventListener('toggle', () => {
      if (element.open) loadRepeaterHistory(view);
    });
    select.addEventListener('change', () => {
      view.version += 1;
      view.loaded = null;
      view.loading = null;
      loadRepeaterHistory(view);
    });
  }
  view.item = item;
  return view;
}

async function loadRepeaterHistory(view) {
  if (paused || !view.element.open) return;
  const signature = JSON.stringify([view.item.count, view.item.tokens, view.select.value,
    view.select.value === '0' ? 0 : Math.floor(Date.now() / 60000)]);
  if (signature === view.loaded || signature === view.loading) return;
  const version = ++view.version;
  view.loading = signature;
  view.message.textContent = 'RSSI-Verlauf wird geladen …';
  try {
    const query = new URLSearchParams({identity: view.item.id, hours: view.select.value});
    const response = await fetch(`/api/repeater-history?${query}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    if (version !== view.version || paused || !view.element.isConnected) return;
    renderRepeaterHistory(view, result.items);
    view.message.textContent = result.items.length
      ? `${result.items.length} Messwerte${result.has_more ? ' · nur die neuesten 500 im Zeitraum' : ''} · lokale Empfangszeit · RSSI in dBm`
      : 'Keine RSSI-Messwerte in diesem Zeitraum archiviert.';
    view.loaded = signature;
  } catch (error) {
    if (version === view.version) view.message.textContent = `Verlauf konnte nicht geladen werden: ${error.message}. Automatischer erneuter Versuch folgt.`;
  } finally {
    if (version === view.version) view.loading = null;
  }
}

function renderRepeaterHistory(view, samples) {
  view.plot.replaceChildren();
  view.tooltip.textContent = 'Messpunkt berühren, mit der Maus zeigen oder per Tab auswählen.';
  if (!samples.length) return;
  const svg = (tag, attributes, content) => {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    if (content != null) node.textContent = content;
    return node;
  };
  const chart = svg('svg', {viewBox: '0 0 1000 240', class: 'repeater-chart', role: 'group',
    'aria-label': `RSSI-Verlauf für ${view.item.name}`});
  const start = samples[0].received, end = samples[samples.length - 1].received;
  const low = Math.min(...samples.map(p => p.rssi)) - 2;
  const high = Math.max(...samples.map(p => p.rssi)) + 2;
  const x = time => end === start ? 520 : 64 + (time - start) / (end - start) * 912;
  const y = value => 196 - (value - low) / (high - low) * 176;
  const tick = Math.max(1, Math.ceil((high - low) / 6));
  for (let value = Math.ceil(low / tick) * tick; value <= high; value += tick) {
    chart.append(svg('line', {x1: 64, x2: 976, y1: y(value), y2: y(value), class: 'noise-grid'}));
    chart.append(svg('text', {x: 54, y: y(value) + 4, 'text-anchor': 'end'}, value));
  }
  chart.append(svg('text', {x: 12, y: 12}, 'dBm'));
  const timeLabel = time => new Date(time * 1000).toLocaleString('de-DE');
  chart.append(svg('text', {x: 64, y: 225}, timeLabel(start)));
  if (end !== start) chart.append(svg('text', {x: 976, y: 225, 'text-anchor': 'end'}, timeLabel(end)));
  const series = new Map();
  for (const sample of samples) {
    const identity = sample.origin_id || null;
    if (!series.has(identity)) series.set(identity, []);
    series.get(identity).push(sample);
  }
  const legend = text('div', '', 'repeater-legend');
  const colors = ['var(--accent)', 'var(--blue)', 'var(--warning)', 'var(--purple)', 'var(--strong)'];
  for (const [index, identity] of [...series.keys()].sort().entries()) {
    const readings = series.get(identity);
    const observer = identity ? observerLabel(readings[readings.length - 1], true) : 'Unzugeordnet (ohne Observer-ID)';
    const color = colors[index % colors.length];
    const dash = ['', '8 4', '2 4', '8 3 2 3'][Math.floor(index / colors.length) % 4];
    const entry = text('span', '', 'repeater-legend-entry');
    const swatch = svg('svg', {width: 32, height: 12, 'aria-hidden': 'true'});
    const line = svg('line', {x1: 0, x2: 32, y1: 6, y2: 6, 'stroke-width': 2, 'stroke-dasharray': dash});
    line.style.stroke = color;
    swatch.append(line);
    entry.append(swatch, text('span', observer));
    legend.append(entry);
    const path = svg('path', {d: readings.map((p, i) => `${i ? 'L' : 'M'} ${x(p.received)} ${y(p.rssi)}`).join(' '), class: 'noise-step', 'stroke-dasharray': dash});
    path.style.stroke = color;
    chart.append(path);
    for (const sample of readings) {
      const label = `${sample.origin_id ? observerLabel(sample, true) : observer} · ${timeLabel(sample.received)} · ${sample.rssi} dBm`;
      const point = svg('circle', {cx: x(sample.received), cy: y(sample.rssi), r: 3.5,
        tabindex: 0, class: 'noise-point', 'aria-label': label});
      point.style.stroke = color;
      point.append(svg('title', {}, label));
      for (const event of ['pointerenter', 'focus', 'click']) {
        point.addEventListener(event, () => { view.tooltip.textContent = label; });
      }
      chart.append(point);
    }
  }
  view.plot.append(legend, chart);
}
