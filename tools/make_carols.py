"""Write simple piano arrangements of public-domain carols as .mid files.

    py -3.11 tools/make_carols.py

Each bar is (chords, melody). Melody: "E4 1 D4 .5 ..." = pitch, length in
quarter notes. Chords split the bar evenly ("C G7" = half bar each).
Left hand: bass note on the chord's first beat, then the chord on the
other beats, with the sustain pedal changed at each chord.
"""
from pathlib import Path

import mido

OUT = Path(__file__).resolve().parent.parent / "piano-jukebox" / "library" / "christmas"
TPQ = 480
NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
QUALITY = {"": (0, 4, 7), "m": (0, 3, 7), "7": (0, 4, 7, 10),
           "dim": (0, 3, 6), "m7": (0, 3, 7, 10)}


def pitch(s):
    name, octave = s[:-1], int(s[-1])
    n = NOTE[name[0]] + name.count("#") - name.count("b")
    return 12 * (octave + 1) + n


def chord(sym):
    root = sym[0] + ("#" if sym[1:2] == "#" else "b" if sym[1:2] == "b" else "")
    qual = sym[len(root):]
    r = NOTE[root[0]] + root.count("#") - root.count("b")
    return r, QUALITY[qual]


SONGS = [
    {"title": "Silent Night", "composer": "Franz Xaver Gruber", "bpm": 52,
     "beat": 1.5, "bar": 3, "bars": [
        ("C", "G4 .75 A4 .25 G4 .5 E4 1.5"),
        ("C", "G4 .75 A4 .25 G4 .5 E4 1.5"),
        ("G7", "D5 1 D5 .5 B4 1.5"),
        ("C", "C5 1 C5 .5 G4 1.5"),
        ("F", "A4 1 A4 .5 C5 .75 B4 .25 A4 .5"),
        ("C", "G4 .75 A4 .25 G4 .5 E4 1.5"),
        ("F", "A4 1 A4 .5 C5 .75 B4 .25 A4 .5"),
        ("C", "G4 .75 A4 .25 G4 .5 E4 1.5"),
        ("G7", "D5 1 D5 .5 F5 .75 D5 .25 B4 .5"),
        ("C", "C5 1.5 E5 1.5"),
        ("C G7", "C5 .75 G4 .25 E4 .5 G4 .75 F4 .25 D4 .5"),
        ("C", "C4 3"),
    ]},
    {"title": "Jingle Bells", "composer": "James Lord Pierpont", "bpm": 112,
     "beat": 1, "bar": 4, "bars": [
        ("C", "G4 1 E5 1 D5 1 C5 1"), ("C", "G4 3 G4 .5 G4 .5"),
        ("C", "G4 1 E5 1 D5 1 C5 1"), ("F", "A4 4"),
        ("F", "A4 1 F5 1 E5 1 D5 1"), ("G7", "B4 4"),
        ("G7", "G5 1 G5 1 F5 1 D5 1"), ("C", "E5 4"),
        ("C", "G4 1 E5 1 D5 1 C5 1"), ("C", "G4 4"),
        ("C", "G4 1 E5 1 D5 1 C5 1"), ("F", "A4 3 A4 1"),
        ("F", "A4 1 F5 1 E5 1 D5 1"), ("G7", "G5 1 G5 1 G5 1 G5 1"),
        ("G7", "A5 1 G5 1 F5 1 D5 1"), ("C", "C5 4"),
        ("C", "E5 1 E5 1 E5 2"), ("C", "E5 1 E5 1 E5 2"),
        ("C", "E5 1 G5 1 C5 1.5 D5 .5"), ("C", "E5 4"),
        ("F", "F5 1 F5 1 F5 1.5 F5 .5"), ("C", "F5 1 E5 1 E5 1 E5 .5 E5 .5"),
        ("D7", "E5 1 D5 1 D5 1 E5 1"), ("G7", "D5 2 G5 2"),
        ("C", "E5 1 E5 1 E5 2"), ("C", "E5 1 E5 1 E5 2"),
        ("C", "E5 1 G5 1 C5 1.5 D5 .5"), ("C", "E5 4"),
        ("F", "F5 1 F5 1 F5 1 F5 1"), ("C", "F5 1 E5 1 E5 1 E5 .5 E5 .5"),
        ("G7", "G5 1 G5 1 F5 1 D5 1"), ("C", "C5 4"),
    ]},
    {"title": "Deck the Halls", "composer": "Traditional Welsh", "bpm": 120,
     "beat": 1, "bar": 4, "bars": [
        ("C", "G4 1.5 F4 .5 E4 1 D4 1"), ("C", "C4 1 D4 1 E4 1 C4 1"),
        ("G7 C", "D4 .5 E4 .5 F4 .5 D4 .5 E4 1.5 D4 .5"), ("C G7", "C4 1 B3 1 C4 2"),
        ("C", "G4 1.5 F4 .5 E4 1 D4 1"), ("C", "C4 1 D4 1 E4 1 C4 1"),
        ("G7 C", "D4 .5 E4 .5 F4 .5 D4 .5 E4 1.5 D4 .5"), ("C G7", "C4 1 B3 1 C4 2"),
        ("G7", "D4 1.5 E4 .5 F4 1 D4 1"), ("C", "E4 1.5 F4 .5 G4 1 D4 1"),
        ("D7 G", "E4 .5 F#4 .5 G4 1 A4 .5 B4 .5 C5 1"), ("G D7", "B4 1 A4 1 G4 2"),
        ("C", "G4 1.5 F4 .5 E4 1 D4 1"), ("C", "C4 1 D4 1 E4 1 C4 1"),
        ("F C", "A4 .5 A4 .5 A4 .5 A4 .5 G4 1.5 F4 .5"), ("G7 C", "E4 1 D4 1 C4 2"),
    ]},
    {"title": "We Wish You a Merry Christmas", "composer": "Traditional English",
     "bpm": 132, "beat": 1, "bar": 3, "bars": [
        ("", "G4 1"),
        ("C", "C5 1 C5 .5 D5 .5 C5 .5 B4 .5"), ("F", "A4 1 A4 1 A4 1"),
        ("D7", "D5 1 D5 .5 E5 .5 D5 .5 C5 .5"), ("G", "B4 1 G4 1 G4 1"),
        ("E7", "E5 1 E5 .5 F5 .5 E5 .5 D5 .5"), ("Am", "C5 1 A4 1 G4 .5 G4 .5"),
        ("F G7 G7", "A4 1 D5 1 B4 1"), ("C", "C5 2 G4 1"),
        ("C", "C5 1 C5 .5 D5 .5 C5 .5 B4 .5"), ("F", "A4 1 A4 1 A4 1"),
        ("D7", "D5 1 D5 .5 E5 .5 D5 .5 C5 .5"), ("G", "B4 1 G4 1 G4 1"),
        ("E7", "E5 1 E5 .5 F5 .5 E5 .5 D5 .5"), ("Am", "C5 1 A4 1 G4 .5 G4 .5"),
        ("F G7 G7", "A4 1 D5 1 B4 1"), ("C", "C5 3"),
    ]},
    {"title": "Joy to the World", "composer": "G. F. Handel, arr. Lowell Mason",
     "bpm": 100, "beat": 1, "bar": 2, "bars": [
        ("C", "C5 1 B4 .75 A4 .25"), ("C", "G4 1.5 F4 .5"),
        ("C G7", "E4 1 D4 1"), ("C", "C4 1.5 G4 .5"),
        ("F", "A4 1.5 A4 .5"), ("G", "B4 1.5 B4 .5"),
        ("C", "C5 1.5 C5 .5"), ("C", "C5 .5 B4 .5 A4 .5 G4 .5"),
        ("G7 C", "G4 .75 F4 .25 E4 .5 C5 .5"), ("C", "C5 .5 B4 .5 A4 .5 G4 .5"),
        ("G7 C", "G4 .75 F4 .25 E4 .5 E4 .5"), ("C", "E4 .5 E4 .5 E4 .5 E4 .25 F4 .25"),
        ("C", "G4 1.5 F4 .25 E4 .25"), ("G7", "D4 .5 D4 .5 D4 .5 D4 .25 E4 .25"),
        ("G7", "F4 1.5 E4 .25 D4 .25"), ("C F", "C4 .5 C5 1 A4 .5"),
        ("C F", "G4 .75 F4 .25 E4 .5 F4 .5"), ("C G7", "E4 1 D4 1"), ("C", "C4 2"),
    ]},
]


