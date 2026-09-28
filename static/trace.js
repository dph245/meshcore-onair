let traceRequest = 0;
let traceController;
let traceHistories = [];

function traceNode(node) {
  return node.name ? `${node.name} [${node.hash}]`
    : `${node.hash}${node.ambiguous ? ' (mehrdeutig)' : ''}`;
}

function renderTraces(items) {
  const container = document.getElementById('trace-results');
  const opened = new Set([...container.querySelectorAll('details[open]')].map(node => node.dataset.id));
  container.replaceChildren(...items.map(item => {
    const entry = text('details', '', 'discovery-entry');
    entry.dataset.id = String(item.id);
    entry.open = opened.has(String(item.id));
    const weakest = item.weakest_snr == null ? 'Noch keine SNR-Werte'
      : `Niedrigster SNR: ${item.weakest_snr} dB (Hop ${item.weakest_hops.join(', ')})`;
    entry.append(text('summary', `${new Date(item.first_seen * 1000).toLocaleString('de-DE')} · ${item.observed_hops}/${item.hops.length} Hops gemessen · ${weakest}`));
    entry.append(text('p', `Route: ${item.hops.map(traceNode).join(' → ') || 'Leer'}`));
    entry.append(text('p', `Tag ${item.tag} · ${item.scope} · ${item.receptions} Empfänge`, 'muted'));
    entry.append(text('p', `Observer: ${item.observers.map(o => o.id ? `${o.name} [${o.id}]` : o.name).join(', ')}`, 'muted'));
    for (const [index, hop] of item.hops.entries()) {
      const snr = hop.snr_min == null ? 'Nicht mitgehört'
        : `${hop.snr_min === hop.snr_max ? hop.snr_min : `${hop.snr_min} bis ${hop.snr_max}`} dB`;
      entry.append(text('div', `Hop ${index + 1}: ${traceNode(hop)} · ${snr}`, 'reception'));
    }
    return entry;
  }));
}

function traceSvg(tag, attributes, value) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [name, content] of Object.entries(attributes)) node.setAttribute(name, String(content));
  if (value != null) node.textContent = value;
  return node;
}

function renderTraceHistory() {
  const container = document.getElementById('trace-history');
  container.replaceChildren();
  const history = traceHistories.find(h => String(h.id) === document.getElementById('trace-route').value);
  if (!history) return;
  if (history.point_count > history.points.length) {
    container.append(text('p', `Verlauf auf die neuesten ${history.points.length} von ${history.point_count} Messgruppen dieser Route begrenzt.`, 'muted'));
  }
  const values = history.points.flatMap(p => p.snr_min.filter(v => v != null));
  if (!values.length) {
    container.append(text('p', 'Für diese Route wurden noch keine SNR-Werte mitgehört.', 'muted'));
    return;
  }
  const low = Math.floor(Math.min(...values) / 5) * 5 - 5;
  const high = Math.ceil(Math.max(...values) / 5) * 5 + 5;
  const first = history.points[0].time, last = history.points.at(-1).time;
  const x = time => first === last ? 350 : 60 + (time - first) / (last - first) * 580;
  const y = snr => 230 - (snr - low) / (high - low) * 200;
  const svg = traceSvg('svg', {viewBox: '0 0 700 280', class: 'trace-chart', role: 'img',
    'aria-label': 'SNR-Verlauf pro Routen-Hop; Messpunkte per Tastatur oder Maus auswählbar'});
  for (let i = 0; i <= 4; i++) {
    const value = low + (high - low) * i / 4;
    svg.append(traceSvg('line', {x1: 60, x2: 640, y1: y(value), y2: y(value), class: 'noise-grid'}));
    svg.append(traceSvg('text', {x: 52, y: y(value) + 4, 'text-anchor': 'end'}, `${value} dB`));
  }
  const ticks = first === last ? [[first, 'middle']] : [[first, 'start'], [last, 'end']];
  for (const [time, anchor] of ticks) {
    svg.append(traceSvg('text', {x: x(time), y: 260, 'text-anchor': anchor}, new Date(time * 1000).toLocaleString('de-DE')));
  }
  const tooltip = text('p', 'Messpunkt auswählen für Zeit, Hop und SNR-Bereich.', 'muted');
  tooltip.setAttribute('role', 'status');
  const legend = text('div', '', 'trace-legend');
  const colors = ['#279ec7', '#dc862a', '#8d71d4', '#3da76c', '#de668b', '#989831'];
  history.route.forEach((hop, index) => {
    const color = colors[index % colors.length];
    const label = text('span', `Hop ${index + 1}: ${traceNode(hop)}`);
    label.style.borderColor = color;
    legend.append(label);
    let previous = null;
    for (const point of history.points) {
      const value = point.snr_min[index];
      if (value == null) { previous = null; continue; }
      const current = {x: x(point.time), y: y(value)};
      if (previous) svg.append(traceSvg('line', {x1: previous.x, y1: previous.y,
        x2: current.x, y2: current.y, stroke: color, 'stroke-width': 2}));
      const description = `${new Date(point.time * 1000).toLocaleString('de-DE')} · Tag ${point.tag} · Hop ${index + 1}: ${traceNode(hop)} · SNR ${value} bis ${point.snr_max[index]} dB`;
      const circle = traceSvg('circle', {cx: current.x, cy: current.y, r: 4, fill: color,
        tabindex: 0, 'aria-label': description});
      circle.append(traceSvg('title', {}, description));
      for (const event of ['focus', 'mouseenter', 'click']) circle.addEventListener(event, () => { tooltip.textContent = description; });
      svg.append(circle);
      previous = current;
    }
  });
  const scroll = text('div', '', 'noise-scroll');
  scroll.append(svg);
  container.append(scroll, legend, tooltip);
}

