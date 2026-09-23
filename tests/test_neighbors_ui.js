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
globalThis.L = {
  layerGroup: () => ({addTo() { return this; }, clearLayers() { lines.length = 0; }}),
  polyline: (positions, options) => ({
    bindTooltip() { return this; }, bindPopup(info) { this.info = info; return this; },
    addTo() { lines.push({positions, options, info: this.info}); return this; }
  }),
};
const source = await Deno.readTextFile('static/map.js');
new Function(`${source}
const assert = (ok, message) => { if (!ok) throw Error(message); };
const a = {id:'aabb', name:'<A>', resolved:true}, b = {id:'ccdd', name:'B', resolved:true};
const link = {source:a, target:b, count:8, last_seen:123};
nodeMap = {};
mapMarkers.set(a.id, {marker:{getLatLng: () => [1,2]}});
mapMarkers.set(b.id, {marker:{getLatLng: () => [3,4]}});
renderMapNeighbors({items:[link, {...link, target:{id:'ee', name:'ee', ambiguous:true}}]});
drawMapNeighbors();
assert(document.getElementById('map-neighbors-status').textContent.includes('1 auf der Karte'), 'Only resolved positioned links mapped');
assert(neighborLabel({id:'aa', name:'aa', ambiguous:true}).includes('mehrdeutig'), 'Collision label');
assert(document.getElementById('map-neighbors-list').children[0].children.length === 3, 'All links in table');
renderMapNeighbors({items:Array.from({length:201}, (_, i) => ({...link, source:{...a, name:'Node'+i}}))});
assert(document.getElementById('map-neighbors-list').children[0].children.length === 101, 'Bounded table');
neighborPage = 2; renderNeighborTable();
assert(document.getElementById('map-neighbors-list').children[0].children.length === 2, 'Last page');
document.getElementById('map-neighbors-search').value = 'Node200'; renderNeighborTable();
assert(neighborPage === 0 && document.getElementById('map-neighbors-list').children[0].children.length === 2, 'Search and page clamp');
document.getElementById('map-neighbors-toggle').checked = false; drawMapNeighbors();
console.log('Neighbor UI: resolution, labels, pagination, search and toggle passed');
`)();
if (lines.length) throw Error('Toggle must clear connections');
