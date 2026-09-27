const routeStart = document.getElementById('routes-start');
const routeTarget = document.getElementById('routes-target');
const routeStatus = document.getElementById('routes-status');
const routeResults = document.getElementById('routes-results');
let routeCatalog = [], routeNodesLoading = false, routeRequest = 0;

function routeOption(node) { return `${node.name} [${node.id}]`; }
function routeLabel(node) {
  const hash = node.id.length > 6 ? node.id.slice(0, 6) + '…' : node.id;
  return (node.name === node.id ? hash : `${node.name} [${hash}]`) +
    (node.resolved ? '' : ' (unaufgelöster Hash)');
}
function routeElement(tag, value, className = '') {
  const element = document.createElement(tag);
  element.textContent = value;
  element.className = className;
  return element;
}
async function loadRouteNodes() {
  if (routeNodesLoading) return;
  routeNodesLoading = true;
  const request = routeRequest;
  try {
    const response = await fetch('/api/routes/nodes');
    if (!response.ok) throw new Error('Nodes konnten nicht geladen werden.');
    const data = await response.json();
    routeCatalog = data.items;
    const list = document.getElementById('routes-nodes');
    list.replaceChildren(...routeCatalog.map(node => {
      const option = routeElement('option', '');
      option.value = routeOption(node);
      return option;
    }));
    if (request === routeRequest && !routeResults.children.length) routeStatus.textContent = routeCatalog.length
      ? `${routeCatalog.length} Nodes verfügbar · Start und Ziel auswählen.`
      : 'Noch keine eindeutigen Nachbarverbindungen im Archiv vorhanden.';
  } catch (error) {
    if (request === routeRequest && !routeResults.children.length) routeStatus.textContent = error.message;
  } finally { routeNodesLoading = false; }
}
function routeQuery(value) {
  const selected = routeCatalog.find(node => routeOption(node) === value);
  return selected ? selected.id : value.trim();
}
function renderRoutes(data) {
  routeResults.replaceChildren();
  if (!data.routes.length) {
    routeStatus.textContent = `Keine Route mit höchstens ${data.max_hops} Funkstrecken und den gewählten Richtungen gefunden.`;
    return;
  }
  routeStatus.textContent = `${data.routes.length} Route(n) · ${routeLabel(data.start)} → ${routeLabel(data.target)} · ` +
    `${data.excluded_links} Verbindungen mit mehrdeutigen Hashes ausgeschlossen.`;
  const shortest = data.routes[0].hops;
  data.routes.forEach((route, index) => {
    const card = routeElement('article', '', 'route-card');
    const title = index === 0 ? 'Kürzeste Route' : route.hops === shortest ? 'Gleich kurze Alternative' : 'Alternative';
    card.append(routeElement('h3', `${index + 1}. ${title} · ${route.hops} Funkstrecken`));
    card.append(routeElement('p', `${route.one_way_steps} einseitig bekannt · ${route.unobserved_steps} in Reiserichtung unbeobachtet` +
      (route.distance_km == null ? ' · Entfernung unbekannt' : ` · ${route.distance_km.toFixed(1)} km Luftlinie entlang der Route`), 'muted'));
    const path = routeElement('ol', '', 'route-path');
    route.nodes.forEach((node, nodeIndex) => {
      const item = routeElement('li', '');
      const label = routeElement('strong', routeLabel(node));
      label.title = node.id;
      item.append(label);
      const step = route.steps[nodeIndex];
      if (step) {
        const direction = !step.forward_count ? '⇢ Nur Gegenrichtung beobachtet' :
          !step.reverse_count ? '→ Nur Reiserichtung beobachtet' : '↔ Beide Richtungen beobachtet';
        const lastSeen = new Date(step.last_seen * 1000).toLocaleString('de-DE');
        item.append(routeElement('div', `${direction} · ${step.forward_count} hin / ${step.reverse_count} zurück · zuletzt ${lastSeen}`,
          'route-step' + (!step.forward_count || !step.reverse_count ? ' route-one-way' : '')));
      }
      path.append(item);
    });
    card.append(path);
    if (!route.hops) card.append(routeElement('p', 'Start und Ziel sind identisch. Keine Funkstrecke erforderlich.'));
    routeResults.append(card);
  });
}
function invalidateRoutes() {
  routeRequest++;
  document.getElementById('routes-submit').disabled = false;
  routeResults.replaceChildren();
  routeStatus.textContent = 'Auswahl geändert · Routen erneut suchen.';
}
document.getElementById('routes-search').addEventListener('input', invalidateRoutes);
document.getElementById('routes-swap').addEventListener('click', () => {
  [routeStart.value, routeTarget.value] = [routeTarget.value, routeStart.value];
  invalidateRoutes();
});
document.getElementById('routes-search').addEventListener('submit', async event => {
  event.preventDefault();
  const request = ++routeRequest;
  const submit = document.getElementById('routes-submit');
  submit.disabled = true;
  routeResults.replaceChildren();
  routeStatus.textContent = 'Routen werden gesucht …';
  const query = new URLSearchParams({start: routeQuery(routeStart.value), target: routeQuery(routeTarget.value),
    observed_only: String(document.getElementById('routes-direction').value === 'observed'),
    max_hops: document.getElementById('routes-max-hops').value});
  try {
    const response = await fetch(`/api/routes?${query}`);
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Routen konnten nicht geladen werden. Bitte Eingaben prüfen.');
    if (request === routeRequest) renderRoutes(data);
  } catch (error) {
    if (request === routeRequest) routeStatus.textContent = error.message;
  } finally {
    if (request === routeRequest) submit.disabled = false;
  }
});
