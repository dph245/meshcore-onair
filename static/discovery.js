let discoveryRequest = 0;
let discoveryController;

function renderDiscovery(items) {
  const container = document.getElementById('discovery-results');
  const opened = new Set([...container.querySelectorAll('details[open]')].map(node => node.dataset.id));
  const entries = items.map(item => {
    const entry = text('details', '', 'discovery-entry');
    entry.dataset.id = String(item.id);
    entry.open = opened.has(String(item.id));
    const title = item.request
      ? `Suche: ${item.request.node_types.join(', ') || 'Keine Node-Typen'}`
      : 'Suchanfrage nicht mitgehört';
    const time = new Date(item.first_seen * 1000).toLocaleString('de-DE');
    entry.append(text('summary', `${time} · ${title} · ${item.responses.length} antwortende Nodes${item.unknown_nodes ? ` · ${item.unknown_nodes} ohne bekannten Namen` : ''}`));
    entry.append(text('p', `Tag ${item.tag} · ${item.scope} · ${item.receptions} Empfänge · Suchender unbekannt`, 'muted'));
    entry.append(text('p', `Observer: ${item.observers.map(o => o.id ? `${o.name} [${o.id}]` : o.name).join(', ')}`, 'muted'));
    if (item.request) {
      const since = item.request.since
        ? new Date(item.request.since * 1000).toLocaleString('de-DE') : 'keine Zeitbegrenzung';
      entry.append(text('p', `${item.request_receptions} Anfrage-Empfänge · angefordert: ${item.request.prefix_only ? '8-Byte-Key-Präfix' : 'vollständiger Public Key'} · geändert seit: ${since}`));
    }
    const replies = text('div', '', 'discovery-replies');
    for (const response of item.responses) {
      const row = text('div', '', 'reception');
      row.append(text('strong', response.name || (response.ambiguous ? 'Mehrdeutiges Key-Präfix' : 'Unbekannter Node')));
      const snr = response.snr_min === response.snr_max ? `${response.snr_max}` : `${response.snr_min} bis ${response.snr_max}`;
      row.append(text('span', ` · ${response.node_type} · SNR ${snr} dB · ${response.receptions} Empfänge`));
      row.append(text('div', response.public_key, 'muted'));
      replies.append(row);
    }
    if (!item.responses.length) replies.append(text('p', 'Keine Antworten im Zuordnungsfenster mitgehört.', 'muted'));
    entry.append(replies);
    return entry;
  });
  container.replaceChildren(...entries);
}

async function loadDiscovery() {
  if (paused || document.getElementById('panel-discovery').hidden) return;
  const version = ++discoveryRequest;
  discoveryController?.abort();
  const controller = discoveryController = new AbortController();
  const status = document.getElementById('discovery-status');
  const hours = document.getElementById('discovery-hours').value;
  status.textContent = 'Discovery-Meldungen werden geladen …';
  try {
    const response = await fetch(`/api/discovery?hours=${encodeURIComponent(hours)}`, {signal: controller.signal});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    if (version !== discoveryRequest || paused || document.getElementById('panel-discovery').hidden) return;
    renderDiscovery(result.items);
    status.textContent = result.items.length
      ? `${result.items.length} Suchvorgänge / Antwortgruppen · ${result.scanned} CONTROL-Empfänge im Zeitraum`
      : 'Keine auswertbaren Discovery-Meldungen im gewählten Zeitraum.';
    if (result.truncated) status.textContent += ' · Auswertung auf die neuesten 5000 CONTROL-Empfänge begrenzt; Gruppen können unvollständig sein.';
    if (result.more_sessions) status.textContent += ' · Nur die neuesten 100 Gruppen angezeigt.';
    if (result.ignored) status.textContent += ` · ${result.ignored} andere oder nicht auswertbare CONTROL-Empfänge ausgelassen.`;
  } catch (error) {
    if (version === discoveryRequest && error.name !== 'AbortError' && !paused) {
      status.textContent = `Discovery konnte nicht geladen werden: ${error.message}. Erneuter Versuch folgt automatisch.`;
    }
  }
}

document.getElementById('discovery-search').addEventListener('submit', event => {
  event.preventDefault();
  loadDiscovery();
});
document.getElementById('discovery-hours').addEventListener('change', loadDiscovery);
setInterval(loadDiscovery, 10000);
