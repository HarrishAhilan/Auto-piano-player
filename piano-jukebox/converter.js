// Song -> MIDI converter panel. Talks to the local server in the song-to-midi folder
// (Start Converter.bat). Audio is decoded in the browser and sent as WAV, so any format
// the browser can play works (mp3, m4a, wav, ogg, flac, mic recordings).

const LOCAL = /^(localhost|127\.0\.0\.1)$/.test(location.hostname) && location.port === "8770";
const API = LOCAL ? "" : "http://localhost:8770";
const AUDIO_RE = /\.(mp3|wav|m4a|aac|ogg|oga|opus|flac|webm|aiff?|wma|mp4)$/i;
const PART_LABELS = { vocals: "Melody (vocals)", other: "Chords & instruments", bass: "Bass" };

let D;                      // deps from app.js: { el, icon, toast, addFiles }
const jobs = [];            // { key, name, state, status, id, error }
let online = null;          // null = unknown, true/false after a health check
const opts = Object.assign({ mode: "auto", parts: ["vocals", "other", "bass"] },
  JSON.parse(localStorage.getItem("pj-convert") || "{}"));
const saveOpts = () => localStorage.setItem("pj-convert", JSON.stringify(opts));
const rec = { on: false, start: 0, level: 0, timer: null, stop: null };

export function initConverter(deps) { D = deps; }
export const isAudio = f => AUDIO_RE.test(f.name) || (f.type || "").startsWith("audio/");

// ------------------------------------------------------------------ server
async function checkServer() {
  try {
    const r = await fetch(API + "/api/health", { signal: AbortSignal.timeout(2500) });
    online = r.ok;
  } catch { online = false; }
  refresh();
  return online;
}

async function toWav(blob) {
  const buf = await blob.arrayBuffer();
  const ctx = new OfflineAudioContext(2, 1, 44100);
  const ab = await ctx.decodeAudioData(buf);
  if (ab.duration > 20 * 60) throw new RangeError("That's over 20 minutes - please use a shorter clip.");
  if (ab.duration < 1) throw new RangeError("That recording is too short.");
  const ch = Math.min(2, ab.numberOfChannels), n = ab.length;
  const data = [...Array(ch)].map((_, i) => ab.getChannelData(i));
  const out = new DataView(new ArrayBuffer(44 + n * ch * 2));
  const str = (o, s) => [...s].forEach((c, i) => out.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF"); out.setUint32(4, 36 + n * ch * 2, true); str(8, "WAVE"); str(12, "fmt ");
  out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, ch, true);
  out.setUint32(24, ab.sampleRate, true); out.setUint32(28, ab.sampleRate * ch * 2, true);
  out.setUint16(32, ch * 2, true); out.setUint16(34, 16, true); str(36, "data"); out.setUint32(40, n * ch * 2, true);
  let o = 44;
  for (let i = 0; i < n; i++) for (let c = 0; c < ch; c++) {
    const v = Math.max(-1, Math.min(1, data[c][i])); out.setInt16(o, v < 0 ? v * 0x8000 : v * 0x7fff, true); o += 2;
  }
  return new Blob([out], { type: "audio/wav" });
}

// fetch() can't report upload progress, so use XMLHttpRequest for the upload
function upload(url, body, onProgress) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", url);
    x.setRequestHeader("Content-Type", "audio/wav");
    x.upload.onprogress = e => e.lengthComputable && onProgress(e.loaded / e.total);
    x.onload = () => {
      let j = {};
      try { j = JSON.parse(x.responseText); } catch {}
      x.status >= 200 && x.status < 300 ? resolve(j) : reject(new Error(j.error || `server error ${x.status}`));
    };
    x.onerror = () => reject(new TypeError("network error"));
    x.send(body);
  });
}
const fmtEta = s => s == null ? "" : s < 60 ? "less than a minute left" : `about ${Math.round(s / 60)} min left`;

