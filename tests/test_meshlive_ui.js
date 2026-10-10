// Pure event/model tests: no server, MQTT, timers or browser needed.
const source = await Deno.readTextFile('static/meshlive.js');
const {MeshLiveModel, meshLivePhase, MESH_LIVE} = new Function(
  source.slice(0, source.indexOf('window.MeshLive =')) + '\nreturn {MeshLiveModel, meshLivePhase, MESH_LIVE};')();
const assert = (ok, message) => { if (!ok) throw Error(message); };
const now = Date.now(), seconds = now / 1000;
const key = prefix => prefix.padEnd(64, '0');
const [A, B, C, O, P] = ['aabbcc', 'bbccdd', 'ccddee', 'ddeeff', 'eeff00'].map(key);
const node = (public_key, i = 0, extra = {}) => ({public_key, name: public_key.slice(0, 6),
  latitude: 52 + i * .01, longitude: 10 + i * .01, first_seen: seconds - 100,
  last_seen: seconds, advert_time: 100, position_time: 100, node_type: 2, ...extra});
function model(extra = []) {
  const m = new MeshLiveModel();
  m.bootstrap({nodes: [A, B, C, O, P].map((k, i) => node(k, i)).concat(extra), tokens: []});
  return m;
}
function packet(hops = ['aabb', 'bbcc'], extra = {}, decoded = {}) {
  return {number: 1, direction: 'rx', observer_hash: 'HASH', origin_id: O,
    received_at: new Date(now).toISOString(), ...extra,
    decoded: {route_type: 1, payload_type: 5, payload_ver: 0, payload_hex: 'aabb', hops, ...decoded}};
}
function ingest(m, p, at = 0, animate = true) { m.learn(p); m.ingest(p, at, now, animate); }

