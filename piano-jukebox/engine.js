// engine.js - MIDI file parsing, outputs (Web MIDI + preview synth), scheduler.
// Mirrors piano_player.py: keys 21-108 only, drums (ch 10) skipped,
// sustain (64) + soft (67) pedals passed, velocity = max(floor, v*volume),
// and every key released when playback stops.

export const LOW_KEY = 21, HIGH_KEY = 108, SUSTAIN = 64, SOFT = 67;

// ------------------------------------------------------------------ parsing
export function parseMidi(buf) {
  const d = new DataView(buf);
  let p = 0;
  const u8 = () => d.getUint8(p++);
  const u16 = () => { const v = d.getUint16(p); p += 2; return v; };
  const u32 = () => { const v = d.getUint32(p); p += 4; return v; };
  const str = n => { let s = ""; for (let i = 0; i < n; i++) s += String.fromCharCode(d.getUint8(p + i)); p += n; return s; };
  const vlq = () => { let v = 0, b; do { b = u8(); v = (v << 7) | (b & 127); } while (b & 128); return v; };

  if (str(4) !== "MThd") throw new Error("Not a MIDI file");
  const hlen = u32(); u16(); const ntracks = u16(), div = u16(); p += hlen - 6;

  const raw = [];
  for (let t = 0; t < ntracks && p + 8 <= d.byteLength; t++) {
    const id = str(4), len = u32(), end = Math.min(p + len, d.byteLength);
    if (id !== "MTrk") { p = end; continue; }
    let tick = 0, run = 0;
    while (p < end) {
      tick += vlq();
      let st = d.getUint8(p);
      if (st & 0x80) { p++; if (st < 0xF0) run = st; }
      else { if (!run) break; st = run; }
      if (st === 0xFF) {
        const type = u8(), l = vlq();
        if (type === 0x51 && l === 3)
          raw.push({ tick, o: 0, tempo: (d.getUint8(p) << 16) | (d.getUint8(p + 1) << 8) | d.getUint8(p + 2) });
        p += l;
        if (type === 0x2F) break;
        continue;
      }
      if (st === 0xF0 || st === 0xF7) { p += vlq(); continue; }
      const type = st & 0xF0, ch = st & 15;
      const a = u8(), b = (type === 0xC0 || type === 0xD0) ? 0 : u8();
      raw.push({ tick, o: 1, type, ch, a, b });
    }
    p = end;
  }
  raw.sort((x, y) => x.tick - y.tick || x.o - y.o);

  const events = [];
  let sec = 0, lastTick = 0, spt;                      // seconds per tick
  if (div & 0x8000) spt = 1 / ((256 - (div >> 8)) * (div & 255));
  else spt = 0.5 / div;                                 // 120 bpm default
  for (const e of raw) {
    sec += (e.tick - lastTick) * spt; lastTick = e.tick;
    if (e.o === 0) { if (!(div & 0x8000)) spt = e.tempo / 1e6 / div; continue; }
    if (e.ch === 9) continue;                           // drums
    if (e.type === 0x90 || e.type === 0x80) {
      if (e.a < LOW_KEY || e.a > HIGH_KEY) continue;
      events.push({ t: sec, k: (e.type === 0x90 && e.b > 0) ? 1 : 0, n: e.a, v: e.b });
    } else if (e.type === 0xB0 && (e.a === SUSTAIN || e.a === SOFT)) {
      events.push({ t: sec, k: 2, n: e.a, v: e.b });
    }
  }
  const duration = events.length ? events[events.length - 1].t : 0;
  return { events, duration };
}

