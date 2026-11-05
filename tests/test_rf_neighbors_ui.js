const source = await Deno.readTextFile('static/rf-neighbors.js');
const assert = (value, message) => { if (!value) throw Error(message); };
class Element {
  constructor(tag, value = '') { this.tag = tag; this.textContent = value; this.children = []; this.listeners = {}; this.value = ''; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(event, callback) { this.listeners[event] = callback; }
}
const ids = ['panel-rf-neighbors', 'rf-neighbor-observer', 'rf-neighbor-history', 'rf-neighbor-status',
  'rf-neighbor-results', 'rf-neighbor-older', 'rf-neighbor-form', 'rf-neighbor-observer-note'];
const elements = Object.fromEntries(ids.map(id => [id, new Element('div')]));
const document = {getElementById: id => elements[id]};
const text = (tag, value, className) => Object.assign(new Element(tag, value), {className});
const window = {};
const flatten = node => [node.textContent, ...node.children.map(flatten)].join(' ');
const results = elements['rf-neighbor-results'];
const panel = elements['panel-rf-neighbors'];
const east = '74'.repeat(32), west = '77'.repeat(32);
const fixtures = {
  report: {message_id: 5, observer_key: east, name: '<Observer>', reported_at: 1000,
    received_at: '2026-11-05T12:00:00Z', total_neighbors: 3, queried_neighbors: null,
    truncated: true, self_scopes: '* de', self_default_scope: null, retain: 1},
  entries: [{name: '<script>test</script>', pubkey: 'ab'.repeat(32), snr: 0, scopes: '',
    status: 'timeout', heard_at: 1000, heard_secs_ago: 0},
    {name: null, pubkey: 'cd'.repeat(32), snr: null, scopes: null,
      status: 'send_failed', heard_at: null, heard_secs_ago: null}], entries_more: false
};
let calls = [];
let fetchImpl = async url => {
  calls.push(url);
  if (url.includes('/observers')) return {ok: true, json: async () => ({items: [
    {observer_key: east, name: 'WF-Ost', reports: 3}, {observer_key: west, name: 'WF-Rodeland', reports: 1}], more: false})};
  if (url.includes('/reports?')) return {ok: true, json: async () => ({items: [
    {message_id: url.includes('before=') ? 3 : 5, reported_at: 1000, truncated: true}],
    next_before: url.includes('before=') ? null : 5})};
  return {ok: true, json: async () => structuredClone(fixtures)};
};
new Function('window', 'document', 'text', 'fetch', 'setInterval', source)(
  window, document, text, (...args) => fetchImpl(...args), () => { throw Error('No polling allowed'); });
const drain = async () => { for (let i=0; i<30; i++) await Promise.resolve(); };
const event = async (id, type) => { elements[id].listeners[type]({preventDefault() {}}); await drain(); };

assert(!calls.length, 'Loading script must not fetch');
panel.hidden = true;
await window.RFNeighbors.select(true);
assert(!calls.length, 'Hidden tab must not fetch');
panel.hidden = false;
await window.RFNeighbors.select(true);
assert(calls.length === 3, 'Initial load: observers, history and selected detail only');
let content = flatten(results);
for (const value of ['<script>test</script>', '0 dB', 'Alter bei Erhebung: 0 s', 'Unbekannt',
  'truncated: Ja', 'Default-Scope: Unbekannt', 'Retained-Zustellung', 'timeout', 'send_failed', 'Leer gemeldet']) {
  assert(content.includes(value), `Missing report data: ${value}`);
}
assert(!source.includes('innerHTML'), 'Untrusted values render through textContent');
const previous = results.children[0];
await window.RFNeighbors.select(true);
assert(results.children[0] === previous && calls.length === 3, 'Revisit keeps snapshot and DOM without polling');
await event('rf-neighbor-older', 'click');
assert(calls.at(-1).includes('before=5'), 'History uses bounded cursor');
assert(elements['rf-neighbor-history'].children.length === 2, 'Older history appended');
assert(elements['rf-neighbor-older'].disabled, 'End of history disables loading');
elements['rf-neighbor-history'].value = '3';
await event('rf-neighbor-history', 'change');
assert(calls.at(-1).includes('/reports/3?'), 'Historical report can be selected');
fixtures.entries[0].status = 'constructor';
await event('rf-neighbor-history', 'change');
assert(flatten(results).includes('constructor') && !flatten(results).includes('native code'),
  'Unknown status renders literal text, including prototype property names');
fixtures.entries[0].status = '';
await event('rf-neighbor-history', 'change');
assert(results.children[1].children[0].children[1].children[0].children[3].textContent === 'Unbekannt',
  'Empty status explicitly unknown');

let release;
fetchImpl = () => new Promise(resolve => { release = resolve; });
elements['rf-neighbor-history'].value = '4';
elements['rf-neighbor-history'].listeners.change();
window.RFNeighbors.select(false); panel.hidden = true;
release({ok: true, json: async () => fixtures}); await drain();
assert(!results.children.length, 'Late hidden response cannot mutate DOM');
panel.hidden = false;
fetchImpl = async () => ({ok: false, status: 503});
await window.RFNeighbors.select(true);
assert(elements['rf-neighbor-status'].textContent.includes('HTTP 503'), 'Read error visible');

fetchImpl = async url => {
  if (url.includes('/observers')) return {ok: true, json: async () => ({items: [], more: false})};
  throw Error('No follow-up fetch for empty observer list');
};
await event('rf-neighbor-form', 'submit');
assert(elements['rf-neighbor-status'].textContent.includes('Noch keine'), 'Empty archive explained');
assert(elements['rf-neighbor-history'].disabled, 'Empty history disabled');

// Out-of-order observer selections must not display the older response.
let firstRelease;
elements['rf-neighbor-observer'].value = east;
fetchImpl = () => new Promise(resolve => { firstRelease = resolve; });
elements['rf-neighbor-observer'].listeners.change();
elements['rf-neighbor-observer'].value = west;
fetchImpl = async url => ({ok: true, json: async () => url.includes('/reports?')
  ? {items: [{message_id: 9, reported_at: null}], next_before: null}
  : {...fixtures, report: {...fixtures.report, observer_key: west, name: 'WEST', message_id: 9,
    reported_at: null, truncated: null}, entries: []}});
await event('rf-neighbor-observer', 'change');
firstRelease({ok: true, json: async () => ({items: [{message_id: 1}], next_before: null})});
await drain();
content = flatten(results);
assert(content.includes('WEST') && content.includes('Report #9'), 'Late response cannot overwrite selected observer');
assert(content.includes('Erhebung: Unbekannt') && content.includes('truncated: Unbekannt'), 'Unknown time and completeness explicit');
assert(content.includes('keine Nachbareinträge'), 'Empty report not interpreted as disappearance');
console.log('RF neighbors UI: lazy loading, history, values, text safety, hidden/stale responses, errors passed');
