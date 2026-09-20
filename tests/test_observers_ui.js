class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.value = ''; this.hidden = true; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener() {}
  get firstChild() { return this.children[0]; }
  get selectedOptions() { return this.children.filter(c => c.value === this.value); }
  get selectedIndex() { return this.children.findIndex(c => c.value === this.value); }
}
const elements = new Map();
globalThis.document = {getElementById: id => {
  if (!elements.has(id)) elements.set(id, new Element('div'));
  return elements.get(id);
}};
globalThis.localStorage = {getItem: () => null};
globalThis.setInterval = () => {};
globalThis.paused = false;
globalThis.text = (tag, value) => { const e = new Element(tag); e.textContent = value; return e; };
globalThis.measurement = (v,u) => v == null ? '—' : `${v} ${u}`;
const reading = origin_id => ({origin_id,count:84,best_snr:7,best_rssi:-80,last_seen:1});
globalThis.fetch = async () => ({ok:true,json:async()=>({
  observers:[{origin_id:'e',origin:'Same'},{origin_id:'w',origin:'Same'},{origin_id:null,count:3}],
  items:[{id:'a',name:'Both',tokens:['a'],observers:[reading('e'),reading('w')]},
    {id:'b',name:'East',tokens:['b'],observers:[reading('e')]},
    {id:'c',name:'West',tokens:['c'],observers:[reading('w')]}]
})});
const source = await Deno.readTextFile('static/observers.js');
await new Function(`return (async()=>{${source}
await loadObservers();
observerEast.value='e'; observerWest.value='w'; observerFilter.value='all';
renderObservers();
const result=document.getElementById('observers-results');
const rows=()=>result.children[0].children[1].children;
if(rows().length!==3) throw Error('Expected three nodes');
if(rows()[1].children[3].textContent!=='nicht gesehen') throw Error('Missing reception');
if(rows()[0].children[2].children[0].textContent!=='+7.0 dB / 84 RX') throw Error('Metrics');
for(const f of ['east','west','both']) {observerFilter.value=f;renderObservers();if(rows().length!==1)throw Error('Filter '+f);}
const fullHash = 'abcdef' + '12'.repeat(29);
observerData.items[0].id = fullHash;
observerData.items[0].name = fullHash;
renderObservers();
if(rows()[0].children[0].textContent !== 'abcdef') throw Error('Short repeater hash');
if(!rows()[0].children[0].title.includes(fullHash)) throw Error('Full identity in tooltip');
observerData.items[0].name = 'Repeater[' + fullHash + ']';
renderObservers();
if(rows()[0].children[0].textContent !== 'Repeater[abcdef]') throw Error('Short hash with alias');
observerWest.value='e'; renderObservers();
if(result.children.length) throw Error('Same observer accepted');
if(observerLabel({origin_id:'e',origin:'Same'})===observerLabel({origin_id:'w',origin:'Same'})) throw Error('Identity collision');
console.log('Observer UI: selection, identity, metrics, missing reception and filters passed');
})()` )();
