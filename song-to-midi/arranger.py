"""Piano arranger: turns any song into a piano arrangement for a player piano, on the first try.

This is everything learned from the calibration runs on 'Dancing in the Moonlight' (arranged v1..v18,
12 real-piano checks) - see docs/CALIBRATION.md for the why behind every rule. In short:

  melody   the singer's pitch track (not the piano model's reading of the voice), notes start on the
           real syllables and end when the singer stops, short wobbles/blips merged, notes the song
           doesn't contain dropped, small gaps joined so it sounds sung
  bass     the real bass-guitar line (walking/passing notes), one strike per pluck
  keys     the band's keys/guitar part (piano-model transcription of the instruments), judged against
           the INSTRUMENTS (not the vocal-heavy mix) so the chorus doesn't empty out, always kept at
           least 5 semitones under the tune
  groove   every beat has something: bass on 1 & 3, a chord on 2 & 4 where the band leaves a gap;
           crowded beats are trimmed
  sections keys-only intro/outro played as transcribed; choruses found automatically (repeated +
           loudest + sung) get a fuller part, the tune in octaves and bass octaves, and swell in/out;
           light instrumental breaks are thinned to their high 'twinkle' figure
  piano    every note fitted to the player piano (piano_profile.json): loud enough to sound, long
           enough for the hammer, time for keys to reset, soft notes sent early, weak keys firmer,
           never too many keys ringing, pedal changed at every tune note and bass note
"""
import json
import time
from pathlib import Path

import numpy as np

SR = 16000
HERE = Path(__file__).resolve().parent
PROFILE = HERE / "piano_profile.json"
LOCKS = HERE / "locks"
NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


# ============================================================================ piano calibration
class Piano:
    def __init__(self, path=PROFILE):
        p = json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {}
        self.p = p
        self.vol = p.get("jukebox_volume", 0.6)
        self.floor = p.get("jukebox_softest", 35)
        self.L = dict(melody_verse=73, melody_chorus=75, melody_octave_double=60, melody_light_break=60, bass=56,
                      bass_chorus=60, chords=52, chords_chorus=58, keys_part=58, light_figure=52, under_melody_cap=52,
                      minimum=45)
        self.L.update({k: v for k, v in p.get("levels", {}).items() if not k.startswith("_")})
        self.weak = set(p.get("weak_keys", []))
        self.weak_min = p.get("weak_key_minimum", 58)
        self.weak_over = {int(k): v for k, v in p.get("weak_key_overrides", {}).items()}
        self.min_note = p.get("min_note_seconds", 0.15)
        self.reset = p.get("key_reset_seconds", 0.12)
        self.merge = p.get("merge_same_key_within", 0.2)
        self.mel_repeat = p.get("melody_repeat_within", 0.15)
        self.lag = p.get("soft_note_lag", [[45, 0.027], [60, 0.020]])
        self.max_ring = p.get("max_keys_ringing", 12)
        pd = p.get("pedal", {})
        self.ped_min, self.ped_max = pd.get("min_press", 0.12), pd.get("max_span", 4.0)

    def vel(self, level):
        """MIDI velocity that lands at `level` on the piano (after the jukebox's volume)."""
        return int(np.clip(np.ceil(level / self.vol), 1, 127))

    def played(self, v):
        return max(self.floor, min(127, round(v * self.vol)))

    def key_min(self, p):
        return self.weak_over.get(p, self.weak_min) if p in self.weak else self.L["minimum"]

    def lag_for(self, v):
        pv = self.played(v)
        for upto, sec in self.lag:
            if pv <= upto: return sec
        return 0.0


# ============================================================================ analysis
def _merge_same_key(notes, gap):
    notes = sorted(notes, key=lambda n: n["s"]); last, out = {}, []
    for n in notes:
        p = last.get(n["p"])
        if p is not None and n["s"] - p["e"] < gap:
            p["e"] = max(p["e"], n["e"]); p["v"] = max(p["v"], n["v"]); continue
        n = dict(n); last[n["p"]] = n; out.append(n)
    return out


