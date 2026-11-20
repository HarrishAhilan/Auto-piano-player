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
// Record the real piano while a song plays, then have the converter find where it goes wrong.
const chk = { on: false, start: 0, level: 0, timer: null, stop: null, busy: false, result: null, error: null };

async function startCheck() {
  const cur = D.currentTrack?.();
  if (!cur) { D.toast("Play a song on the piano first, then start the check"); return; }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: {
      echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
  } catch { D.toast("Couldn't use the microphone - check the browser's permission"); return; }
  const mr = new MediaRecorder(stream), chunks = [];
  mr.ondataavailable = e => e.data.size && chunks.push(e.data);
  const actx = new AudioContext(), an = actx.createAnalyser(), buf = new Float32Array(2048);
  an.fftSize = 2048; actx.createMediaStreamSource(stream).connect(an);
  const pos = cur.position();                     // where in the song the recording starts (refined by the analysis)
  Object.assign(chk, { on: true, start: Date.now(), level: 0, result: null, error: null });
  chk.timer = setInterval(() => { an.getFloatTimeDomainData(buf); chk.level = Math.max(...buf.map(Math.abs)); refreshRec(); }, 100);
  chk.stop = () => new Promise(res => { mr.onstop = res; mr.stop(); }).then(async () => {
    clearInterval(chk.timer); stream.getTracks().forEach(t => t.stop()); actx.close();
    chk.on = false;
    if ((Date.now() - chk.start) / 1000 < 8) { chk.error = "Record at least 8 seconds of the piano."; refresh(); return; }
    chk.busy = true; refresh();
    try {
      const [wav, midi] = await Promise.all([toWav(new Blob(chunks, { type: mr.mimeType })), cur.load()]);
      const s = D.settings?.() || {};
      const q = new URLSearchParams({ midi_len: midi.byteLength, pos: pos.toFixed(2), name: cur.name,
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

function checkSection() {
  const { el } = D;
  const parts = [el("h3", { className: "cv-sub", textContent: "Check how your piano sounds" }),
    el("p", { className: "note", textContent: "Play a song on the piano from the jukebox, put the laptop near the piano, and press Start check. Stop after 30-60 seconds (or longer). It lines the recording up with the song and lists, with timestamps, where the melody gets buried, notes come in late, or it stops sounding like the original." })];
  const row = el("div", { className: "cv-row" });
  if (chk.on) {
    row.append(el("button", { className: "pill warn", onclick: () => chk.stop() }, "■ Stop and analyse"),
      el("span", { className: "cv-rec-time", textContent: `${Math.floor((Date.now() - chk.start) / 1000)}s` }),
      el("span", { className: "cv-meter" }, el("i")));
  } else if (chk.busy) {
    row.append(el("span", { className: "cv-job working" }, el("span", { textContent: "Analysing the recording..." })));
  } else {
    // (checked at click time, so it works even if a song was started after this panel was drawn)
    row.append(el("button", { className: "pill", disabled: rec.on, onclick: startCheck }, "🎙 Start check"),
      el("span", { className: "note", textContent: "Checks whichever song the jukebox is playing on the piano." }));
  }
  parts.push(row);
  if (chk.error) parts.push(el("div", { className: "cv-off", textContent: chk.error }));
  if (chk.result) {
    const s = chk.result.summary, P = chk.result.problems;
    const stat = (label, v, good) => v == null ? null : el("div", { className: "cv-stat" + (good ? " ok" : " bad") },
      el("span", { textContent: label }), el("b", { textContent: v }));
    parts.push(el("div", { className: "cv-report" },
      !s.alignment_ok ? el("div", { className: "cv-off", textContent: "Couldn't confidently match the recording to the song - was the piano loud enough and playing this song?" }) : null,
      el("div", { className: "cv-stats" },
        stat("Melody over backing", s.melody_over_backing_db == null ? null : `${s.melody_over_backing_db > 0 ? "+" : ""}${s.melody_over_backing_db} dB`, s.melody_over_backing_db >= 6),
        stat("Timing", s.timing_ms == null ? null : `${s.timing_ms > 0 ? "+" : ""}${s.timing_ms} ms`, Math.abs(s.timing_ms) <= 30),
        stat("Notes on time", s.heard_on_time == null ? null : `${Math.round(s.heard_on_time * 100)}%`, s.heard_on_time >= 0.7),
        stat("Like the original", s.sounds_like_song == null ? null : `${Math.round(s.sounds_like_song * 100)}%`, s.sounds_like_song >= 0.7)),
      el("p", { className: "note", textContent: P.length ? `${P.length} of ${s.checked_sections} sections need work (recorded from ${s.starts_at}):` : `No problems found in ${s.checked_sections} sections (recorded from ${s.starts_at}).` }),
      P.length ? el("ul", { className: "cv-problems" }, ...P.map(p => el("li", {}, el("b", { textContent: p.time }), " " + p.issues.join("; ")))) : null,
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
