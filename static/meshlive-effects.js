/* Client-only effects: one pulse per marker, bounded synthesized harp voices. */
const MESH_HARP = Object.freeze({MAX_VOICES: 8, MAX_PER_SECOND: 8, DURATION: 1.4,
  PULSE_MS: 350, MAX_HEARD: 5000, NOTES: [60, 62, 64, 67, 69, 72, 74, 76, 79, 81]});

function meshHarpNote(key) {
  if (!/^[0-9a-f]{64}$/i.test(key || '')) return null;
  let hash = 2166136261;
  for (const c of key.toLowerCase()) hash = Math.imul(hash ^ c.charCodeAt(0), 16777619) >>> 0;
  return MESH_HARP.NOTES[hash % MESH_HARP.NOTES.length];
}

function meshPulse(age) {
  if (age < 0 || age >= MESH_HARP.PULSE_MS) return 1;
  return 1 + .5 * Math.sin(Math.PI * age / MESH_HARP.PULSE_MS) ** 2;
}

class MeshLiveEffects {
  constructor() { this.heard = new Map(); }
  reset() { this.heard.clear(); }
  step(events, now, travel, node, sound) {
    const pulses = new Map();
    for (const event of events) for (const [key, due] of [[event.source,event.started], [event.target,event.started+travel]]) {
      const age = now-due;
      if (age < 0) continue;
      const scale = meshPulse(age);
      if (scale > 1) pulses.set(key, Math.max(scale, pulses.get(key) || 1));
      if (node(key)?.node_type !== 2) continue;
      const id = JSON.stringify([event.packetIdentity, key]);
      const previous = this.heard.get(id);
      if (previous != null && event.seenAt-previous < 10000) continue;
      this.heard.delete(id); this.heard.set(id,event.seenAt);
      while (this.heard.size > MESH_HARP.MAX_HEARD) this.heard.delete(this.heard.keys().next().value);
      // Never play a backlog after stalled frames, disabled audio or rate limiting.
      if (age < 120) sound(key);
    }
    return pulses;
  }
}

class MeshHarp {
  constructor(storage, Context) {
    this.storage=storage; this.Context=Context; this.context=null;
    this.voices=new Set(); this.recent=[]; this.timer=null; this.enabled=false;
    this.generation=0; this.allowed=false;
    try { this.enabled=storage?.getItem('onair-meshlive-tones')==='true'; } catch { /* Optional storage. */ }
  }
  setEnabled(enabled) {
    this.enabled=enabled;
    try { this.storage?.setItem('onair-meshlive-tones',String(enabled)); } catch { /* Optional storage. */ }
    if (!enabled) this.stop();
  }
  async unlock() {
    if (!this.enabled || !this.Context) return false;
    const generation=++this.generation;
    try {
      clearTimeout(this.timer); this.timer=null;
      if (!this.context) this.context=new this.Context();
      await this.context.resume();
      if (generation!==this.generation || !this.enabled) return false;
      this.allowed=this.context.state==='running';
      return this.allowed;
    } catch { this.allowed=false; return false; }
  }
  play(key) {
    const midi=meshHarpNote(key), ctx=this.context;
    if (midi==null || !this.enabled || !this.allowed || ctx?.state!=='running') return false;
    const now=ctx.currentTime;
    this.recent=this.recent.filter(t=>now-t<1);
    if (this.voices.size>=MESH_HARP.MAX_VOICES || this.recent.length>=MESH_HARP.MAX_PER_SECOND) return false;
    this.recent.push(now);
    const voice={gain:ctx.createGain(),oscillators:[]};
    voice.gain.gain.setValueAtTime(1,now); voice.gain.connect(ctx.destination);
    this.voices.add(voice);
    let remaining=3;
    for (const [harmonic,level,decay] of [[1,.045,1.35],[2,.014,.8],[3,.006,.45]]) {
      const oscillator=ctx.createOscillator(), envelope=ctx.createGain();
      oscillator.type='sine'; oscillator.frequency.value=440*2**((midi-69)/12)*harmonic;
      envelope.gain.setValueAtTime(.00001,now);
      envelope.gain.exponentialRampToValueAtTime(level,now+.012);
      envelope.gain.exponentialRampToValueAtTime(.00001,now+decay);
      oscillator.connect(envelope); envelope.connect(voice.gain);
      oscillator.onended=()=>{
        oscillator.disconnect(); envelope.disconnect();
        if (!--remaining) { voice.gain.disconnect(); this.voices.delete(voice); }
      };
      voice.oscillators.push(oscillator);
      oscillator.start(now); oscillator.stop(now+MESH_HARP.DURATION);
    }
    return true;
  }
  stop() {
    this.allowed=false; this.generation++;
    clearTimeout(this.timer);
    const ctx=this.context;
    if (!ctx) return;
    const now=ctx.currentTime;
    for (const voice of this.voices) {
      voice.gain.gain.cancelScheduledValues(now);
      voice.gain.gain.setValueAtTime(voice.gain.gain.value,now);
      voice.gain.gain.linearRampToValueAtTime(0,now+.04);
      for (const osc of voice.oscillators) { try { osc.stop(now+.05); } catch { /* Already ended. */ } }
    }
    this.timer=setTimeout(()=>{this.timer=null; ctx.suspend().catch(()=>{});},70);
  }
}
