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

const noiseViews = new Map();
const noiseObserverMaxAge = 24 * 60 * 60 * 1000;
function noiseObserverActive(sample, now = Date.now()) {
  return Date.parse(sample.status_at || sample.received_at) > now - noiseObserverMaxAge;
}

const observerStatusRows = new Map();
const observerActivityLimits = Object.freeze({
  activeMs: 15 * 60 * 1000,
  visibleMs: 24 * 60 * 60 * 1000,
});
const radioParameterMaxAge = 24 * 60 * 60 * 1000;
const headerRadioFields = ['frequency_hz', 'bandwidth_hz', 'spreading_factor', 'coding_rate'];
const radioNumber = new Intl.NumberFormat('de-DE', {maximumFractionDigits: 6, useGrouping: false});

function renderObserverStatus(activity, readings, radios, connected, now = Date.now()) {
  const container = document.getElementById('noise-floor');
  const observers = new Map();
  for (const [id, contact] of Object.entries(activity)) {
    const age = now - contact.last_contact * 1000;
    if (age <= observerActivityLimits.visibleMs) {
      observers.set(id, {origin: contact.origin, offline: age >= observerActivityLimits.activeMs});
    }
  }
  const latestNoise = new Map();
  for (const reading of readings) {
    if (!noiseObserverActive(reading, now)) continue;
    const id = reading.origin_id?.trim() || '';
    const key = /^[0-9a-f]{64}$/i.test(id) ? id.toLowerCase() : id;
    const previous = latestNoise.get(key);
    if (!previous || Date.parse(reading.status_at || reading.received_at) >=
                     Date.parse(previous.status_at || previous.received_at)) {
      latestNoise.set(key, reading);
    }
  }
  const profiles = new Map(radios.map(radio => [radio.origin_id, radio]));

  if (!observers.size) {
    if (observerStatusRows.size) {
      container.textContent = 'Noise Floor: —';
      observerStatusRows.clear();
    }
    return;
  }
  if (!observerStatusRows.size) container.textContent = '';
  for (const [id, row] of observerStatusRows) {
    if (!observers.has(id)) {
      row.element.remove();
      observerStatusRows.delete(id);
    }
  }
  for (const [id, {origin, offline}] of observers) {
    const radio = profiles.get(id);
    const reading = latestNoise.get(id);
    const observer = {origin_id: id || null, origin: origin || reading?.origin || radio?.origin};
    const aged = radio && headerRadioFields.some(field =>
      radio.field_times[field] != null && radio.field_times[field] * 1000 <= now - radioParameterMaxAge);
    const noise = connected ? reading?.noise_floor : null;
    const noiseAt = reading?.status_at || reading?.received_at;
    let row = observerStatusRows.get(id);
    if (!row) {
      const element = text('span', '', 'observer-status-row');
      const reading = text('span', '', 'observer-reading');
      const label = text('span', '', 'observer-name');
      const noiseReading = text('span', '');
      const profile = text('span', '', 'observer-radio');
      const band = text('span', '');
      const sf = text('strong', '');
      const rate = text('span', '');
      reading.append(label, noiseReading);
      profile.append(band, sf, rate);
      element.append(reading, profile);
      container.append(element);
      row = {element, label, noiseReading, band, sf, rate};
      observerStatusRows.set(id, row);
    }
    const signature = [radio, aged, noise, noiseAt, observer.origin, connected, offline];
    if (row.signature?.every((value, index) => value === signature[index])) continue;
    row.signature = signature;
    row.element.classList.toggle('observer-offline', offline);
    const fields = radio?.profile || {};
    const hasRadio = headerRadioFields.some(field => fields[field] != null);
    const suffix = radio?.ambiguous ? ' · widersprüchlich' : aged ? ' · veraltet'
      : hasRadio && !connected ? ' · zuletzt gemeldet' : '';
    const freq = fields.frequency_hz == null ? 'Frequenz —' : `${radioNumber.format(fields.frequency_hz / 1e6)} MHz`;
    const bw = fields.bandwidth_hz == null ? 'BW —' : `BW ${radioNumber.format(fields.bandwidth_hz / 1e3)} kHz`;
    const label = observerLabel(observer, true);
    const band = hasRadio ? `${freq} · ${bw} · ` : `Funkprofil unbekannt${suffix}`;
    const sf = hasRadio ? `SF${fields.spreading_factor ?? ' —'}` : '';
    const rate = hasRadio ? ` · CR ${fields.coding_rate == null ? '—' : '4/' + fields.coding_rate}${suffix}` : '';
    const noiseValue = `· ${measurement(noise, 'dBm')}${offline ? ' · Offline' : ''}`;
    for (const [element, value] of [[row.label, label], [row.noiseReading, noiseValue],
                                   [row.band, band], [row.sf, sf], [row.rate, rate]]) {
      if (element.textContent !== value) element.textContent = value;
    }
    const details = [`${observerLabel(observer)} ${noiseValue}`, band + sf + rate];
    if (noiseAt) details.push(`Noise Floor · ${new Date(noiseAt).toLocaleString('de-DE')}`);
    if (radio) {
      details.push(`Letzte Profilangabe · ${new Date(radio.last_confirmed_at * 1000).toLocaleString('de-DE')}`);
      if (fields.firmware || fields.firmware_version) {
        details.push([fields.firmware, fields.firmware_version].filter(Boolean).join(' '));
      }
      if (fields.radio_ic) details.push(fields.radio_ic);
      if (fields.tx_power_dbm != null) details.push(`TX ${fields.tx_power_dbm} dBm`);
      if (fields.preamble_length != null) details.push(`Präambel ${fields.preamble_length} Symbole`);
      if (fields.sync_word != null) details.push(`Sync Word 0x${fields.sync_word.toString(16).toUpperCase()}`);
    }
    const title = details.join(' · ');
    if (row.element.title !== title) row.element.title = title;
  }
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
  if (document.getElementById('panel-noise').hidden) return;
  const activeSeries = noiseSeries(samples).filter(series =>
    noiseObserverActive(series[series.length - 1], now));
  const results = document.getElementById('noise-charts');
  const activeKeys = new Set(activeSeries.map(series => series[0].origin_id || null));
  for (const [key, view] of noiseViews) {
    if (!activeKeys.has(key)) { view.section.remove(); noiseViews.delete(key); }
  }
  document.getElementById('noise-empty').hidden = activeSeries.length > 0;
  for (const [index, series] of activeSeries.entries()) {
    const key = series[0].origin_id || null, signature = JSON.stringify(series);
    const previous = noiseViews.get(key);
    if (previous?.signature === signature) {
      if (results.children[index] !== previous.section) results.insertBefore(previous.section, results.children[index] || null);
      continue;
    }
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
    previous?.section.remove();
    results.insertBefore(section, results.children[index] || null);
    noiseViews.set(key, {section, signature});
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