// ------------------------------------------------------------------ outputs
export class PreviewSynth {             // simple piano-ish sound for testing
  constructor() { this.id = "preview"; this.name = "This device (preview sound)"; this.voices = new Map(); this.held = new Set(); this.sus = false; }
  _ctx() {
    if (!this.ctx) {
      this.ctx = new AudioContext();
      this.master = this.ctx.createGain(); this.master.gain.value = 0.22;
      const comp = this.ctx.createDynamicsCompressor();
      this.master.connect(comp); comp.connect(this.ctx.destination);
    }
    if (this.ctx.state === "suspended") this.ctx.resume();
    return this.ctx;
  }
  send([st, a, b], at) {
    const ctx = this._ctx();
    const when = ctx.currentTime + Math.max(0, (at - performance.now()) / 1000);
    const type = st & 0xF0;
    if (type === 0x90 && b > 0) this._on(a, b, when);
    else if (type === 0x80 || type === 0x90) {
      if (this.sus) this.held.add(a); else this._off(a, when);
    } else if (type === 0xB0 && a === SUSTAIN) {
      this.sus = b >= 64;
      if (!this.sus) { for (const n of this.held) this._off(n, when); this.held.clear(); }
    }
  }
  _on(n, vel, when) {
    this._off(n, when);
    const ctx = this.ctx, f = 440 * 2 ** ((n - 69) / 12);
    const g = ctx.createGain(), o1 = ctx.createOscillator(), o2 = ctx.createOscillator(), g2 = ctx.createGain();
    o1.type = "triangle"; o1.frequency.value = f;
    o2.type = "sine"; o2.frequency.value = f * 2; g2.gain.value = 0.25;
    const peak = 0.15 + 0.6 * (vel / 127) ** 1.5, decay = Math.max(0.6, 4 - (n - 21) / 30);
    g.gain.setValueAtTime(0, when);
    g.gain.linearRampToValueAtTime(peak, when + 0.006);
    g.gain.setTargetAtTime(0, when + 0.01, decay / 3);
    o1.connect(g); o2.connect(g2); g2.connect(g); g.connect(this.master);
    o1.start(when); o2.start(when);
    const stopAt = when + decay * 2;
    o1.stop(stopAt); o2.stop(stopAt);
    this.voices.set(n, { g, o1, o2 });
    o1.onended = () => { if (this.voices.get(n)?.o1 === o1) this.voices.delete(n); };
  }
  _off(n, when) {
    const v = this.voices.get(n);
    if (!v) return;
    v.g.gain.cancelScheduledValues(when);
    v.g.gain.setTargetAtTime(0, when, 0.06);
    try { v.o1.stop(when + 0.4); v.o2.stop(when + 0.4); } catch {}
    this.voices.delete(n);
  }
  reset() { this.sus = false; this.held.clear(); for (const n of [...this.voices.keys()]) this._off(n, this.ctx ? this.ctx.currentTime : 0); }
}

// Sends notes through piano_web.py (local server) when the browser can't
// reach MIDI devices itself. Messages carry "play in N ms" and are batched.
export class BridgeOutput {
  constructor(piano) {
    this.id = "bridge"; this.name = `${piano} (via this PC)`;
    this.buf = []; this.batch = 0; this.clearNext = false; this.timer = null;
  }
  send(bytes, at) {
    this.buf.push([at, ...bytes]);
    if (!this.timer) this.timer = setTimeout(() => this.flush(), 0);
  }
  clear() {                       // drop notes the server is still holding
    this.buf = []; this.clearNext = true;
    if (!this.timer) this.timer = setTimeout(() => this.flush(), 0);
  }
  flush() {
    this.timer = null;
    const now = performance.now();
    const body = { batch: ++this.batch, clear: this.clearNext,
                   msgs: this.buf.map(([at, ...b]) => [Math.max(0, at - now), ...b]) };
    this.buf = []; this.clearNext = false;
    if (!body.msgs.length && !body.clear) return;
    fetch("bridge/send", { method: "POST", headers: { "Content-Type": "application/json" },
                           body: JSON.stringify(body), keepalive: true }).catch(() => {});
  }
}

async function findBridge() {
  try {
    const r = await fetch("bridge/status", { cache: "no-store" });
    if (!r.ok) return null;
    const s = await r.json();
    return s.piano ? new BridgeOutput(s.piano) : null;
  } catch { return null; }
}

const SKIP_NAMES = ["microsoft gs wavetable", "midi through"];
const PREFER_NAMES = ["widi", "ble", "bluetooth", "md-bt", "usb midi", "pianodisc"];

// Returns at once; MIDI devices are added (via onChange) when the browser
// grants access, so the preview works while the permission prompt is open.
export function getOutputs(onChange) {
  const preview = new PreviewSynth();
  let access = null, bridge = null;
  const api = { preview, error: "pending" };
  // Check for the local bridge now and every 10 s (piano may connect later).
  const pollBridge = async () => {
    const b = await findBridge();
    if (!!b !== !!bridge || (b && bridge && b.name !== bridge.name)) { bridge = b; onChange(list()); }
  };
  pollBridge(); setInterval(pollBridge, 10000);
  if (!navigator.requestMIDIAccess) api.error = "unsupported";
  else navigator.requestMIDIAccess({ sysex: false }).then(a => {
    access = a; api.error = "";
    access.onstatechange = () => onChange(list());
    onChange(list());
  }, e => { api.error = e.name === "SecurityError" || e.name === "NotAllowedError" ? "denied" : "failed"; onChange(list()); });
  const list = () => {
    const outs = access ? [...access.outputs.values()].map(o => ({
      id: o.id, name: o.name, raw: o,
      send: (bytes, at) => o.send(bytes, at),
      skip: SKIP_NAMES.some(s => o.name.toLowerCase().includes(s)),
    })) : [];
    return [...(bridge ? [bridge] : []), ...outs, preview];
  };
  api.list = list;
  api.pickPiano = outs => {
    const usable = outs.filter(o => o.id !== "preview" && !o.skip);
    return usable.find(o => o.id === "bridge") || usable.find(o => PREFER_NAMES.some(p => o.name.toLowerCase().includes(p))) ||
           (usable.length === 1 ? usable[0] : null);
  };
  return api;
}

