const source = await Deno.readTextFile('static/trace-map.js');
const {segments, format} = new Function(`${source.split('// Historical observations')[0]}; return {segments: traceMapSnrSegments, format: traceMapSnrText}`)();
const equal = (actual, expected) => { if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error(`${JSON.stringify(actual)} != ${JSON.stringify(expected)}`); };
const hop = (hash, snr, extra = {}) => ({hash, public_key: hash.repeat(32), snr_min: snr, snr_max: snr,
  position: {latitude: 50 + ['aa','bb','cc'].indexOf(hash), longitude: 10}, ...extra});
const route = [hop('aa', 12), hop('bb', 7.5), hop('cc', -10.5), hop('bb', -3), hop('aa', .25)];
const samples = value => segments(value).map(s => s.samples.map(v => [v.snr, v.forward, v.hop]));
equal(samples(route), [[[7.5,true,2],[.25,false,5]],[[-10.5,true,3],[-3,false,4]]]);
// First SNR is from the unknown source, never from aa to bb. Keep quarter-dB precision.
equal(format(7.5), '+7,5 dB'); equal(format(-10.5), '−10,5 dB');
equal(format(0), '+0,0 dB'); equal(format(.25), '+0,25 dB');
equal(samples([hop('aa', 9), hop('bb', 0)]), [[[0,true,2]]]);
equal(samples([hop('aa', 9), hop('bb', null), hop('cc', 5)]), []);
equal(samples([hop('aa', 9), hop('bb', 3, {position: null}), hop('cc', 5)]), []);
equal(samples([hop('aa', 9), hop('bb', 3, {ambiguous: true})]), []);
// An aggregate range cannot be reinterpreted as two directional measurements.
equal(samples([hop('aa', 9), hop('bb', 3, {snr_max: 7})]), []);
// Repeated traversals, including equal measurements, must never overwrite one another.
equal(samples([hop('aa', 9), hop('bb', 3), hop('aa', -2), hop('bb', 3)]),
  [[[3,true,2],[-2,false,3],[3,true,4]]]);
equal(samples([hop('bb', 9), hop('aa', -2), hop('bb', 3)]), [[[-2,true,2],[3,false,3]]]);
const moved = [...route]; moved[4] = hop('aa', .25, {position: {latitude: 54, longitude: 10}});
equal(segments(moved).length, 3);
equal(segments([hop('aa', 9), hop('aa', 2)]).length, 0);
console.log('TRACE SNR: receiver-side mapping, round trips, precision, gaps, ambiguity and lossless repeated traversals passed');
