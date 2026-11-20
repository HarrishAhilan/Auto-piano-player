import { parseMidi, getOutputs, Engine } from "./engine.js";
import { initConverter, converterCard, convertFiles, isAudio } from "./converter.js";

// ------------------------------------------------------------------ helpers
const $ = id => document.getElementById(id);
const ICONS = {
  home: "M12 3 2 12h3v8h6v-6h2v6h6v-8h3z",
  search: "M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z",
  library: "M4 6H2v14a2 2 0 0 0 2 2h14v-2H4V6zm16-4H8a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2zm-1 9h-4v4h-2v-4H9V9h4V5h2v4h4v2z",
  play: "M8 5v14l11-7z",
  pause: "M6 19h4V5H6v14zm8-14v14h4V5h-4z",
  next: "M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z",
  prev: "M6 6h2v12H6zm3.5 6 8.5 6V6z",
  shuffle: "M10.59 9.17 5.41 4 4 5.41l5.17 5.17 1.42-1.41zM14.5 4l2.04 2.04L4 18.59 5.41 20 17.96 7.46 20 9.5V4h-5.5zm.33 9.41-1.41 1.41 3.13 3.13L14.5 20H20v-5.5l-2.04 2.04-3.13-3.13z",
  repeat: "M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4z",
  repeat1: "M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4zm-4-2V9h-1l-2 1v1h1.5v4H13z",
  queue: "M15 6H3v2h12V6zm0 4H3v2h12v-2zM3 16h8v-2H3v2zM17 6v8.18A3 3 0 0 0 16 14a3 3 0 1 0 3 3V8h3V6h-5z",
  device: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm-5 9.5a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm3-4a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm4 0a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm3 4a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zM12 13a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3z",
  volume: "M3 9v6h4l5 5V4L7 9H3zm13.5 3A4.5 4.5 0 0 0 14 7.97v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z",
  alert: "M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z",
  gear: "M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 0 0 .12-.61l-1.92-3.32a.49.49 0 0 0-.59-.22l-2.39.96a7.03 7.03 0 0 0-1.62-.94l-.36-2.54a.48.48 0 0 0-.48-.41h-3.84a.48.48 0 0 0-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96a.48.48 0 0 0-.59.22L2.74 8.87a.47.47 0 0 0 .12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58a.49.49 0 0 0-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32a.47.47 0 0 0-.12-.61l-2.01-1.58zM12 15.6A3.6 3.6 0 1 1 12 8.4a3.6 3.6 0 0 1 0 7.2z",
  plus: "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z",
  close: "M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z",
  upload: "M9 16h6v-6h4l-7-7-7 7h4zm-4 2h14v2H5z",
  heart: "M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z",
  heartOutline: "M16.5 3c-1.74 0-3.41.81-4.5 2.09C10.91 3.81 9.24 3 7.5 3 4.42 3 2 5.42 2 8.5c0 3.78 3.4 6.86 8.55 11.54L12 21.35l1.45-1.32C18.6 15.36 22 12.28 22 8.5 22 5.42 19.58 3 16.5 3zm-4.4 15.55-.1.1-.1-.1C7.14 14.24 4 11.39 4 8.5 4 6.5 5.5 5 7.5 5c1.54 0 3.04.99 3.57 2.36h1.87C13.46 5.99 14.96 5 16.5 5c2 0 3.5 1.5 3.5 3.5 0 2.89-3.14 5.74-7.9 10.05z",
};
function icon(name) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true");
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
  p.setAttribute("d", ICONS[name]); s.append(p); return s;
}
function setIcon(elm, name) { elm.replaceChildren(icon(name)); }
function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "style") Object.assign(e.style, v);
    else if (k === "dataset") Object.assign(e.dataset, v);
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) e[k] = v;
  }
  for (const c of kids.flat()) if (c !== null && c !== undefined && c !== false) e.append(c);
  return e;
}
const fmt = s => { s = Math.max(0, Math.round(s || 0)); const m = Math.floor(s / 60), x = String(s % 60).padStart(2, "0");
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${x}` : `${m}:${x}`; };
const fmtLong = s => { const m = Math.round(s / 60); return m >= 60 ? `${Math.floor(m / 60)} hr ${m % 60} min` : `${m} min`; };
const hash = s => { let h = 7; for (const c of s) h = (h * 31 + c.codePointAt(0)) | 0; return Math.abs(h); };
function shuffled(a) { a = a.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; }
function shortName(a) {
  return a.split(" / ").map(n => n.replace(/^(.*)\s(van|von|de)\s/i, "$2 ").split(" ").filter(w => !/^(van|von|de)$/i.test(w)).pop()).join(" & ");
}
let toastTimer;
function toast(msg, ms = 3200) { const t = $("toast"); t.textContent = msg; t.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => t.hidden = true, ms); }
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem("pj-" + k)) ?? d; } catch { return d; } },
  set(k, v) { localStorage.setItem("pj-" + k, JSON.stringify(v)); },
};

// ----------------------------------------------------------- artwork tiles
function art(label, seed, style) {
  const d = el("div", { className: "art", textContent: label });
  const h = hash(seed) % 360;
  d.style.background = style || `linear-gradient(135deg, hsl(${h} 52% 46%), hsl(${(h + 55) % 360} 58% 20%))`;
  return d;
}
const XMAS_BG = "linear-gradient(135deg, #c0392b 0%, #7b1d1d 45%, #14532d 100%)";
const MY_BG = "linear-gradient(135deg, #6d28d9, #1e1b4b)";
const LIKED_BG = "linear-gradient(135deg, #4c1d95, #93c5fd)";
const MIX_BG = "linear-gradient(135deg, #e8b04b, #7c2d12)";
const FAMOUS_BG = "linear-gradient(135deg, #0ea5e9, #1e3a8a)";
const RAG_BG = "linear-gradient(135deg, #f97316, #422006)";
const SHEET_COLLECTIONS = ["christmas", "famous", "ragtime"];   // album = source/license

// -------------------------------------------------------------- my music
const idb = (() => {
  let dbp;
  const open = () => dbp ??= new Promise((res, rej) => {
    const r = indexedDB.open("piano-jukebox", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("files", { keyPath: "id" });
    r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
  });
  const tx = async (mode, fn) => { const db = await open(); return new Promise((res, rej) => {
    const t = db.transaction("files", mode), req = fn(t.objectStore("files"));
    t.oncomplete = () => res(req && req.result); t.onerror = () => rej(t.error); }); };
  return { all: () => tx("readonly", s => s.getAll()), put: v => tx("readwrite", s => s.put(v)),
           del: id => tx("readwrite", s => s.delete(id)), get: id => tx("readonly", s => s.get(id)) };
})();

// ------------------------------------------------------------------- data
const LIB = { tracks: [], byId: new Map(), composers: [], my: [], mix: [] };
let liked = new Set(store.get("liked", []));
let recent = store.get("recent", []);

async function loadMy() {
  let rows = [];
  try { rows = await idb.all(); } catch (e) { console.warn("IndexedDB unavailable", e); }
  LIB.my = rows.sort((a, b) => a.added - b.added).map(r => ({
    id: "my:" + r.id, t: r.name.replace(/\.(mid|midi)$/i, ""), a: "My Music", c: "my", y: "", d: r.d, key: r.id }));
  for (const t of LIB.my) LIB.byId.set(t.id, t);
}
async function addFiles(files) {
  const audio = files.filter(f => !/\.(mid|midi)$/i.test(f.name) && isAudio(f));
  if (audio.length) convertFiles(audio);
  files = files.filter(f => !audio.includes(f));
  if (!files.length) return;
  let ok = 0;
  for (const f of files) {
    if (!/\.(mid|midi)$/i.test(f.name)) { toast(`${f.name} isn't a MIDI file (.mid)`); continue; }
    if (f.size > 8e6) { toast(`${f.name} is too large`); continue; }
    try {
      const buf = await f.arrayBuffer(), parsed = parseMidi(buf);
      if (!parsed.events.length) throw new Error("no piano notes");
      await idb.put({ id: crypto.randomUUID(), name: f.name, d: Math.round(parsed.duration), data: buf, added: Date.now() });
      ok++;
    } catch (e) { toast(`Couldn't read ${f.name}: ${e.message}`); }
  }
  await loadMy();
  if (ok) { toast(`Added ${ok} song${ok > 1 ? "s" : ""} to My Music`); if (location.hash !== "#/c/my") location.hash = "#/c/my"; else render(); }
  renderSidebar();
}