def _pitch_line(f0, voiced, rms, hop, smooth, min_len, jump, legato, lo, hi):
    """A line of notes from a pitch track: round to keys, median-smooth vibrato, new note only on a real move."""
    import librosa
    import scipy.ndimage as ndi
    midi = np.where(voiced & (f0 > 0), librosa.hz_to_midi(np.where(f0 > 0, f0, 1)), np.nan)
    k = max(1, int(smooth / hop)) | 1
    med = ndi.median_filter(np.where(np.isnan(midi), -1, midi), size=k, mode="nearest")
    med = np.where(ndi.median_filter((~np.isnan(midi)).astype(float), size=k) > 0.5, med, -1)
    notes, cur = [], None
    for i, m in enumerate(med):
        if cur and m > 0 and abs(m - cur["p"]) < jump:
            cur["e"] = (i + 1) * hop; cur["w"].append(rms[min(i, len(rms) - 1)]); continue
        if cur: notes.append(cur); cur = None
        if m > 0: cur = dict(s=i * hop, e=(i + 1) * hop, p=int(round(m)), w=[rms[min(i, len(rms) - 1)]])
    if cur: notes.append(cur)
    notes = [n for n in notes if n["e"] - n["s"] >= min_len and lo <= n["p"] <= hi]
    for n in notes: n["v"] = float(np.mean(n.pop("w")))
    notes = _merge_same_key(notes, 0.08)
    for a, b in zip(notes, notes[1:]):
        if 0 < b["s"] - a["e"] < legato: a["e"] = b["s"]
    return notes


