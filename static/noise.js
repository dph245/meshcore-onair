// Raw readings only: horizontal hold, then a vertical jump at the next receipt.
function noiseGeometry(samples) {
  const times = samples.map(sample => Date.parse(sample.received_at));
  const values = samples.map(sample => sample.noise_floor);
  const start = Math.min(...times), end = Math.max(...times);
  const low = Math.min(...values) - 1, high = Math.max(...values) + 1;
  const x = time => end === start ? 520 : 64 + (time - start) / (end - start) * 912;
  const y = value => 196 - (value - low) / (high - low) * 176;
  const points = samples.map((sample, i) => ({x: x(times[i]), y: y(sample.noise_floor), sample}));
  // Sort by receipt time in case the host clock was corrected backwards.
  points.sort((a, b) => Date.parse(a.sample.received_at) - Date.parse(b.sample.received_at));
  const path = points.map((p, i) => i ? `H ${p.x} V ${p.y}` : `M ${p.x} ${p.y}`).join(' ');
  return {points, path, start, end, low, high, y};
}

let noiseRendered = '';
const noiseObserverMaxAge = 24 * 60 * 60 * 1000;
function noiseObserverActive(sample, now = Date.now()) {
  return Date.parse(sample.status_at || sample.received_at) > now - noiseObserverMaxAge;
}
function noiseSeries(samples) {
  const series = new Map();
  for (const sample of samples) {
    const key = sample.origin_id || null;
    if (!series.has(key)) series.set(key, []);
    series.get(key).push(sample);
  }
  return [...series.values()];
}
function renderNoise(samples, now = Date.now()) {
  const activeSeries = noiseSeries(samples).filter(series =>
    noiseObserverActive(series[series.length - 1], now));
  const signature = JSON.stringify(activeSeries);
  if (signature === noiseRendered) return;
  noiseRendered = signature;
  const results = document.getElementById('noise-charts');
  results.replaceChildren();
  document.getElementById('noise-empty').hidden = activeSeries.length > 0;
  for (const series of activeSeries) {
    const latest = series[series.length - 1];
    const label = observerLabel(latest, true);
    const section = text('section', '', 'noise-observer');
    const heading = text('h3', `${label} · ${latest.noise_floor} dBm`);
    heading.title = observerLabel(latest);
    section.append(heading);
    section.append(text('p', `${series.length} Messwerte · letzter Status: ${new Date(latest.status_at || latest.received_at).toLocaleString('de-DE')}`, 'muted'));
    const scroll = text('div', '', 'noise-scroll');
    const chart = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    chart.setAttribute('viewBox', '0 0 1000 240');
    chart.setAttribute('role', 'group');
    chart.setAttribute('class', 'noise-chart');
    chart.setAttribute('aria-label', `Noise Floor: ${label} in dBm`);
    const tooltip = text('p', 'Messpunkt berühren, mit der Maus zeigen oder per Tab auswählen: exakte Empfangszeit und dBm.', 'noise-tooltip');
    tooltip.setAttribute('role', 'status');
    renderNoiseChart(series, chart, tooltip);
    scroll.append(chart);
    section.append(scroll, tooltip);
    results.append(section);
  }
}
function renderNoiseChart(samples, chart, tooltip) {
  const svg = (tag, attributes, content) => {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    if (content != null) node.textContent = content;
    return node;
  };
  const {points, path, start, end, low, high, y} = noiseGeometry(samples);
  const tick = Math.max(1, Math.ceil((high - low) / 6));
  for (let value = Math.ceil(low / tick) * tick; value <= high; value += tick) {
    chart.append(svg('line', {x1: 64, x2: 976, y1: y(value), y2: y(value), class: 'noise-grid'}));
    chart.append(svg('text', {x: 54, y: y(value) + 4, 'text-anchor': 'end'}, value));
  }
  chart.append(svg('text', {x: 12, y: 12}, 'dBm'));
  const timeLabel = time => new Date(time).toLocaleString('de-DE');
  chart.append(svg('text', {x: 64, y: 225}, timeLabel(start)));
  if (end !== start) chart.append(svg('text', {x: 976, y: 225, 'text-anchor': 'end'}, timeLabel(end)));
  chart.append(svg('path', {d: path, class: 'noise-step'}));
  for (const point of points) {
    const label = `${observerLabel(point.sample, true)} · ${point.sample.received_at} · ${point.sample.noise_floor} dBm · lokale MQTT-Empfangszeit`;
    const marker = svg('circle', {cx: point.x, cy: point.y, r: 3.5, tabindex: 0,
      class: 'noise-point', 'aria-label': label});
    marker.append(svg('title', {}, label));
    const show = () => { tooltip.textContent = label; };
    marker.addEventListener('pointerenter', show);
    marker.addEventListener('focus', show);
    marker.addEventListener('click', show);
    chart.append(marker);
  }
}
