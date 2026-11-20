"""Local Song -> MIDI server for Piano Jukebox.

  python server.py            then open http://localhost:8770

Serves the Piano Jukebox app at / and a small conversion API:
  POST /api/convert?mode=piano|pop&parts=vocals,other,bass&name=Song   body = audio file
       -> {"id": "..."}
  GET  /api/job/<id>       -> {"state": "queued|working|done|error", "status": "...", ...}
  GET  /api/job/<id>/midi  -> the .mid file
  GET  /api/health         -> {"ok": true}
Jobs run one at a time. Every finished MIDI is also saved in the output folder.
"""
import json
import os
import queue
import re
import tempfile
import threading
import time
import traceback
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import song2midi

PORT = int(os.environ.get("PORT", 8770))
HERE = Path(__file__).resolve().parent
APP_DIR = HERE.parent / "piano-jukebox"
MAX_UPLOAD = 300 * 1024 * 1024
EXTS = {".mp3", ".wav", ".flac", ".ogg", ".oga", ".aiff", ".aif"}
ALLOWED_ORIGIN = re.compile(r"^(https?://(localhost|127\.0\.0\.1)(:\d+)?|https://piano-jukebox[a-z0-9-]*\.vercel\.app)$")

jobs = {}
work = queue.Queue()


def worker():
    while True:
        job_id, path = work.get()
        job = jobs[job_id]
        job["state"] = "working"

        def status(msg):
            job["status"] = msg.strip()
            print(f"[{job['name']}] {msg.strip()}", flush=True)

        # Share of the total time each step takes (measured on this laptop: splitting a
        # song takes ~0.55x as long as transcribing it).
        weights = {"split": 0.36, "transcribe": 0.64} if job["mode"] != "piano" else {"transcribe": 1.0}
        started = time.time()

        def on_progress(stage, frac):
            before = sum(w for s, w in weights.items() if s == "split" and stage == "transcribe")
            p = min(0.99, before + weights[stage] * frac)
            job["progress"] = round(p, 4)
            elapsed = time.time() - started
            job["eta"] = round(elapsed * (1 - p) / p) if p > 0.02 else None

        try:
            job["progress"] = 0
            if job.get("youtube"):                      # YouTube link: fetch the audio first
                import youtube
                path, title, _ = youtube.download(job["youtube"], status=status,
                                                  progress=lambda f: job.__setitem__("progress", round(0.03 * f, 4)))
                job["name"] = title
            status("Loading audio...")
            audio, rate = song2midi.load_file(str(path))
            job["seconds"] = round(audio.shape[1] / rate)
            midi_path = song2midi.output_path(job["name"], job["mode"])
            job["summary"] = song2midi.convert(audio, rate, job["mode"], job["parts"], midi_path,
                                               status=status, progress=False, on_progress=on_progress)
            job["progress"], job["eta"] = 1, 0
            job["midi"] = midi_path.read_bytes()
            job["file"] = midi_path.name
            job["state"] = "done"
        except ValueError as e:                         # friendly problems (bad link, too long, ...)
            job["state"], job["status"] = "error", str(e)
        except Exception as e:
            traceback.print_exc()
            job["state"], job["status"] = "error", f"Conversion failed: {e}"
        finally:
            try:
                if path:
                    os.unlink(path)
                    if job.get("youtube"): os.rmdir(os.path.dirname(path))
            except OSError:
                pass
            for j in jobs.values():  # keep queue positions fresh
                if j["state"] == "queued":
                    j["status"] = f"Waiting ({sum(1 for k in jobs.values() if k['state'] == 'queued' and k['added'] < j['added'])} ahead)..."


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(APP_DIR), **kw)

    def log_message(self, fmt, *args):
        if "/api/job/" not in self.path and "/bridge/status" not in self.path:  # don't spam the polling
            super().log_message(fmt, *args)

    def end_headers(self):
        # Only the jukebox itself (here, or the online Vercel copy) may use the converter,
        # so other websites you visit can't send it work or read your results.
        origin = self.headers.get("Origin", "")
        if ALLOWED_ORIGIN.match(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Vary", "Origin")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        p = url.path
        if p == "/bridge/status":  # the jukebox checks for an optional piano helper; say "none here"
            return self.send_json({"piano": None})
        if p == "/api/checks/latest":   # the most recent piano check report (to reopen it)
            import piano_check
            files = sorted(piano_check.CHECKS.glob("*.json"), key=lambda f: f.stat().st_mtime) if piano_check.CHECKS.exists() else []
            if not files:
                return self.send_json({"error": "no checks yet"}, 404)
            r = json.loads(files[-1].read_text(encoding="utf-8"))
            r["saved"] = str(files[-1].with_suffix(".txt"))
            return self.send_json(r)
        if p == "/api/reference":   # the original song's 88-key picture, for the live comparison view
            import piano_check
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            r = piano_check.reference_for_browser(q.get("name", ""))
            return self.send_json(r if r else {"error": "no reference for this song (convert it here first)"}, 200 if r else 404)
        if p == "/api/health":
            return self.send_json({"ok": True, "busy": sum(j["state"] in ("queued", "working") for j in jobs.values())})
        if p.startswith("/api/job/"):
            bits = p.split("/")
            job = jobs.get(bits[3]) if len(bits) > 3 else None
            if not job:
                return self.send_json({"error": "unknown job"}, 404)
            if len(bits) > 4 and bits[4] == "midi":
                if job["state"] != "done":
                    return self.send_json({"error": "not ready"}, 409)
                self.send_response(200)
                self.send_header("Content-Type", "audio/midi")
                # ASCII fallback + UTF-8 name, so Tamil/Hindi/etc. song names don't crash the download
                ascii_name = job["file"].encode("ascii", "ignore").decode().replace('"', "") or "song.mid"
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(job["file"])}')
                self.send_header("Content-Length", str(len(job["midi"])))
                self.end_headers()
                self.wfile.write(job["midi"])
                return
            return self.send_json({k: v for k, v in job.items() if k not in ("midi", "added")})
        if p.startswith("/api/"):
            return self.send_json({"error": "not found"}, 404)
        return super().do_GET()

    def read_body(self, limit):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if not 0 < length <= limit:
            return None
        chunks, left = [], length
        while left:
            c = self.rfile.read(min(left, 1 << 20))
            if not c: return None
            chunks.append(c); left -= len(c)
        return b"".join(chunks)

    def do_check(self, q):
        """Piano check: body = MIDI bytes (midi_len of them) followed by a WAV recording of the piano."""
        import io
        import soundfile as sf
        import piano_check
        body = self.read_body(200 * 1024 * 1024)
        if body is None:
            return self.send_json({"error": "recording missing or too large"}, 400)
        try:
            n = int(q.get("midi_len", "0"))
            midi, wav = body[:n], body[n:]
            rec, rate = sf.read(io.BytesIO(wav), dtype="float32", always_2d=True)
            rec = rec.mean(1)
            if rate != piano_check.SR:
                import librosa
                rec = librosa.resample(rec, orig_sr=rate, target_sr=piano_check.SR)
            if len(rec) < piano_check.SR * 5:
                return self.send_json({"error": "recording too short - record at least 5 seconds"}, 400)
            name = q.get("name", "song")[:120]
            hint = float(q["pos"]) if q.get("pos") else None
            vol = float(q["vol"]) if q.get("vol") else None
            floor = int(q["floor"]) if q.get("floor") else None
            print(f"[check] {name}: {len(rec) / piano_check.SR:.0f}s recording", flush=True)
            r = piano_check.analyse(rec, midi, name=name, hint=hint, ref_path=piano_check.ref_for(name), vol=vol, floor=floor)
            base = piano_check.save(r, rec)
            r["text"] = piano_check.text_report(r)
            r["saved"] = str(base) + ".txt"
            print(r["text"], flush=True)
            return self.send_json(r)
        except Exception as e:
            traceback.print_exc()
            return self.send_json({"error": f"check failed: {e}"}, 500)

    def do_POST(self):
        url = urlparse(self.path)
        origin = self.headers.get("Origin")
        if origin and not ALLOWED_ORIGIN.match(origin):
            return self.send_json({"error": "not allowed from this website"}, 403)
        if url.path == "/api/check":
            return self.do_check({k: v[0] for k, v in parse_qs(url.query).items()})
        if url.path == "/api/youtube":
            import youtube
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            link, mode = q.get("url", ""), q.get("mode", "auto")
            if mode not in ("auto", "piano", "pop"):
                return self.send_json({"error": "mode must be auto, piano or pop"}, 400)
            if not youtube.video_id(link):
                return self.send_json({"error": "That doesn't look like a YouTube video link."}, 400)
            parts = [x for x in q.get("parts", "vocals,other,bass").split(",") if x in song2midi.PARTS] or ["vocals", "other"]
            job_id = uuid.uuid4().hex[:12]
            ahead = sum(j["state"] in ("queued", "working") for j in jobs.values())
            jobs[job_id] = {"id": job_id, "name": "YouTube song", "mode": mode, "parts": parts, "state": "queued", "youtube": link,
                            "status": f"Waiting ({ahead} ahead)..." if ahead else "Starting...", "added": time.time()}
            work.put((job_id, None))
            return self.send_json({"id": job_id})
        if url.path != "/api/convert":
            return self.send_json({"error": "not found"}, 404)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        mode = q.get("mode", "auto")
        if mode not in ("auto", "piano", "pop"):
            return self.send_json({"error": "mode must be auto, piano or pop"}, 400)
        parts = [x for x in q.get("parts", "vocals,other,bass").split(",") if x]
        if not parts or any(x not in song2midi.PARTS for x in parts):
            return self.send_json({"error": "bad parts"}, 400)
        ext = Path(q.get("filename", "audio.wav")).suffix.lower()
        if ext not in EXTS:
            return self.send_json({"error": f"unsupported file type {ext or '(none)'} - use mp3, wav, flac or ogg"}, 400)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if not 0 < length <= MAX_UPLOAD:
            return self.send_json({"error": "file missing or too large"}, 400)

        fd, tmp = tempfile.mkstemp(suffix=ext, prefix="song2midi-")
        with os.fdopen(fd, "wb") as f:
            left = length
            while left:
                chunk = self.rfile.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left:  # upload was cut off part-way
            os.unlink(tmp)
            return self.send_json({"error": "upload was interrupted"}, 400)

        name = (q.get("name") or Path(q.get("filename", "song")).stem)[:120]
        job_id = uuid.uuid4().hex[:12]
        ahead = sum(j["state"] in ("queued", "working") for j in jobs.values())
        jobs[job_id] = {"id": job_id, "name": name, "mode": mode, "parts": parts, "state": "queued",
                        "status": f"Waiting ({ahead} ahead)..." if ahead else "Starting...", "added": time.time()}
        work.put((job_id, tmp))
        self.send_json({"id": job_id})


def main():
    if not APP_DIR.exists():
        raise SystemExit(f"Can't find the Piano Jukebox folder at {APP_DIR}")
    threading.Thread(target=worker, daemon=True).start()

    def warm():  # load the models in the background so the first song is quicker
        try:
            song2midi.piano_model()
            song2midi.demucs_model()
            print("Models loaded - ready.", flush=True)
        except Exception as e:
            print("Model preload failed:", e, flush=True)
    threading.Thread(target=warm, daemon=True).start()

    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Piano Jukebox + Song to MIDI running at http://localhost:{PORT}")
    print("Leave this window open while you use it. Close it (or Ctrl+C) to stop.", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
