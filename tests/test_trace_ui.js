const source = await Deno.readTextFile('static/trace.js');
class Element {
  constructor(tag, value = '') {
    Object.assign(this, {tag, textContent: value, children: [], dataset: {}, listeners: {}, style: {}, attributes: {}});
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  querySelectorAll() { return this.children.filter(node => node.open); }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  setAttribute(name, value) { this.attributes[name] = value; }
}
const elements = Object.fromEntries(['trace-results', 'trace-status', 'panel-trace', 'trace-hours',
  'trace-search', 'trace-route', 'trace-history'].map(id => [id, new Element('div')]));
elements['trace-hours'].value = '24';
elements['panel-trace'].hidden = false;
const document = {getElementById: id => elements[id], createElementNS: (_, tag) => new Element(tag)};
const text = (tag, value, className) => Object.assign(new Element(tag, value), {className});
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
await new AsyncFunction('document', 'text', 'setInterval', `${source}
let paused = false, calls = 0;
const assert = (ok, message) => { if (!ok) throw Error(message); };
const all = node => [node, ...node.children.flatMap(all)];
const flatten = node => all(node).map(n => n.textContent).join(' ');
const hop = {hash: 'aa', name: '<script>unsafe</script>', snr_min: -3, snr_max: 2};
const item = {id: 1, first_seen: 1000, tag: '00000001', scope: 'Kein Scope', receptions: 3,
  observed_hops: 1, hops: [hop], weakest_snr: -3, weakest_hops: [1], observers: [{id: 'east', name: '<Observer>'}]};
const history = {id: 1, scope: 'Kein Scope', route: [hop], point_count: 3,
  points: [
    {id: 1, time: 1000, tag: '1', snr_min: [-3], snr_max: [2]},
    {id: 2, time: 1100, tag: '2', snr_min: [null], snr_max: [null]},
    {id: 3, time: 1200, tag: '3', snr_min: [1], snr_max: [1]}]};
const data = {items: [item], histories: [history], scanned: 3, ignored: 0};
let fetch = async () => { calls++; return {ok: true, json: async () => data}; };
await loadTraces();
const container = document.getElementById('trace-results');
const chart = document.getElementById('trace-history');
assert(flatten(container).includes('-3 bis 2 dB'), 'SNR range visible');
assert(flatten(container).includes('<script>unsafe</script>'), 'Untrusted names rendered as text');
assert(!all(container).some(n => n.tag === 'script'), 'No markup from names');
assert(all(chart).filter(n => n.tag === 'circle').length === 2, 'Missing values do not become zero');
assert(all(chart).filter(n => n.tag === 'line').length === 5, 'Missing measurement breaks line; only grid remains');
all(chart).find(n => n.tag === 'circle').listeners.focus();
assert(chart.children.at(-1).textContent.includes('SNR -3 bis 2 dB'), 'Point keyboard focus shows details');
container.children[0].open = true;
await loadTraces();
assert(container.children[0].open, 'Open details survive refresh');
paused = true;
await loadTraces();
assert(calls === 2, 'Pause prevents fetching');
paused = false;
document.getElementById('panel-trace').hidden = true;
await loadTraces();
assert(calls === 2, 'Hidden panel prevents fetching');
document.getElementById('panel-trace').hidden = false;
let release;
fetch = () => new Promise(resolve => { release = resolve; });
const old = loadTraces();
fetch = async () => ({ok: true, json: async () => ({items: [], histories: [], scanned: 0})});
await loadTraces();
release({ok: true, json: async () => data});
await old;
assert(!container.children.length && !chart.children.length, 'Late response cannot overwrite newer selection');
fetch = async () => ({ok: false, status: 503});
await loadTraces();
assert(document.getElementById('trace-status').textContent.includes('HTTP 503'), 'Fetch failure shown');
fetch = async () => ({ok: true, json: async () => ({...data, truncated: true, more_sessions: true, more_routes: true})});
await loadTraces();
assert(document.getElementById('trace-status').textContent.includes('5000'), 'Truncation shown');
fetch = async () => ({ok: true, json: async () => ({items: [], histories: [], scanned: 0})});
const pending = loadTraces();
paused = true;
await pending;
assert(container.children.length === 1, 'In-flight result respects pause');
paused = false;
traceHistories = [{...history, point_count: 500}];
renderTraceHistory();
assert(flatten(chart).includes('500 Messgruppen'), 'History point limit visible');
traceHistories = [{...history, points: [history.points[0]], point_count: 1}];
renderTraceHistory();
assert(all(chart).find(n => n.tag === 'circle').attributes.cx === '350', 'Single time is centered');
traceHistories = [{...history, points: [history.points[1]], point_count: 1}];
renderTraceHistory();
assert(flatten(chart).includes('noch keine SNR'), 'All missing data explained');
`)(document, text, () => {});
console.log('TRACE UI: safe rendering, chart gaps, tooltips, pause, refresh, stale responses and limits passed');
