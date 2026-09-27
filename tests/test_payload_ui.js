const source = await Deno.readTextFile('static/app.js');
const start = source.indexOf('function appendPayloadDetails(');
const end = source.indexOf('// Central thresholds', start);
const text = (tag, value, className) => ({tag, textContent: value, className});
const appendDetails = new Function('text', `${source.slice(start, end)}; return appendPayloadDetails;`)(text);
const nodes = [];
const container = {append: node => nodes.push(node)};
appendDetails(container, {});
if (nodes.length) throw Error('Old packets must remain supported');
appendDetails(container, {
  payload_summary: 'Pfad-Rückgabe',
  payload_fields: [{label: 'Chiffretext', value: '<script>untrusted</script>'}],
  payload_status: 'verschlüsselt',
});
if (nodes.length !== 3 || nodes[1].textContent !== 'Chiffretext: <script>untrusted</script>'
    || nodes[2].className !== 'muted') throw Error('Details must render as text with status');
if (!source.includes('appendPayloadDetails(block, decoded)')
    || !source.includes('appendPayloadDetails(entry, d)')) throw Error('Live and archive must show details');
console.log('Payload UI: details, status, old packets and safe text passed');