class Song:
    """Everything the arranger needs to know about the song, computed once."""

    def __init__(self, stems, other_out, status=print):
        import librosa
        from piano_transcription_inference.utilities import RegressionPostProcessor
        t0 = time.time()
        self.stems = stems
        self.dur = len(stems["original"]) / SR
        y = stems["original"]
        status("Finding the beat...")
        _, beats = librosa.beat.beat_track(y=y, sr=SR, hop_length=512, units="time")
        self.beats = np.asarray(beats, float)
        if len(self.beats) < 8:                           # no clear beat: a steady grid at 100 bpm
            self.beats = np.arange(0, self.dur, 0.6)
        self.bl = float(np.median(np.diff(self.beats)))
        # the band's keys/guitar part, as the piano model heard it (with its own pedal)
        pp = RegressionPostProcessor(100, 88, 0.2, 0.3, 0.05, 0.2)
        notes, pedals = pp.output_dict_to_midi_events(other_out)
        self.keys_raw = [dict(s=n["onset_time"] - 0.5, e=n["offset_time"] - 0.5, p=int(n["midi_note"]), v=int(n["velocity"]))
                         for n in notes if n["offset_time"] - 0.5 > 0]
        self.keys_pedal = [(p["onset_time"] - 0.5, p["offset_time"] - 0.5) for p in (pedals or [])]
        status("Following the singer...")
        v = stems["vocals"]
        f0, vc, _ = librosa.pyin(v, fmin=80, fmax=1000, sr=SR, hop_length=160, frame_length=1024)
        self.f0, self.vc = np.nan_to_num(f0), vc
        self.vrms = librosa.feature.rms(y=v, frame_length=1024, hop_length=160)[0]
        env = librosa.onset.onset_strength(y=v, sr=SR, hop_length=160)
        self.sylls = librosa.onset.onset_detect(onset_envelope=env, sr=SR, hop_length=160, units="time", backtrack=True, delta=0.2, wait=8)
        n = min(len(self.vrms), len(self.vc))
        self.singing = (self.vrms[:n] > 0.12 * np.percentile(self.vrms, 95)) & self.vc[:n]
        status("Following the bass...")
        bf0, bvc, _ = librosa.pyin(stems["bass"], fmin=30, fmax=300, sr=SR, hop_length=320, frame_length=4096)
        self.bf0, self.bvc = np.nan_to_num(bf0), bvc
        self.brms = librosa.feature.rms(y=stems["bass"], frame_length=1024, hop_length=320)[0]
        benv = librosa.onset.onset_strength(y=stems["bass"], sr=SR, hop_length=160)
        self.bass_on = librosa.onset.onset_detect(onset_envelope=benv, sr=SR, hop_length=160, units="time", delta=0.07, wait=5)
        status("Reading the harmony...")
        self.song_pc = self._pc(stems["vocals"] + stems["other"] + stems["bass"])       # what the song sounds like
        self.inst_pc = self._pc(stems["other"] + 0.5 * stems["bass"])                  # what the INSTRUMENTS play
        fr = librosa.time_to_frames(self.beats, sr=SR, hop_length=512)
        self.beat_chroma = librosa.util.sync(librosa.feature.chroma_cqt(y=stems["other"] + stems["bass"], sr=SR, hop_length=512), fr, aggregate=np.mean)[:, 1:len(self.beats)]
        self.beat_bass = librosa.util.sync(librosa.feature.chroma_cqt(y=stems["bass"], sr=SR, hop_length=512), fr, aggregate=np.mean)[:, 1:len(self.beats)]
        self._sections(fr)
        status(f"  analysed in {time.time() - t0:.0f}s: {60 / self.bl:.0f} bpm, {len(self.choruses)} choruses, "
               f"{len(self.light)} light break(s), keys-only intro {self.intro_end:.1f}s")

    def _pc(self, y, hop=0.1):
        import librosa
        import scipy.ndimage as ndi
        C = np.abs(librosa.cqt(y, sr=SR, hop_length=int(hop * SR), fmin=librosa.midi_to_hz(21) / 2 ** (1 / 36), n_bins=264, bins_per_octave=36)) ** 2
        C = C.reshape(88, 3, -1).max(1); pc = np.zeros((12, C.shape[1]))
        for k in range(88): pc[(k + 21) % 12] += C[k]
        loud = pc.sum(0) > 0.02 * np.percentile(pc.sum(0), 95)
        return ndi.median_filter(pc / (pc.max(0, keepdims=True) + 1e-12), size=(1, 3)), loud

    def strength(self, n, which="song", span=0.3):
        pc, _ = self.song_pc if which == "song" else self.inst_pc
        a = int(n["s"] / 0.1); b = max(a + 1, int(min(n["e"], n["s"] + span) / 0.1))
        a, b = min(max(a, 0), pc.shape[1] - 1), min(b, pc.shape[1])
        return float(pc[n["p"] % 12, a:b].mean()) if b > a else 1.0

    def _sections(self, fr):
        import librosa
        s, B = self.stems, self.beats
        lvl = lambda y: (lambda r: librosa.util.sync(r[None], fr, aggregate=np.mean)[0][1:len(B)] / (np.percentile(r, 95) + 1e-9))(
            librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0])
        vo, ba, dr, ot = lvl(s["vocals"]), lvl(s["bass"]), lvl(s["drums"]), lvl(s["other"])
        nb = len(vo)
        # keys-only intro (and outro): no singing, bass or drums
        keys_only = (vo < 0.15) & (ba < 0.15) & (dr < 0.15)
        i = 0
        while i < nb and keys_only[i]: i += 1
        self.intro_end = float(B[i]) if i >= 6 else 0.0
        j = nb - 1
        while j > 0 and keys_only[j]: j -= 1
        self.outro_keys = float(B[j + 1]) if nb - 1 - j >= 6 else self.dur + 1
        # choruses: 2-bar patterns that repeat elsewhere + loudest + sung
        C = self.beat_chroma / (np.linalg.norm(self.beat_chroma, axis=0) + 1e-9)
        M = np.zeros((12, nb)); hop = 0.01
        for k in range(nb):
            a, b = int(B[k] / hop), int(B[k + 1] / hop)
            seg = self.f0[a:b][self.vc[a:b] & (self.f0[a:b] > 0)]
            if len(seg): M[np.round(librosa.hz_to_midi(seg)).astype(int) % 12, k] += 1
        F = np.vstack([C, M / (np.linalg.norm(M, axis=0) + 1e-9)])
        W = 8; n = F.shape[1] - W
        self.choruses = []
        if n > 40:
            X = np.stack([F[:, k:k + W].ravel() for k in range(n)]); X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
            S = X @ X.T
            rep = np.array([np.sort(S[k][np.abs(np.arange(n) - k) > 16])[-3:].mean() for k in range(n)])
            loud = np.array([(vo + ba + ot)[k:k + W].mean() for k in range(n)]); voc = np.array([vo[k:k + W].mean() for k in range(n)])
            z = lambda a: (a - a.mean()) / (a.std() + 1e-9)
            score = z(rep) + z(loud) + 0.5 * z(voc); on = score > np.percentile(score, 70)
            k = 0
            while k < n:
                if on[k]:
                    m = k
                    while m < n and on[m]: m += 1
                    if m - k >= 6: self.choruses.append([float(B[k]), float(B[min(m + W - 1, len(B) - 1)])])
                    k = m
                else: k += 1
            merged = []
            for a, b in self.choruses:                    # join overlapping chorus windows
                if merged and a <= merged[-1][1] + 2 * self.bl: merged[-1][1] = max(merged[-1][1], b)
                else: merged.append([a, b])
            self.choruses = [tuple(c) for c in merged]
        # light instrumental breaks: barely any singing or bass, instruments still going (>= 3 bars)
        import scipy.ndimage as ndi
        light = (vo < 0.35) & (ba < 0.5) & (ot > 0.3) & ~keys_only
        light = ndi.median_filter(light.astype(float), size=5) > 0.5          # ignore single-beat blips
        self.light, k = [], 0
        while k < nb:
            if light[k] and B[k] > self.intro_end + 4:
                m = k
                while m < nb and light[m]: m += 1
                if m - k >= 8: self.light.append((float(B[k]), float(B[min(m, len(B) - 1)])))
                k = m
            else: k += 1
        last_ch = max([b for a, b in self.choruses], default=self.dur - 20)
        self.outro = max(last_ch, self.dur - 15)
        # which beats are 1 & 3 (bass + kick), and where bars start
        import librosa as lr
        low = lr.feature.rms(y=s["bass"] + lr.effects.preemphasis(s["drums"], coef=-0.9), hop_length=160)[0]
        bi = [min(len(low) - 1, int(b * 100)) for b in B]
        par = int(np.argmax([np.mean([low[bi[k]] for k in range(p, len(B), 2)]) for p in (0, 1)]))
        self.first_strong = next((k for k in range(len(B)) if B[k] >= self.intro_end + 0.05 and k % 2 == par), 0)
        bp = int(np.argmax([np.mean([low[bi[k]] for k in range(self.first_strong + 2 * q, len(B), 4)] or [0]) for q in (0, 1)]))
        self.first_bar = self.first_strong + 2 * bp

    def in_chorus(self, t): return any(a <= t < b for a, b in self.choruses)
    def in_light(self, t): return any(a <= t < b for a, b in self.light)