async function runJob(blob, name) {
  const job = { key: crypto.randomUUID(), name, state: "working", status: "Preparing audio..." };
  jobs.unshift(job); refreshJobs();
  try {
    if (online === false && !(await checkServer())) throw new Error("The converter isn't running. Double-click Start Converter.bat in the song-to-midi folder.");
    let wav;
    try { wav = await toWav(blob); }
    catch (e) { throw new Error(e instanceof RangeError ? e.message : "This browser couldn't read that audio file."); }
    job.status = "Uploading..."; job.progress = 0; refreshJobs();
    const q = new URLSearchParams({ mode: opts.mode, parts: opts.parts.join(","), name, filename: "audio.wav" });
    const j = await upload(`${API}/api/convert?${q}`, wav, f => { job.progress = f; refreshJobs(); });
    job.id = j.id; job.progress = null; job.eta = null;
    for (;;) {
      await new Promise(res => setTimeout(res, 1000));
      const r = await fetch(`${API}/api/job/${job.id}`);
      if (!r.ok) throw new Error("The converter was restarted and lost this song - please try again.");
      const s = await r.json();
      job.status = s.status || s.state; job.progress = s.progress ?? null; job.eta = s.eta ?? null; refreshJobs();
      if (s.state === "error") throw new Error(s.status);
      if (s.state === "done") { job.summary = s.summary; job.file = s.file; break; }
    }
    const mr = await fetch(`${API}/api/job/${job.id}/midi`);
    if (!mr.ok) throw new Error("Couldn't download the finished MIDI - please try again.");
    const mid = await mr.arrayBuffer();
    job.url = URL.createObjectURL(new Blob([mid], { type: "audio/midi" }));
    job.state = "done"; job.status = `Done - ${job.summary}. Added to My Music.`; refreshJobs();
    await D.addFiles([new File([mid], job.file || `${name}.mid`, { type: "audio/midi" })]);
  } catch (e) {
    if (e instanceof TypeError) { online = false; e = new Error("Couldn't reach the converter. Is Start Converter.bat running?"); }
    job.state = "error"; job.status = e.message; refresh();  // full refresh: may show "offline" banner
    D.toast(`Couldn't convert ${name}`);
  }
}

export function convertFiles(files) {
  const audio = files.filter(isAudio);
  for (const f of audio) runJob(f, f.name.replace(/\.[^.]+$/, ""));
  if (audio.length) {
    D.toast(`Converting ${audio.length} song${audio.length > 1 ? "s" : ""} to MIDI...`);
    if (location.hash !== "#/c/my") location.hash = "#/c/my";
  }
}

// -------------------------------------------------------------- recording
async function startRecording(nameInput) {
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: {
      echoCancellation: false, noiseSuppression: false, autoGainControl: false } });  // these wreck music
  } catch { D.toast("Couldn't use the microphone - check the browser's permission"); return; }
  const mr = new MediaRecorder(stream), chunks = [];
  mr.ondataavailable = e => e.data.size && chunks.push(e.data);
  const actx = new AudioContext(), an = actx.createAnalyser(), buf = new Float32Array(2048);
  an.fftSize = 2048; actx.createMediaStreamSource(stream).connect(an);
  Object.assign(rec, { on: true, start: Date.now(), level: 0 });
  rec.timer = setInterval(() => { an.getFloatTimeDomainData(buf); rec.level = Math.max(...buf.map(Math.abs)); refreshRec(); }, 100);
  const name = nameInput.value.trim() || `Recording ${new Date().toLocaleString([], { dateStyle: "short", timeStyle: "short" })}`;
  rec.stop = () => new Promise(res => { mr.onstop = res; mr.stop(); }).then(() => {
    clearInterval(rec.timer); stream.getTracks().forEach(t => t.stop()); actx.close();
    rec.on = false; refresh();
    const secs = (Date.now() - rec.start) / 1000;
    if (secs < 2) { D.toast("Recording too short"); return; }
    draftName = ""; refresh();
    runJob(new Blob(chunks, { type: mr.mimeType }), name);
  });
  mr.start(500); refresh();
}

