/* Geographic policy shared by every map. Packet data and resolution stay intact. */
class RepeaterMapVisibility {
  constructor() {
    this.prefixes = new Map();
    this.keys = new Set();
    this.collisions = new Set();
    this.changed = new Set();
    this.listeners = new Set();
    this.version = 0;
  }

  addKeys(keys = []) {
    let changed = false;
    for (const value of keys) {
      const key = typeof value === 'string' ? value.toLowerCase() : '';
      if (!/^[0-9a-f]{64}$/.test(key) || this.keys.has(key)) continue;
      this.keys.add(key);
      const prefix = key.slice(0, 6);
      if (!this.prefixes.has(prefix)) this.prefixes.set(prefix, new Set());
      const bucket = this.prefixes.get(prefix);
      bucket.add(key);
      if (bucket.size < 2) continue;
      this.collisions.add(prefix);
      if (bucket.size === 2) for (const identity of bucket) this.changed.add(identity);
      else this.changed.add(key);
      changed = true;
    }
    if (changed) {
      this.version++;
      for (const listener of this.listeners) listener();
    }
  }

  hidden(value, nodeType = 2) {
    const key = value?.toLowerCase();
    return (nodeType == null || nodeType === 2) && this.keys.has(key) && this.collisions.has(key.slice(0, 6));
  }

  repeaterKey(packet) {
    const decoded = packet.decoded || {}, advert = decoded.advert;
    if (packet.direction === 'rx' && !decoded.advert_status &&
        advert?.signature_status === 'Gültig' && advert.node_type === 2) return advert.public_key;
  }

  learn(packet) {
    const key = this.repeaterKey(packet);
    if (key) this.addKeys([key]);
  }

  receive(data) {
    const packets = data.receptions ?? (data.groups || []).flatMap(group => group.receptions || []);
    this.addKeys(packets.map(packet => this.repeaterKey(packet)).filter(Boolean));
  }
}

// Keep learned collisions across tab changes and stale HTTP snapshots.
const repeaterMapVisibility = new RepeaterMapVisibility();
