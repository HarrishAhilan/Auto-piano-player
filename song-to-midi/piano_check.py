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


def robust_align(rec, notes, song_len, hint=None):
    """Line up 30 s pieces across the whole recording and take the consensus offset, so a repetitive
    passage (e.g. an intro riff) can't pull the alignment a phrase off. Falls back to align()."""
    dur = len(rec) / SR
    if dur < 45:
        return align(rec, notes, song_len, hint)
    offs = []
    for c0 in np.arange(0, dur - 30, 15):
        a = int(c0 * SR)
        s, conf = align(rec[a: a + 30 * SR], notes, song_len)
        if conf >= 6: offs.append((s - c0, conf))
    if len(offs) < 2:
        return align(rec, notes, song_len, hint)
    o = np.array([x[0] for x in offs]); med = float(np.median(o))
    agree = np.abs(o - med) <= 0.1
    if agree.sum() < max(2, 0.5 * len(o)):
        return align(rec, notes, song_len, hint)
    # each piece is aligned to 10 ms; the consensus can also be slightly negative (recording began first)
    return float(np.median(o[agree])), float(np.mean([x[1] for x, ok in zip(offs, agree) if ok]))


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
    """Energy at each piano key over time: constant-Q with 3 bins per semitone (so neighbouring keys
    don't blur together), 10 ms grid, taking the strongest bin around each key's exact pitch."""
    import librosa
    C = np.abs(librosa.cqt(rec, sr=SR, hop_length=HOP, fmin=librosa.midi_to_hz(21) / 2 ** (1 / 36),
                           n_bins=88 * 3, bins_per_octave=36)) ** 2
    return C.reshape(88, 3, -1).max(1)                    # [88 keys, frames]


NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
def key_name(p):
    return f"{NOTE_NAMES[p % 12]}{p // 12 - 1}"


def partial_energy(E):
    """A key's evidence = its fundamental plus its first overtones (overtones are shorter-windowed in
    the constant-Q transform, so they pin down WHEN a note starts much more precisely)."""
    P = E.copy()
    for k, w in ((12, 0.6), (19, 0.4), (24, 0.3), (28, 0.2)):
        P[:-k] += w * E[k:]
    return P


T_HOP = 80                     # 5 ms grid for timing
T_FFT = 1024


def stft_mag(rec):
    """Two spectrograms on a 5 ms grid: a short window (32 ms, sharp timing) for notes from C3 up,
    and a longer one (64 ms, enough frequency detail) for the bass."""
    import librosa
    return {n: np.abs(librosa.stft(rec, n_fft=n, hop_length=T_HOP, center=True)) for n in (512, 1024)}


def harmonic_bins(p, nfft, lo=150, hi=7000):
    f0 = 440 * 2 ** ((p - 69) / 12); df = SR / nfft
    B = 0.0004 if p < 60 else 0.0008                            # piano strings are slightly inharmonic
    return {int(round(k * f0 * np.sqrt(1 + B * k * k) / df)) for k in range(1, 11) if lo <= k * f0 <= hi}


def note_flux(S, p, others=()):
    """How sharply this note's own harmonics jump, every 5 ms (spectral flux on just those bins).
    Only harmonics NO other nearby note shares are used, so it's about THIS note."""
    nfft = 512 if p >= 48 else 1024; X = S[nfft]
    taken = set()
    for q in others:
        for b in harmonic_bins(q, nfft, 60, 7600): taken |= {b - 2, b - 1, b, b + 1, b + 2}
    bins = sorted(b for b in harmonic_bins(p, nfft) if b not in taken)
    rows = [b for b in bins if 0 <= b < X.shape[0]]
    if len(rows) < 2: return None                                  # nothing unique to listen to
    M = X[rows]
    F = np.zeros_like(M); F[:, 2:] = np.maximum(0, M[:, 2:] - M[:, :-2])
    return F, M                                                    # per-harmonic flux, per-harmonic level


def leading_edge(w):
    """Where a jump starts: first frame (with sub-frame interpolation) reaching half the peak."""
    j = int(np.argmax(w)); e = j
    while e > 0 and w[e - 1] >= 0.5 * w[j]: e -= 1
    if e > 0:
        return e - 1 + float(np.clip((0.5 * w[j] - w[e - 1]) / (w[e] - w[e - 1] + 1e-9), 0, 1)), w[j]
    return float(e), w[j]


