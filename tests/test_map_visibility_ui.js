const source = await Deno.readTextFile('static/map-visibility.js');
const mesh = await Deno.readTextFile('static/meshlive.js');
const trace = await Deno.readTextFile('static/trace-map.js');
const {RepeaterMapVisibility, MeshLiveModel, MeshLiveReplay, traceMapSnrSegments, repeaterMapVisibility} =
  new Function(source + '\n' + mesh.split('window.MeshLive =')[0] + '\n' +
    trace.split('// Historical observations')[0] +
    '; return {RepeaterMapVisibility, MeshLiveModel, MeshLiveReplay, traceMapSnrSegments, repeaterMapVisibility};')();
const assert = (ok, message) => { if (!ok) throw Error(message); };
const A = 'aabbcc'.padEnd(64, '0'), B = 'bbccdd'.padEnd(64, '0'), C = 'aabbcc'.padEnd(64, 'f');
const now = Date.now(), t = now / 1000;
const node = (public_key, node_type = 2) => ({public_key, node_type, latitude: 52,
  longitude: 10, last_seen: t, first_seen: t, advert_time: 1, position_time: 1});
const advert = key => ({direction: 'rx', received_at: new Date(now).toISOString(),
  decoded: {advert: {...node(key), timestamp: 2, signature_status: 'Gültig'}}});
const policy = new RepeaterMapVisibility();
policy.addKeys([A, A.toUpperCase(), 'aabbcc', 'invalid']);
assert(!policy.hidden(A) && policy.keys.size === 1, 'Repeated identity, casing and short hop tokens never collide');
policy.learn({...advert(C), decoded: {advert: {...advert(C).decoded.advert, node_type: 1}}});
assert(!policy.hidden(A), 'Companions do not create repeater collisions');
policy.learn({...advert(C), decoded: {advert: {...advert(C).decoded.advert, signature_status: 'Ungültig'}}});
assert(!policy.hidden(A), 'Invalid signatures do not contribute identities');
let updates = 0; policy.listeners.add(() => updates++);
policy.receive({receptions: [advert(C)]});
assert(policy.hidden(A) && policy.hidden(C.toUpperCase()) && !policy.hidden(B), 'Both colliding repeaters hidden');
assert(!policy.hidden(A, 1) && !policy.hidden(A, 3) && !policy.hidden(A, 4), 'Other types remain visible');
policy.receive({groups: [{receptions: [advert(C), advert(A)]}]});
assert(updates === 1 && policy.changed.has(A) && policy.changed.has(C), 'Delta invalidates both identities once');

const model = new MeshLiveModel();
model.bootstrap({nodes: [node(A), {...node(B), latitude: 53}]});
const packet = {direction: 'rx', origin_id: B, observer_hash: 'packet',
  decoded: {route_type: 1, payload_type: 5, payload_hex: 'abcd', hops: ['aabbcc']}};
model.ingest(packet, 0, now);
assert(model.position(A, now) && model.active.length === 1, 'Unique repeater is mapped and animates');
const input = advert(C), original = JSON.stringify(input);
model.learn(input);
assert(!model.position(A, now) && !model.position(C, now), 'New collision suppresses old and new positions');
assert(model.active.length === 0, 'Existing geographic animations are removed');
assert(model.changedKeys(new Set([C])).has(A), 'Incremental rendering removes the pre-existing marker too');
assert(JSON.stringify(input) === original && model.nodes.size === 3, 'Packets and node directory are preserved');

const replay = new MeshLiveReplay({window_start: t, window_end: t + 600, speed: 10,
  bootstrap: {nodes: [node(A), node(B), {...node(C), node_type: null, latitude: null}],
    map_repeater_keys: [A, B, C]}, events: []}, 0);
assert(!replay.model.position(A, now), 'Replay hides collision before the second historical ADVERT is played');

const hop = key => ({public_key: key, node_type: 2, snr_min: 2, snr_max: 2,
  position: {latitude: 52, longitude: 10}});
assert(traceMapSnrSegments([hop(A), hop(B)]).length === 1, 'TRACE can show a unique segment');
repeaterMapVisibility.addKeys([A, C]);
assert(traceMapSnrSegments([hop(A), hop(B)]).length === 0, 'TRACE SNR labels cannot disclose a blocked endpoint');
console.log('Map visibility: identities, casing, types, deltas, animation purge, replay and TRACE passed');
