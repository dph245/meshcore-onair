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
globalThis.window = {openDistanceAnalysis(link) { this.lastAnalysis = link; }};
const lines = [];
let activePopup;
globalThis.L = {
  popup: () => ({
    setLatLng(position) { this.position = position; return this; },
    setContent(content) { this.content = content; return this; },
    openOn() { activePopup = this; return this; },
  }),
  layerGroup: () => ({addTo() { return this; },
    clearLayers() { throw Error('Connections must be reconciled individually'); },
    removeLayer(layer) {
      const index = lines.indexOf(layer);
      if (index < 0) throw Error('Removing a connection layer that is not present');
      lines.splice(index, 1); return this;
    }}),
  polyline: (positions, options) => ({
    positions, options, events: {}, geometryUpdates: 0,
    setLatLngs(points) { this.positions = points; this.geometryUpdates++; return this; },
    setStyle(style) { Object.assign(this.options, style); return this; },
    setTooltipContent(content) { this.tooltip = content; return this; },
    on(event, handler) { this.events[event] = handler; return this; },
    closeTooltip() {},
    bindTooltip() { return this; }, bindPopup(info) { this.info = info; return this; },
    addTo() { lines.push(this); return this; }
  }),
};
const source = await Deno.readTextFile('static/map.js');
new Function('lines', 'getPopup', `${source}
const assert = (ok, message) => { if (!ok) throw Error(message); };
const sample = {name:'Sender', public_key:'aabb', advert_path:{received:123, origin:'<Observer>',
  hops:[{token:'cc', name:'<Relay>', resolved:true}, {token:'dd', ambiguous:true}, {token:'ee'}]}};
const details = mapAdvertPath(sample);
assert(!details.open && details.children[0].textContent.includes('3 Hops'), 'Path is collapsed with compact hop count');
const steps = details.children[2].children;
assert(steps.length === 5 && steps[1].textContent === '<Relay> [cc]', 'Ordered path includes sender and safely rendered relay name');
assert(steps[2].textContent.includes('mehrdeutig') && steps[3].textContent.includes('unaufgelöst'), 'Ambiguous and unknown hops are explicit');
assert(steps[4].textContent === 'Empfänger: <Observer>', 'Reception identifies observer');
sample.advert_path.hops = [];
assert(mapAdvertPath(sample).children[0].textContent.includes('direkt'), 'Empty flood path means direct reception');
sample.advert_path.hops = null;
assert(mapAdvertPath(sample).children[0].textContent.includes('nicht verfügbar'), 'Other route types are not labeled direct');
assert(mapAdvertPath({}).textContent.includes('kein Empfang'), 'Missing reception is explicit');
document.getElementById('neighbors-one-way').checked = false;
const a = {id:'aabb', name:'<A>', resolved:true}, b = {id:'ccdd', name:'B', resolved:true};
const link = {source:a, target:b, count:8, forward_count:6, reverse_count:2, last_seen:123, distance_km:12.34};
const layers = new Set();
const classes = new Set();
let zoom = 10;
nodeMap = {
  getZoom: () => zoom,
  project: p => ({x:p[0]*100*2**(zoom-10), y:p[1]*100*2**(zoom-10)}), unproject: p => p,
  hasLayer: layer => layers.has(layer),
  getContainer: () => ({classList:{toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); }}}),
};
function marker(position) {
  const layer = {position, getLatLng() { return this.position; },
    addTo() { layers.add(this); return this; }, remove() { layers.delete(this); }};
  return layer.addTo(nodeMap);
}
mapMarkers.set(a.id, {marker:marker([1,2])});
mapMarkers.set(b.id, {marker:marker([3,4])});
renderMapNeighbors({items:[link, {...link, target:{id:'ee', name:'ee', ambiguous:true}}]});
drawMapNeighbors();
assert(lines.length === 0, 'Default without selection renders no geometry');
setMapLinkMode('all');
assert(document.getElementById('map-neighbors-status').textContent.includes('1 Verbindungen dargestellt'), 'Only resolved positioned links mapped');
assert(neighborLabel({id:'aa', name:'aa', ambiguous:true}).includes('mehrdeutig'), 'Collision label');

assert(lines.length === 3 && lines[0].options.color === '#3388ff', 'Two arrowheads for bidirectional link');
lines[0].events.click({latlng:[2,3]});
const snapshot = getPopup();
assert(snapshot.content.textContent.includes('A → B: 6'), 'Clicked popup shows initial counts');
assert(snapshot.content.textContent.includes('Luftlinie: 12,3 km'), 'Popup shows geographic distance');
const initialLine = lines[0], initialArrows = lines.slice(1), initialTooltip = lines[0].tooltip;
const initialInfo = mapConnectionViews.values().next().value.info;
zoom++;
mapLayoutVersion++; drawMapNeighbors();
assert(lines[0] === initialLine && initialArrows.every((arrow, i) => lines[i+1] === arrow), 'Zoom retains line and arrow objects');
assert(initialLine.geometryUpdates === 0 && initialArrows.every(arrow => arrow.geometryUpdates === 1), 'Zoom updates only pixel-dependent arrows');
assert(initialLine.tooltip === initialTooltip && mapConnectionViews.values().next().value.info === initialInfo, 'Zoom retains tooltip and detail content');
mapMarkers.get(b.id).marker.position = [4,5];
mapLayoutVersion++; drawMapNeighbors();
assert(initialLine.geometryUpdates === 1 && initialLine.positions[1][0] === 4, 'Moved endpoint updates retained line');
assert(initialArrows.every(arrow => arrow.geometryUpdates === 2), 'Moved endpoint updates retained arrows');
mapLayoutVersion++; drawMapNeighbors();
assert(initialLine.geometryUpdates === 1 && initialArrows.every(arrow => arrow.geometryUpdates === 2), 'Unchanged geometry avoids setters even with invalidated layout');
mapMarkers.get(b.id).marker.position = [3,4];
zoom = 10; mapLayoutVersion++; drawMapNeighbors();
renderMapNeighbors({items:[{...link, forward_count:99}]}); drawMapNeighbors();
assert(lines[0] === initialLine && initialLine.tooltip.textContent.includes('A → B: 99'), 'Metadata refresh retains line and updates tooltip');
assert(getPopup() === snapshot && snapshot.content.textContent.includes('A → B: 6'), 'Refresh preserves popup and original text');
assert(snapshot.position[0] === 2 && snapshot.position[1] === 3, 'Popup remains at clicked position');
const savedLayers = [...lines];
document.getElementById('map-neighbors-status').textContent = 'temporary error';
drawMapNeighbors();
assert(lines.every((line, i) => line === savedLayers[i]), 'Unchanged map state retains actual layers');
assert(!document.getElementById('map-neighbors-status').textContent.includes('temporary error'), 'Unchanged state restores success status');
assert(getPopup() === snapshot, 'Layout redraw also keeps popup');
lines[0].events.click({latlng:[3,4]});
assert(getPopup() !== snapshot && getPopup().content.textContent.includes('A → B: 99'), 'Next click opens fresh values');
getPopup().content.children[2].events.click();
assert(window.lastAnalysis.forward_count === 99, 'DX button uses updated connection metadata');
snapshot.content.children[2].events.click();
assert(window.lastAnalysis.forward_count === 6, 'Existing popup keeps its original DX snapshot');
const c = {id:'eeff', name:'C', resolved:true};
mapMarkers.set(c.id, {marker:marker([5,6]), line:marker([5,6])});
renderMapNeighbors({items:[link, {...link, source:b, target:c}]});
setMapLinkMode('selected');
selectMapRepeater(a.id);
assert(layers.has(mapMarkers.get(a.id).marker) && layers.has(mapMarkers.get(b.id).marker), 'Selected repeater and direct neighbor remain visible');
assert(!layers.has(mapMarkers.get(c.id).marker) && !layers.has(mapMarkers.get(c.id).line), 'Unrelated markers and position lines are detached');

setMapLinkMode('none');
assert([...mapMarkers.values()].every(view => layers.has(view.marker)), 'Disabling links restores all markers');
assert(layers.has(mapMarkers.get(c.id).line) && !classes.has('map-neighbor-focus'), 'Disabling links restores position lines and normal labels');
setMapLinkMode('selected');
assert(!layers.has(mapMarkers.get(c.id).marker), 'Selected mode hides unrelated markers');
assert(lines.length === 3 && !document.getElementById('map-neighbors-reset').disabled, 'Source selection hides unrelated lines and arrows');
drawMapNeighbors();
assert(lines.length === 3, 'Selection survives redraw');
const savedLinks = neighborLinks;
neighborLinks = {[Symbol.iterator]() { throw Error('Selected mode must not iterate all links'); }};
drawMapNeighbors();
neighborLinks = savedLinks;
selectMapRepeater(c.id);
assert(lines.length === 3 && lines[0].positions[0][0] === 3, 'Target selection includes incoming neighbors');
selectMapRepeater(b.id);
assert([...mapMarkers.values()].every(view => layers.has(view.marker)), 'Switching selection restores newly involved neighbors');
assert(lines.length === 6, 'Both incoming and outgoing connections retained');
const retainedAB = mapConnectionViews.get(JSON.stringify([a.id,b.id]));
const retainedBC = mapConnectionViews.get(JSON.stringify([b.id,c.id]));
const unchangedBC = [retainedBC.line, retainedBC.forward, retainedBC.reverse];
const removedReverse = retainedAB.reverse;
renderMapNeighbors({items:[{...link, reverse_count:0, count:32}, {...link, source:b, target:c}]}); drawMapNeighbors();
assert(lines.length === 5 && lines.includes(retainedAB.line) && lines.includes(retainedAB.forward) && !lines.includes(removedReverse), 'Direction change removes only obsolete reverse arrow');
assert(unchangedBC.every(layer => lines.includes(layer)), 'Unchanged neighboring connection retains every layer');
assert(retainedAB.line.options.color === '#d97706' && retainedAB.forward.options.color === '#d97706', 'Retained line and arrow adopt one-way color');
assert(retainedAB.line.options.weight === 1 + Math.log2(33), 'Retained line updates count-dependent width');
renderMapNeighbors({items:[link, {...link, source:b, target:c}]}); drawMapNeighbors();
assert(lines.length === 6 && lines.includes(retainedAB.line) && retainedAB.reverse !== removedReverse, 'Returning reverse direction adds only missing arrow');
const survivingAB = [retainedAB.line, retainedAB.forward, retainedAB.reverse];
renderMapNeighbors({items:[link]}); drawMapNeighbors();
assert(lines.length === 3 && survivingAB.every(layer => lines.includes(layer)) && mapConnectionViews.size === 1, 'Topology removal drops only the obsolete connection and its cache');
renderMapNeighbors({items:[link, {...link, source:b, target:c}]}); drawMapNeighbors();
assert(lines.length === 6 && survivingAB.every(layer => lines.includes(layer)) && unchangedBC.every(layer => !lines.includes(layer)), 'Topology addition creates only new connection layers');
selectMapRepeater(null);
assert(lines.length === 0 && document.getElementById('map-neighbors-reset').disabled, 'Reset clears lines');
selectMapRepeater(a.id);
renderMapNeighbors({items:[]}); drawMapNeighbors();
assert(layers.size === 1 && layers.has(mapMarkers.get(a.id).marker), 'Refresh without links keeps only selection');
selectMapRepeater(null);
assert([...mapMarkers.values()].every(view => layers.has(view.marker)), 'Reset restores all icons and names');
renderMapNeighbors({items:[link, {...link, source:b, target:c}]});
selectMapRepeater(c.id); mapMarkers.delete(c.id); drawMapNeighbors();
assert(selectedMapRepeater === null && lines.length === 0, 'Expired selection is cleared without showing all links');
setMapLinkMode('all');
renderMapNeighbors({items:[{...link, forward_count:0, reverse_count:8}]}); drawMapNeighbors();
assert(lines.length === 2 && lines[0].options.color === '#d97706', 'One orange arrow for reverse-only link');
assert(lines[1].positions[1][0] < lines[1].positions[0][0], 'Reverse arrow points toward A');
assert(neighborDirection({...link, forward_count:0}).includes('B → A'), 'Reverse direction label');
const shortLine = lines[0];
mapMarkers.get(b.id).marker.position = [1.01,2.01];
mapLayoutVersion++; drawMapNeighbors();
assert(lines.length === 1 && lines[0] === shortLine, 'Short link loses arrow but retains connection');
zoom = 15; mapLayoutVersion++; drawMapNeighbors();
assert(lines.length === 2 && lines[0] === shortLine, 'Zoom crossing 24px threshold restores direction arrow');
zoom = 10; mapMarkers.get(b.id).marker.position = [3,4];
mapLayoutVersion++; drawMapNeighbors();
assert(sameMapPosition([1,2], {lat:1,lng:2}) && !sameMapPosition([1,2], {lat:1,lng:3}), 'Position equality supports stored coordinates and Leaflet LatLng');
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
setMapLinkMode('none');
console.log('Neighbor UI: incremental layers, zoom, endpoints, directions, popup snapshots, DX, selection and table passed');
`)(lines, () => activePopup);
if (lines.length) throw Error('Toggle must clear connections');