async function loadTraces() {
  if (paused || document.getElementById('panel-trace').hidden) return;
  const version = ++traceRequest;
  traceController?.abort();
  const controller = traceController = new AbortController();
  const status = document.getElementById('trace-status');
  status.textContent = 'TRACE-Messungen werden geladen …';
  try {
    const hours = document.getElementById('trace-hours').value;
    const response = await fetch(`/api/traces?hours=${encodeURIComponent(hours)}`, {signal: controller.signal});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    if (version !== traceRequest || paused || document.getElementById('panel-trace').hidden) return;
    renderTraces(result.items);
    const select = document.getElementById('trace-route');
    const selected = traceHistories.find(h => String(h.id) === select.value);
    traceHistories = result.histories;
    const options = traceHistories.map(history => {
      const option = text('option', `${history.route.map(traceNode).join(' → ') || 'Leere Route'} · ${history.scope} · ${history.point_count} Messgruppen`);
      option.value = String(history.id);
      return option;
    });
    select.replaceChildren(...options);
    select.disabled = !options.length;
    // Keep the route selection even when the first session leaves the time window.
    const same = selected && traceHistories.find(h => h.scope === selected.scope
      && h.route.map(n => n.hash).join(',') === selected.route.map(n => n.hash).join(','));
    select.value = same ? String(same.id) : options[0]?.value || '';
    renderTraceHistory();
    status.textContent = result.items.length
      ? `${result.items.length} Messgruppen · ${result.scanned} TRACE-Empfänge im Zeitraum`
      : 'Keine auswertbaren TRACE-Messungen im gewählten Zeitraum.';
    if (result.truncated) status.textContent += ' · Auf die neuesten 5000 Empfänge begrenzt; Gruppen und Verläufe können unvollständig sein.';
    if (result.more_sessions) status.textContent += ' · Nur die neuesten 100 Messgruppen angezeigt; der Verlauf berücksichtigt auch ältere Gruppen im geladenen Zeitraum.';
    if (result.more_routes) status.textContent += ' · Nur die neuesten 100 Routen im Verlauf auswählbar.';
    if (result.ignored) status.textContent += ` · ${result.ignored} nicht auswertbare Empfänge ausgelassen.`;
  } catch (error) {
    if (version === traceRequest && error.name !== 'AbortError' && !paused) {
      status.textContent = `TRACE konnte nicht geladen werden: ${error.message}. Erneuter Versuch folgt automatisch.`;
    }
  }
}

document.getElementById('trace-search').addEventListener('submit', event => { event.preventDefault(); loadTraces(); });
document.getElementById('trace-hours').addEventListener('change', loadTraces);
document.getElementById('trace-route').addEventListener('change', renderTraceHistory);
setInterval(loadTraces, 10000);
