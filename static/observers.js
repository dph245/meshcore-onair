function observerLabel(packet, compact = false) {
  if (!packet.origin_id) return packet.origin ? `${packet.origin} (ohne Observer-ID)` : 'Unzugeordnet (ohne Observer-ID)';
  const identity = compact ? packet.origin_id.slice(0, 6) : packet.origin_id;
  return packet.origin ? `${packet.origin} [${identity}]` : identity;
}
let observersLoading = false, observerData = null;
const observerEast = document.getElementById('observer-east');
const observerWest = document.getElementById('observer-west');
const observerFilter = document.getElementById('observer-filter');
let observerSelection = {};
try { observerSelection = JSON.parse(localStorage.getItem('onair-observers') || '{}') || {}; } catch (_) {}

function renderObservers() {
  if (!observerData) return;
  const east = observerEast.value, west = observerWest.value;
  const result = document.getElementById('observers-results');
  const message = document.getElementById('observers-status');
  result.replaceChildren();
  const unknown = observerData.observers.find(o => o.origin_id == null)?.count || 0;
  const suffix = ` · ${unknown} RX ohne Observer-ID im Archiv · Aktualisierung alle 5 Sekunden`;
  if (!east || !west || east === west) {
    message.textContent = 'Bitte zwei unterschiedliche Observer für Ost und West auswählen.' + suffix;
    return;
  }
  const table = text('table', '');
  const head = text('thead', ''), headings = text('tr', '');
  for (const label of ['Node', 'Gesehen', `Ost · ${observerEast.selectedOptions[0].textContent}`, `West · ${observerWest.selectedOptions[0].textContent}`]) {
    const cell = text('th', label); cell.scope = 'col'; headings.append(cell);
  }
  head.append(headings); table.append(head);
  const body = text('tbody', '');
  let count = 0;
  for (const item of observerData.items) {
    const a = item.observers.find(o => o.origin_id === east);
    const b = item.observers.find(o => o.origin_id === west);
    if (!a && !b) continue;
    const visibility = a && b ? 'both' : a ? 'east' : 'west';
    if (observerFilter.value !== 'all' && observerFilter.value !== visibility) continue;
    count++;
    const row = text('tr', '');
    const shortHash = item.id.slice(0, 6);
    const label = item.name === item.id ? shortHash
      : item.name.endsWith(`[${item.id}]`)
        ? `${item.name.slice(0, -(item.id.length + 2))}[${shortHash}]` : item.name;
    const name = text('td', label);
    name.title = `Kennung: ${item.id} · Empfangene Kennungen: ${item.tokens.join(', ')}`;
    row.append(name, text('td', {both: 'Von beiden', east: 'Nur Ost', west: 'Nur West'}[visibility]));
    for (const reception of [a, b]) {
      const cell = text('td', '');
      if (!reception) cell.textContent = 'nicht gesehen';
      else {
        const snr = reception.best_snr;
        cell.append(text('strong', `${snr == null ? '—' : (snr >= 0 ? '+' : '') + snr.toFixed(1)} dB / ${reception.count.toLocaleString('de-DE')} RX`));
        cell.append(text('div', `Bester RSSI: ${measurement(reception.best_rssi, 'dBm')}`, 'muted'));
        cell.append(text('div', `Zuletzt: ${new Date(reception.last_seen * 1000).toLocaleString('de-DE')}`, 'muted'));
      }
      row.append(cell);
    }
    body.append(row);
  }
  table.append(body); result.append(table);
  message.textContent = `${count} Nodes / Hop-Kennungen · Stand: ${new Date().toLocaleTimeString('de-DE')}` + suffix;
}
async function loadObservers() {
  if (observersLoading || paused) return;
  observersLoading = true;
  try {
    const response = await fetch('/api/observer-comparison');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (paused) return;
    observerData = data;
    for (const [side, select] of [['east', observerEast], ['west', observerWest]]) {
      const selected = select.value || observerSelection[side] || '';
      select.replaceChildren(text('option', 'Observer auswählen …'));
      select.firstChild.value = '';
      for (const observer of data.observers) {
        if (!observer.origin_id) continue;
        const option = text('option', observerLabel(observer, true));
        option.title = observerLabel(observer);
        option.value = observer.origin_id; select.append(option);
      }
      select.value = selected;
      if (select.selectedIndex < 0) select.value = '';
    }
    renderObservers();
  } catch (error) {
    document.getElementById('observers-status').textContent = `Vergleich konnte nicht geladen werden: ${error.message}. Erneuter Versuch in 5 Sekunden; vorhandene Werte bleiben stehen.`;
  } finally { observersLoading = false; }
}
document.getElementById('observers-select').onsubmit = event => event.preventDefault();
for (const select of [observerEast, observerWest, observerFilter]) select.addEventListener('change', () => {
  observerSelection = {east: observerEast.value, west: observerWest.value};
  try { localStorage.setItem('onair-observers', JSON.stringify(observerSelection)); } catch (_) {}
  renderObservers();
});
setInterval(() => { if (!document.getElementById('panel-observers').hidden) loadObservers(); }, 5000);
