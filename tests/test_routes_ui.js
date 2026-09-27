class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.value = ''; this.handlers = {}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(name, fn) { this.handlers[name] = fn; }
}
const elements = new Map();
globalThis.document = {
  createElement: tag => new Element(tag),
  getElementById: id => {
    if (!elements.has(id)) elements.set(id, new Element('div'));
    return elements.get(id);
  }
};
const assert = (condition, message) => { if (!condition) throw Error(message); };
const a = {id: 'aa'.repeat(32), name: '<script>bad</script>', resolved: true};
const b = {id: 'bb', name: 'Beta', resolved: false};
const route = {nodes: [a, b], hops: 1, one_way_steps: 1, unobserved_steps: 1, distance_km: null,
  steps: [{forward_count: 0, reverse_count: 9, last_seen: 1}]};
const data = {routes: [route], start: a, target: b, excluded_links: 2, max_hops: 32};
let fetchResult = {items: [a, b]}, fetchOK = true, lastURL;
globalThis.fetch = async url => {
  lastURL = url;
  return {ok: fetchOK, json: async () => fetchResult};
};
const source = await Deno.readTextFile('static/routes.js');
await new Function('assert', 'a', 'b', 'data', `return (async()=>{${source}
await loadRouteNodes();
assert(document.getElementById('routes-nodes').children.length === 2, 'catalog');
assert(routeQuery(routeOption(a)) === a.id, 'selection maps to full identity');
assert(routeQuery('  Beta ') === 'Beta', 'free search trimmed');
renderRoutes(data);
const card = routeResults.children[0];
const path = card.children[2];
assert(path.children[0].children[0].textContent.startsWith(a.name), 'name stays literal text');
assert(path.children[0].children[0].title === a.id, 'full hash available');
assert(path.children[0].children[1].textContent.includes('Nur Gegenrichtung'), 'reverse warning');
assert(path.children[1].children[0].textContent.includes('unaufgelöster Hash'), 'unknown identity');
routeStart.value = routeOption(a); routeTarget.value = 'Beta';
document.getElementById('routes-swap').handlers.click();
assert(routeStart.value === 'Beta' && routeTarget.value === routeOption(a), 'swap');
assert(routeResults.children.length === 0, 'old results cleared');
renderRoutes({...data, routes: []});
assert(routeStatus.textContent.includes('Keine Route'), 'no route status');
})()`)(assert, a, b, data);
// Exercise submit errors, parameters, and a response arriving after input changes.
fetchResult = data;
await new Function('assert', 'a', 'data', `return (async()=>{${source}
routeStart.value='aa'; routeTarget.value='bb';
document.getElementById('routes-direction').value='observed';
document.getElementById('routes-max-hops').value='16';
const submit = document.getElementById('routes-search').handlers.submit;
await submit({preventDefault(){}});
assert(!document.getElementById('routes-submit').disabled, 'submit recovers');
assert(routeResults.children.length === 1, 'successful submit renders route');
})()`)(assert, a, data);
assert(lastURL.includes('observed_only=true') && lastURL.includes('max_hops=16'), 'query options');
fetchOK = false; fetchResult = {detail: 'Mehrere Nodes passen'};
await elements.get('routes-search').handlers.submit({preventDefault(){}});
assert(elements.get('routes-status').textContent === fetchResult.detail, 'server error visible');
let complete;
globalThis.fetch = () => new Promise(resolve => { complete = resolve; });
const pending = elements.get('routes-search').handlers.submit({preventDefault(){}});
elements.get('routes-search').handlers.input();
complete({ok:true,json:async()=>data});
await pending;
assert(elements.get('routes-results').children.length === 0, 'stale response ignored');
assert(elements.get('routes-status').textContent.includes('Auswahl geändert'), 'selection status retained');
console.log('Route UI tests passed');