// ----------------------------------------------------------- collections
function collection(id) {
  if (id === "christmas") return { kind: "Playlist", title: "Christmas Carols", bg: XMAS_BG, label: "Christmas Carols",
    desc: "Carols for the holidays, ready for the piano.", tracks: LIB.tracks.filter(t => t.c === "christmas") };
  if (id === "my") return { kind: "Playlist", title: "My Music", bg: MY_BG, label: "My Music",
    desc: "Your own MIDI files. Stored only in this browser.", tracks: LIB.my };
  if (id === "liked") return { kind: "Playlist", title: "Liked Songs", bg: LIKED_BG, label: "♥",
    desc: "Songs you've liked.", tracks: [...liked].map(i => LIB.byId.get(i)).filter(Boolean) };
  if (id === "mix") return { kind: "Mix", title: "Classical Mix", bg: MIX_BG, label: "Classical Mix",
    desc: "A random mix of concert performances. Refreshes every visit.", tracks: LIB.mix };
  if (id === "famous") return { kind: "Playlist", title: "Famous Piano Classics", bg: FAMOUS_BG, label: "Famous Classics",
    desc: "Für Elise, Clair de Lune, the Turkish March, Hall of the Mountain King and more.", tracks: LIB.tracks.filter(t => t.c === "famous") };
  if (id === "ragtime") return { kind: "Playlist", title: "Ragtime & Marches", bg: RAG_BG, label: "Ragtime & Marches",
    desc: "Scott Joplin rags and Sousa marches: the classic player-piano sound.", tracks: LIB.tracks.filter(t => t.c === "ragtime") };
  return null;
}
function composerCollection(name) {
  return { kind: "Composer", title: name, seed: name, label: shortName(name), round: true,
    desc: "", tracks: LIB.tracks.filter(t => t.a === name).sort((a, b) => a.t.localeCompare(b.t) || b.y - a.y) };
}
const albumOf = t => SHEET_COLLECTIONS.includes(t.c) ? t.y : t.c === "my" ? "My Music" : `Recorded ${t.y}`;
const trackArt = t => t.c === "christmas" ? art("♪", t.id, XMAS_BG) : t.c === "my" ? art("♪", t.id, MY_BG)
  : t.c === "ragtime" ? art(shortName(t.a), t.a, RAG_BG) : t.c === "famous" ? art(shortName(t.a), t.a, FAMOUS_BG)
  : art(shortName(t.a), t.a);

