class Element {
  constructor() { this.children = []; this.value = ''; this.checked = true; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener() {}
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
const link = {source:a, target:b, count:8, forward_count:6, reverse_count:2, last_seen:123};
nodeMap = {project: p => ({x:p[0]*100, y:p[1]*100}), unproject: p => p};
mapMarkers.set(a.id, {marker:{getLatLng: () => [1,2]}});
mapMarkers.set(b.id, {marker:{getLatLng: () => [3,4]}});
renderMapNeighbors({items:[link, {...link, target:{id:'ee', name:'ee', ambiguous:true}}]});
drawMapNeighbors();
assert(document.getElementById('map-neighbors-status').textContent.includes('1 auf der Karte'), 'Only resolved positioned links mapped');
assert(neighborLabel({id:'aa', name:'aa', ambiguous:true}).includes('mehrdeutig'), 'Collision label');
assert(document.getElementById('map-neighbors-list').children[0].children.length === 3, 'All links in table');
assert(lines.length === 3 && lines[0].options.color === '#3388ff', 'Two arrowheads for bidirectional link');
lines[0].events.click({latlng:[2,3]});
const snapshot = getPopup();
assert(snapshot.content.textContent.includes('A → B: 6'), 'Clicked popup shows initial counts');
renderMapNeighbors({items:[{...link, forward_count:99}]}); drawMapNeighbors();
assert(getPopup() === snapshot && snapshot.content.textContent.includes('A → B: 6'), 'Refresh preserves popup and original text');
assert(snapshot.position[0] === 2 && snapshot.position[1] === 3, 'Popup remains at clicked position');
drawMapNeighbors();
assert(getPopup() === snapshot, 'Layout redraw also keeps popup');
lines[0].events.click({latlng:[3,4]});
assert(getPopup() !== snapshot && getPopup().content.textContent.includes('A → B: 99'), 'Next click opens fresh values');
const c = {id:'eeff', name:'C', resolved:true};
mapMarkers.set(c.id, {marker:{getLatLng: () => [5,6]}});
renderMapNeighbors({items:[link, {...link, source:b, target:c}]});
selectMapRepeater(a.id);
assert(lines.length === 3 && !document.getElementById('map-neighbors-reset').hidden, 'Source selection hides unrelated lines and arrows');
drawMapNeighbors();
assert(lines.length === 3, 'Selection survives redraw');
selectMapRepeater(c.id);
assert(lines.length === 3 && lines[0].positions[0][0] === 3, 'Target selection includes incoming neighbors');
selectMapRepeater(b.id);
assert(lines.length === 6, 'Both incoming and outgoing connections retained');
selectMapRepeater(null);
assert(lines.length === 6 && document.getElementById('map-neighbors-reset').hidden, 'Reset restores all lines');
selectMapRepeater(c.id); mapMarkers.delete(c.id); drawMapNeighbors();
assert(selectedMapRepeater === null && lines.length === 3, 'Expired selection is cleared');
renderMapNeighbors({items:[{...link, forward_count:0, reverse_count:8}]}); drawMapNeighbors();
assert(lines.length === 2 && lines[0].options.color === '#d97706', 'One orange arrow for reverse-only link');
assert(lines[1].positions[1][0] < lines[1].positions[0][0], 'Reverse arrow points toward A');
assert(neighborDirection({...link, forward_count:0}).includes('B → A'), 'Reverse direction label');
const row = document.getElementById('map-neighbors-list').children[0].children[1];
assert(row.children[2].textContent === 0 && row.children[3].textContent === 8, 'Separate directional counts');
renderMapNeighbors({items:[link, {...link, reverse_count:0}]});
document.getElementById('neighbors-one-way').checked = true; renderNeighborTable();
assert(document.getElementById('map-neighbors-list').children[0].children.length === 2, 'One-way filter');
document.getElementById('neighbors-one-way').checked = false;
renderMapNeighbors({items:Array.from({length:201}, (_, i) => ({...link, source:{...a, name:'Node'+i}}))});
assert(document.getElementById('map-neighbors-list').children[0].children.length === 101, 'Bounded table');
neighborPage = 2; renderNeighborTable();
assert(document.getElementById('map-neighbors-list').children[0].children.length === 2, 'Last page');
document.getElementById('map-neighbors-search').value = 'Node200'; renderNeighborTable();
assert(neighborPage === 0 && document.getElementById('map-neighbors-list').children[0].children.length === 2, 'Search and page clamp');
document.getElementById('map-neighbors-toggle').checked = false; drawMapNeighbors();
console.log('Neighbor UI: resolution, labels, pagination, search and toggle passed');
`)(lines, () => activePopup);
if (lines.length) throw Error('Toggle must clear connections');
