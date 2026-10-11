const source = await Deno.readTextFile('static/meshlive.js');
const {MeshLiveModel, MeshLiveReplay} = new Function(source.slice(0,source.indexOf('window.MeshLive =')) +
  '; return {MeshLiveModel, MeshLiveReplay};')();
const assert = (ok, message) => { if (!ok) throw Error(message); };
const t=1791696600, A='36477e'.padEnd(64,'a'), B='abcd11'.padEnd(64,'b');
const manual={public_key:A,name:'Extern',latitude:52,longitude:10,source:'Betreiber',created_at:t+10,updated_at:t+10};
const node={public_key:B,name:'Real',latitude:53,longitude:11,node_type:2,first_seen:t-1,last_seen:t-1,advert_time:1,position_time:1};
const p={direction:'rx',origin_id:B,observer_hash:'same',received_at:new Date(t*1000).toISOString(),
 decoded:{route_type:1,payload_type:5,payload_ver:0,payload_hex:'abcd',hops:['3647','abcd']}};
const m=new MeshLiveModel(); m.bootstrap({nodes:[node],tokens:['36477e']});
m.learn(p);m.ingest(p,0,t*1000);assert(!m.active.length,'Missing identity is not guessed');
m.bootstrap({nodes:[],manual_nodes:[manual]});
assert(!m.active.length && m.nodes.size===1,'Bootstrap invents no reception or ADVERT');
assert(m.resolve('3647')===A && m.nodeKeys().size===2,'Full external key resolves archived token');
assert(m.node(A).last_seen===null && m.node(A).position_time===null,'No artificial observation times');
m.ingest(p,10,t*1000);assert(m.active.length===1,'Only a real packet triggers newly resolved edge');
m.bootstrap({nodes:[],manual_nodes:[{...manual,latitude:54}]});
assert(m.position(A,t*1000)[0]===54,'Manual update replaces position');
m.bootstrap({nodes:[],manual_nodes:[]});
assert(!m.node(A)&&!m.resolve('3647'),'Delete removes node and prefix candidate');
m.bootstrap({nodes:[],manual_nodes:[manual,{...manual,public_key:'36477f'.padEnd(64,'c')}]});
assert(!m.resolve('3647') && m.resolve('36477e')===A,'Collision remains strict');
m.bootstrap({nodes:[],manual_nodes:[manual]});
assert(m.resolve('3647')===A,'Deleted collision candidate does not linger');
const advert={...p,decoded:{advert:{public_key:A,name:'Advert',node_type:2,timestamp:2,signature_status:'Gültig',latitude:null,longitude:null}}};
m.learn(advert);assert(m.nodeKeys().size===2 && m.node(A).name_source==='advert' && m.node(A).position_source==='manual','Real identity merges without duplicate; manual coordinate fallback');
advert.decoded.advert={...advert.decoded.advert,latitude:55,longitude:12,timestamp:3};m.learn(advert);
assert(m.position(A,t*1000)[0]===55 && m.node(A).position_source==='advert','Actual position wins over manual administration time');
m.bootstrap({nodes:[],manual_nodes:[]});
assert(m.position(A,t*1000)[0]===55 && m.node(A).name==='Advert','Deleting fallback preserves received ADVERT');
const replay=new MeshLiveReplay({window_start:t,window_end:t+600,speed:10,
 bootstrap:{nodes:[node],tokens:['36477e'],manual_nodes:[manual]},events:[{id:1,received:t,packet:p}]},0);
replay.advance(0);assert(!replay.model.active.length && !replay.model.resolve('3647'),'Strict replay ignores external positions and identities');
console.log('Manual MeshLive: lifecycle, provenance, ADVERT priority, collisions and strict replay passed');
