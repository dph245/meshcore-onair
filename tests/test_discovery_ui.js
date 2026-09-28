const source = await Deno.readTextFile('static/discovery.js');
class Element {
  constructor(tag, value = '') { this.tag = tag; this.textContent = value; this.children = []; this.dataset = {}; this.listeners = {}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  querySelectorAll() { return this.children.filter(node => node.open); }
  addEventListener(name, fn) { this.listeners[name] = fn; }
}
const elements = Object.fromEntries(['discovery-results', 'discovery-status', 'panel-discovery', 'discovery-hours', 'discovery-search'].map(id => [id, new Element('div')]));
elements['discovery-hours'].value = '24';
elements['panel-discovery'].hidden = false;
const document = {getElementById: id => elements[id]};
const text = (tag, value, className) => Object.assign(new Element(tag, value), {className});
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
await new AsyncFunction('document', 'text', 'setInterval', `${source}
let paused = false, calls = 0;
const assert = (ok, message) => { if (!ok) throw Error(message); };
const flatten = node => [node.textContent, ...node.children.map(flatten)].join(' ');
const item = {id: 1, first_seen: 1000, tag: '00000001', scope: 'Kein Scope', receptions: 3,
  request: null, unknown_nodes: 0, observers: [{id: 'east', name: '<Observer>'}],
  responses: [{name: '<script>unsafe</script>', public_key: 'abcd', node_type: 'Repeater',
    snr_min: -2.75, snr_max: 2, receptions: 2}]};
const data = {items: [item], scanned: 3, ignored: 0};
let fetch = async () => { calls++; return {ok: true, json: async () => data}; };
await loadDiscovery();
const container = document.getElementById('discovery-results');
assert(flatten(container).includes('Suchanfrage nicht mitgehört'), 'Orphan replies visible');
assert(flatten(container).includes('-2.75 bis 2 dB'), 'SNR range visible');
assert(container.children[0].children.at(-1).children[0].children[0].textContent === '<script>unsafe</script>', 'Untrusted name stays text');
container.children[0].open = true;
await loadDiscovery();
assert(container.children[0].open, 'Open details survive refresh');
paused = true;
await loadDiscovery();
assert(calls === 2, 'Pause prevents fetching');
paused = false;
document.getElementById('panel-discovery').hidden = true;
await loadDiscovery();
assert(calls === 2, 'Hidden panel prevents fetching');
document.getElementById('panel-discovery').hidden = false;
let release;
fetch = () => new Promise(resolve => { release = resolve; });
const old = loadDiscovery();
fetch = async () => ({ok: true, json: async () => ({items: [], scanned: 0})});
await loadDiscovery();
release({ok: true, json: async () => data});
await old;
assert(!container.children.length, 'Late response cannot overwrite newer selection');
fetch = async () => ({ok: false, status: 503});
await loadDiscovery();
assert(document.getElementById('discovery-status').textContent.includes('HTTP 503'), 'Fetch failure shown');
fetch = async () => ({ok: true, json: async () => ({...data, truncated: true, more_sessions: true})});
await loadDiscovery();
assert(document.getElementById('discovery-status').textContent.includes('5000'), 'Truncation shown');
fetch = async () => ({ok: true, json: async () => ({items: [], scanned: 0})});
const pending = loadDiscovery();
paused = true;
await pending;
assert(container.children.length === 1, 'In-flight result respects pause');
`)(document, text, () => {});
console.log('Discovery UI: rendering, text safety, refresh, pause, stale responses and errors passed');