// ------------------------------------------------------------------ player
const engine = new Engine();
const P = { list: [], idx: -1, upNext: [], shuffle: store.get("shuffle", false), repeat: store.get("repeat", 0),
            cur: null, played: new Set(), token: 0, listName: "" };
const settings = Object.assign({ volume: 0.8, floor: 35, channel: 1, out: "" }, store.get("settings", {}));
Object.assign(engine.settings, { volume: settings.volume, floor: settings.floor, channel: settings.channel });
const saveSettings = () => { store.set("settings", settings); Object.assign(engine.settings, { volume: settings.volume, floor: settings.floor, channel: settings.channel }); };

async function loadBuffer(t) {
  if (t.c === "my") { const r = await idb.get(t.key); if (!r) throw new Error("file missing"); return r.data; }
  const res = await fetch(t.u); if (!res.ok) throw new Error(`download failed (${res.status})`);
  return res.arrayBuffer();
}
async function start(t) {
  const token = ++P.token;
  P.cur = t; P.played.add(t.id); updateNowPlaying(); markCurrent();
  $("npArtist").textContent = "Loading…";
  try {
    const parsed = parseMidi(await loadBuffer(t));
    if (token !== P.token) return;
    ensureOutput();
    engine.load(parsed); engine.play();
    recent = [t.id, ...recent.filter(i => i !== t.id)].slice(0, 12); store.set("recent", recent);
  } catch (e) {
    if (token !== P.token) return;
    toast(`Couldn't play “${t.t}”: ${e.message}`);
  }
  updateNowPlaying();
}
function playList(list, idx = 0, name = "") {
  if (!list.length) return;
  if (P.shuffle && idx < 0) idx = Math.floor(Math.random() * list.length);
  P.list = list.slice(); P.idx = Math.max(0, idx); P.played = new Set(); P.listName = name;
  start(P.list[P.idx]);
}
function next(auto = false) {
  if (P.upNext.length) return start(P.upNext.shift());
  if (!P.list.length) return;
  if (auto && P.repeat === 2) return start(P.list[P.idx]);
  if (P.shuffle) {
    let pool = P.list.map((_, i) => i).filter(i => !P.played.has(P.list[i].id));
    if (!pool.length) { if (P.repeat !== 1 && auto) return stopped(); P.played.clear(); pool = P.list.map((_, i) => i).filter(i => i !== P.idx); }
    if (!pool.length) pool = [P.idx];
    P.idx = pool[Math.floor(Math.random() * pool.length)];
  } else if (P.idx + 1 < P.list.length) P.idx++;
  else if (P.repeat === 1 || !auto) P.idx = 0;
  else return stopped();
  start(P.list[P.idx]);
}
function prev() {
  if (engine.position() > 3 || !P.list.length) return engine.seek(0);
  P.idx = (P.idx - 1 + P.list.length) % P.list.length;
  start(P.list[P.idx]);
}
function stopped() { engine.stop(); updateNowPlaying(); }
function togglePlay() {
  if (!P.cur) return playList(collection("christmas").tracks, P.shuffle ? -1 : 0, "Christmas Carols");
  if (engine.playing) engine.pause(); else { ensureOutput(); engine.play(); }
  updateNowPlaying();
}
engine.onend = () => next(true);
function enqueue(t) { P.upNext.push(t); toast(`Added “${t.t}” to queue`); if (location.hash === "#/queue") render(); }
function toggleLike(t, btn) {
  liked.has(t.id) ? liked.delete(t.id) : liked.add(t.id);
  store.set("liked", [...liked]);
  if (btn) { setIcon(btn, liked.has(t.id) ? "heart" : "heartOutline"); btn.classList.toggle("on", liked.has(t.id)); }
  toast(liked.has(t.id) ? "Added to Liked Songs" : "Removed from Liked Songs", 1600);
  renderSidebar();
}