// ------------------------------------------------------------ piano check
// Record the real piano while a song plays (by hand, or automatically in Analyse mode), show live
// how it SHOULD sound (from the original mp3) next to what the mic hears, then analyse precisely.
const chk = { on: false, start: 0, level: 0, timer: null, stop: null, busy: false, result: null, error: null,
              song: null, live: null };
const refCache = new Map();                        // song name -> { hop, frames, data: Uint8Array } | null

async function loadReference(name) {
  if (refCache.has(name)) return refCache.get(name);
  let ref = null;
  try {
    const r = await fetch(`${API}/api/reference?${new URLSearchParams({ name })}`);
    if (r.ok) { const j = await r.json(); ref = { hop: j.hop, frames: j.frames, data: Uint8Array.from(atob(j.data), c => c.charCodeAt(0)) }; }
  } catch {}
  refCache.set(name, ref); return ref;
}

// colour maps: "should sound" in blue, "piano heard" in amber, "notes sent" in grey
const CMAP = {
  expected: v => [20 + v * 0.25, 40 + v * 0.55, 60 + v * 0.75],
  heard: v => [30 + v * 0.88, 20 + v * 0.62, 10 + v * 0.2],
  sent: v => [v * 0.8, v * 0.8, v * 0.85],
};

async function startCheck(auto = false) {
  const cur = D.currentTrack?.();
  if (!cur) { if (!auto) D.toast("Play a song on the piano first, then start the check"); return; }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: {
      echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
  } catch { D.toast("Couldn't use the microphone - check the browser's permission"); opts.analyse = false; saveOpts(); refresh(); return; }
  const mr = new MediaRecorder(stream), chunks = [];
  mr.ondataavailable = e => e.data.size && chunks.push(e.data);
  const actx = new AudioContext(), an = actx.createAnalyser();
  an.fftSize = 8192; an.smoothingTimeConstant = 0.3;
  actx.createMediaStreamSource(stream).connect(an);
  const tbuf = new Float32Array(2048), fbuf = new Float32Array(an.frequencyBinCount);
  // which FFT bins belong to each of the 88 keys (±half a semitone)
  const binHz = actx.sampleRate / an.fftSize;
  const keyBins = [...Array(88)].map((_, k) => {
    const f = 440 * 2 ** ((k + 21 - 69) / 12);
    return [Math.max(1, Math.floor(f * 2 ** (-1 / 24) / binHz)), Math.max(1, Math.ceil(f * 2 ** (1 / 24) / binHz))];
  });
  const pos0 = cur.position();
  Object.assign(chk, { on: true, start: Date.now(), level: 0, result: null, error: null, song: cur.name });
  chk.live = { ref: undefined, cols: [] };                       // undefined = still loading, null = none
  loadReference(cur.name).then(r => { if (chk.live) chk.live.ref = r; });
  chk.timer = setInterval(() => {
    an.getFloatTimeDomainData(tbuf); chk.level = Math.max(...tbuf.map(Math.abs));
    an.getFloatFrequencyData(fbuf);
    const col = new Uint8Array(88);
    for (let k = 0; k < 88; k++) {
      let m = -140; const [a, b] = keyBins[k];
      for (let i = a; i <= b && i < fbuf.length; i++) m = Math.max(m, fbuf[i]);
      col[k] = Math.max(0, Math.min(255, (m + 95) * 4.5));
    }
    const live = chk.live; if (!live) return;
    live.cols.push({ heard: col, pos: D.currentTrack?.()?.position() ?? null });
    if (live.cols.length > 400) live.cols.shift();
    refreshRec(); drawLive();
  }, 40);
  chk.stop = () => new Promise(res => { mr.onstop = res; mr.stop(); }).then(async () => {
    clearInterval(chk.timer); stream.getTracks().forEach(t => t.stop()); actx.close();
    chk.on = false; chk.live = null;
    if ((Date.now() - chk.start) / 1000 < 8) { chk.error = "Record at least 8 seconds of the piano."; refresh(); return; }
    chk.busy = true; refresh();
    try {
      const [wav, midi] = await Promise.all([toWav(new Blob(chunks, { type: mr.mimeType })), cur.load()]);
      const s = D.settings?.() || {};
      const q = new URLSearchParams({ midi_len: midi.byteLength, pos: pos0.toFixed(2), name: cur.name,
        vol: s.volume ?? "", floor: s.floor ?? "" });
      const r = await fetch(`${API}/api/check?${q}`, { method: "POST", body: new Blob([midi, wav]) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || `server error ${r.status}`);
      chk.result = j;
    } catch (e) {
      chk.error = e instanceof TypeError ? "Couldn't reach the converter. Is Start Converter.bat running?" : e.message;
    }
    chk.busy = false; refresh();
  });
  mr.start(500); refresh();
}

async function showLastCheck() {
  try {
    const r = await fetch(`${API}/api/checks/latest`); const j = await r.json();
    if (!r.ok) throw new Error(j.error || `server error ${r.status}`);
    chk.result = j; chk.error = null;
  } catch (e) { chk.error = e instanceof TypeError ? "Couldn't reach the converter. Is Start Converter.bat running?" : e.message; }
  refresh();
}

// Analyse mode: start recording the moment a song plays, stop + analyse when it pauses, ends or changes.
setInterval(() => {
  if (!D || !opts.analyse) return;
  const cur = D.currentTrack?.();
  if (chk.on && (!cur || cur.name !== chk.song)) chk.stop();
  else if (!chk.on && !chk.busy && cur && !rec.on) startCheck(true);
}, 250);

// live view: two strips scrolling right-to-left, keys bottom (low) to top (high)
function drawLive() {
  const cv = root?.querySelector(".cv-live canvas"); const live = chk.live;
  if (!cv || !live) return;
  const g = cv.getContext("2d"), W = cv.width, H = 88, cols = live.cols, n = cols.length;
  const img = g.createImageData(W, H * 2 + 6);
  const put = (x, y, rgb) => { const o = (y * W + x) * 4; img.data[o] = rgb[0]; img.data[o + 1] = rgb[1]; img.data[o + 2] = rgb[2]; img.data[o + 3] = 255; };
  for (let x = 0; x < W; x++) {
    const c = cols[n - W + x]; if (!c) continue;
    const ref = live.ref;
    if (ref && c.pos != null) {
      const fi = Math.round(c.pos / ref.hop);
      if (fi >= 0 && fi < ref.frames) for (let k = 0; k < 88; k++) put(x, H - 1 - k, CMAP.expected(ref.data[fi * 88 + k]));
    }
    for (let k = 0; k < 88; k++) put(x, H + 6 + H - 1 - k, CMAP.heard(c.heard[k]));
  }
  g.putImageData(img, 0, 0);
}

// results: three aligned pictures + issue markers; click an issue to jump the jukebox there
function drawResult(div, viz, issues) {
  const panels = [["expected", "How the song should sound (from the mp3)"], ["heard", "What the piano played (mic)"], ["sent", "Notes sent to the piano"]];
  const W = viz.frames, H = 88, dec = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  const colour = { "melody buried": "#ff7a59", "not heard": "#ff4d6d", "timing (stretch)": "#f5c542", "wrong vs song": "#c77dff", "missing vs song": "#4cc9f0" };
  for (const [key, label] of panels) {
    if (!viz[key]) continue;
    const data = dec(viz[key]);
    const cv = document.createElement("canvas"); cv.width = W; cv.height = H; cv.className = "cv-viz";
    const g = cv.getContext("2d"), img = g.createImageData(W, H);
    for (let x = 0; x < W; x++) for (let k = 0; k < 88; k++) {
      const v = data[x * 88 + k], rgb = CMAP[key](v), o = ((H - 1 - k) * W + x) * 4;
      img.data[o] = rgb[0]; img.data[o + 1] = rgb[1]; img.data[o + 2] = rgb[2]; img.data[o + 3] = 255;
    }
    g.putImageData(img, 0, 0);
    for (const is of issues) {                                     // issue markers on every panel
      const x = Math.round((is.t - viz.start) / viz.hop);
      if (x < 0 || x >= W) continue;
      g.fillStyle = colour[is.kind] || "#fff";
      g.globalAlpha = 0.22; g.fillRect(x, 0, 1, H);                 // faint line through the picture
      g.globalAlpha = 1; g.fillRect(x, 0, Math.max(2, W / 300), 6);  // solid tick at the top
    }
    g.globalAlpha = 1;
    cv.title = label;
    cv.onclick = e => { const r = cv.getBoundingClientRect(); D.seek?.(viz.start + (e.clientX - r.left) / r.width * W * viz.hop); };
    div.append(D.el("div", { className: "cv-viz-label", textContent: label }), cv);
  }
  const t0 = viz.start, t1 = viz.start + W * viz.hop, f = t => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
  div.append(D.el("div", { className: "cv-viz-axis" }, D.el("span", { textContent: f(t0) }), D.el("span", { textContent: f((t0 + t1) / 2) }), D.el("span", { textContent: f(t1) })));
  div.append(D.el("div", { className: "cv-legend" }, ...Object.entries(colour).map(([k, c]) =>
    D.el("span", {}, D.el("i", { style: { background: c } }), k))));
}

function checkSection() {
  const { el } = D;
  const parts = [el("h3", { className: "cv-sub", textContent: "Check how your piano sounds" }),
    el("p", { className: "note", textContent: "Put the laptop near the piano. In Analyse mode it starts recording the moment you press play and analyses when you pause or the song ends. Top strip: how the song should sound (from the mp3). Bottom strip: what the mic hears." }),
    el("label", { className: "cv-part" }, el("input", { type: "checkbox", checked: !!opts.analyse,
      onchange: e => { opts.analyse = e.target.checked; saveOpts(); if (!opts.analyse && chk.on) chk.stop(); refresh(); } }),
      "Analyse mode: record automatically whenever a song plays")];
  const row = el("div", { className: "cv-row" });
  if (chk.on) {
    row.append(el("button", { className: "pill warn", onclick: () => chk.stop() }, "■ Stop and analyse"),
      el("span", { className: "cv-rec-time", textContent: `${Math.floor((Date.now() - chk.start) / 1000)}s` }),
      el("span", { className: "cv-meter" }, el("i")), el("span", { className: "note", textContent: `Recording: ${chk.song}` }));
    parts.push(row, el("div", { className: "cv-live" },
      el("div", { className: "cv-viz-label", textContent: "Should sound like (mp3)" + (chk.live?.ref === null ? " - not available for this song" : "") }),
      el("canvas", { width: 400, height: 88 * 2 + 6 }),
      el("div", { className: "cv-viz-label", textContent: "Piano (live mic) - lower half" })));
  } else if (chk.busy) {
    row.append(el("span", { className: "cv-job working" }, el("span", { textContent: "Analysing the recording note by note..." })));
    parts.push(row);
  } else {
    row.append(el("button", { className: "pill", disabled: rec.on, onclick: () => startCheck(false) }, "🎙 Start check now"),
      el("button", { className: "pill", onclick: showLastCheck }, "Show last check"),
      el("span", { className: "note", textContent: "Uses whichever song the jukebox is playing." }));
    parts.push(row);
  }
  if (chk.error) parts.push(el("div", { className: "cv-off", textContent: chk.error }));
  if (chk.result) {
    const s = chk.result.summary, I = chk.result.issues || [];
    const stat = (label, v, good) => v == null ? null : el("div", { className: "cv-stat" + (good ? " ok" : " bad") },
      el("span", { textContent: label }), el("b", { textContent: v }));
    const sign = v => `${v > 0 ? "+" : ""}${v}`;
    const viz = el("div", { className: "cv-vizbox" });
    if (chk.result.viz) drawResult(viz, chk.result.viz, I);
    parts.push(el("div", { className: "cv-report" },
      !s.alignment_ok ? el("div", { className: "cv-off", textContent: "Couldn't confidently match the recording to the song - was the piano loud enough and playing this song?" }) : null,
      el("div", { className: "cv-stats" },
        stat("Melody over backing", s.melody_over_backing_db == null ? null : `${sign(s.melody_over_backing_db)} dB`, s.melody_over_backing_db >= 6),
        stat("Melody notes on top", s.melody_notes_on_top == null ? null : `${Math.round(s.melody_notes_on_top * 100)}%`, s.melody_notes_on_top >= 0.8),
        stat("Timing steadiness", s.stretch_timing_spread_ms == null ? null : `±${s.stretch_timing_spread_ms} ms`, s.stretch_timing_spread_ms <= 15),
        stat("Soft notes lag", s.soft_notes_lag_ms == null ? null : `${sign(s.soft_notes_lag_ms)} ms`, Math.abs(s.soft_notes_lag_ms) <= 15),
        stat("Notes sounded", s.notes_heard == null ? null : `${Math.round(s.notes_heard * 100)}%`, s.notes_heard >= 0.9),
        stat("Pitch match with song", s.pitch_agreement_with_song == null ? null : `${Math.round(s.pitch_agreement_with_song * 100)}%`, s.pitch_agreement_with_song >= 0.7)),
      viz,
      el("p", { className: "note", textContent: I.length ? `${I.length} precise issues (recorded from ${s.starts_at}; click one to jump there):` : `No problems found (recorded from ${s.starts_at}).` }),
      I.length ? el("ul", { className: "cv-problems" }, ...I.slice(0, 200).map(x => el("li", { onclick: () => D.seek?.(x.t), title: "Jump the jukebox here" },
        el("b", { textContent: x.time }), el("em", { textContent: `[${x.kind}] ` }), x.text))) : null,
      el("p", { className: "note", textContent: `Saved for Claude to read: ${chk.result.saved}` })));
  }
  return el("div", { className: "cv-check" }, ...parts);
}

// --------------------------------------------------------------------- UI
let root = null, draftName = "";
function refresh() { if (root?.isConnected) root.replaceChildren(...cardBody().filter(Boolean)); }
// Progress updates only redraw the job list, so typing in the name box isn't interrupted
function refreshJobs() {
  const list = root?.isConnected && root.querySelector(".cv-jobs");
  if (list) list.replaceChildren(...jobRows()); else refresh();
}
function jobRows() {
  const { el } = D;
  return jobs.map(j => el("div", { className: "cv-job " + j.state },
    el("b", { textContent: j.name }), el("span", { textContent: j.status }),
    j.state === "working" && j.progress != null ? el("div", { className: "cv-progress" },
      el("div", { className: "cv-bar" }, el("i", { style: { width: `${Math.round(j.progress * 100)}%` } })),
      el("small", { textContent: [`${Math.round(j.progress * 100)}%`, fmtEta(j.eta)].filter(Boolean).join(" · ") })) : null,
    j.url ? el("a", { className: "link", href: j.url, download: j.file || `${j.name}.mid`, textContent: "Download .mid" }) : null));
}
function refreshRec() {
  const src = chk.on ? chk : rec;
  const t = root?.querySelector(".cv-rec-time"), m = root?.querySelector(".cv-meter i");
  if (t) t.textContent = `${Math.floor((Date.now() - src.start) / 1000)}s`;
  if (m) m.style.width = `${Math.min(100, src.level * 100)}%`;
}

function cardBody() {
  const { el, icon } = D;
  const file = el("input", { type: "file", accept: "audio/*,.mp3,.m4a,.wav,.flac,.ogg", multiple: true, hidden: true,
    onchange: e => { convertFiles([...e.target.files]); e.target.value = ""; } });
  const nameInput = el("input", { className: "cv-name", placeholder: "Song name (optional)", disabled: rec.on,
    value: draftName, oninput: e => { draftName = e.target.value; } });
  const modeBtn = (m, label) => el("button", { className: "pill" + (opts.mode === m ? " primary" : ""),
    onclick: () => { opts.mode = m; saveOpts(); refresh(); } }, label);
  const partBox = p => el("label", { className: "cv-part" }, el("input", { type: "checkbox", checked: opts.parts.includes(p),
    onchange: e => { opts.parts = e.target.checked ? [...new Set([...opts.parts, p])] : opts.parts.filter(x => x !== p);
      if (!opts.parts.length) { opts.parts = [p]; e.target.checked = true; D.toast("Keep at least one part"); } saveOpts(); } }), PART_LABELS[p]);

  const status = online === false
    ? el("div", { className: "cv-off" }, "The converter isn't running. Double-click ", el("b", { textContent: "Start Converter.bat" }),
        " in the song-to-midi folder, then ", el("button", { className: "link", textContent: "check again", onclick: checkServer }), ".")
    : null;

  return [
    el("div", { className: "cv-head" }, el("h2", { textContent: "Convert a song to MIDI" }),
      el("span", { className: "cv-dot " + (online ? "on" : online === false ? "off" : ""), textContent: online ? "Converter ready" : online === false ? "Converter offline" : "Checking..." })),
    el("p", { className: "note", textContent: "Turn any recording into a MIDI file your piano can play. Drop an audio file (mp3, m4a, wav...) anywhere on this page, or record a song playing on your phone." }),
    status,
    el("div", { className: "cv-row" }, el("span", { className: "cv-label", textContent: "Mode" }),
      modeBtn("auto", "✨ Auto"), modeBtn("piano", "Piano recording"), modeBtn("pop", "Pop / Film song")),
    opts.mode === "pop" ? el("div", { className: "cv-row" }, el("span", { className: "cv-label", textContent: "Turn into piano" }),
      ...["vocals", "other", "bass"].map(partBox)) : null,
    el("p", { className: "note cv-hint", textContent: {
      auto: "Listens to the song first and picks what to turn into piano: keeps the singing as the melody and the instruments as chords, drops the drums, and only keeps the bass when it's needed. Pure piano recordings are used as-is. It'll tell you what it picked.",
      pop: "Removes the drums first, then turns the parts you pick into piano. Untick everything except Melody for a simple tune.",
      piano: "Best when the song is only piano. Everything it hears (singing, drums, guitar) becomes piano keys." }[opts.mode] }),
    el("div", { className: "cv-row" },
      el("button", { className: "pill", onclick: () => file.click() }, icon("upload"), "Choose audio file"), file,
      nameInput,
      rec.on
        ? el("button", { className: "pill warn", onclick: () => rec.stop() }, "■ Stop recording")
        : el("button", { className: "pill", disabled: chk.on, onclick: () => startRecording(nameInput) }, "● Record from mic"),
      rec.on ? el("span", { className: "cv-rec-time", textContent: `${Math.floor((Date.now() - rec.start) / 1000)}s` }) : null,
      rec.on ? el("span", { className: "cv-meter" }, el("i")) : null),
    el("div", { className: "cv-jobs" }, ...jobRows()),
    checkSection(),
  ];
}

export function converterCard() {
  root = D.el("section", { className: "converter" });
  refresh();
  if (online !== true) checkServer();
  return root;
}
