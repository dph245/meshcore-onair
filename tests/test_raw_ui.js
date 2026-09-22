const source = await Deno.readTextFile('static/app.js');
const elements = {
  'raw-output': {textContent: '', scrollTop: 0, scrollHeight: 100},
  'raw-follow': {checked: true, addEventListener() {}},
  'panel-raw': {hidden: false},
};
globalThis.document = {getElementById: id => elements[id]};
const start = source.indexOf('let rawPackets = []');
const end = source.indexOf('const groups = ', start);
new Function(`${source.slice(start, end)}
let paused = false;
const assert = (ok, message) => { if (!ok) throw Error(message); };
rawPackets = ['first\\n', '<script>untrusted</script>\\n'];
renderRaw();
assert(rawOutput.textContent === rawPackets.join(''), 'Verbatim text, no HTML parsing');
assert(rawOutput.scrollTop === 100, 'Follow newest packet');
paused = true;
rawPackets.push('third\\n');
renderRaw();
assert(!rawOutput.textContent.includes('third'), 'Pause freezes display');
paused = false;
rawFollow.checked = false;
rawOutput.scrollTop = 12;
renderRaw();
assert(rawOutput.textContent.includes('third'), 'Resume catches up');
assert(rawOutput.scrollTop === 12, 'Follow can be disabled for reading');
document.getElementById('panel-raw').hidden = true;
rawPackets.push('fourth\\n');
renderRaw();
assert(!rawOutput.textContent.includes('fourth'), 'Hidden panel waits');
document.getElementById('panel-raw').hidden = false;
renderRaw();
assert(rawOutput.textContent.includes('fourth'), 'Opening tab catches up');
`)();
console.log('Raw UI: text safety, follow, pause and tab switching passed');
