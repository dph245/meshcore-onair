const source = await Deno.readTextFile('static/meshlive.js');
const {MeshLiveReplay, MeshLiveModel, meshLivePhase} = new Function(source.slice(0, source.indexOf('window.MeshLive =')) +
  '; return {MeshLiveReplay, MeshLiveModel, meshLivePhase};')();
const assert = (ok, message) => { if (!ok) throw Error(message); };
const start = 1700000000, end = start + 600;
const keys = ['aabbcc','bbccdd','ccddee'].map(k => k.padEnd(64,'0'));
const nodes = keys.map((key,i) => ({public_key:key, name:key, node_type:2, latitude:52+i*.1,
  longitude:10, first_seen:start-100, last_seen:start-1, advert_time:100, position_time:100}));
function event(id, offset, hash='same', hops=['aabb','bbcc']) {
  return {id, received:start+offset, packet:{direction:'rx', observer_hash:hash, origin_id:keys[2],
    received_at:new Date((start+offset)*1000).toISOString(),
    decoded:{route_type:1,payload_type:5,payload_ver:0,payload_hex:'aabb',transport_code:null,hops}}};
}
const data = events => ({window_start:start,window_end:end,speed:10,
  bootstrap:{nodes:structuredClone(nodes),tokens:[]},events});
function advance(r, t) { for(let i=0;i<30;i++) { const before=r.index; r.advance(t); if(r.index===before) break; } }
{
  const r = new MeshLiveReplay(data([event(1,1),event(2,3),event(3,12)]), 500);
  r.advance(599); assert(r.index===0, 'Historical gap compressed by exactly 10');
  r.advance(600); assert(r.index===1 && r.model.active.length===2, 'Both evidence types share renderer/model');
  assert(r.model.active.every(e=>Math.abs(e.started-100)<.001), 'Start time is visual, not epoch');
  r.advance(800); assert(r.index===2 && r.model.active.length===2, 'Observer duplicates deduped in source time');
  r.advance(1700); assert(r.index===3 && r.model.active.length===2, '11 historical seconds expire dedup after 1.1 real seconds');
  assert(r.model.active.every(e=>e.started===1200), 'New event after historical window gets full animation');
  assert(meshLivePhase(300).alpha===1 && meshLivePhase(650).alpha===.5, 'Animation still 300+700ms');
}
{
  const r = new MeshLiveReplay(data([event(1,1),event(2,20,'next')]), 0);
  r.advance(200); r.pause(250);
  const historical=r.sourceTime(100000), started=r.model.active[0].started;
  r.advance(100000);
  assert(r.index===1 && r.time(100000)===250 && r.model.active[0].started===started, 'Pause freezes cursor and trails');
  r.pause(100000); r.resume(100000); r.advance(100050);
  assert(r.time(100050)===300 && r.sourceTime(100050)===historical+500, 'Resume preserves both clocks');
  r.advance(101750); assert(r.index===2, 'Next event is delayed by paused wall time');
}
{
  const input=data([event(1,2),event(2,4,'after')]);
  input.bootstrap.nodes[1].latitude=null;
  const a=event(3,3,'advert',[]);
  a.packet.decoded.advert={public_key:keys[1],name:'historical',node_type:2,timestamp:200,
    latitude:54,longitude:11,signature_status:'Gültig'};
  input.events=[input.events[0],a,input.events[1]];
  const r=new MeshLiveReplay(input,0);
  r.advance(200); assert(r.model.active.length===0,'Unknown historical position is not filled from the future');
  r.advance(300); assert(r.model.nodes.get(keys[1]).latitude===54,'ADVERT position becomes available at its own event');
  r.advance(400); assert(r.model.active.some(e=>e.from[0]===54||e.to[0]===54),'Later hops use newly learned historical position');
  const late=data([]); late.bootstrap.nodes[0].last_seen=start-28*86400-1;
  const old=new MeshLiveReplay(late,0);
  assert(!old.model.position(keys[0],old.sourceTime(0)),'Visibility uses historical clock');
}
{
  const input=data([]);
  input.bootstrap.nodes[0]={...nodes[0],latitude:null,longitude:null,advert_time:-1,last_seen:0};
  const seed=(stamp,latitude)=>({direction:'rx',received_at:new Date((start-10)*1000).toISOString(),
    decoded:{advert:{public_key:keys[0],name:'seed',timestamp:stamp,node_type:2,
      latitude,longitude:latitude==null?null:11,signature_status:'Gültig'}}});
  input.bootstrap.seed_packets=[seed(101,53),seed(102,null)];
  const r=new MeshLiveReplay(input,0);
  assert(r.model.nodes.get(keys[0]).latitude===53,'Seed ADVERTs use live merge rules, preserving absent positions');
  assert(r.model.active.length===0 && r.model.seen.size===0,'Bootstrap never animates or populates dedup');
}
{
  const r=new MeshLiveReplay(data([event(1,599.9)]),0);
  r.advance(59991); assert(r.model.active.length===2,'Late-window event begins');
  r.advance(60000); assert(!r.finished(60000),'Timeline ends at 60s, trailing animation remains');
  r.advance(60991); assert(r.finished(60991),'Last trail expires without shortening its duration');
  const live=new MeshLiveModel(); live.bootstrap({nodes});
  live.ingest(event(1,1).packet,100, (start+1)*1000);
  const independent=new MeshLiveReplay(data([event(1,1)]),0); independent.advance(100);
  assert(independent.model.active.length===2 && live.active.length===2,'Live and replay dedup states independent');
}
{
  const r=new MeshLiveReplay(data(Array.from({length:1000},(_,i)=>event(i+1,1,String(i)))),0);
  r.advance(100);
  assert(r.index<=200 && r.model.active.length<=64,'Per-frame work and animation counts bounded');
  advance(r,100);
  assert(r.index===1000 && r.model.active.length===64 && r.model.limited===1936,'Burst does not create unbounded animation queue');
  const late=new MeshLiveReplay(data([event(1,1)]),0);late.advance(10000);
  assert(late.index===1 && late.late===1 && late.model.active.length===0,'Stalled browser consumes old events without fireworks');
}
for(const modify of [d=>d.speed=1,d=>d.window_end++,d=>d.events=[event(1,600)],
  d=>d.events=[event(1,3),event(2,1)],d=>d.events=[event(2,1),event(1,1)]]) {
  const d=data([]);modify(d);let failed=false;try{new MeshLiveReplay(d,0);}catch{failed=true;}
  assert(failed,'Reject invalid replay time/reception ordering');
}
console.log('Replay model: separate clocks/state, historic positions, pause, 10× timing, tail and load bounds passed');
