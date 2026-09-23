class Element {
  constructor() { this.children = []; this.value = ''; this.checked = true; this.attributes = {}; this.events = {}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, callback) { this.events[name] = callback; }
}
const elements = new Map();
globalThis.document = {
  getElementById: id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); },
  querySelectorAll: () => [],
};
globalThis.text = (_, value) => Object.assign(new Element(), {textContent: value});
globalThis.setInterval = () => {};
const lines = [];
let activePopup;
globalThis.L = {
  popup: () => ({
    setLatLng(position) { this.position = position; return this; },
    setContent(content) { this.content = content; return this; },
    openOn() { activePopup = this; return this; },
  }),
  layerGroup: () => ({addTo() { return this; }, clearLayers() { lines.length = 0; }}),
  polyline: (positions, options) => ({
    events: {},
    on(event, handler) { this.events[event] = handler; return this; },
    closeTooltip() {},
    bindTooltip() { return this; }, bindPopup(info) { this.info = info; return this; },
    addTo() { lines.push({positions, options, info: this.info, events:this.events}); return this; }
  }),
};
const source = await Deno.readTextFile('static/map.js');
new Function('lines', 'getPopup', `${source}
const assert = (ok, message) => { if (!ok) throw Error(message); };
document.getElementById('neighbors-one-way').checked = false;
const a = {id:'aabb', name:'<A>', resolved:true}, b = {id:'ccdd', name:'B', resolved:true};
const link = {source:a, target:b, count:8, forward_count:6, reverse_count:2, last_seen:123, distance_km:12.34};
const layers = new Set();
const classes = new Set();
nodeMap = {
  project: p => ({x:p[0]*100, y:p[1]*100}), unproject: p => p,
  hasLayer: layer => layers.has(layer),
  getContainer: () => ({classList:{toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); }}}),
};
function marker(position) {
  const layer = {getLatLng: () => position,
    addTo() { layers.add(this); return this; }, remove() { layers.delete(this); }};
  return layer.addTo(nodeMap);
}
mapMarkers.set(a.id, {marker:marker([1,2])});
mapMarkers.set(b.id, {marker:marker([3,4])});
renderMapNeighbors({items:[link, {...link, target:{id:'ee', name:'ee', ambiguous:true}}]});
drawMapNeighbors();
assert(document.getElementById('map-neighbors-status').textContent.includes('1 auf der Karte'), 'Only resolved positioned links mapped');
assert(neighborLabel({id:'aa', name:'aa', ambiguous:true}).includes('mehrdeutig'), 'Collision label');

assert(lines.length === 3 && lines[0].options.color === '#3388ff', 'Two arrowheads for bidirectional link');
lines[0].events.click({latlng:[2,3]});
const snapshot = getPopup();
assert(snapshot.content.textContent.includes('A → B: 6'), 'Clicked popup shows initial counts');
assert(snapshot.content.textContent.includes('Luftlinie: 12,3 km'), 'Popup shows geographic distance');
renderMapNeighbors({items:[{...link, forward_count:99}]}); drawMapNeighbors();
assert(getPopup() === snapshot && snapshot.content.textContent.includes('A → B: 6'), 'Refresh preserves popup and original text');
assert(snapshot.position[0] === 2 && snapshot.position[1] === 3, 'Popup remains at clicked position');
drawMapNeighbors();
assert(getPopup() === snapshot, 'Layout redraw also keeps popup');
lines[0].events.click({latlng:[3,4]});
assert(getPopup() !== snapshot && getPopup().content.textContent.includes('A → B: 99'), 'Next click opens fresh values');
const c = {id:'eeff', name:'C', resolved:true};
mapMarkers.set(c.id, {marker:marker([5,6]), line:marker([5,6])});
renderMapNeighbors({items:[link, {...link, source:b, target:c}]});
selectMapRepeater(a.id);
assert(layers.has(mapMarkers.get(a.id).marker) && layers.has(mapMarkers.get(b.id).marker), 'Selected repeater and direct neighbor remain visible');
assert(!layers.has(mapMarkers.get(c.id).marker) && !layers.has(mapMarkers.get(c.id).line), 'Unrelated icon, name and position line are removed');
assert(classes.has('map-neighbor-focus'), 'Focused neighbors keep labels visible at low zoom');
document.getElementById('map-neighbors-toggle').checked = false; drawMapNeighbors();
assert([...mapMarkers.values()].every(view => layers.has(view.marker)), 'Disabling links restores all markers');
assert(layers.has(mapMarkers.get(c.id).line) && !classes.has('map-neighbor-focus'), 'Disabling links restores position lines and normal labels');
document.getElementById('map-neighbors-toggle').checked = true; drawMapNeighbors();
assert(!layers.has(mapMarkers.get(c.id).marker), 'Enabling links reapplies the selection');
assert(lines.length === 3 && !document.getElementById('map-neighbors-reset').hidden, 'Source selection hides unrelated lines and arrows');
drawMapNeighbors();
assert(lines.length === 3, 'Selection survives redraw');
selectMapRepeater(c.id);
assert(lines.length === 3 && lines[0].positions[0][0] === 3, 'Target selection includes incoming neighbors');
selectMapRepeater(b.id);
assert([...mapMarkers.values()].every(view => layers.has(view.marker)), 'Switching selection restores newly involved neighbors');
assert(lines.length === 6, 'Both incoming and outgoing connections retained');
selectMapRepeater(null);
assert(lines.length === 6 && document.getElementById('map-neighbors-reset').hidden, 'Reset restores all lines');
selectMapRepeater(a.id);
renderMapNeighbors({items:[]}); drawMapNeighbors();
assert(layers.has(mapMarkers.get(a.id).marker) && !layers.has(mapMarkers.get(b.id).marker), 'Refresh without links retains only selected repeater');
selectMapRepeater(null);
assert([...mapMarkers.values()].every(view => layers.has(view.marker)), 'Reset restores all icons and names');
renderMapNeighbors({items:[link, {...link, source:b, target:c}]});
selectMapRepeater(c.id); mapMarkers.delete(c.id); drawMapNeighbors();
assert(selectedMapRepeater === null && lines.length === 3, 'Expired selection is cleared');
renderMapNeighbors({items:[{...link, forward_count:0, reverse_count:8}]}); drawMapNeighbors();
assert(lines.length === 2 && lines[0].options.color === '#d97706', 'One orange arrow for reverse-only link');
assert(lines[1].positions[1][0] < lines[1].positions[0][0], 'Reverse arrow points toward A');
assert(neighborDirection({...link, forward_count:0}).includes('B → A'), 'Reverse direction label');
renderMapNeighbors({nodes:[[a.id,a.name],[b.id,b.name]], links:[[0,1,8,6,2,123,12.34]], total:200});
assert(neighborLinks.length === 1 && neighborLinks[0].target.name === 'B', 'Compact map response resolves node references');
assert(neighborTotal === 200, 'Map retains total including unmapped connections');
renderNeighborTable({items:[link], page:2, total:201});
const row = document.getElementById('map-neighbors-list').children[0].children[1];
assert(row.children[2].textContent === 6 && row.children[3].textContent === 2, 'Server page renders directional counts');
assert(row.children[7].textContent === '12,3 km', 'Server page renders distance');
assert(document.getElementById('map-neighbors-next').disabled && neighborPage === 2, 'Server page controls pagination');
renderNeighborTable({items:[], page:0, total:0});
assert(document.getElementById('map-neighbors-prev').disabled && document.getElementById('map-neighbors-next').disabled, 'Empty results disable pagination');
document.getElementById('map-neighbors-toggle').checked = false; drawMapNeighbors();
console.log('Neighbor UI: resolution, labels, pagination, search, sorting and toggle passed');
`)(lines, () => activePopup);
if (lines.length) throw Error('Toggle must clear connections');