def build(song):
    events = []                                    # (beat, order, msg)
    t = 0.0
    for n, (chords, melody) in enumerate(song["bars"]):
        toks = melody.split()
        notes = [(toks[i], float(toks[i + 1])) for i in range(0, len(toks), 2)]
        length = sum(d for _, d in notes)
        if n > 0 and abs(length - song["bar"]) > 1e-6:
            raise ValueError(f"{song['title']} bar {n + 1}: {length} beats")
        pos = t
        for p, d in notes:
            events.append((pos, 1, mido.Message("note_on", note=pitch(p), velocity=78)))
            events.append((pos + d * 0.95, 0, mido.Message("note_off", note=pitch(p))))
            pos += d
        syms = chords.split()
        if syms:
            seg = length / len(syms)
            for k, sym in enumerate(syms):
                start = t + k * seg
                if k > 0 and sym == syms[k - 1]:
                    continue
                span = seg * (syms[k:].count(sym) if len(set(syms[k:])) == 1 else 1)
                root, ivs = chord(sym)
                bass = 36 + root if root <= 7 else 24 + root       # C2..G2 / G#1..B1
                upper = [48 + root + i if 48 + root + i < 60 else 36 + root + i for i in ivs]
                upper = sorted(set(n if n >= 52 else n + 12 for n in upper))
                events.append((start, 0, mido.Message("control_change", control=64, value=0)))
                events.append((start + 0.05, 2, mido.Message("control_change", control=64, value=100)))
                events.append((start, 1, mido.Message("note_on", note=bass, velocity=62)))
                events.append((start + song["beat"] * 0.9, 0, mido.Message("note_off", note=bass)))
                b = start + song["beat"]
                while b < start + span - 1e-6:
                    for u in upper:
                        events.append((b, 1, mido.Message("note_on", note=u, velocity=48)))
                        events.append((b + song["beat"] * 0.8, 0, mido.Message("note_off", note=u)))
                    b += song["beat"]
        t += length
    events.append((t + 1, 0, mido.Message("control_change", control=64, value=0)))
    events.sort(key=lambda e: (e[0], e[1]))

    mid = mido.MidiFile(ticks_per_beat=TPQ)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("track_name", name=song["title"]))
    tr.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(song["bpm"])))
    last = 0
    for beat, _, msg in events:
        tick = round(beat * TPQ)
        tr.append(msg.copy(time=tick - last))
        last = tick
    return mid


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for s in SONGS:
        name = "arr_" + s["title"].lower().replace(" ", "_") + ".mid"
        m = build(s)
        m.save(OUT / name)
        print(f"{name:40s} {m.length:5.1f} s")