# ============================================================================ the parts
def melody(S, P):
    """The singer's tune: syllable-accurate starts, ends when the singer stops, no blips or unsupported notes."""
    import librosa
    import scipy.ndimage as ndi
    hop = 0.01; n = min(len(S.f0), len(S.singing))
    midi = np.where(S.vc[:n] & (S.f0[:n] > 0), librosa.hz_to_midi(np.where(S.f0[:n] > 0, S.f0[:n], 1)), np.nan)
    k = int(0.1 / hop) | 1
    med = ndi.median_filter(np.where(np.isnan(midi), -1, midi), size=k, mode="nearest")
    on = S.singing[:n] & (ndi.median_filter((~np.isnan(midi)).astype(float), size=k) > 0.5)
    notes, cur = [], None
    for i in range(n):
        m = med[i] if on[i] and med[i] > 0 else None
        if cur and m is not None and abs(m - cur["p"]) < 0.75:
            cur["e"] = (i + 1) * hop; cur["w"].append(S.vrms[i]); continue
        if cur: notes.append(cur); cur = None
        if m is not None: cur = dict(s=i * hop, e=(i + 1) * hop, p=int(round(m)), w=[S.vrms[i]])
    if cur: notes.append(cur)
    notes = [x for x in notes if x["e"] - x["s"] >= 0.05 and 48 <= x["p"] <= 84]
    for x in notes:                                     # start on the real syllable (consonants come before pitch)
        j = np.searchsorted(S.sylls, x["s"] + 0.03) - 1
        if j >= 0 and x["s"] - 0.15 <= S.sylls[j] <= x["s"] + 0.03: x["s"] = float(S.sylls[j])
    out = []
    for x in notes:                                     # same pitch, new clear syllable -> strike again
        s = x["s"]
        for c in S.sylls[np.searchsorted(S.sylls, x["s"] + 0.12): np.searchsorted(S.sylls, x["e"] - 0.12)]:
            out.append(dict(x, s=s, e=c - 0.02)); s = float(c)
        out.append(dict(x, s=s))
    notes = sorted(out, key=lambda x: x["s"])
    for a, b in zip(notes, notes[1:]):
        if a["e"] > b["s"]: a["e"] = b["s"] - 0.01
    for x in notes: x.pop("w", None)
    notes = [x for x in notes if x["e"] - x["s"] > 0.04]
    ch = True                                           # merge one-off pitch blips into a neighbour
    while ch:
        ch = False
        for i in range(1, len(notes) - 1):
            x, a, b = notes[i], notes[i - 1], notes[i + 1]
            if x["e"] - x["s"] < 0.1 and abs(x["p"] - a["p"]) > 2 and abs(x["p"] - b["p"]) > 2 and x["s"] - a["e"] < 0.05:
                a["e"] = x["e"]; del notes[i]; ch = True; break
    kept = []                                           # notes the song doesn't contain at all: move or drop
    for x in notes:
        if x["s"] < S.intro_end: continue
        if S.strength(x) >= 0.15: kept.append(x); continue
        best = next((x["p"] + d for d in (1, -1, 2, -2) if S.strength(dict(x, p=x["p"] + d)) >= 0.4), None)
        if best is not None: kept.append(dict(x, p=int(best)))
        elif S.strength(x) < 0.06 and x["e"] - x["s"] < 0.25: continue
        else: kept.append(x)
    late = S.dur * 0.85
    for a, b in zip(kept, kept[1:]):                    # join small gaps so it sounds sung
        gap = b["s"] - a["e"]
        if 0 < gap <= (0.30 if a["s"] >= late else 0.20): a["e"] = b["s"] - 0.02
    for x in kept:
        x["role"] = "melody"
        lvl = P.L["melody_light_break"] if S.in_light(x["s"]) else (P.L["melody_chorus"] if S.in_chorus(x["s"]) else P.L["melody_verse"])
        x["v"] = P.vel(lvl)
    return kept


