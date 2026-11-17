/* Lazy, bounded local analysis; textContent protects archived names. */
window.PrefixExplorer = (() => {
  const el = id => document.getElementById(`prefix-${id}`);
  let active = false, sequence = 0, controller, next = null, search = '';
  const node = (tag, text) => { const n = document.createElement(tag); n.textContent = text; return n; };
  function button(text, prefix) {
    const b = node('button', text); b.type = 'button';
    b.addEventListener('click', () => { search = prefix; el('search').value = prefix; load(); });
    return b;
  }
  function table(headers, rows) {
    const t = document.createElement('table'), head = document.createElement('thead');
    const tr = document.createElement('tr'); headers.forEach(h => tr.append(node('th', h))); head.append(tr); t.append(head);
    const body = document.createElement('tbody'); rows.forEach(values => {
      const r = document.createElement('tr'); values.forEach(v => r.append(node('td', v))); body.append(r);
    }); t.append(body); return t;
  }
  async function load(more = false) {
    controller?.abort(); controller = new AbortController(); const request = ++sequence;
    el('status').textContent = 'Lokalen Datenbestand auswerten …'; el('more').hidden = true;
    if (!more) { el('results').replaceChildren(); el('heatmap').replaceChildren(); el('levels').replaceChildren(); }
    const query = new URLSearchParams({days: el('days').value, prefix: search,
      reference: el('reference').value, reference_q: el('reference-search').value, radius: el('radius').value, sort: el('sort').value,
      offset: more ? next : 0});
    try {
      const response = await fetch(`/api/prefix-explorer?${query}`, {signal: controller.signal});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Abfrage fehlgeschlagen');
      if (!active || request !== sequence) return;
      if (!more) {
        el('statistics').replaceChildren(table(['Bytes', 'Möglich', 'Belegt', 'Kollidierende Prefixe'],
          data.statistics.map(s => [s.bytes, s.possible.toLocaleString('de-DE'), s.occupied, s.collisions])));
        el('busiest').replaceChildren(node('span', 'Stark belegt: '));
        data.busiest.forEach(c => el('busiest').append(button(`${c.prefix} (${c.count})`, c.prefix)));
        el('levels').replaceChildren(button('00–ff', ''));
        data.levels.forEach(c => el('levels').append(button(`${c.prefix}: ${c.count} Repeater${c.count >= 2 ? ' · Kollision' : ''}`, c.prefix)));
        el('heading').textContent = `${data.parent.length / 2 + 1}-Byte-Belegung${data.parent ? ` unter ${data.parent}` : ''}`;
        const max = Math.max(1, ...data.cells.map(c => c.count));
        const cells = data.cells.map(c => {
          const b = button(c.prefix.slice(-2), c.prefix); b.title = `${c.prefix}: ${c.count} Repeater`;
          b.setAttribute('aria-label', b.title); b.style.setProperty('--prefix-intensity', c.count ? .15 + .85 * Math.log1p(c.count) / Math.log1p(max) : 0);
          b.className = c.count ? 'occupied' : ''; return b;
        });
        el('heatmap').replaceChildren(...cells);
        const value = el('reference').value;
        el('reference').replaceChildren(new Option('Wolfenbüttel (Zentrum)', ''),
          ...data.references.map(r => new Option(`${r.name || 'Repeater'} · ${r.public_key.slice(0, 12)}`, r.public_key)));
        el('reference').value = value;
      }
      const rows = data.items.map(r => [r.name || 'Unbekannt', r.public_key,
        new Date(r.last_seen * 1000).toLocaleString('de-DE'),
        r.distance_km == null ? r.position_status : `${r.distance_km.toFixed(1)} km`, r.unique_prefix]);
      if (more) {
        const tbody = el('results').querySelector('tbody');
        const extra = table([], rows); tbody.append(...extra.querySelector('tbody').children);
      } else {
        el('results').replaceChildren(search ? table(['Repeater', 'Public Key', 'Letzte Sichtung', 'Entfernung', 'Eindeutiger Prefix'], rows) : node('p', 'Prefix anklicken oder suchen.'));
      }
      next = data.next_offset; el('more').hidden = next == null;
      el('status').textContent = `${data.total} eindeutige Repeater · ${data.matched} Treffer in der Liste · Stand: ${new Date(data.generated_at * 1000).toLocaleString('de-DE')} (Cache bis 30 s)`;
    } catch (error) {
      if (error.name !== 'AbortError' && active && request === sequence) el('status').textContent = error.message;
    }
  }
  el('form').addEventListener('submit', e => {e.preventDefault(); search = el('search').value.trim().toLowerCase(); load();});
  ['days', 'reference', 'reference-search', 'radius', 'sort'].forEach(id => el(id).addEventListener('change', () => load()));
  el('reset').addEventListener('click', () => {search = ''; el('search').value = ''; load();});
  el('more').addEventListener('click', () => load(true));
  return {select(value) {active = value; if (active) load(); else {sequence++; controller?.abort();}}};
})();
