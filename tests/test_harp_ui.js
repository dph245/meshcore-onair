const source=await Deno.readTextFile('static/meshlive-effects.js');
const {meshHarpNote,meshPulse,MeshLiveEffects,MeshHarp,MESH_HARP}=new Function(source+';return {meshHarpNote,meshPulse,MeshLiveEffects,MeshHarp,MESH_HARP}')();
const assert=(ok,msg)=>{if(!ok)throw Error(msg);};
const keys=['aa','bb','cc'].map(k=>k.repeat(32));
for(const k of keys){assert(meshHarpNote(k)===meshHarpNote(k.toUpperCase()),'Case-independent complete key');assert(MESH_HARP.NOTES.includes(meshHarpNote(k)),'Pentatonic range');}
assert(meshHarpNote('aa')===null,'No short-prefix notes');
assert(meshPulse(0)===1&&meshPulse(175)===1.5&&meshPulse(350)===1,'Smooth 350ms pulse');
const effects=new MeshLiveEffects(), played=[];
const events=[{source:keys[0],target:keys[1],started:0,seenAt:0,packetIdentity:'p'},
 {source:keys[1],target:keys[2],started:0,seenAt:0,packetIdentity:'p'}];
const step=(t,ev=events)=>effects.step(ev,t,700,()=>({node_type:2}),k=>played.push(k));
step(0);step(16);assert(played.length===2,'Sources once, no duplicate frames');
assert(step(175).get(keys[0])===1.5,'Source pulse follows departure');
step(700);assert(played.length===3,'Shared middle node sounds once per packet');
assert(step(875).get(keys[2])===1.5,'Receiver pulse follows arrival');
assert(step(1050).size===0,'No leftover pulse');
step(5000,events.map(e=>({...e,started:5000,seenAt:5000})));assert(played.length===3,'Observer repeats deduped');
step(10000,events.map(e=>({...e,started:10000,seenAt:10000})));assert(played.length===5,'Fixed source-time packet window');
effects.reset();step(2000);assert(played.length===5,'No sound backlog after stall');
const params=()=>({value:1,setValueAtTime(){},exponentialRampToValueAtTime(){},linearRampToValueAtTime(){},cancelScheduledValues(){}});
class Context {
 constructor(){this.state='suspended';this.currentTime=0;this.destination={};this.osc=[];}
 async resume(){this.state='running';} async suspend(){this.state='suspended';}
 createGain(){return {gain:params(),connect(){},disconnect(){}};}
 createOscillator(){const o={frequency:{},connect(){},disconnect(){},start(){},stop(){}};this.osc.push(o);return o;}
}
const values=new Map(),storage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};
const harp=new MeshHarp(storage,Context);assert(!harp.enabled&&!harp.context,'Default off, no eager context');
harp.setEnabled(true);await harp.unlock();
for(let i=0;i<1000;i++)harp.play(keys[i%3]);
assert(harp.voices.size===8 && harp.context.osc.length===24,'Bounded polyphony and oscillator count');
for(const o of harp.context.osc)o.onended();
assert(harp.voices.size===0&&!harp.play(keys[0]),'Rate bounded even after voice cleanup');
harp.context.currentTime=1.1;assert(harp.play(keys[0]),'Rate replenishes');
harp.setEnabled(false);assert(!harp.play(keys[0]),'Off stops playback immediately');
await new Promise(r=>setTimeout(r,90));assert(harp.context.state==='suspended','Context suspended after gentle release');
harp.setEnabled(true);const restored=new MeshHarp(storage,Context);assert(restored.enabled&&!restored.context,'Preference restored without autoplay');
const unavailable=new MeshHarp({getItem(){throw Error();},setItem(){throw Error();}},undefined);
unavailable.setEnabled(true);assert(!await unavailable.unlock()&&!unavailable.play(keys[0]),'Unsupported audio and storage are harmless');
console.log('Harp: deterministic pitch, pulse timing, once per packet, storage, voice/rate limits and stop passed');
