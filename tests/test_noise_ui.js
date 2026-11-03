// DOM model: verify that alternating Observer samples produce separate step paths.
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.attributes = {}; }
  append(...nodes) { for (const node of nodes) this.insertBefore(node, null); }
  insertBefore(node, next) {
    node.remove();
    const index = next ? this.children.indexOf(next) : this.children.length;
    this.children.splice(index, 0, node); node.parent = this;
  }
  remove() {
    if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1);
    this.parent = null;
  }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener() {}
}
const elements = new Map();
globalThis.document = {
  getElementById: id => {
    if (!elements.has(id)) elements.set(id, new Element('div'));
    return elements.get(id);
  },
  createElementNS: (_, tag) => new Element(tag),
};
globalThis.text = (tag, value) => { const e = new Element(tag); e.textContent = value; return e; };
globalThis.observerLabel = (p, compact) => p.origin_id
  ? `${p.origin} [${compact ? p.origin_id.slice(0, 6) : p.origin_id}]` : 'Unzugeordnet';
const source = await Deno.readTextFile('static/noise.js');
new Function(`${source}
const assert = (ok, message) => {if (!ok) throw Error(message);};
const samples = [
  {origin_id:'abcdef-east', origin:'Same', noise_floor:-110, received_at:'2026-09-20T10:00:00Z'},
  {origin_id:'abcdef-west', origin:'Same', noise_floor:-120, received_at:'2026-09-20T10:00:01Z'},
  {origin_id:'abcdef-east', origin:'Renamed', noise_floor:-111, received_at:'2026-09-20T10:00:02Z'},
  {noise_floor:-130, received_at:'2026-09-20T10:00:03Z'}
];
const retained = {origin_id:'C0CADC', received_at:'2026-09-20T11:59:04+02:00',
  status_at:'2026-09-15T18:44:14+00:00', noise_floor:-104};
assert(!noiseObserverActive(retained, Date.parse('2026-09-20T12:00:00+02:00')),
  'Retained C0CADC status must not become fresh on delivery');
renderNoise([retained], Date.parse('2026-09-20T12:00:00+02:00'));
assert(document.getElementById('noise-charts').children.length === 0, 'Retained observer hidden');
const series = noiseSeries(samples);
assert(series.length === 3, 'Full IDs, not labels or short IDs, determine series');
assert(series[0].length === 2 && series[1].length === 1, 'Samples must stay separated');
const now = Date.parse('2026-09-20T12:00:00Z');
renderNoise(samples, now);
const cards = [...document.getElementById('noise-charts').children];
assert(cards.length === 3, 'One chart per observer plus legacy data');
assert(cards[0].children[0].textContent === 'Renamed [abcdef] · -111 dBm', 'Latest value and name');
assert(cards[0].children[0].title.includes('abcdef-east'), 'Full identity in tooltip');
const chart = card => card.children[2].children[0];
const path = card => chart(card).children.find(e => e.tag === 'path').attributes.d;
assert(path(cards[0]).includes(' H '), 'East has a step');
assert(!path(cards[1]).includes(' H '), 'West must not connect to East');
assert(chart(cards[0]).children.filter(e => e.tag === 'circle').length === 2, 'Raw samples preserved');
assert(cards[2].children[0].textContent.startsWith('Unzugeordnet'), 'Legacy series');
renderNoise(structuredClone(samples), now);
assert(document.getElementById('noise-charts').children.every((node, i) => node === cards[i]), 'Equal data retains every series node');
const changed = [...samples, {...samples[0], noise_floor:-109, received_at:'2026-09-20T10:00:04Z'}];
renderNoise(changed, now);
assert(document.getElementById('noise-charts').children[0] !== cards[0], 'Changed series rebuilt');
assert(document.getElementById('noise-charts').children[1] === cards[1], 'Unchanged observer retained');
assert(document.getElementById('noise-charts').children[2] === cards[2], 'Unchanged legacy series retained');
const frozen = [...document.getElementById('noise-charts').children];
document.getElementById('panel-noise').hidden = true;
renderNoise([], now);
assert(document.getElementById('noise-charts').children.every((node, i) => node === frozen[i]), 'Hidden chart stays untouched');
document.getElementById('panel-noise').hidden = false;
renderNoise(samples, now);
const boundary = Date.parse('2026-09-21T10:00:01Z');
assert(!noiseObserverActive(samples[1], boundary), 'Exactly 24h expires in header');
assert(noiseObserverActive(samples[2], boundary), 'Recent observer remains in header');
renderNoise(samples, boundary);
const remaining = document.getElementById('noise-charts').children;
assert(remaining.length === 2, 'Expired observer disappears even when samples are unchanged');
assert(chart(remaining[0]).children.filter(e => e.tag === 'circle').length === 2,
  'Keep older measurements of an active observer');
renderNoise(samples, boundary + 2000);
assert(document.getElementById('noise-charts').children.length === 0, 'All observers expire');
const returning = [...samples, {...samples[1], received_at:'2026-09-21T10:00:04Z'}];
renderNoise(returning, boundary + 3000);
const restored = document.getElementById('noise-charts').children;
assert(restored.length === 1, 'Observer reappears after new status');
assert(chart(restored[0]).children.filter(e => e.tag === 'circle').length === 2,
  'History retained after reappearance');
assert(samples.length === 4, 'Display filtering does not delete source samples');
renderNoise([]);
assert(document.getElementById('noise-charts').children.length === 0, 'Clear charts');
assert(!document.getElementById('noise-empty').hidden, 'Empty state');
assert(noiseViews.size === 0, 'Removed observer series release cached DOM references');
console.log('Noise UI: independent curves, full identities, renamed labels and legacy data passed');
`)();
