/* On-demand RF snapshots. No timers, RF requests or live-stream work. */
(() => {
  const panel = document.getElementById('panel-rf-neighbors');
  const observer = document.getElementById('rf-neighbor-observer');
  const history = document.getElementById('rf-neighbor-history');
  const status = document.getElementById('rf-neighbor-status');
  const results = document.getElementById('rf-neighbor-results');
  const older = document.getElementById('rf-neighbor-older');
  let version = 0, controller, active = false, ready = false, nextBefore = null;
  const visible = () => active && !panel.hidden;
  const current = id => id === version && visible();
  const unknown = value => value == null ? 'Unbekannt' : String(value);
  const scopes = value => value == null ? 'Unbekannt' : value === '' ? 'Leer gemeldet (keine Scope-Aussage)' : value;
  const time = value => {
    if (value == null) return 'Unbekannt';
    const date = new Date(typeof value === 'number' ? value * 1000 : value);
    return Number.isNaN(date.getTime()) ? 'Unbekannt' : date.toLocaleString('de-DE');
  };
  const truncated = value => value == null ? 'Unbekannt' : value ? 'Ja · Bericht unvollständig' : 'Nein';

  function render(data) {
    const r = data.report;
    const summary = text('div', '', 'reception');
    summary.append(text('h3', r.name || 'Observername unbekannt'));
    summary.append(text('p', r.observer_key, 'muted'));
    summary.append(text('p', `Erhebung: ${time(r.reported_at)} · MQTT-Empfang: ${time(r.received_at)} · Report #${r.message_id}`));
    summary.append(text('p', `Erkannte Nachbarn: ${unknown(r.total_neighbors)} · Abgefragt: ${unknown(r.queried_neighbors)} · Enthalten: ${data.entries.length}${data.entries_more ? '+' : ''}`));
    summary.append(text('p', `truncated: ${truncated(r.truncated)}`));
    summary.append(text('p', `Eigene Scopes: ${scopes(r.self_scopes)} · Default-Scope: ${scopes(r.self_default_scope)}`));
    if (r.retain) summary.append(text('p', 'Retained-Zustellung: Die Empfangszeit ist keine neue Erhebung.', 'muted'));
    const scroll = text('div', '', 'noise-scroll');
    const table = text('table', '', 'rf-neighbor-table');
    const head = text('thead', ''), headings = text('tr', '');
    for (const title of ['Name / Public Key', 'SNR', 'Scopes', 'Scope-Abfragestatus', 'Zuletzt gehört']) {
      const cell = text('th', title); cell.scope = 'col'; headings.append(cell);
    }
    head.append(headings); table.append(head);
    const body = text('tbody', '');
    for (const e of data.entries) {
      const row = text('tr', '');
      const identity = text('td', '');
      identity.append(text('strong', e.name || 'Name unbekannt'), text('div', e.pubkey, 'muted'));
      const labels = {responded: 'Geantwortet', timeout: 'Keine Scope-Antwort im Zeitfenster (timeout)',
        send_failed: 'Scope-Anfrage nicht gesendet (send_failed)'};
      const label = Object.hasOwn(labels, e.status) ? labels[e.status] : e.status || 'Unbekannt';
      const heard = text('td', time(e.heard_at));
      heard.append(text('div', `Alter bei Erhebung: ${e.heard_secs_ago == null ? 'Unbekannt' : `${e.heard_secs_ago} s`}`, 'muted'));
      row.append(identity, text('td', e.snr == null ? 'Unbekannt' : `${e.snr} dB`),
        text('td', scopes(e.scopes)), text('td', label), heard);
      body.append(row);
    }
    table.append(body); scroll.append(table);
    results.replaceChildren(summary);
    if (data.entries.length) results.append(scroll);
    else results.append(text('p', 'Dieser Report enthält keine Nachbareinträge. Frühere Beobachtungen bleiben erhalten.', 'muted'));
    if (data.entries_more) results.append(text('p', 'Anzeige auf die ersten 1000 Einträge begrenzt; der vollständige Report bleibt archiviert.', 'muted'));
  }

  async function load({refresh = false, append = false, reportId = null} = {}) {
    if (!visible()) return;
    const id = ++version;
    controller?.abort();
    controller = new AbortController();
    const signal = controller.signal;
    const read = async url => {
      const response = await fetch(url, {signal});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    };
    status.textContent = 'RF-Nachbarschaftsberichte werden geladen …';
    older.disabled = true;
    if (!append) { ready = false; results.replaceChildren(); }
    try {
      if (refresh) {
        const data = await read('/api/rf-neighbors/observers');
        if (!current(id)) return;
        const selected = observer.value;
        observer.replaceChildren(...data.items.map(item => {
          const option = text('option', `${item.name || 'Name unbekannt'} [${item.observer_key.slice(0, 6)}] · ${item.reports} ${item.reports === 1 ? 'Report' : 'Reports'}`);
          option.value = item.observer_key; option.title = item.observer_key; return option;
        }));
        observer.disabled = !data.items.length;
        if (data.items.some(item => item.observer_key === selected)) observer.value = selected;
        else observer.value = data.items[0]?.observer_key || '';
        document.getElementById('rf-neighbor-observer-note').textContent = data.more
          ? 'Observer-Auswahl auf die ersten 500 Observer begrenzt.' : '';
      }
      const key = observer.value;
      if (!key) {
        history.replaceChildren(); history.disabled = true; nextBefore = null; ready = true;
        status.textContent = 'Noch keine ausgewerteten RF-Nachbarschaftsreports vorhanden.'; return;
      }
      if (reportId == null) {
        const cursor = append && nextBefore != null ? `&before=${nextBefore}` : '';
        const data = await read(`/api/rf-neighbors/reports?observer=${encodeURIComponent(key)}&limit=20${cursor}`);
        if (!current(id)) return;
        const selected = history.value;
        const options = data.items.map(item => {
          const option = text('option', `${item.reported_at == null ? 'Erhebung unbekannt · Empfang ' + time(item.received_at) : time(item.reported_at)} · #${item.message_id}${item.truncated ? ' · gekürzt' : ''}`);
          option.value = String(item.message_id); return option;
        });
        if (append) history.append(...options); else history.replaceChildren(...options);
        history.disabled = !history.children.length;
        nextBefore = data.next_before;
        if (append) {
          history.value = selected;
          status.textContent = `${history.children.length} Reports zur Auswahl geladen. Älteren Report über „Historie“ auswählen.`;
          return;
        }
        reportId = data.items[0]?.message_id;
        if (reportId == null) {
          status.textContent = 'Für diesen Observer sind keine Reports vorhanden.'; ready = true; return;
        }
        history.value = String(reportId);
      }
      const data = await read(`/api/rf-neighbors/reports/${reportId}?observer=${encodeURIComponent(key)}`);
      if (!current(id)) return;
      render(data); ready = true;
      status.textContent = `Report #${data.report.message_id} · ${data.entries.length} ${data.entries.length === 1 ? 'Nachbareintrag' : 'Nachbareinträge'} · Zeitangaben in lokaler Browserzeit.`;
    } catch (error) {
      if (current(id) && error.name !== 'AbortError') {
        ready = false;
        status.textContent = `RF-Nachbarn konnten nicht geladen werden: ${error.message}. Bitte erneut aktualisieren.`;
      }
    } finally {
      if (current(id)) older.disabled = nextBefore == null;
    }
  }

  document.getElementById('rf-neighbor-form').addEventListener('submit', event => {
    event.preventDefault(); nextBefore = null; history.replaceChildren(); load({refresh: true});
  });
  observer.addEventListener('change', () => {
    nextBefore = null; history.replaceChildren(); history.disabled = true; ready = false; load();
  });
  history.addEventListener('change', () => load({reportId: history.value}));
  older.addEventListener('click', () => { if (nextBefore != null) load({append: true}); });
  window.RFNeighbors = {select(selected) {
    active = selected;
    if (!selected) { ++version; controller?.abort(); return; }
    if (!ready) return load({refresh: true});
    older.disabled = nextBefore == null;
  }};
})();