function updateNowPlaying() {
  const t = P.cur;
  $("npTitle").textContent = t ? t.t : "Pick something to play";
  $("npArtist").textContent = t ? (t.c === "my" ? "My Music" : t.a) : "";
  $("npArt").replaceChildren(t ? trackArt(t) : "");
  setIcon($("playBtn"), engine.playing ? "pause" : "play");
  $("playBtn").title = engine.playing ? "Pause" : "Play";
  document.title = t && engine.playing ? `${t.t} · ${shortName(t.a)}` : "Piano Jukebox";
  if ("mediaSession" in navigator && t) {
    navigator.mediaSession.metadata = new MediaMetadata({ title: t.t, artist: t.a, album: albumOf(t) });
    navigator.mediaSession.playbackState = engine.playing ? "playing" : "paused";
  }
}
function markCurrent() {
  document.querySelectorAll("tr.row").forEach(r => r.classList.toggle("current", P.cur && r.dataset.id === P.cur.id));
}
let seeking = false;
function setPct(input) { const min = +input.min, max = +input.max; input.style.setProperty("--pct", `${((input.value - min) / (max - min)) * 100}%`); }
setInterval(() => {
  const dur = engine.dur || (P.cur && P.cur.d) || 0, pos = engine.position();
  $("timeDur").textContent = fmt(dur);
  if (!seeking) { $("timeCur").textContent = fmt(pos); $("seek").value = dur ? Math.round(pos / dur * 1000) : 0; setPct($("seek")); }
  const playingIcon = engine.playing ? "pause" : "play";
  if ($("playBtn").dataset.state !== playingIcon) { $("playBtn").dataset.state = playingIcon; updateNowPlaying(); }
}, 250);

// ------------------------------------------------------------------ outputs
let outputs = [], midi = null;
function currentOutputs() { return outputs.filter(o => !o.skip); }
function ensureOutput() {
  if (!midi) return;                     // still asking for MIDI access
  const outs = currentOutputs();
  let o = outs.find(x => x.id === settings.out);
  if (!o || (o.id === "preview" && !settings.chosePreview)) o = midi.pickPiano(outs) || o || midi.preview;
  if (engine.out !== o) {
    engine.setOutput(o);
    if (o.id === "preview" && !settings.chosePreview) toast("Piano not connected, so this is playing on this device. Use the device button to pick the piano.", 5000);
  }
  updateConnect();
}
function chooseOutput(o) {
  settings.out = o.id; settings.chosePreview = o.id === "preview"; saveSettings();
  engine.setOutput(o); updateConnect(); closeMenu();
  toast(o.id === "preview" ? "Playing on this device" : `Playing on ${o.name}`, 2000);
}
function updateConnect() {
  const piano = midi && midi.pickPiano(currentOutputs());
  const using = engine.out;
  const pill = $("connectBtn");
  pill.classList.toggle("ok", !!(using && using.id !== "preview"));
  pill.classList.toggle("warn", !piano && !(using && using.id !== "preview"));
  $("connectLabel").textContent = using && using.id !== "preview" ? using.name
    : piano ? `Piano found: ${piano.name}` : using ? "Preview sound"
    : midi && midi.error === "pending" ? "Allow MIDI access" : "Piano not connected";
  $("outBtn").classList.toggle("on", !!(using && using.id !== "preview"));
}
function openMenu(anchor) {
  const m = $("outMenu");
  const outs = currentOutputs();
  const kids = [el("h4", { textContent: "Play on" }),
    ...outs.map(o => el("button", { className: engine.out === o ? "sel" : "", onclick: () => chooseOutput(o) },
      icon(o.id === "preview" ? "volume" : "device"), o.name))];
  let hint = "";
  if (midi.error === "unsupported") hint = "This browser can't talk to MIDI devices. To play the piano, open this site in Chrome or Edge on the computer paired with it.";
  else if (midi.error === "pending") hint = "Your browser is asking for permission to use MIDI devices. Click Allow (top-left of the window) so the site can reach the piano.";
  else if (midi.error === "denied") hint = "MIDI access is blocked. Click the icon at the left of the address bar, allow MIDI, then reload.";
  else if (!midi.pickPiano(outs)) hint = "No piano found. Turn off Bluetooth on your phone, pair the WIDI Jack in Windows Settings › Bluetooth & devices, and it will appear here.";
  if (hint) kids.push(el("div", { className: "hint", textContent: hint }));
  m.replaceChildren(...kids);
  m.hidden = false;
  const r = anchor.getBoundingClientRect(), w = m.offsetWidth, h = m.offsetHeight;
  m.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.right - w)) + "px";
  m.style.top = (r.top > innerHeight / 2 ? r.top - h - 8 : r.bottom + 8) + "px";
}
function closeMenu() { $("outMenu").hidden = true; }
document.addEventListener("click", e => { if (!$("outMenu").hidden && !$("outMenu").contains(e.target) && !e.target.closest("#outBtn,#connectBtn")) closeMenu(); });