{
  const m = model(), p = packet();
  const original = JSON.stringify(p);
  ingest(m, p);
  assert(JSON.stringify(p) === original, 'Shared text-view packet stays untouched');
  assert(m.active.length === 2, 'Both observed and reconstructed enabled by default');
  assert(m.active[0].source === A && m.active[0].target === B && m.style(m.active[0]) === 'reconstructed', 'Adjacent inferred hop');
  assert(m.active[1].source === B && m.active[1].target === O && m.style(m.active[1]) === 'observed', 'Last hop to exact Observer');
  assert(m.active.every(e => e.started === 0), 'No invented inter-hop timing');
  ingest(m, packet(['aabb', 'bbcc'], {origin_id: P, number: 2}), 50);
  assert(m.active.length === 3, 'Shared hop deduped across observers; distinct reception preserved');
  ingest(m, packet(['aabb', 'bbcc'], {number: 3}), 100);
  assert(m.active.length === 3, 'Repeated reception does not animate again');
  ingest(m, packet(['aabb', 'bbcc', 'ccdd'], {number: 4}), 150);
  assert(m.active.some(e => e.source === B && e.target === C), 'New hop of same packet remains');
  assert(m.active.filter(e => e.source === A && e.target === B).length === 1, 'Whole path is not dedup identity');
}
{
  const m = model();
  ingest(m, packet(['aabb', 'bbcc'], {origin_id: null}));
  ingest(m, packet(['aabb'], {origin_id: B, number: 2}), 100);
  assert(m.active.length === 1 && m.active[0].observed && m.active[0].reconstructed, 'Direct evidence upgrades same event');
  assert(m.active[0].started === 0 && m.style(m.active[0]) === 'observed', 'Upgrade does not restart duration');
  m.observed = false;
  assert(m.style(m.active[0]) === 'reconstructed', 'Independent switch falls back to dashed evidence');
  m.reconstructed = false; m.expire(200);
  assert(m.active.length === 0, 'Both switches off clear animations');
  for (const kind of ['observed', 'reconstructed']) {
    const x = model(); x[kind] = false; ingest(x, packet());
    assert(x.active.length === 1 && x.style(x.active[0]) !== kind, 'Each switch independent');
  }
}
{
  const m = model();
  ingest(m, packet(['aabb', 'ffff', 'ccdd'], {origin_id: null}));
  assert(m.active.length === 0, 'Unknown intermediate hop never bridged');
  ingest(m, packet(['aabb', null, 'bbcc', 'ccdd'], {origin_id: null}), 1);
  assert(m.active.length === 1 && m.active[0].source === B, 'Incomplete path preserves only real adjacent pair');
  for (const decoded of [{route_type: 2}, {route_type: 3}, {payload_type: 9}]) {
    const x = model(); ingest(x, packet(undefined, {}, decoded));
    assert(x.active.length === 0, 'DIRECT and TRACE excluded');
  }
  const x = model(); ingest(x, packet(undefined, {direction: 'tx'}));
  assert(x.active.length === 0, 'TX excluded');
  ingest(x, packet([], {}, {}));
  assert(x.active.length === 0, 'Empty path does not invent a sender');
  ingest(x, packet([], {}, {payload_type: 4, advert: {public_key: A, timestamp: 101,
    signature_status: 'Gültig', latitude: 52, longitude: 10, node_type: 1}}));
  assert(x.active.length === 1 && x.active[0].source === A, 'Signed zero-hop ADVERT supports all node types');
  const bad = model(); ingest(bad, packet([], {}, {advert: {public_key: A, signature_status: 'Ungültig'}}));
  assert(bad.active.length === 0, 'Unsigned sender not used');
}
{
  const collision = node(key('aabbee'), 8, {latitude: null, longitude: null, last_seen: 0});
  const m = model([collision]); ingest(m, packet(['aabb', 'bbcc'], {origin_id: null}));
  assert(!m.resolve('aabb') && m.active.length === 0, 'Invisible inactive identities still collide');
  assert(m.resolve('aabbcc') === A, 'Longer unique prefix resolves');
  m.identity('aabbff');
  assert(!m.resolve('aabb'), 'Unpositioned longer hop evidence also collides');
  const x = model(); x.identity('1122');
  assert(!x.resolve('11'), 'Unknown prefix is not a known node');
  x.mergeNode(node(key('112233'), 9));
  assert(x.resolve('11') === key('112233'), 'Full identity replaces its unresolved prefix');
  for (const props of [{latitude:null}, {longitude:NaN}, {latitude:91}, {longitude:181},
    {latitude:0,longitude:0}, {last_seen:seconds - 29*86400}]) {
    const y = model(); y.nodes.set(A, node(A, 0, props));
    ingest(y, packet(['aabb'], {origin_id: B}));
    assert(y.active.length === 0, 'Missing/invalid/inactive coordinates skipped');
  }
  const y = model(); ingest(y, packet(['aabb'], {origin_id: O.slice(0, 6), origin: 'Node O'}));
  assert(y.active.length === 0, 'Observer never resolved by prefix or name');
  ingest(y, packet(['aabb'], {origin_id: A}));
  assert(y.active.length === 0, 'Self hop skipped');
  y.nodes.set(B, node(B)); ingest(y, packet(['aabb'], {origin_id: B}));
  assert(y.active.length === 0, 'Same coordinates never artificially displaced');
}
{
  const m = model(); ingest(m, packet(['aabb'], {origin_id:B}));
  ingest(m, packet(['bbcc'], {origin_id:A}), 10);
  assert(m.active.length === 2, 'Opposite directions remain separate');
  ingest(m, packet(['aabb'], {origin_id:B}, {payload_hex:'ccdd'}), 20);
  assert(m.active.length === 3, 'Hash alone cannot collapse distinct payloads');
  ingest(m, packet(['aabb'], {origin_id:B}, {transport_code:'00110022'}), 30);
  assert(m.active.length === 4, 'Scopes remain separate');
  ingest(m, packet(['aabb'], {origin_id:B}), 9999);
  assert(m.active.length === 0, 'Repeat within window does not replay after fading');
  ingest(m, packet(['aabb'], {origin_id:B}), 10000);
  assert(m.active.length === 1, 'Fixed window expires, never prolonged by repeats');
  const x = model(); ingest(x, packet(['aabb'], {origin_id:B, observer_hash:null}));
  ingest(x, packet(['aabb'], {origin_id:B, observer_hash:null, number:2}), 1);
  assert(x.active.length === 1, 'Missing hash falls back to identical packet content');
}
{
  const m = model();
  for (let i = 0; i < 5100; i++) ingest(m, packet(['aabb'], {origin_id:B, observer_hash:String(i)}));
  assert(m.active.length === MESH_LIVE.MAX_ACTIVE && m.limited === 5100 - MESH_LIVE.MAX_ACTIVE, 'Parallel events bounded; excess dropped without queue');
  assert(m.seen.size === MESH_LIVE.MAX_DEDUP_ENTRIES, 'Dedup memory bounded');
  m.expire(1000); assert(m.active.length === 0, 'All animations removed at exactly 1000ms');
  m.expire(10000); assert(m.seen.size === 0, 'Old dedup entries removed');
  ingest(m, packet(), 11000, false);
  assert(m.active.length === 0, 'Pause/loading consumes events without animation');
  ingest(m, packet(), 11001, true);
  assert(m.active.length === 0, 'No replay on resume');
  assert(meshLivePhase(0).progress === 0 && meshLivePhase(150).progress === .5, 'Travel 0–300ms');
  assert(meshLivePhase(300).progress === 1 && !meshLivePhase(300).moving, 'Point stops at 300ms');
  assert(meshLivePhase(650).alpha === .5 && meshLivePhase(999).alpha > 0, 'Continuous 700ms fade');
  assert(meshLivePhase(1000) === null, 'No permanent trail');
}
{
  const m = model();
  m.learn(packet([], {}, {advert:{public_key:A,name:'new',node_type:3,timestamp:200,
    signature_status:'Gültig',latitude:53,longitude:11}}));
  m.bootstrap({nodes:[node(A, 0, {last_seen:seconds - 10})]});
  assert(m.nodes.get(A).name === 'new' && m.nodes.get(A).latitude === 53, 'Slow HTTP bootstrap cannot overwrite live ADVERT');
  m.learn(packet([], {}, {advert:{public_key:A,name:'newer',node_type:3,timestamp:300,
    signature_status:'Gültig',latitude:null,longitude:null}}));
  assert(m.nodes.get(A).latitude === 53 && m.nodes.get(A).position_time === 200, 'ADVERT without position preserves last coordinates');
}
console.log('MeshLive model: evidence, dedup, gaps, identities, coordinates, concurrency and timing passed');
