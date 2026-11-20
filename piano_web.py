"""
piano_web.py - run the Piano Jukebox website locally and play it on the piano.

    py -3.11 piano_web.py            then open http://localhost:8765

Serves the site in piano-jukebox/ and acts as a MIDI bridge: the page sends
timestamped note/pedal messages to /bridge/send and this server plays them
on the piano through python-rtmidi (the same route as piano_player.py).
That works even when the browser itself can't see MIDI devices.

Only this PC can use it: the server listens on localhost and rejects
requests from other websites.
"""
import argparse
import heapq
import itertools
import json
import threading
import time
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import mido

from piano_player import pick_port

SITE = Path(__file__).resolve().parent / "piano-jukebox"
IDLE_CLOSE = 5             # seconds of silence before the MIDI port is released
                           # (Windows lets only one program use it at a time)


class Bridge:
    """Plays timestamped MIDI messages on the piano at the right moment."""

    def __init__(self):
        self.cond = threading.Condition()
        self.heap = []
        self.seq = itertools.count()
        self.clear_batch = -1           # batches older than the last clear are dropped
        self.port = None
        self.name = ""
        self.error = ""
        self.last_send = 0.0
        threading.Thread(target=self._run, daemon=True).start()

    def _open(self):
        if self.port is None:
            try:
                self.name = pick_port(None)
                self.port = mido.open_output(self.name)
                self.error = ""
            except SystemExit as e:                 # pick_port exits on failure
                self.error = str(e)
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
        return self.port

    def _close(self):
        if self.port is not None:
            try:
                self.port.close()
            except Exception:
                pass
            self.port = None

    def submit(self, batch, msgs, clear=False):
        now = time.perf_counter()
        with self.cond:
            if clear:
                self.heap.clear()
                self.clear_batch = max(self.clear_batch, batch)
            elif batch < self.clear_batch:
                return                              # arrived late, after a stop
            for m in msgs:
                delay, data = float(m[0]), [int(x) & 0xFF for x in m[1:4]]
                heapq.heappush(self.heap, (now + max(0.0, delay) / 1000, next(self.seq), data))
            self.cond.notify()

    def _run(self):
        while True:
            with self.cond:
                while True:
                    now = time.perf_counter()
                    if self.heap and self.heap[0][0] <= now:
                        _, _, data = heapq.heappop(self.heap)
                        break
                    if self.port is not None and not self.heap and now - self.last_send > IDLE_CLOSE:
                        self._close()
                    wait = self.heap[0][0] - now if self.heap else 1.0
                    self.cond.wait(min(wait, 1.0))
            port = self._open()
            if port is None:
                continue
            try:
                port.send(mido.Message.from_bytes(data))
                self.last_send = time.perf_counter()
            except ValueError:
                pass                                # malformed message: skip it
            except Exception as e:
                self.error = f"Send failed: {e}"
                self._close()

    def status(self):
        try:
            outs = mido.get_output_names()
        except Exception:
            outs = []
        try:
            piano = pick_port(None)
        except SystemExit:
            piano = ""
        return {"ok": bool(piano), "piano": piano, "outputs": outs, "error": self.error}


BRIDGE = Bridge()


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _local_host(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in ("localhost", "127.0.0.1")

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._local_host():
            return self._json(403, {"error": "forbidden"})
        if self.path.split("?")[0] == "/bridge/status":
            return self._json(200, BRIDGE.status())
        super().do_GET()

    def do_HEAD(self):
        if not self._local_host():
            return self._json(403, {"error": "forbidden"})
        super().do_HEAD()

    def do_POST(self):
        # JSON content type forces a CORS preflight that we never approve,
        # so other websites open in the browser can't drive the piano.
        if (not self._local_host() or
                "application/json" not in self.headers.get("Content-Type", "")):
            return self._json(403, {"error": "forbidden"})
        if self.path != "/bridge/send":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            BRIDGE.submit(int(body.get("batch", 0)), body.get("msgs", []),
                          bool(body.get("clear")))
        except (ValueError, TypeError, IndexError):
            return self._json(400, {"error": "bad request"})
        self._json(200, {"ok": True})


def main():
    ap = argparse.ArgumentParser(description="Local Piano Jukebox + MIDI bridge.")
    ap.add_argument("--port", type=int, default=8765, help="web port")
    ap.add_argument("--no-browser", action="store_true",
                    help="don't open the browser automatically")
    args = ap.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port),
                                 partial(Handler, directory=str(SITE)))
    url = f"http://localhost:{args.port}"
    st = BRIDGE.status()
    print(f"Piano Jukebox: {url}")
    print(f"Piano: {st['piano'] or 'not found - pair the WIDI Jack'}")
    print("Keep this window open while playing. Ctrl+C to quit.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
        BRIDGE.submit(1 << 60, [], clear=True)
        port = BRIDGE._open()
        if port:
            from piano_player import panic
            panic(port, 0)


if __name__ == "__main__":
    main()