// ----------------------------------------------------------------- views
const ROW_CHUNK = 150;
function trackTable(list, { name = "", removable = false } = {}) {
  const body = el("tbody");
  const table = el("table", { className: "tracks" },
    el("thead", {}, el("tr", {}, el("th", { className: "num", textContent: "#" }), el("th", { textContent: "Title" }),
      el("th", { className: "alb", textContent: "Album" }), el("th", { className: "act" }), el("th", { className: "dur", textContent: "Length" }))),
    body);
  let shown = 0;
  const more = el("button", { className: "pill more", onclick: () => addRows() });
  function addRows() {
    const end = Math.min(list.length, shown + ROW_CHUNK);
    for (let i = shown; i < end; i++) body.append(row(list[i], i));
    shown = end;
    more.hidden = shown >= list.length;
    more.textContent = `Show ${Math.min(ROW_CHUNK, list.length - shown)} more`;
    markCurrent();
  }
  function row(t, i) {
    const likeBtn = el("button", { className: "icon-btn" + (liked.has(t.id) ? " on" : ""), title: "Like",
      onclick: e => { e.stopPropagation(); toggleLike(t, likeBtn); } }, icon(liked.has(t.id) ? "heart" : "heartOutline"));
    const second = removable
      ? el("button", { className: "icon-btn", title: "Remove from My Music", onclick: async e => {
          e.stopPropagation(); await idb.del(t.key); await loadMy(); render(); renderSidebar(); toast(`Removed “${t.t}”`); } }, icon("close"))
      : el("button", { className: "icon-btn", title: "Add to queue", onclick: e => { e.stopPropagation(); enqueue(t); } }, icon("plus"));
    const artist = t.c === "classical"
      ? el("a", { href: "#/composer/" + encodeURIComponent(t.a), textContent: t.a, onclick: e => e.stopPropagation() })
      : t.a;
    return el("tr", { className: "row", dataset: { id: t.id }, onclick: () => playList(list, i, name) },
      el("td", { className: "num" }, el("span", { className: "n", textContent: i + 1 }), el("span", { className: "play-ico" }, icon("play"))),
      el("td", { className: "ttl" }, el("b", { textContent: t.t }), el("small", {}, artist)),
      el("td", { className: "alb", textContent: albumOf(t) }),
      el("td", { className: "act" }, likeBtn, second),
      el("td", { className: "dur", textContent: fmt(t.d) }));
  }
  addRows();
  return el("div", {}, table, more);
}
function playButton(onclick, title = "Play") { return el("button", { className: "big-play", title, onclick }, icon("play")); }
function hero(c) {
  const a = art(c.label, c.seed || c.title, c.bg);
  if (c.round) a.style.borderRadius = "50%";
  const total = c.tracks.reduce((s, t) => s + (t.d || 0), 0);
  const h = el("div", { className: "hero" }, a, el("div", {},
    el("div", { className: "kind", textContent: c.kind }), el("h1", { textContent: c.title }),
    c.desc ? el("p", { textContent: c.desc }) : null,
    el("p", { textContent: `${c.tracks.length} ${c.kind === "Composer" ? "performances" : "songs"}${total ? " · " + fmtLong(total) : ""}` })));
  const hue = hash(c.seed || c.title) % 360;
  h.style.setProperty("--hero", c.bg ? "#5a2a2a" : `hsl(${hue} 40% 32%)`);
  if (c.bg === XMAS_BG) h.style.setProperty("--hero", "#6b1f1f");
  if (c.bg === MY_BG) h.style.setProperty("--hero", "#3b1e7a");
  if (c.bg === LIKED_BG) h.style.setProperty("--hero", "#3d2a8a");
  if (c.bg === MIX_BG) h.style.setProperty("--hero", "#7a4a12");
  if (c.bg === FAMOUS_BG) h.style.setProperty("--hero", "#1d4f7a");
  if (c.bg === RAG_BG) h.style.setProperty("--hero", "#7a3a12");
  return h;
}
function collectionView(c) {
  const shuffleBtn = el("button", { className: "icon-btn" + (P.shuffle ? " on" : ""), title: "Shuffle",
    onclick: () => { setShuffle(!P.shuffle); shuffleBtn.classList.toggle("on", P.shuffle); } }, icon("shuffle"));
  const parts = [hero(c), el("div", { className: "actions" },
    c.tracks.length ? playButton(() => playList(c.tracks, P.shuffle ? -1 : 0, c.title)) : null, shuffleBtn,
    c.title === "My Music" ? el("button", { className: "pill", onclick: () => $("fileInput").click() }, icon("upload"), "Add MIDI files") : null)];
  if (c.title === "My Music") {
    const drop = el("div", { className: "drop", textContent: "Drop .mid files here (or anywhere on the page) to add them to My Music. Drop audio files (mp3, m4a, wav...) to convert them to MIDI." });
    parts.push(converterCard(), drop,
      el("p", { className: "note", textContent: "Use this for songs that aren't in the built-in library, like Tamil songs or your favourite film and pop tunes. Any MIDI file works. Files are saved only in this browser on this device and are never uploaded." }));
  }
  parts.push(c.tracks.length ? trackTable(c.tracks, { name: c.title, removable: c.title === "My Music" })
    : el("div", { className: "empty", textContent: c.title === "Liked Songs" ? "Tap the heart on any song to save it here." : "Nothing here yet." }));
  return parts;
}
function tile(label, sub, artNode, href, onplay, round = false) {
  const t = el("a", { className: "tile" + (round ? " round" : ""), href }, artNode, el("b", { textContent: label }), el("small", { textContent: sub }));
  if (onplay) t.append(el("button", { className: "big-play hover-play", title: "Play",
    onclick: e => { e.preventDefault(); e.stopPropagation(); onplay(); } }, icon("play")));
  return t;
}
function composerTile(c) {
  return tile(c.name, `${c.count} performances`, art(shortName(c.name), c.name), "#/composer/" + encodeURIComponent(c.name),
    () => { const cc = composerCollection(c.name); playList(cc.tracks, P.shuffle ? -1 : 0, cc.title); }, true);
}
function homeView() {
  const hr = new Date().getHours();
  const greet = hr < 5 ? "Good night" : hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
  const quick = ["famous", "ragtime", "christmas", "liked", "my", "mix"]
    .map(id => { const c = collection(id); return el("a", { href: "#/c/" + id }, art(c.label, c.title, c.bg), c.title); });
  for (const name of ["Frédéric Chopin", "Ludwig van Beethoven"])
    quick.push(el("a", { href: "#/composer/" + encodeURIComponent(name) }, art(shortName(name), name), name));
  const xmas = collection("christmas").tracks;
  const row = id => { const c = collection(id); return [
    el("h2", { className: "section" }, el("a", { href: "#/c/" + id, textContent: c.title })),
    el("div", { className: "cards row" }, c.tracks.slice(0, 16).map((t, i) => tile(t.t, t.a, trackArt(t), "#/c/" + id, () => playList(c.tracks, i, c.title))))]; };
  const parts = [el("h1", { className: "greeting", textContent: greet }), el("div", { className: "quick" }, quick),
    ...row("famous"), ...row("ragtime"),
    el("h2", { className: "section" }, el("a", { href: "#/c/christmas", textContent: "Christmas Carols" })),
    el("div", { className: "cards row" }, xmas.map((t, i) => tile(t.t, t.a, trackArt(t), "#/c/christmas", () => playList(xmas, i, "Christmas Carols"))))];
  const rec = recent.map(i => LIB.byId.get(i)).filter(Boolean);
  if (rec.length) parts.push(el("h2", { className: "section", textContent: "Recently played" }),
    el("div", { className: "cards row" }, rec.map((t, i) => tile(t.t, t.a, trackArt(t), t.c === "classical" ? "#/composer/" + encodeURIComponent(t.a) : "#/c/" + t.c, () => playList(rec, i, "Recently played")))));
  parts.push(el("h2", { className: "section" }, el("a", { href: "#/search", textContent: "Composers" })),
    el("div", { className: "cards row" }, LIB.composers.slice(0, 14).map(composerTile)),
    el("h2", { className: "section", textContent: "Your songs" }),
    el("div", { className: "cards row" },
      tile("My Music", "Add Tamil songs or any MIDI file you have", art("+", "my", MY_BG), "#/c/my", null),
      tile("Liked Songs", `${liked.size} songs`, art("♥", "liked", LIKED_BG), "#/c/liked", null),
      tile("Classical Mix", "50 random performances", art("Classical Mix", "mix", MIX_BG), "#/c/mix", () => playList(LIB.mix, 0, "Classical Mix"))));
  return parts;
}
let query = "";
function searchView() {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [el("h2", { className: "section", textContent: "Browse all" }),
    el("div", { className: "cards" },
      tile("Famous Piano Classics", `${collection("famous").tracks.length} songs`, art("Famous Classics", "f", FAMOUS_BG), "#/c/famous", null),
      tile("Ragtime & Marches", `${collection("ragtime").tracks.length} songs`, art("Ragtime & Marches", "r", RAG_BG), "#/c/ragtime", null),
      tile("Christmas Carols", `${collection("christmas").tracks.length} songs`, art("Christmas Carols", "x", XMAS_BG), "#/c/christmas", null),
      tile("My Music", "Your own MIDI files", art("My Music", "my", MY_BG), "#/c/my", null),
      ...LIB.composers.map(composerTile))];
  const all = [...LIB.my, ...LIB.tracks];
  const songs = all.filter(t => { const s = (t.t + " " + t.a + " " + (t.c === "christmas" ? "christmas carol xmas" : "")).toLowerCase();
    return words.every(w => s.includes(w)); });
  const comps = LIB.composers.filter(c => words.every(w => c.name.toLowerCase().includes(w)));
  const parts = [];
  if (comps.length) parts.push(el("h2", { className: "section", textContent: "Composers" }), el("div", { className: "cards row" }, comps.slice(0, 12).map(composerTile)));
  parts.push(el("h2", { className: "section", textContent: songs.length ? `Songs (${songs.length})` : "No songs found" }));
  if (songs.length) parts.push(trackTable(songs, { name: `Search “${query}”` }));
  else parts.push(el("p", { className: "note", textContent: "Not in the library? Add your own MIDI files under My Music." }));
  return parts;
}
function queueView() {
  const parts = [el("h1", { className: "greeting", textContent: "Queue" })];
  if (P.cur) parts.push(el("h2", { className: "section", textContent: "Now playing" }), trackTable([P.cur], { name: P.listName }));
  if (P.upNext.length) parts.push(el("h2", { className: "section", textContent: "Next in queue" }), trackTable(P.upNext, { name: "Queue" }));
  const rest = P.shuffle ? [] : P.list.slice(P.idx + 1, P.idx + 51);
  if (rest.length) parts.push(el("h2", { className: "section", textContent: `Next from: ${P.listName || "list"}` }), trackTable(rest, { name: P.listName }));
  else if (P.shuffle && P.list.length) parts.push(el("p", { className: "note", textContent: `Shuffling ${P.listName || "the list"}.` }));
  if (!P.cur) parts.push(el("div", { className: "empty", textContent: "Nothing playing yet. Pick a song or playlist." }));
  return parts;
}
function libraryView() {
  return [el("h1", { className: "greeting", textContent: "Your Library" }), el("div", { className: "lib-list" }, libItems())];
}
function libItems() {
  const items = ["liked", "famous", "ragtime", "christmas", "my", "mix"].map(id => {
    const c = collection(id);
    return el("a", { className: "lib-item", href: "#/c/" + id }, art(c.label, c.title, c.bg),
      el("div", {}, el("b", { textContent: c.title }), el("small", { textContent: `Playlist · ${c.tracks.length} songs` })));
  });
  items.push(el("div", { className: "lib-sep", textContent: "Composers" }));
  for (const c of LIB.composers) {
    const a = art(shortName(c.name), c.name); a.style.borderRadius = "50%";
    items.push(el("a", { className: "lib-item", href: "#/composer/" + encodeURIComponent(c.name) }, a,
      el("div", {}, el("b", { textContent: c.name }), el("small", { textContent: `Composer · ${c.count}` }))));
  }
  return items;
}
function renderSidebar() {
  $("libList").replaceChildren(...libItems());
  document.querySelectorAll(".lib-item").forEach(a => a.classList.toggle("active", a.getAttribute("href") === location.hash));
}
function render() {
  const h = decodeURIComponent(location.hash.replace(/^#/, "")) || "/";
  let parts;
  $("searchWrap").hidden = h !== "/search";
  if (h === "/search") parts = searchView();
  else if (h === "/queue") parts = queueView();
  else if (h === "/library") parts = libraryView();
  else if (h.startsWith("/c/") && collection(h.slice(3))) parts = collectionView(collection(h.slice(3)));
  else if (h.startsWith("/composer/")) parts = collectionView(composerCollection(h.slice(10)));
  else parts = homeView();
  $("view").replaceChildren(...parts);
  document.querySelectorAll("[data-nav]").forEach(a => a.classList.toggle("active",
    (a.dataset.nav === "home" && h === "/") || (a.dataset.nav === "search" && h === "/search") || (a.dataset.nav === "library" && h === "/library")));
  document.querySelectorAll(".lib-item").forEach(a => a.classList.toggle("active", a.getAttribute("href") === location.hash));
  markCurrent();
}

// -------------------------------------------------------------- controls
function setShuffle(on) { P.shuffle = on; store.set("shuffle", on); $("shuffleBtn").classList.toggle("on", on); }
function setRepeat(r) { P.repeat = r; store.set("repeat", r); setIcon($("repeatBtn"), r === 2 ? "repeat1" : "repeat");
  $("repeatBtn").classList.toggle("on", r > 0); $("repeatBtn").title = ["Repeat: off", "Repeat: all", "Repeat: one"][r]; }

function wire() {
  document.querySelectorAll("i[data-icon]").forEach(i => setIcon(i, i.dataset.icon));
  $("playBtn").onclick = togglePlay;
  $("nextBtn").onclick = () => next(false);
  $("prevBtn").onclick = prev;
  $("shuffleBtn").onclick = () => setShuffle(!P.shuffle);
  $("repeatBtn").onclick = () => setRepeat((P.repeat + 1) % 3);
  $("panicBtn").onclick = () => { engine.panic(); updateNowPlaying(); toast("Released every key and pedal"); };
  $("outBtn").onclick = e => { e.stopPropagation(); $("outMenu").hidden ? openMenu($("outBtn")) : closeMenu(); };
  $("connectBtn").onclick = e => { e.stopPropagation(); $("outMenu").hidden ? openMenu($("connectBtn")) : closeMenu(); };
  const seek = $("seek");
  seek.oninput = () => { seeking = true; setPct(seek); $("timeCur").textContent = fmt(seek.value / 1000 * (engine.dur || 0)); };
  seek.onchange = () => { engine.seek(seek.value / 1000 * engine.dur); seeking = false; };
  const vol = $("volume");
  vol.value = settings.volume; setPct(vol);
  vol.oninput = () => { settings.volume = +vol.value; saveSettings(); setPct(vol); vol.title = `Volume ×${settings.volume.toFixed(2)}`; };

  const dlg = $("settings");
  const chSel = $("setChannel");
  for (let c = 1; c <= 16; c++) chSel.append(el("option", { value: c, textContent: c === 1 ? "1 (default)" : c }));
  $("settingsBtn").onclick = () => { chSel.value = settings.channel; $("setFloor").value = settings.floor; $("setVolume").value = settings.volume; dlg.showModal(); };
  dlg.addEventListener("close", () => {
    const ch = +chSel.value, fl = +$("setFloor").value, vo = +$("setVolume").value;
    if (ch !== settings.channel) engine.panic();
    settings.channel = ch;
    if (fl >= 1 && fl <= 127) settings.floor = Math.round(fl);
    if (vo >= 0.3 && vo <= 1.5) { settings.volume = vo; vol.value = vo; setPct(vol); }
    saveSettings(); updateNowPlaying();
  });

  const si = $("searchInput");
  let st;
  si.oninput = () => { clearTimeout(st); st = setTimeout(() => { query = si.value.trim(); render(); }, 150); };
  addEventListener("hashchange", () => { render(); $("mainScroll").scrollTop = 0; if (location.hash === "#/search") si.focus(); });

  initConverter({ el, icon, toast, addFiles,
    // for the piano check: what's playing, its MIDI, where we are in it, and the key-strength settings
    currentTrack: () => P.cur && engine.playing ? { name: P.cur.t, load: () => loadBuffer(P.cur), position: () => engine.position() } : null,
    settings: () => ({ volume: settings.volume, floor: settings.floor }),
    seek: t => { if (P.cur) engine.seek(Math.max(0, t - 1)); } });   // jump to just before an issue
  $("fileInput").onchange = e => { addFiles([...e.target.files]); e.target.value = ""; };
  addEventListener("dragover", e => { if ([...e.dataTransfer.types].includes("Files")) { e.preventDefault(); document.querySelector(".drop")?.classList.add("over"); } });
  addEventListener("dragleave", () => document.querySelector(".drop")?.classList.remove("over"));
  addEventListener("drop", e => { if (e.dataTransfer.files.length) { e.preventDefault(); document.querySelector(".drop")?.classList.remove("over"); addFiles([...e.dataTransfer.files]); } });

  addEventListener("keydown", e => {
    if (e.target.matches("input, select, textarea") || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.code === "Space") { e.preventDefault(); togglePlay(); }
    else if (e.key === "ArrowRight" && e.shiftKey) next(false);
    else if (e.key === "ArrowLeft" && e.shiftKey) prev();
  });
  if ("mediaSession" in navigator) {
    navigator.mediaSession.setActionHandler("play", togglePlay);
    navigator.mediaSession.setActionHandler("pause", togglePlay);
    navigator.mediaSession.setActionHandler("nexttrack", () => next(false));
    navigator.mediaSession.setActionHandler("previoustrack", prev);
  }
  addEventListener("beforeunload", () => engine.panic());
  // Browsers only allow sound after a click/tap: unlock the preview synth then.
  const unlock = () => { if (midi && (engine.out === midi.preview || !midi.pickPiano(currentOutputs()))) midi.preview._ctx(); };
  addEventListener("pointerdown", unlock, true);
  addEventListener("keydown", unlock, true);
  setShuffle(P.shuffle); setRepeat(P.repeat);
}

async function init() {
  wire();
  const [cat] = await Promise.all([fetch("catalog.json").then(r => r.json()), loadMy()]);
  LIB.tracks = cat.tracks;
  for (const t of LIB.tracks) LIB.byId.set(t.id, t);
  const counts = new Map();
  for (const t of LIB.tracks) if (t.c === "classical") counts.set(t.a, (counts.get(t.a) || 0) + 1);
  LIB.composers = [...counts].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  LIB.mix = shuffled(LIB.tracks.filter(t => t.c === "classical" && t.d < 900)).slice(0, 50);
  render(); renderSidebar(); updateNowPlaying();

  midi = getOutputs(list => { outputs = list; if (engine.out) ensureOutput(); else updateConnect(); });
  outputs = midi.list();
  if (P.cur) ensureOutput(); else updateConnect();
}
init();