def bass_line(S, P):
    line = _pitch_line(S.bf0, S.bvc, S.brms, 0.02, 0.08, 0.06, 0.7, 0.15, 28, 55)
    ons = np.sort(S.bass_on); out = []
    for x in line:                                      # one strike per pluck
        while x["p"] < 31: x["p"] += 12
        s = x["s"]
        for c in ons[np.searchsorted(ons, x["s"] + 0.07): np.searchsorted(ons, x["e"] - 0.07)]:
            if c - s >= 0.07: out.append(dict(x, s=s, e=c - 0.015)); s = c
        out.append(dict(x, s=s))
    return [dict(x, role="bass", v=P.vel(P.L["bass_chorus"] if S.in_chorus(x["s"]) else P.L["bass"]))
            for x in out if x["s"] >= S.intro_end and S.strength(x) >= 0.08]


def keys_part(S, P, mel):
    """The band's keys/guitar part under the tune: only what the instruments really play, >= 5 semitones below."""
    ms = sorted(mel, key=lambda m: m["s"]); st = np.array([m["s"] for m in ms]); out = []
    for x in S.keys_raw:
        if x["s"] < S.intro_end or x["e"] - x["s"] < 0.05 or S.in_light(x["s"]): continue
        if S.strength(x, "inst") < 0.35: continue
        k = np.searchsorted(st, x["s"] + 0.1, "right") - 1
        mp = ms[k]["p"] if 0 <= k < len(ms) and ms[k]["s"] - 0.1 <= x["s"] < ms[k]["e"] + 0.05 else None
        p = x["p"]; top = (mp - 5) if mp else 72
        while p > top and p - 12 >= 43: p -= 12
        while p < 46: p += 12
        if p > top: continue
        out.append(dict(s=x["s"], e=x["e"], p=int(p), role="keys",
                        v=P.vel(P.L["keys_part"] if S.in_chorus(x["s"]) else P.L["chords"])))
    return out


def harmony(S, i):
    c = S.beat_chroma[:, i:i + 2].mean(1); b = S.beat_bass[:, i:i + 2].mean(1)
    root = int(np.argmax(b)) if b.max() > 1.5 * (b.mean() + 1e-9) else int(np.argmax(c))
    pcs = [int(p) for p in np.argsort(-c) if c[p] >= 0.45 * c.max()][:4]
    if root not in pcs: pcs = [root] + pcs[:3]
    t0, t1 = S.beats[i], S.beats[min(len(S.beats) - 1, i + 2)]
    return root, [p for p in pcs if p == root or S.strength(dict(s=t0, e=t1, p=p), span=t1 - t0) >= 0.2] or [root]


