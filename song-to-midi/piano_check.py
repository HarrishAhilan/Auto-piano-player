"""Piano check: record the real piano playing a song and find where it goes wrong.

  python piano_check.py --midi "output/Song.mid" --seconds 60      record 60 s from the mic now
  python piano_check.py --midi "output/Song.mid" --file take.wav   analyse an existing recording

The recording is lined up with the MIDI automatically (you can start recording at any point
in the song). Then, every few seconds, it checks:
  - timing:   does the piano strike the notes when the MIDI says? (early / late / missing)
  - notes:    does what you hear match the notes that were sent?
  - melody:   does the tune stand out over the backing, on the real instrument?
  - song:     does it sound like the original song there? (if the song was converted here)
and writes a report with timestamps to output/checks/.
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

SR = 16000
HOP = 160                      # 10 ms
HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
CHECKS = OUT / "checks"
REFS = OUT / "refs"
WINDOW = 5.0                   # seconds per checked section


# ------------------------------------------------------------------------------ MIDI
def read_midi(data):
    import io
    import mido
    mf = mido.MidiFile(file=io.BytesIO(data)) if isinstance(data, (bytes, bytearray)) else mido.MidiFile(str(data))
    t, on, notes, ped, down = 0.0, {}, [], [], None
    for m in mf:
        t += m.time
        if m.type == "control_change" and m.control == 64:
            if m.value >= 64 and down is None: down = t
            elif m.value < 64 and down is not None: ped.append((down, t)); down = None
        elif m.type == "note_on" and m.velocity:
            on.setdefault(m.note, []).append((t, m.velocity))
        elif m.type in ("note_off", "note_on") and on.get(m.note):
            s, v = on[m.note].pop(0); notes.append(dict(s=s, e=t, p=m.note, v=v))
    if down is not None: ped.append((down, t))
    return notes, ped, mf.length


def sounding_until(n, ped):
    for s, e in ped:
        if s <= n["e"] < e: return e
    return n["e"]


def melody_line(notes, ped):
    """The tune a listener follows: the highest note sounding (from middle C up) at each moment."""
    mel = []
    for n in sorted(notes, key=lambda n: n["s"]):
        if n["p"] < 60: continue
        if mel and n["s"] < mel[-1]["e"] - 0.02:
            if n["p"] > mel[-1]["p"]: mel[-1] = dict(mel[-1], e=n["s"]); mel.append(n)
            continue
        mel.append(n)
    return [m for m in mel if m["e"] - m["s"] > 0.04]


# ------------------------------------------------------------------------------ audio features
def onset_env(y):
    import librosa
    return librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)


def midi_onset_train(notes, n_frames):
    x = np.zeros(n_frames)
    for n in notes:
        i = int(n["s"] * SR / HOP)
        if 0 <= i < n_frames: x[i] += (n["v"] / 127) ** 1.5
    k = np.exp(-np.arange(8) / 2.5)                       # a struck note decays in the onset curve
    return np.convolve(x, k)[:n_frames]


def align(rec, notes, song_len, hint=None):
    """Where in the song does the recording start? Cross-correlate onset curves (FFT)."""
    env = onset_env(rec); env = (env - env.mean()) / (env.std() + 1e-9)
    n_song = int((song_len + 2) * SR / HOP)
    train = midi_onset_train(notes, n_song); train = (train - train.mean()) / (train.std() + 1e-9)
    L = len(train) + len(env)
    F = np.fft.rfft(train, L) * np.conj(np.fft.rfft(env, L))
    corr = np.fft.irfft(F, L)[: max(1, len(train) - len(env) // 4)]
    if hint is not None:
        lo, hi = max(0, int((hint - 3) * SR / HOP)), int((hint + 3) * SR / HOP)
        mask = np.full(len(corr), -np.inf); mask[lo:hi] = 0; corr = corr + mask
    k = int(np.argmax(corr))
    finite = corr[np.isfinite(corr)]
    conf = float((corr[k] - np.median(finite)) / (np.std(finite) + 1e-9))
    return k * HOP / SR, conf


def chroma(y):
    import librosa
    c = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=1024)
    return c / (np.linalg.norm(c, axis=0, keepdims=True) + 1e-9)


def roll_chroma(notes, ped, t0, n_frames):
    hop = 1024 / SR; c = np.zeros((12, n_frames))
    for n in notes:
        a = int((n["s"] - t0) / hop); b = int((sounding_until(n, ped) - t0) / hop) + 1
        a, b = max(0, a), min(n_frames, b)
        if b <= a: continue
        tt = (np.arange(a, b) * hop + t0 - n["s"]).clip(0)
        env = (n["v"] / 127) ** 1.7 * np.exp(-tt / np.interp(n["p"], [21, 108], [4.0, 0.6]))
        for k, w in ((0, 1.0), (0, 0.41), (7, 0.24), (0, 0.16), (4, 0.12)):
            c[(n["p"] + k) % 12, a:b] += w * env
    return c / (np.linalg.norm(c, axis=0, keepdims=True) + 1e-9)


def note_energy(rec):
    """Energy at each piano key over time (constant-Q, one bin per semitone, 10 ms grid)."""
    import librosa
    C = np.abs(librosa.cqt(rec, sr=SR, hop_length=HOP, fmin=librosa.midi_to_hz(21), n_bins=88, bins_per_octave=12))
    return C ** 2                                         # [88 keys, frames]


# ------------------------------------------------------------------------------ the check
def analyse(rec, midi, name="song", hint=None, ref_path=None, vol=None, floor=None):
    import librosa
    notes, ped, song_len = read_midi(midi)
    rec = rec.astype(np.float32); rec = rec / (np.abs(rec).max() + 1e-9)
    dur = len(rec) / SR
    start, conf = align(rec, notes, song_len, hint)
    rec_on = librosa.onset.onset_detect(y=rec, sr=SR, hop_length=HOP, units="time", backtrack=False, delta=0.05) + start
    seg = [n for n in notes if start - 0.5 <= n["s"] < start + dur]
    mel = melody_line(seg, ped)
    E = note_energy(rec); nf = E.shape[1]
    C_rec = chroma(rec); C_sent = roll_chroma(seg, ped, start, C_rec.shape[1])
    ref = None
    if ref_path and Path(ref_path).exists():
        d = np.load(ref_path); ref = dict(chroma=d["chroma"], hop=float(d["hop"]))
    windows = []
    for w0 in np.arange(start, start + dur - 1.0, WINDOW):
        w1 = min(w0 + WINDOW, start + dur)
        wn = [n for n in seg if w0 <= n["s"] < w1]
        if not wn:
            windows.append(dict(t=round(float(w0), 1), silent=True)); continue
        # timing: each sent note start -> nearest heard note start
        st = np.array([n["s"] for n in wn]); ro = rec_on[(rec_on > w0 - 0.2) & (rec_on < w1 + 0.2)]
        if len(ro):
            d = ro[np.clip(np.searchsorted(ro, st), 0, len(ro) - 1)] - st
            d2 = ro[np.clip(np.searchsorted(ro, st) - 1, 0, len(ro) - 1)] - st
            d = np.where(np.abs(d) < np.abs(d2), d, d2)
            heard = np.abs(d) <= 0.07
            late_ms = float(np.median(d[np.abs(d) <= 0.15]) * 1000) if (np.abs(d) <= 0.15).any() else None
            heard_share = float(heard.mean())
        else:
            late_ms, heard_share = None, 0.0
        # notes: what you hear vs what was sent
        a, b = int((w0 - start) * SR / 1024), int((w1 - start) * SR / 1024)
        sent_vs_heard = float((C_rec[:, a:b] * C_sent[:, a:b]).sum(0).mean()) if b > a else None
        # melody: energy at the tune's keys vs the other keys sounding at the same moments
        ratios = []
        for m in [m for m in mel if w0 <= m["s"] < w1]:
            i0, i1 = int((m["s"] - start) * SR / HOP) + 2, int((m["s"] - start) * SR / HOP) + 12
            if i1 >= nf or i0 < 0: continue
            mk = m["p"] - 21
            if not 0 <= mk < 88: continue
            around = [n for n in seg if n is not m and n["s"] <= m["s"] + 0.05 and sounding_until(n, ped) > m["s"]
                      and n["p"] != m["p"] and 0 <= n["p"] - 21 < 88 and abs(n["p"] - m["p"]) != 12]
            if not around: continue
            # only judge notes that were SENT as the tune (clearly louder than what's around them);
            # otherwise it's just the top note of a chord or lick, not a melody
            if m["v"] < max(n["v"] for n in around) + 10: continue
            others = [n["p"] - 21 for n in around]
            em = E[mk, i0:i1].mean(); eo = np.mean([E[k, i0:i1].mean() for k in others])
            ratios.append(10 * np.log10((em + 1e-12) / (eo + 1e-12)))
        melody_db = float(np.median(ratios)) if ratios else None
        like_song = None
        if ref is not None:
            ra, rb = int(w0 / ref["hop"]), int(w1 / ref["hop"])
            rc = ref["chroma"][:, ra:rb]; k = min(rc.shape[1], b - a)
            if k > 2: like_song = float((C_rec[:, a:a + k] * rc[:, :k]).sum(0).mean())
        windows.append(dict(t=round(float(w0), 1), notes_sent=len(wn), heard_on_time=round(heard_share, 2),
                            timing_ms=None if late_ms is None else round(late_ms),
                            sounds_like_sent=None if sent_vs_heard is None else round(sent_vs_heard, 2),
                            melody_over_backing_db=None if melody_db is None else round(melody_db, 1),
                            sounds_like_song=None if like_song is None else round(like_song, 2),
                            notes_per_sec=round(len(wn) / (w1 - w0), 1)))
    # ------------------------------------------------ problems, in plain words
    problems = []
    for w in windows:
        if w.get("silent"): continue
        why = []
        if w["melody_over_backing_db"] is not None and w["melody_over_backing_db"] < 3:
            why.append(f"melody buried (only {w['melody_over_backing_db']:+.0f} dB over the backing)")
        if w["timing_ms"] is not None and abs(w["timing_ms"]) > 40:
            why.append(f"notes {'late' if w['timing_ms'] > 0 else 'early'} by ~{abs(w['timing_ms'])} ms")
        if w["heard_on_time"] < 0.5:
            why.append(f"only {w['heard_on_time']:.0%} of notes heard on time (missed or smeared)")
        if w["sounds_like_sent"] is not None and w["sounds_like_sent"] < 0.6:
            why.append("what the piano plays doesn't match the notes sent (dropped/muddy notes)")
        if w["sounds_like_song"] is not None and w["sounds_like_song"] < 0.55:
            why.append("doesn't sound like the original song here (wrong chords/notes in the arrangement)")
        if w["notes_per_sec"] > 14:
            why.append(f"very busy ({w['notes_per_sec']} notes/s) - may sound jumbled")
        if why: problems.append(dict(time=fmt(w["t"]), t=w["t"], issues=why))
    good = [w for w in windows if not w.get("silent")]
    summary = dict(
        song=name, recorded_seconds=round(dur, 1), starts_at=fmt(start), alignment_confidence=round(conf, 1),
        alignment_ok=conf > 6,
        melody_over_backing_db=med([w["melody_over_backing_db"] for w in good]),
        timing_ms=med([w["timing_ms"] for w in good]), heard_on_time=med([w["heard_on_time"] for w in good]),
        sounds_like_sent=med([w["sounds_like_sent"] for w in good]), sounds_like_song=med([w["sounds_like_song"] for w in good]),
        jukebox_volume=vol, jukebox_softest=floor, problem_sections=len(problems), checked_sections=len(good))
    return dict(summary=summary, problems=problems, windows=windows)


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(float(np.median(xs)), 2) if xs else None


def fmt(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def base_name(name):
    return re.sub(r"\s*\((auto|pop|piano|tuned|arranged[^)]*|\d+)\)\s*$", "", Path(name).stem).strip()


def ref_for(name):
    p = REFS / f"{base_name(name)}.npz"
    return p if p.exists() else None


def text_report(r):
    s = r["summary"]; L = []
    L.append(f"Piano check: {s['song']}  ({s['recorded_seconds']}s recorded, starting at {s['starts_at']} in the song)")
    if not s["alignment_ok"]:
        L.append("  ! Couldn't confidently line the recording up with the song - was the piano playing this song, loud enough?")
    def line(label, v, unit=""):
        if v is not None: L.append(f"  {label:34s} {v}{unit}")
    line("Melody louder than backing (median)", s["melody_over_backing_db"], " dB   (want 6+)")
    line("Timing (median, + = piano late)", s["timing_ms"], " ms   (want within ±30)")
    line("Notes heard on time", None if s["heard_on_time"] is None else f"{s['heard_on_time']:.0%}")
    line("Sounds like the notes sent", s["sounds_like_sent"], "   (1.0 = perfect)")
    line("Sounds like the original song", s["sounds_like_song"], "   (1.0 = perfect)")
    L.append(f"  {s['problem_sections']} of {s['checked_sections']} sections have problems:")
    for p in r["problems"]:
        L.append(f"    {p['time']}  " + "; ".join(p["issues"]))
    return "\n".join(L)


def save(r, rec=None):
    CHECKS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = CHECKS / f"{base_name(r['summary']['song'])} {stamp}"
    (base.with_suffix(".json")).write_text(json.dumps(r, indent=1), encoding="utf-8")
    (base.with_suffix(".txt")).write_text(text_report(r), encoding="utf-8")
    if rec is not None:
        import soundfile as sf
        sf.write(str(base) + ".wav", rec, SR)
    return base


def save_reference(original_audio_16k, name):
    """Called by the converter: remember what the original song sounds like, for later checks."""
    REFS.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(REFS / f"{base_name(name)}.npz", chroma=chroma(original_audio_16k).astype(np.float32), hop=1024 / SR)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--midi", required=True)
    ap.add_argument("--file", help="analyse this recording instead of recording now")
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--at", type=float, help="roughly where in the song the recording starts (seconds)")
    a = ap.parse_args()
    if a.file:
        import librosa
        rec, _ = librosa.load(a.file, sr=SR, mono=True)
    else:
        import sounddevice as sd
        print(f"Recording {a.seconds:.0f}s from {sd.query_devices(kind='input')['name']} - play the song on the piano now...")
        rate = int(sd.query_devices(kind="input")["default_samplerate"])
        x = sd.rec(int(a.seconds * rate), samplerate=rate, channels=1, dtype="float32"); sd.wait()
        import librosa
        rec = librosa.resample(x[:, 0], orig_sr=rate, target_sr=SR)
    r = analyse(rec, Path(a.midi), name=Path(a.midi).name, hint=a.at, ref_path=ref_for(a.midi))
    base = save(r, rec)
    print(text_report(r)); print(f"\nSaved: {base}.txt / .json / .wav")


if __name__ == "__main__":
    main()
