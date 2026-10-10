const source = await Deno.readTextFile('static/app.js');
const start = source.indexOf('function receptionLastHop(');
const end = source.indexOf('function render(', start);
const text = (tag, value, className) => ({
  tag, textContent: value, className, children: [],
  append(...nodes) { this.children.push(...nodes); },
});
const {receptionPath, receptionLastHop} = new Function('text',
  `${source.slice(start, end)}; return {receptionPath, receptionLastHop};`)(text);
const assert = (ok, message) => { if (!ok) throw Error(message); };
const content = node => [node.textContent, ...node.children.map(content)].join(' ');
for (const route_type of [2, 3]) {
  const packet = {last_hop: 'Wrong last sender', decoded: {
    route_type, payload_type: 2, hops: ['aabb', 'ccdd'],
    hop_labels: ['Repeater A[aabb]', '<img src=x onerror=alert(1)>[ccdd]'],
  }};
  const path = receptionPath(packet), chain = path.children[1];
  assert(content(path).includes('Restpfad · 2 Hops ausstehend'), 'DIRECT remaining path');
  assert(chain.children[0].textContent === 'Repeater A[aabb]', 'First hop resolved');
  assert(content(chain.children[0]).includes('nächster Hop'), 'First hop is next');
  assert(chain.children[2].textContent === packet.decoded.hop_labels[1], 'Labels remain literal text');
  assert(receptionLastHop(packet) === 'Unbekannt', 'Old incorrect last sender overridden');
  packet.decoded.hops = [];
  assert(content(receptionPath(packet)).includes('Keine weiteren Repeater'), 'Empty DIRECT means no remaining repeaters');
  assert(receptionLastHop(packet) === 'Unbekannt', 'Empty path does not identify last sender');
}
for (const route_type of [0, 1]) {
  const packet = {last_hop: 'cc', decoded: {route_type, hops: ['aa', 'cc']}};
  const path = receptionPath(packet);
  assert(content(path).includes('Empfangspfad · 2 Hops'), 'FLOOD observed path');
  assert(!content(path).includes('nächster Hop'), 'FLOOD has no next hop');
  assert(path.children[1].children[0].textContent === 'aa', 'Hash fallback for old packets');
  assert(receptionLastHop(packet) === 'cc', 'FLOOD last hop preserved');
  packet.decoded.hops = [];
  assert(content(receptionPath(packet)).includes('Ohne Repeater-Hop'), 'Zero-hop FLOOD');
}
const trace = {last_hop: 'bad', decoded: {payload_type: 9, route_type: 2, hops: []}};
assert(content(receptionPath(trace)).includes('TRACE'), 'TRACE remains special');
assert(!content(receptionPath(trace)).includes('Restpfad'), 'SNR samples are not a remaining path');
assert(receptionLastHop(trace) === 'Unbekannt', 'TRACE has no last sender');
assert(source.includes('receptionPath(p)') && source.includes('receptionPath(reception)'), 'Summary and individual reception paths');
console.log('Live path UI: DIRECT, TC_DIRECT, FLOOD, TRACE, legacy packets and safe labels passed');
