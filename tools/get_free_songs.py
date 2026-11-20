"""Download the free/public-domain songs listed in tools/free_songs.tsv.

    py -3.11 tools/get_free_songs.py

Files go to piano-jukebox/library/free/<collection>/. Each download is
checked to be a readable MIDI file with piano notes; bad files are deleted.
Already-downloaded files are skipped. One request per second (polite).
"""
import csv
import re
import time
import urllib.request
from pathlib import Path

import mido

ROOT = Path(__file__).resolve().parent.parent
LIST = ROOT / "tools" / "free_songs.tsv"
OUT = ROOT / "piano-jukebox" / "library" / "free"
UA = "Mozilla/5.0 (piano-jukebox personal project)"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:60]


def main():
    ok = bad = skipped = 0
    with open(LIST, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for r in rows:
        dest = OUT / r["collection"] / (slug(r["composer"].split()[-1] + "_" + r["title"]) + ".mid")
        if dest.exists():
            skipped += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            req = urllib.request.Request(r["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            if not data.startswith(b"MThd"):
                raise ValueError("not a MIDI file")
            dest.write_bytes(data)
            m = mido.MidiFile(dest)
            notes = sum(1 for msg in m if msg.type == "note_on" and msg.velocity)
            if notes == 0:
                raise ValueError("no notes")
            ok += 1
            print(f"OK   {m.length:6.0f}s {notes:6d} notes  {r['title']}")
        except Exception as e:
            bad += 1
            dest.unlink(missing_ok=True)
            print(f"FAIL {r['title']}: {e}")
        time.sleep(5 if "wikimedia" in r["url"] else 1)   # Commons rate-limits
    print(f"\n{ok} downloaded, {skipped} already had, {bad} failed")


if __name__ == "__main__":
    main()
