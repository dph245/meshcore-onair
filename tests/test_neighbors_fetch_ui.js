class Element {
  constructor() { this.children = []; this.value = ''; this.checked = false; this.hidden = false; this.events = {}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute() {}
  addEventListener(name, fn) { this.events[name] = fn; }
}
const elements = new Map();
globalThis.document = {
  getElementById(id) { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); },
  querySelectorAll: () => [],
};
globalThis.text = (_, value) => Object.assign(new Element(), {textContent:value});
globalThis.setInterval = () => {};
globalThis.paused = false;
const source = await Deno.readTextFile('static/map.js');
await new (Object.getPrototypeOf(async function(){}).constructor)(`${source}
const assert = (ok, message) => { if (!ok) throw Error(message); };
const page = {items:[], page:0, total:0, total_all:25, one_way_total:4};
const requests = [];
let responseStatus = 200;
globalThis.fetch = async (url, options) => {
  requests.push({url, options});
  return {status:responseStatus, ok:responseStatus === 200, headers:new Headers({ETag:'"v1"'}),
    json:async () => { if (responseStatus === 304) throw Error('304 has no JSON'); return page; }};
};
await loadNeighborTable();
assert(requests[0].url.includes('limit=100') && requests[0].url.includes('sort=count'), 'Table requests bounded server page');
responseStatus = 304;
await loadNeighborTable();
assert(requests[1].options.headers['If-None-Match'] === '"v1"', 'Repeated query sends ETag');
assert(document.getElementById('neighbors-status').textContent.includes('25 beobachtete'), '304 retains page and status');
responseStatus = 200;
document.getElementById('map-neighbors-search').value = 'Node & A';
neighborSortKey = 'distance_km'; neighborSortDirection = 1; neighborPage = 2;
document.getElementById('neighbors-one-way').checked = true;
await loadNeighborTable();
const params = new URL(requests[2].url, 'http://localhost').searchParams;
assert(params.get('q') === 'Node & A' && params.get('one_way') === 'true' && params.get('page') === '2' && params.get('descending') === 'false', 'Search, filter, sort and page sent to server');
assert(!requests[2].options.headers['If-None-Match'], 'Different query does not reuse ETag');
const pending = [];
globalThis.fetch = (url, options) => new Promise(resolve => pending.push({resolve, options}));
const old = loadNeighborTable();
document.getElementById('map-neighbors-search').value = 'new';
const fresh = loadNeighborTable();
assert(pending[0].options.signal.aborted, 'New request aborts previous fetch');
const response = total => ({status:200, ok:true, headers:new Headers({ETag:'"next"'}), json:async () => ({...page,total_all:total})});
pending[1].resolve(response(42)); await fresh;
pending[0].resolve(response(999)); await old;
assert(document.getElementById('neighbors-status').textContent.includes('42 beobachtete'), 'Late old response cannot overwrite latest search');
globalThis.fetch = async () => { throw Error('offline'); };
const oldTable = document.getElementById('map-neighbors-list').children[0];
await loadNeighborTable();
assert(document.getElementById('map-neighbors-list').children[0] === oldTable, 'Network error preserves previous table');
let calls = 0;
globalThis.fetch = async (url, options) => {
  calls++;
  assert(url.endsWith('/map'), 'Map uses compact endpoint');
  if (calls === 2) assert(options.headers['If-None-Match'] === '"map1"', 'Map sends its own ETag');
  return {status:calls === 1 ? 200 : 304, ok:calls === 1, headers:new Headers({ETag:'"map1"'}),
    json:async () => { if (calls === 2) throw Error('304 should not decode'); return {nodes:[],links:[],total:123}; }};
};
await loadMapNeighbors(); await loadMapNeighbors();
assert(neighborTotal === 123, 'Map 304 preserves previous data');
console.log('Neighbor fetch UI: query parameters, conditional requests, races and errors passed');
`)();
