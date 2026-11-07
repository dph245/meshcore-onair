// Run the production message handler and the hidden MeshLive consumer without DOM work.
import {createReadStream, readFileSync} from 'node:fs';
import {createInterface} from 'node:readline';
import {createHash} from 'node:crypto';
import {Script, createContext, runInContext} from 'node:vm';
import assert from 'node:assert/strict';

const [trace, clientCount, ticks, sources] = process.argv.slice(2);
const [app, effects, meshLive] = JSON.parse(readFileSync(sources, 'utf8'));
const start = app.indexOf('function applyReceptionDelta(');
const end = app.indexOf("document.getElementById('pause').onclick");
const handler = app.slice(start < 0 ? app.indexOf('function connect()') : start, end);
const code = new Script(`
${effects}
${meshLive}
const groups = new Map(), expanded = new Set();
let rawPackets = [], status = {}, socket;
const connection = () => {}, render = () => {};
${handler}
connect();
`);
const clients = Array.from({length: Number(clientCount)}, () => {
  const context = createContext({window: {}, location: {protocol: 'http:', host: 'bench'},
    WebSocket: class {
      close() { throw Error('Unexpected sequence gap'); }
    }});
  code.runInContext(context);
  return {context, receive: runInContext('socket.onmessage', context)};
});

function normalized({groups, raw_packets, status}) {
  const ordered = groups.slice().sort((a, b) => a.id.localeCompare(b.id));
  const keys = new Set();
  JSON.stringify({groups, raw_packets, status}, (key, value) => { keys.add(key); return value; });
  return JSON.stringify({groups: ordered, raw_packets, status}, [...keys].sort());
}
const cpuUs = ({user, system}) => user + system;
let normalCpu = 0, snapshotCpu = 0, normalFrames = 0, digest, peakRss;
for await (const line of createInterface({input: createReadStream(trace), crlfDelay: Infinity})) {
  const target = line[0], data = line.slice(1);
  if (target === 'R') {
    peakRss = process.resourceUsage().maxRSS;
    const expected = normalized(JSON.parse(data));
    for (const {context} of clients) {
      const state = runInContext('({groups: [...groups.values()], raw_packets: rawPackets, status})', context);
      assert.equal(createHash('sha256').update(normalized(state)).digest('hex'),
                   createHash('sha256').update(expected).digest('hex'));
    }
    digest = createHash('sha256').update(expected).digest('hex');
    continue;
  }
  const peers = target === 'A' ? clients : target === 'F' ? clients.slice(0, -1) : clients.slice(-1);
  const before = process.cpuUsage();
  for (const {receive} of peers) receive({data});
  const cpu = cpuUs(process.cpuUsage(before));
  if (target === 'A' && normalFrames++ <= Number(ticks)) normalCpu += cpu;
  if (target === 'B') snapshotCpu = cpu;
}
assert.ok(digest);
console.log(JSON.stringify({
  client_cpu_ms_all_including_initial: normalCpu / 1000,
  client_peak_rss_kib_all: peakRss,
  overflow_client_cpu_ms: snapshotCpu / 1000,
  final_state_sha256: digest,
}));