def _voice(pcs, top, prev):
    centre = float(np.mean(prev)) if prev else 54
    for lo in (46, 41):
        out = sorted({min([p for p in range(lo, top + 1) if p % 12 == pc], key=lambda p: abs(p - centre))
                      for pc in pcs if any(p % 12 == pc for p in range(lo, top + 1))})
        if len(out) >= 2 or lo == 41: break
    return out or [40 + (pcs[0] - 40) % 12]


def groove_and_sections(S, P, mel, parts):
    """Steady pulse (fill empty beats), chorus octaves, light-break figure, final bars."""
    B, bl = S.beats, S.bl
    ms = sorted(mel, key=lambda m: m["s"]); st = np.array([m["s"] for m in ms])
    def mel_low(t, d):
        lo = None
        for m in ms[max(0, np.searchsorted(st, t - 2)): np.searchsorted(st, t + d)]:
            if m["s"] < t + d and m["e"] > t: lo = m["p"] if lo is None else min(lo, m["p"])
        return lo
    beat_of = lambda t: int(np.searchsorted(B, t + 0.08) - 1)
    per = {}
    for x in parts:
        per.setdefault(beat_of(x["s"]), []).append(x)
    keep = []
    for k, L in per.items():                            # crowded beats: bass first, then loudest; max 4
        keep += sorted(L, key=lambda x: (x["p"] >= 48, -x["v"]))[:4]
    out = keep; prev = [52, 55, 59]; end_groove = S.dur - 10
    for i in range(S.first_strong, len(B) - 1):
        t = B[i]; nxt = B[i + 1]
        if t >= min(end_groove, S.outro_keys): break
        pos = (i - S.first_bar) % 4; root, pcs = harmony(S, i - (pos % 2)); chorus = S.in_chorus(t)
        if S.in_light(t):
            if pos == 0: out.append(dict(s=t, e=t + 4 * bl - 0.12, p=36 + (root - 36) % 12, role="bass", v=P.vel(46)))
            continue
        if per.get(i): continue
        if pos in (0, 2):
            out.append(dict(s=t, e=nxt + bl - 0.12, p=36 + (root - 36) % 12, role="bass", v=P.vel(P.L["bass_chorus"] if chorus else P.L["bass"])))
        else:
            ml = mel_low(t, bl); vs = _voice(pcs, min((ml - 5) if ml else 64, 64), prev); prev = vs
            out += [dict(s=t + 0.01, e=nxt - 0.12, p=p, role="chord", v=P.vel(P.L["chords_chorus"] if chorus else P.L["chords"])) for p in vs]
    for i in range(S.first_bar, len(B) - 1, 4):         # chorus: bass octave on each bar's first beat
        t = B[i]
        if not S.in_chorus(t): continue
        bs = [x for x in out if x["role"] == "bass" and abs(x["s"] - t) < 0.12]
        if bs and bs[0]["p"] - 12 >= 28: out.append(dict(bs[0], p=bs[0]["p"] - 12, role="bass"))
    for m in mel:                                       # chorus: the tune in octaves (held notes)
        if S.in_chorus(m["s"]) and m["p"] + 12 <= 96 and m["e"] - m["s"] >= 0.25:
            out.append(dict(s=m["s"] + 0.005, e=m["e"], p=m["p"] + 12, role="double", v=P.vel(P.L["melody_octave_double"])))
    for a, b in S.light:                                # light break: just the high twinkle figure
        fig = [x for x in S.keys_raw if a <= x["s"] < b and x["p"] >= 84 and x["e"] - x["s"] >= 0.05]
        if not fig: fig = [x for x in S.keys_raw if a <= x["s"] < b and x["p"] >= 72 and x["e"] - x["s"] >= 0.05]
        out += [dict(s=x["s"], e=max(x["e"], x["s"] + 0.15), p=x["p"], role="figure", v=P.vel(P.L["light_figure"])) for x in fig]
    for i in range(len(B) - 1):                         # final bars: one held chord per bar
        t = B[i]
        if t < end_groove or (i - S.first_bar) % 4 or t >= S.outro_keys: continue
        root, pcs = harmony(S, i); prev = _voice(pcs, 64, prev)
        out.append(dict(s=t, e=t + 4 * bl - 0.12, p=36 + (root - 36) % 12, role="bass", v=P.vel(50)))
        out += [dict(s=t + 0.02, e=t + 4 * bl - 0.12, p=p, role="chord", v=P.vel(48)) for p in prev]
    return out


