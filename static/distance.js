/* Historical analysis is explicitly requested, never part of the 30s refresh. */
(() => {
  const el = id => document.getElementById(`distance-${id}`);
  const root = el('analysis');
  if (!root) return;
  let request = 0, controller, result, selected, evidenceOffset = 0;
  let overview = [], shown = 0;
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  el('zone').textContent = `Zeitraumauswahl: ${timezone}. Diagramme und Empfangszeiten: Europe/Berlin.`;
  const localValue = date => new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const now = new Date();
  now.setMinutes(now.getMinutes() + 1, 0, 0);
  el('end').value = localValue(now);
  el('start').value = localValue(new Date(now - 3 * 86400000));
  const node = (tag, value, cls) => {
    const n = document.createElement(tag);
    if (value !== undefined) n.textContent = value;
    if (cls) n.className = cls;
    return n;
  };
  const time = value => value == null ? '—' : new Date(value * 1000).toLocaleString('de-DE', {
    timeZone: 'Europe/Berlin', fractionalSecondDigits: 3, year:'numeric', month:'2-digit', day:'2-digit',
    hour:'2-digit', minute:'2-digit', second:'2-digit', timeZoneName:'short'
  });
  const distance = l => `${l.distance_min_km.toFixed(1)}${l.distance_max_km - l.distance_min_km >= .05 ? `–${l.distance_max_km.toFixed(1)}` : ''} km`;
  function params() {
    const start = new Date(el('start').value).getTime() / 1000;
    const end = new Date(el('end').value).getTime() / 1000;
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || end - start > 31 * 86400)
      throw new Error('Bitte einen Zeitraum von höchstens 31 Tagen mit Ende nach Beginn wählen.');
    return new URLSearchParams({start, end, minimum: el('minimum').value});
  }
  function clear() {
    result = null;
    selected = null;
    el('links').replaceChildren();
    el('detail').replaceChildren();
    el('more-links').hidden = true;
    el('more').hidden = true;
  }
  async function load(pair = null, append = false) {
    const ticket = ++request;
    controller?.abort();
    controller = new AbortController();
    let query;
    try { query = params(); }
    catch (error) { clear(); el('status').textContent = error.message; return; }
    if (pair) {
      query.set('source', pair[0]); query.set('target', pair[1]);
      query.set('offset', append ? evidenceOffset : 0);
    }
    el('status').textContent = 'Gespeicherte Fernverbindungen werden ausgewertet …';
    el('more').disabled = true;
    if (!pair) clear();
    else if (!append) { el('detail').replaceChildren(); el('more').hidden = true; }
    try {
      const response = await fetch(`/api/repeater-neighbors/analysis?${query}`, {signal: controller.signal});
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${response.status}`);
      if (ticket !== request) return;
      if (!pair) {
        result = data;
        overview = data.items;
        shown = 0;
        renderLinks();
        el('status').textContent = `${data.items.length} Fernverbindungen · ${data.packet_count} unterschiedliche Paketinhalte über alle Verbindungen. Ein Paket kann mehrere Verbindungen belegen; das sind keine unabhängigen Ausbreitungsereignisse. Archiv: ${time(data.archive_first)} bis ${time(data.archive_last)}. ${data.missing_position_pairs} Kandidatenpaare ohne historische Position; ${data.missing_at_reception} Hop-Beobachtungen ohne Position zum Empfang ausgeschlossen.`;
      } else if (!data.link) {
        selected = null;
        el('detail').replaceChildren();
        el('more').hidden = true;
        el('status').textContent = 'Für diese Verbindung gibt es im gewählten Zeitraum und Entfernungsfilter keine eindeutig zuordenbaren Belege mit damaligen Positionsangaben.';
      } else {
        selected = pair;
        if (!append) { evidenceOffset = 0; renderDetail(data.link); }
        evidenceOffset += data.evidence.length;
        renderEvidence(data.evidence);
        el('more').hidden = !data.more;
        el('status').textContent = `${data.link.packets} unterschiedliche Pakete · ${data.link.receptions} Empfänge · ${data.link.paths} vollständige Pfadvarianten. ${evidenceOffset} Einzelbelege angezeigt.`;
      }
    } catch (error) {
      if (ticket !== request || error.name === 'AbortError') return;
      el('status').textContent = `Analyse nicht verfügbar: ${error.message}`;
    } finally { if (ticket === request) el('more').disabled = false; }
  }
  function renderLinks() {
    for (const link of overview.slice(shown, shown + 50)) {
      const card = node('div', undefined, 'distance-link');
      const button = node('button', `${link.source.name} ↔ ${link.target.name}`);
      button.type = 'button';
      button.addEventListener('click', () => load([link.source.id, link.target.id]));
      card.append(button, node('span', `${distance(link)} · ${link.packets} Pakete / ${link.receptions} Empfänge · A → B: ${link.forward_packets} · B → A: ${link.reverse_packets}`));
      el('links').append(card);
    }
    shown = Math.min(shown + 50, overview.length);
    el('more-links').hidden = shown >= overview.length;
  }
  function chart(title, values) {
    const section = node('section', undefined, 'distance-chart');
    section.append(node('h4', title));
    const max = Math.max(1, ...values.flatMap(v => [v.forward, v.reverse]));
    for (const v of values) {
      const row = node('div', undefined, 'distance-bin');
      row.append(node('span', v.label));
      for (const [key, label] of [['forward', 'A → B'], ['reverse', 'B → A']]) {
        const bar = node('div', undefined, `distance-bar ${key}`);
        const fill = node('span'); fill.style.width = `${v[key] / max * 100}%`;
        bar.append(fill, node('span', `${label}: ${v[key]} (${v[key + '_receptions']} Empf.)`));
        row.append(bar);
      }
      section.append(row);
    }
    return section;
  }
  function renderDetail(link) {
    const detail = el('detail');
    detail.replaceChildren(node('h3', `${link.source.name} ↔ ${link.target.name}`));
    detail.append(node('p', `A: ${link.source.name} · ${link.source.id}`, 'distance-identity'),
      node('p', `B: ${link.target.name} · ${link.target.id}`, 'distance-identity'),
      node('p', `${distance(link)} nach den damals zuletzt bekannten Positionen · ${link.packets} Pakete · ${link.receptions} Empfänge · ${link.paths} Pfadvarianten`),
      node('p', `Erster Empfang: ${time(link.first_seen)} · Letzter Empfang: ${time(link.last_seen)}`));
    for (const [key, label] of [['forward', 'A → B'], ['reverse', 'B → A']])
      detail.append(node('p', `${label}: ${link[key + '_packets']} Pakete / ${link[key + '_receptions']} Empfänge · ${time(link[key + '_first'])} bis ${time(link[key + '_last'])}`));
    detail.append(node('p', 'Balken: unterschiedliche Paketinhalte je Richtung, dem ersten Empfang innerhalb dieses Zeitraums zugeordnet. Wiederholungen über Tage/Stunden zählen dort nicht erneut; Empfänge in Klammern enthalten alle Wiederholungen. Stunden sind über die gewählten Tage zusammengefasst.', 'muted'));
    const charts = node('div', undefined, 'distance-charts');
    charts.append(chart('Nach Kalendertag · Europe/Berlin', link.days), chart('Nach Stunde des Tages · Europe/Berlin', link.hours));
    detail.append(charts, node('h4', 'Einzelne Empfangsbelege'));
    const list = node('div'); list.id = 'distance-evidence'; detail.append(list);
  }
  function renderEvidence(rows) {
    const list = el('evidence');
    for (const row of rows) {
      const card = node('details', undefined, 'distance-evidence');
      card.append(node('summary', `${time(row.received)} · ${row.kind} · ${row.directions.map(d => d === 'forward' ? 'A → B' : 'B → A').join(' / ')} · #${row.id}`),
        node('p', `Observer: ${row.observer || 'nicht gespeichert'} · ${row.route} · Hash: ${row.observer_hash || 'nicht gespeichert; Inhaltsvergleich'}`),
        node('p', `Paketinhalt-ID: ${row.packet_key}`, 'distance-identity'));
      const path = node('p', undefined, 'distance-path');
      row.path.forEach((token, i) => {
        if (i) path.append(document.createTextNode(' → '));
        const isEndpoint = selected?.some(id => id.startsWith(token));
        path.append(node(isEndpoint ? 'strong' : 'span', token));
      });
      card.append(path); list.append(card);
    }
  }
  el('form').addEventListener('submit', event => { event.preventDefault(); load(); });
  el('form').addEventListener('input', () => {
    ++request; controller?.abort(); clear();
    el('status').textContent = 'Filter geändert. Analyse neu laden.';
  });
  el('more').addEventListener('click', () => selected && load(selected, true));
  el('more-links').addEventListener('click', renderLinks);
  el('example').addEventListener('click', () => {
    ++request; controller?.abort(); clear();
    el('start').value = localValue(new Date('2026-09-28T00:00:00+02:00'));
    el('end').value = localValue(new Date('2026-10-01T00:00:00+02:00'));
    el('minimum').value = '200';
    load();
  });
  window.openDistanceAnalysis = link => {
    root.open = true;
    const end = new Date((link.last_seen + 60) * 1000);
    el('end').value = localValue(end);
    el('start').value = localValue(new Date(Math.max(link.first_seen - 60, end.getTime() / 1000 - 31 * 86400 + 60) * 1000));
    el('minimum').value = String([300, 250, 200, 150, 100].find(v => v <= (link.distance_km ?? 100)) || 100);
    clear(); load([link.source.id, link.target.id]);
    root.scrollIntoView({block:'start'});
  };
})();