// ---------------------------------------------------------------- scheduler
const LOOKAHEAD = 350;      // ms of notes handed to the output in advance

export class Engine {
  constructor() {
    this.ev = []; this.i = 0; this.t0 = 0; this.pos = 0; this.dur = 0;
    this.playing = false; this.out = null; this.active = new Set();
    this.quietUntil = 0;
    this.settings = { volume: 0.8, floor: 25, channel: 1 };
    this.onend = () => {};
    // A worker timer keeps ticking even when the tab is in the background.
    const src = "setInterval(() => postMessage(0), 25)";
    this.timer = new Worker(URL.createObjectURL(new Blob([src], { type: "text/javascript" })));
    this.timer.onmessage = () => this.tick();
  }
  setOutput(out) {
    if (this.out && this.out !== out) this.silence();
    this.out = out;
    if (this.playing) this._restorePedals(performance.now());
  }
  load({ events, duration }) {
    this.stop();
    this.ev = events; this.dur = duration; this.pos = 0; this.i = 0;
  }
  position() { return this.playing ? Math.min(this.dur, (performance.now() - this.t0) / 1000) : this.pos; }
  play() {
    if (!this.ev.length || this.playing) return;
    // small head start so the first notes are scheduled on time, not late
    const now = performance.now(), start = Math.max(now + 60, this.quietUntil + 20);
    if (this.pos >= this.dur) this.pos = 0;
    this.t0 = start - this.pos * 1000;
    this.i = this._indexAt(this.pos);
    this._restorePedals(start);
    this.playing = true;
  }
  pause() {
    if (!this.playing) return;
    this.pos = this.position(); this.playing = false; this.silence();
  }
  stop() { if (this.playing) { this.playing = false; this.silence(); } this.pos = 0; }
  seek(sec) {
    const was = this.playing;
    if (was) { this.playing = false; this.silence(); }
    this.pos = Math.max(0, Math.min(this.dur, sec));
    if (was) this.play();
  }
  _indexAt(sec) {
    let lo = 0, hi = this.ev.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (this.ev[m].t < sec) lo = m + 1; else hi = m; }
    return lo;
  }
  _restorePedals(at) {
    const ch = this.settings.channel - 1;
    const state = { [SUSTAIN]: 0, [SOFT]: 0 };
    for (let j = 0; j < this.i; j++) if (this.ev[j].k === 2) state[this.ev[j].n] = this.ev[j].v;
    for (const c of [SUSTAIN, SOFT]) this._send([0xB0 | ch, c, state[c]], at);
  }
  _send(bytes, at) { try { this.out && this.out.send(bytes, at); } catch (e) { console.warn(e); } }
  tick() {
    if (!this.playing) return;
    const now = performance.now(), horizon = now + LOOKAHEAD;
    const { volume, floor, channel } = this.settings, ch = channel - 1;
    while (this.i < this.ev.length) {
      const e = this.ev[this.i], at = this.t0 + e.t * 1000;
      if (at > horizon) break;
      const when = Math.max(at, now);
      if (e.k === 1) {
        const v = Math.max(floor, Math.min(127, Math.round(e.v * volume)));
        this._send([0x90 | ch, e.n, v], when); this.active.add(e.n);
      } else if (e.k === 0) {
        this._send([0x80 | ch, e.n, 0], when); this.active.delete(e.n);
      } else {
        this._send([0xB0 | ch, e.n, e.v], when);
      }
      this.i++;
    }
    if (this.i >= this.ev.length && now > this.t0 + this.dur * 1000 + 400) {
      this.playing = false; this.pos = this.dur; this.silence(); this.onend();
    }
  }
  // Release pedals and keys now, then sweep all 88 keys again after any
  // notes already handed to the output have gone out.
  silence() {
    if (!this.out) return;
    const ch = this.settings.channel - 1, now = performance.now();
    if (this.out.clear) this.out.clear();     // bridge: drop queued notes first
    this._send([0xB0 | ch, SUSTAIN, 0], now);
    this._send([0xB0 | ch, SOFT, 0], now);
    for (const n of this.active) this._send([0x80 | ch, n, 0], now);
    this.active.clear();
    const later = now + LOOKAHEAD + 30;
    for (let n = LOW_KEY; n <= HIGH_KEY; n++) this._send([0x80 | ch, n, 0], later + (n - LOW_KEY) * 2);
    this._send([0xB0 | ch, SUSTAIN, 0], later + 180);
    this.quietUntil = later + 180;
    if (this.out.reset) this.out.reset();
  }
  panic() { this.pause(); this.silence(); }
}