def note_by_note(E, notes, ped, start, mel_ids, S=None, offset=0.0):
    """Check every note that was sent: did that key sound (fine pitch analysis, wide window),
    exactly when (5 ms harmonic flux), and how loud. `offset` = measured constant latency."""
    L0 = 10 * np.log10(E + 1e-10); nf = L0.shape[1]            # each key's OWN pitch (no overtones)
    res = []
    starts = np.array([x["s"] for x in notes])
    for idx, n in enumerate(notes):
        k = n["p"] - 21
        if not 0 <= k < 88: continue
        t = n["s"] - start + offset
        i0 = int(round(t * SR / HOP))
        if i0 < 25 or i0 + 30 >= nf: continue
        # other notes struck or still held around this one (their harmonics could be mistaken for it)
        lo_i, hi_i = np.searchsorted(starts, n["s"] - 3.0), np.searchsorted(starts, n["s"] + 0.15)
        near = [x["p"] for x in notes[lo_i:hi_i] if x is not n and x["s"] >= n["s"] - 0.15 or
                (x is not n and x["s"] < n["s"] and sounding_until(x, ped) > n["s"] - 0.05)]
        # is this key's own pitch an overtone of something else sounding? then presence is ambiguous
        shadowed = any(n["p"] - q in (12, 19, 24, 28, 31, 36) for q in near)
        # look only until this same key is struck again (so the next strike can't count for this one)
        nxt = [x["s"] for x in notes[idx + 1: idx + 40] if x["p"] == n["p"] and x["s"] > n["s"] + 0.02]
        span = int(min(0.25, (min(nxt) - n["s"]) if nxt else 0.25) * SR / HOP)
        span = max(4, span)
        before = float(np.median(L0[k, i0 - 20: i0 - 3]))         # 200..30 ms before
        peak = float(L0[k, i0: i0 + span].max())
        floor_db = float(np.percentile(L0[k], 20))
        was_ringing = before > floor_db + 12                      # key already sounding (pedal / re-strike)
        rise = peak - before
        if rise >= 4.0 and not (shadowed and rise < 8.0): heard = True
        elif was_ringing and rise <= -1.0: heard = False          # it was ringing and just faded: no new strike
        elif was_ringing or shadowed: heard = None                # can't tell
        else: heard = False
        bass = n["p"] < 48
        edge = t < 1.0 or t > nf * HOP / SR - 1.5                 # too close to the start/end of the recording
        err_ms = None
        FM = note_flux(S, n["p"], [q for q in near if q != n["p"]]) if S is not None else None
        j0 = int(round(t * SR / T_HOP)); lo, hi = j0 - 16, j0 + 24              # -80 .. +120 ms
        if FM is not None and lo > 30 and hi + 60 < FM[0].shape[1]:
            F, M = FM
            # presence from this note's UNIQUE harmonics (no other note can fake these)
            span5 = max(4, span * HOP // T_HOP)
            lv_b = 20 * np.log10(np.median(M[:, j0 - 40: j0 - 6], axis=1) + 1e-9)
            lv_a = 20 * np.log10(M[:, j0: j0 + span5].max(1) + 1e-9)
            urise = float(np.median(lv_a - lv_b))
            if urise >= 6.0: heard = True
            elif urise <= 1.0 and heard is not True: heard = False
            elif urise <= 1.0 and rise < 8.0: heard = False                        # CQT rise came from a neighbour
            if heard:
                # time each unique harmonic separately; only trust it if they agree (within 15 ms)
                bg = np.median(F[:, max(0, j0 - 200): j0 + 200], axis=1) + 1e-9
                need = 3.0 if n["p"] >= 48 else 5.0
                ests = []
                for b in range(F.shape[0]):
                    e, h = leading_edge(F[b, lo:hi])
                    if h > need * bg[b]: ests.append(e)
                if len(ests) >= 2:
                    ests = np.array(ests); med_e = float(np.median(ests))
                    close = ests[np.abs(ests - med_e) <= 3]
                    if len(close) >= max(2, 0.6 * len(ests)):
                        err_ms = (float(np.mean(close)) - 16) * T_HOP / SR * 1000
        if heard is False and (bass or edge): heard = None       # bass pitches are too blurred in time to judge
        res.append(dict(i=idx, s=n["s"], p=n["p"], v=n["v"], melody=idx in mel_ids, heard=heard,
                        err_ms=None if err_ms is None else round(err_ms, 1), level_db=round(peak, 1), rise_db=round(rise, 1)))
    # melody vs backing, note by note: is each tune note louder than the backing keys struck with it?
    by_time = sorted(res, key=lambda r: r["s"])
    for r in by_time:
        if not r["melody"]: continue
        rivals = [x for x in by_time if not x["melody"] and abs(x["s"] - r["s"]) <= 0.06]
        if rivals:
            top = max(rivals, key=lambda x: x["level_db"])
            r["over_backing_db"] = round(r["level_db"] - top["level_db"], 1); r["rival"] = key_name(top["p"])
    return res


def section_timing(rec, notes, start, win=2.0, search_ms=120):
    """How early/late each 2-second stretch runs compared with what was sent: line up that stretch's
    strikes with the sent notes (cross-correlation over many notes -> precise to a few ms).
    Also: do soft notes fire later than loud ones (player-piano solenoids often do)?"""
    import librosa
    env = librosa.onset.onset_strength(y=rec, sr=SR, hop_length=T_HOP, lag=1, max_size=3)
    env = (env - np.median(env)) / (np.std(env) + 1e-9)
    nf = len(env); out = []
    k = np.exp(-np.arange(6) / 2.0)
    span = int(search_ms / 1000 * SR / T_HOP)
    end = start + nf * T_HOP / SR
    # only whole stretches with room to slide (edges of the recording would bias the result)
    for w0 in np.arange(start + search_ms / 1000 + 0.2, end - win - search_ms / 1000 - 0.2, win):
        wn = [n for n in notes if w0 <= n["s"] < w0 + win]
        if len(wn) < 6: continue
        a = int((w0 - start) * SR / T_HOP); b = a + int(win * SR / T_HOP)
        train = np.zeros(b - a + 2 * span)
        for n in wn:
            i = int(round((n["s"] - w0) * SR / T_HOP)) + span
            if 0 <= i < len(train): train[i] += (n["v"] / 127) ** 1.5
        train = np.convolve(train, k)[: len(train)]
        scores = {}
        for d in range(-span, span + 1):                          # try shifting the sent notes by d frames
            s0 = a + d - span
            if s0 < 0 or s0 + len(train) > nf: continue
            scores[d] = float(np.dot(env[s0: s0 + len(train)], train))
        if not scores: continue
        best = max(scores, key=scores.get)
        if abs(best) >= span - 1: continue                       # stuck at the search limit: not trustworthy
        frac = 0.0                                                # parabola through the best shift
        if best - 1 in scores and best + 1 in scores:
            y0, y1, y2 = scores[best - 1], scores[best], scores[best + 1]
            frac = float(np.clip(0.5 * (y0 - y2) / (y0 - 2 * y1 + y2 + 1e-9), -0.5, 0.5))
        out.append(dict(t=round(float(w0), 2), offset_ms=round((best + frac) * T_HOP / SR * 1000, 1), notes=len(wn)))
    if out:
        med = np.median([o["offset_ms"] for o in out])
        for o in out: o["drift_ms"] = round(o["offset_ms"] - med, 1)      # relative to the constant latency
    return out


def against_original(E, ref, start, dur):
    """Pitch by pitch against the original song: which notes does the song have that the piano doesn't
    (missing), and which does the piano play that the song doesn't (wrong/extra)? 100 ms grid, octave-folded."""
    if ref is None or "cqt" not in ref: return [], None
    hop = 0.1
    nf = int(dur / hop)
    # piano recording -> 12 pitch classes per 100 ms
    step = int(hop * SR / HOP)
    R = np.stack([E[:, i * step:(i + 1) * step].mean(1) for i in range(nf)], 1)     # [88, nf]
    rc = np.zeros((12, nf))
    for k in range(88): rc[(k + 21) % 12] += R[k]
    # original (stored as dB on its own grid) -> same grid
    G = 10 ** (ref["cqt"].astype(np.float32) / 10)                                   # [88, frames]
    rh = ref["cqt_hop"]; oc = np.zeros((12, nf))
    for i in range(nf):
        a = int((start + i * hop) / rh); b = max(a + 1, int((start + (i + 1) * hop) / rh))
        if b > G.shape[1]: break
        g = G[:, a:b].mean(1)
        for k in range(88): oc[(k + 21) % 12, i] += g[k]
    import scipy.ndimage as ndi
    norm = lambda X: ndi.median_filter(X / (X.max(0, keepdims=True) + 1e-12), size=(1, 3))
    rn, on = norm(rc), norm(oc)
    loud_o = oc.sum(0) > 0.02 * np.percentile(oc.sum(0), 95)
    loud_r = rc.sum(0) > 0.02 * np.percentile(rc.sum(0), 95)
    missing = (on >= 0.5) & (rn < 0.12) & loud_o & loud_r
    extra = (rn >= 0.5) & (on < 0.12) & loud_o & loud_r
    out = []
    for kind, M in (("missing", missing), ("extra", extra)):
        for pc in range(12):
            row = M[pc]; i = 0
            while i < nf:
                if row[i]:
                    j = i
                    while j < nf and row[j]: j += 1
                    if (j - i) * hop >= 0.3:                                      # at least 300 ms
                        out.append(dict(kind=kind, pc=NOTE_NAMES[pc], t0=round(start + i * hop, 2),
                                        t1=round(start + j * hop, 2)))
                    i = j
                else:
                    i += 1
    agree = float((np.minimum(rn, on).sum(0) / (np.maximum(rn, on).sum(0) + 1e-9))[loud_o & loud_r].mean()) \
        if (loud_o & loud_r).any() else None
    return sorted(out, key=lambda x: x["t0"]), agree


def viz_payload(E, ref, notes, ped, start, dur, hop=0.04):
    """Three aligned pictures (88 keys x time): how it should sound (original), what the piano played
    (recording), and the notes that were sent - as 0..255 images for the browser."""
    import base64
    nf = int(dur / hop); step = hop * SR / HOP
    def to_u8(dbs):
        lo, hi = np.percentile(dbs, 50), np.percentile(dbs, 99.7)
        return (np.clip((dbs - lo) / (hi - lo + 1e-9), 0, 1) * 255).astype(np.uint8)
    H = np.stack([E[:, int(i * step): int((i + 1) * step) + 1].mean(1) for i in range(nf)], 1)
    heard = to_u8(10 * np.log10(H + 1e-10))
    sent = np.zeros((88, nf), np.uint8)
    for n in notes:
        a = int((n["s"] - start) / hop); b = int((sounding_until(n, ped) - start) / hop) + 1
        k = n["p"] - 21
        if 0 <= k < 88 and b > 0 and a < nf: sent[k, max(0, a):min(nf, b)] = max(60, n["v"] * 2)
    exp = None
    if ref is not None and "cqt" in ref:
        rh = ref["cqt_hop"]; G = ref["cqt"].astype(np.float32)
        cols = [G[:, min(G.shape[1] - 1, int((start + i * hop) / rh))] for i in range(nf)]
        exp = to_u8(np.stack(cols, 1))
    b64 = lambda X: base64.b64encode(np.ascontiguousarray(X.T).tobytes()).decode()   # row = one time step
    return dict(hop=hop, frames=nf, keys=88, start=round(start, 3), heard=b64(heard), sent=b64(sent),
                expected=b64(exp) if exp is not None else None)


# ------------------------------------------------------------------------------ the check
def analyse(rec, midi, name="song", hint=None, ref_path=None, vol=None, floor=None):
    import librosa
    notes, ped, song_len = read_midi(midi)
    rec = rec.astype(np.float32); rec = rec / (np.abs(rec).max() + 1e-9)
    dur = len(rec) / SR
    start, conf = robust_align(rec, notes, song_len, hint)
    if start < 0:                                       # recording began before the song: drop that lead-in
        rec = rec[int(round(-start * SR)):]; start = 0.0; dur = len(rec) / SR
    rec_on = librosa.onset.onset_detect(y=rec, sr=SR, hop_length=HOP, units="time", backtrack=False, delta=0.05) + start
    seg = [n for n in notes if start - 0.5 <= n["s"] < start + dur]
    mel = melody_line(seg, ped)
    E = note_energy(rec); nf = E.shape[1]
    C_rec = chroma(rec); C_sent = roll_chroma(seg, ped, start, C_rec.shape[1])
    ref = load_ref(ref_path)
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
    # ------------------------------------------------ note-by-note (precise)
    mel_ids = set()
    for m in mel:
        around = [x for x in seg if x is not m and abs(x["s"] - m["s"]) <= 0.06]
        if not around or m["v"] >= max(x["v"] for x in around) + 10:
            mel_ids.add(next(i for i, x in enumerate(seg) if x is m))
    S = stft_mag(rec)
    first = note_by_note(E, seg, ped, start, mel_ids, S)
    errs0 = [r["err_ms"] for r in first if r["err_ms"] is not None]
    latency_ms = float(np.median(errs0)) if errs0 else 0.0     # constant delay (MIDI -> hammer -> mic): not an error
    nb = note_by_note(E, seg, ped, start, mel_ids, S, offset=latency_ms / 1000)
    vs_orig, orig_agree = against_original(E, ref, start, dur)
    sections = section_timing(rec, seg, start)
    issues = []
    for s_ in sections:
        if abs(s_["drift_ms"]) > 20:
            issues.append(dict(t=s_["t"], kind="timing (stretch)", text=f"this 2 s stretch runs {abs(s_['drift_ms']):.0f} ms "
                               f"{'late' if s_['drift_ms'] > 0 else 'early'} compared with the rest ({s_['notes']} notes)"))
    # do soft notes fire later than loud ones? (median timing of confidently-timed notes by velocity)
    timed_v = [(r["v"], r["err_ms"]) for r in nb if r["err_ms"] is not None]
    vel_lag = None
    if len(timed_v) >= 20:
        tv = np.array(timed_v); soft, loud = tv[tv[:, 0] < np.median(tv[:, 0])], tv[tv[:, 0] >= np.median(tv[:, 0])]
        if len(soft) >= 8 and len(loud) >= 8:
            vel_lag = round(float(np.median(soft[:, 1]) - np.median(loud[:, 1])), 1)
    for r in nb:
        nm, t = key_name(r["p"]), r["s"]
        if r["heard"] is False:
            issues.append(dict(t=round(t, 2), kind="not heard", text=f"{'melody ' if r['melody'] else ''}{nm} didn't sound (sent at velocity {r['v']})"))
        # (single-note timing stays in the data/visual only: in dense chords it isn't reliable enough to list)
        if r.get("over_backing_db") is not None and r["over_backing_db"] < 0:
            issues.append(dict(t=round(t, 2), kind="melody buried",
                               text=f"melody {nm} is {-r['over_backing_db']:.0f} dB quieter than the backing {r['rival']}"))
    for x in vs_orig:
        if x["kind"] == "missing":
            issues.append(dict(t=x["t0"], kind="missing vs song", text=f"the song has {x['pc']} here ({x['t1'] - x['t0']:.1f}s) but the piano doesn't"))
        else:
            culprits = sorted({key_name(n["p"]) for n in seg if NOTE_NAMES[n["p"] % 12] == x["pc"]
                               and n["s"] < x["t1"] and sounding_until(n, ped) > x["t0"]})
            issues.append(dict(t=x["t0"], kind="wrong vs song", text=f"piano plays {x['pc']} ({x['t1'] - x['t0']:.1f}s) that the song doesn't have here"
                               + (f" - sent {', '.join(culprits)}" if culprits else " (not sent: ringing/sympathetic)")))
    issues.sort(key=lambda x: x["t"])
    for x in issues: x["time"] = f"{int(x['t'] // 60)}:{x['t'] % 60:05.2f}"
    heard_n = [r for r in nb if r["heard"]]
    judged = [r for r in nb if r["heard"] is not None]
    timed = [r for r in heard_n if r["err_ms"] is not None]
    errs = np.array([abs(r["err_ms"]) for r in timed]) if timed else np.array([np.nan])
    mel_r = [r for r in nb if r.get("over_backing_db") is not None]
    precise = dict(notes_checked=len(nb), notes_heard=round(len(heard_n) / max(1, len(judged)), 3),
                   notes_unclear=sum(1 for r in nb if r["heard"] is None), latency_ms=round(latency_ms, 1),
                   soft_notes_lag_ms=vel_lag,
                   stretch_timing_spread_ms=round(float(np.std([s_["drift_ms"] for s_ in sections])), 1) if sections else None,
                   timing_median_ms=round(float(np.nanmedian(errs)), 1), timing_p90_ms=round(float(np.nanpercentile(errs, 90)), 1),
                   melody_notes_on_top=round(sum(r["over_backing_db"] >= 0 for r in mel_r) / max(1, len(mel_r)), 3) if mel_r else None,
                   pitch_agreement_with_song=None if orig_agree is None else round(orig_agree, 3))
    viz = viz_payload(E, ref, seg, ped, start, dur)

    good = [w for w in windows if not w.get("silent")]
    summary = dict(
        song=name, recorded_seconds=round(dur, 1), starts_at=fmt(start), alignment_confidence=round(conf, 1),
        alignment_ok=conf > 6,
        melody_over_backing_db=med([w["melody_over_backing_db"] for w in good]),
        timing_ms=med([w["timing_ms"] for w in good]), heard_on_time=med([w["heard_on_time"] for w in good]),
        sounds_like_sent=med([w["sounds_like_sent"] for w in good]), sounds_like_song=med([w["sounds_like_song"] for w in good]),
        jukebox_volume=vol, jukebox_softest=floor, problem_sections=len(problems), checked_sections=len(good), **precise)
    return dict(summary=summary, problems=problems, windows=windows, issues=issues, notes=nb, viz=viz, sections=sections)


def load_ref(path):
    if not path or not Path(path).exists(): return None
    d = np.load(path)
    ref = dict(chroma=d["chroma"], hop=float(d["hop"]))
    if "cqt" in d: ref.update(cqt=d["cqt"], cqt_hop=float(d["cqt_hop"]))
    return ref


def cqt88_db(y, hop_s=0.02):
    """The original's energy at each of the 88 keys (dB, float16) for the 'should sound like' picture."""
    import librosa
    hop = int(hop_s * SR)
    C = np.abs(librosa.cqt(y, sr=SR, hop_length=hop, fmin=librosa.midi_to_hz(21) / 2 ** (1 / 36),
                           n_bins=88 * 3, bins_per_octave=36)) ** 2
    return (10 * np.log10(C.reshape(88, 3, -1).max(1) + 1e-10)).astype(np.float16)


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
    if s.get("notes_checked"):
        L.append(f"  Note by note: {s['notes_checked']} notes checked, {s['notes_heard']:.0%} sounded, timing median "
                 f"{s['timing_median_ms']} ms (90% within {s['timing_p90_ms']} ms)"
                 + (f", melody on top for {s['melody_notes_on_top']:.0%} of tune notes" if s.get("melody_notes_on_top") is not None else "")
                 + (f", pitch agreement with the song {s['pitch_agreement_with_song']:.0%}" if s.get("pitch_agreement_with_song") is not None else ""))
        L.append(f"  {len(r.get('issues', []))} precise issues:")
        for x in r.get("issues", []):
            L.append(f"    {x['time']}  [{x['kind']}] {x['text']}")
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
    np.savez_compressed(REFS / f"{base_name(name)}.npz", chroma=chroma(original_audio_16k).astype(np.float32), hop=1024 / SR,
                        cqt=cqt88_db(original_audio_16k), cqt_hop=0.02)


def reference_for_browser(name, hop=0.04):
    """The whole song's 'should sound like' picture for the live view (88 keys x time, 0..255)."""
    import base64
    ref = load_ref(ref_for(name))
    if ref is None or "cqt" not in ref: return None
    G = ref["cqt"].astype(np.float32); step = max(1, int(round(hop / ref["cqt_hop"])))
    n = G.shape[1] // step
    G = G[:, : n * step].reshape(88, n, step).mean(2)
    lo, hi = np.percentile(G, 50), np.percentile(G, 99.7)
    u8 = (np.clip((G - lo) / (hi - lo + 1e-9), 0, 1) * 255).astype(np.uint8)
    return dict(hop=round(ref["cqt_hop"] * step, 4), frames=n, keys=88, data=base64.b64encode(np.ascontiguousarray(u8.T).tobytes()).decode())


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