def keys_only_parts(S, P):
    """Keys-only intro/outro: play the band's keys part as transcribed (that's what sounded beautiful)."""
    out, ped = [], []
    for a, b in ((0.0, S.intro_end), (S.outro_keys, S.dur + 1)):
        if b - a < 3: continue
        for x in S.keys_raw:
            if a <= x["s"] < b: out.append(dict(x, role="intro", v=max(x["v"], P.vel(P.L["minimum"]))))
        ped += [(max(a, s), min(b, e)) for s, e in S.keys_pedal if e > a and s < b and min(b, e) - max(a, s) > 0.1]
    return out, ped


# ============================================================================ fitting it to the piano
def dynamics(S, P, notes):
    """Smooth section levels: fade the groove in after the intro, swell into choruses, settle after, taper the end."""
    bar = 4 * S.bl; t0 = S.beats[S.first_strong] if len(S.beats) else 0
    def level(t):
        L = 1.0
        for a, b in S.choruses:
            if a - bar <= t < a: L = max(L, 1.0 + 0.12 * (t - (a - bar)) / bar)
            elif b <= t < b + bar: L = max(L, 1.12 - 0.12 * (t - b) / bar)
        if S.in_light(t): L = 0.75
        if t < t0 + 2 * bar: L *= 0.7 + 0.3 * max(0.0, (t - t0) / (2 * bar))
        if t >= S.dur - 12: L *= max(0.6, 1.0 - 0.4 * (t - (S.dur - 12)) / 12)
        return L
    for x in notes:
        if x["role"] in ("melody", "intro", "double", "figure"): continue
        x["v"] = P.vel(min(76, P.played(x["v"]) * level(x["s"])))


def make_room(S, P, notes):
    """Nothing tangled just under the tune; backing struck with a tune note follows it (melody lead) and softer."""
    mel = sorted([x for x in notes if x["role"] == "melody"], key=lambda m: m["s"]); st = np.array([m["s"] for m in mel])
    def at(t):
        k = np.searchsorted(st, t + 0.1, "right") - 1
        for j in (k, k - 1):
            if 0 <= j < len(mel) and mel[j]["s"] - 0.1 <= t < mel[j]["e"] + 0.05: return mel[j]
    out = []
    for x in notes:
        if x["role"] in ("melody", "intro", "double", "bass", "figure") or x["p"] < 48: out.append(x); continue
        m = at(x["s"])
        if m is not None:
            if x["p"] >= m["p"]: continue
            if m["p"] - x["p"] < 5:
                if x["p"] - 12 >= 43: x["p"] -= 12
                else: continue
            if abs(m["s"] - x["s"]) <= 0.06 and m["p"] - x["p"] <= 12:
                d = m["s"] + 0.035 - x["s"]; x["s"] += d; x["e"] += d
                x["v"] = min(x["v"], P.vel(P.L["under_melody_cap"]))
        out.append(x)
    return out


def fit_to_piano(P, notes, intro_end):
    """Loud enough to sound, long enough for the hammer, keys get time to reset, soft notes sent early."""
    for x in notes:
        if x["role"] != "melody": x["v"] = max(x["v"], P.vel(P.key_min(x["p"])))
        lag = P.lag_for(x["v"]); x["s"] = max(0.0, x["s"] - lag); x["e"] -= lag
    by = {}
    for x in sorted(notes, key=lambda x: x["s"]): by.setdefault(x["p"], []).append(x)
    out = []
    for p, seq in by.items():
        keep = []
        for x in seq:
            lim = P.mel_repeat if (x["role"] == "melody" and keep and keep[-1]["role"] == "melody") else P.merge
            if keep and x["s"] - keep[-1]["s"] < lim and x["s"] >= intro_end:
                keep[-1]["e"] = max(keep[-1]["e"], x["e"]); keep[-1]["v"] = max(keep[-1]["v"], x["v"]); continue
            keep.append(x)
        for i, x in enumerate(keep):
            nxt = keep[i + 1]["s"] if i + 1 < len(keep) else 1e9
            if x["s"] >= intro_end: x["e"] = max(x["e"], x["s"] + P.min_note)
            x["e"] = max(min(x["e"], nxt - P.reset), x["s"] + 0.03)
        out += keep
    mel = sorted([x for x in out if x["role"] == "melody"], key=lambda x: x["s"])
    for a, b in zip(mel, mel[1:]):                      # the tune stays one note at a time
        if a["e"] > b["s"] - 0.01: a["e"] = max(a["s"] + 0.08, b["s"] - 0.01)
    return out


def pedal(S, P, notes, intro_ped):
    t0 = S.intro_end
    ped = [(a, min(b, t0 - 0.02)) for a, b in intro_ped if a < t0 and min(b, t0 - 0.02) - a > 0.1]
    mel = [x for x in notes if x["role"] == "melody"]
    pts = sorted({round(x["s"], 3) for x in mel} | {round(x["e"], 3) for x in mel} |
                 {round(x["s"], 3) for x in notes if x["role"] == "bass"} | {round(t0, 3), round(S.dur, 3)})
    ped += [(a + 0.05, b - 0.02) for a, b in zip(pts, pts[1:])
            if a >= t0 and (b - 0.02) - (a + 0.05) >= P.ped_min and b - a <= P.ped_max]
    ped += [(a, b) for a, b in intro_ped if a >= S.outro_keys]
    return sorted(ped)


def cap_ringing(P, notes, ped, start):
    """Never more than max_keys_ringing at once: drop the softest keys-part notes first."""
    def rings(x):
        for a, b in ped:
            if a <= x["e"] < b: return b
        return x["e"]
    ends = {id(x): rings(x) for x in notes}
    dropped = 0
    for t in np.arange(start, max([x["e"] for x in notes] + [start]), 0.25):
        on = [x for x in notes if x["s"] <= t < ends[id(x)]]
        extra = len(on) - P.max_ring
        if extra <= 0: continue
        for x in sorted([x for x in on if x["role"] == "keys"], key=lambda x: x["v"])[:extra]:
            notes.remove(x); dropped += 1
    return dropped


# ============================================================================ entry point
def arrange(S, P=None, status=print, lock=None):
    P = P or Piano()
    mel = melody(S, P)
    intro, intro_ped = keys_only_parts(S, P)
    if lock:                                            # a hand-approved intro (locks/<song>.intro.json)
        intro = [dict(s=n["s"], e=n["e"], p=n["p"], v=n["v"], role="intro") for n in lock["notes"]]
        intro_ped = [tuple(p) for p in lock.get("pedal", [])]
        S.intro_end = max(S.intro_end, lock.get("until", 0))
        mel = [m for m in mel if m["s"] >= S.intro_end]
    bass = bass_line(S, P); keys = keys_part(S, P, mel)
    backing = groove_and_sections(S, P, mel, bass + keys)
    notes = intro + mel + backing
    dynamics(S, P, notes)
    notes = make_room(S, P, notes)
    notes = fit_to_piano(P, notes, S.intro_end)
    ped = pedal(S, P, notes, intro_ped)
    dropped = cap_ringing(P, notes, ped, S.intro_end)
    roles = {}
    for x in notes: roles[x["role"]] = roles.get(x["role"], 0) + 1
    status(f"Arranged: {len(notes)} notes ({', '.join(f'{k} {v}' for k, v in sorted(roles.items()))}), "
           f"{len(ped)} pedal presses{f', {dropped} dropped to avoid jumble' if dropped else ''}")
    return notes, ped


def write_midi(path, notes, ped):
    import mido
    mf = mido.MidiFile(ticks_per_beat=480); tr = mido.MidiTrack(); mf.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=500000))
    ev = []
    for n in notes:
        p = int(np.clip(n["p"], 21, 108))
        ev.append((max(0.0, n["s"]), 1, mido.Message("note_on", note=p, velocity=int(np.clip(n["v"], 1, 127)))))
        ev.append((max(0.0, n["e"]), 0, mido.Message("note_off", note=p, velocity=0)))
    for a, b in ped:
        ev.append((max(0.0, a), 2, mido.Message("control_change", control=64, value=127)))
        ev.append((max(0.0, b), -1, mido.Message("control_change", control=64, value=0)))
    ev = sorted(((int(round(t * 960)), pr, m) for t, pr, m in ev), key=lambda x: (x[0], x[1])); last = 0
    for tick, _, m in ev:
        tr.append(m.copy(time=tick - last)); last = tick
    mf.save(str(path))
