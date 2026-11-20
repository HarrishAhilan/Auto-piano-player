"""Song -> piano MIDI.

  python song2midi.py                    record from the mic, press Enter to stop
  python song2midi.py song.mp3           transcribe an audio file (cleaner than the mic)
  python song2midi.py --mode pop ...     Pop/Film mode: strip drums etc. first (see below)
  python song2midi.py --seconds 60       record for a fixed time instead of waiting for Enter

Modes
  piano  (default) best for songs that are already mostly piano
  pop    for pop / film songs: splits the song into vocals, drums, bass and
         "other" (keys, guitar, strings) with Demucs, throws the drums away,
         transcribes the rest and cleans up stray notes
         --parts vocals,other,bass   choose which parts become piano notes
                                     (e.g. --parts vocals for just the tune)

Output goes to the "output" folder next to this script. Drop the .mid into
Piano Jukebox -> My Music.
"""
import argparse
import contextlib
import io
import os
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import numpy as np

SR = 16000  # the transcription model works at 16 kHz mono
HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
PARTS = ("vocals", "other", "bass", "drums")


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


def record(seconds=None):
    """Returns (audio[channels, samples], samplerate)."""
    import sounddevice as sd

    dev = sd.query_devices(kind="input")
    rate = int(dev["default_samplerate"])
    print(f"Mic: {dev['name']}")
    chunks, level = [], [0.0]

    def cb(data, frames, t, status):
        chunks.append(data[:, 0].copy())
        level[0] = float(np.abs(data).max())

    input("Start the song on your phone, hold it near the mic, then press Enter to start recording...")
    print("Recording" + (f" for {seconds}s" if seconds else " - press Enter to stop") + "\n")
    start = time.time()
    with sd.InputStream(samplerate=rate, channels=1, dtype="float32", callback=cb):
        if os.name == "nt":
            import msvcrt
            while True:
                el = time.time() - start
                bar = "#" * int(min(level[0], 1.0) * 40)
                sys.stdout.write(f"\r  {el:6.1f}s  [{bar:<40}]")
                sys.stdout.flush()
                if seconds and el >= seconds:
                    break
                if msvcrt.kbhit() and msvcrt.getwch() in "\r\n":
                    break
                time.sleep(0.1)
        elif seconds:
            time.sleep(seconds)
        else:
            input()
    print("\n")
    if not chunks:
        sys.exit("Nothing was recorded - check the mic.")
    audio = np.concatenate(chunks)
    if np.abs(audio).max() < 0.01:
        print("Warning: the recording is very quiet. Turn the phone up or move it closer.")
    return audio[None, :], rate


def load_file(path):
    import librosa
    audio, rate = librosa.load(path, sr=None, mono=False)
    if audio.ndim == 1:
        audio = audio[None, :]
    return audio, rate


_models = {}
import threading
_model_lock = threading.RLock()  # the server may ask for a model from two threads at once


def demucs_model():
    with _model_lock:
        return _load_demucs()


def _load_demucs():
    if "demucs" not in _models:
        from demucs.pretrained import get_model
        with quiet():
            m = get_model("htdemucs")
        m.eval()
        _models["demucs"] = m
    return _models["demucs"]


def piano_model():
    with _model_lock:
        return _load_piano()


def _load_piano():
    if "piano" not in _models:
        import torch
        from piano_transcription_inference import PianoTranscription
        with quiet():
            _models["piano"] = PianoTranscription(
                device=torch.device("cuda" if torch.cuda.is_available() else "cpu"))
    return _models["piano"]


MODE_NAMES = {"piano": "Piano", "pop": "Pop/Film", "auto": "Auto"}
PART_NAMES = {"vocals": "Melody (vocals)", "other": "Chords & instruments", "bass": "Bass", "drums": "Drums"}


def analyse_stems(stems, sources, sr):
    """How much of the song each part is playing, and its share of the total energy."""
    win = sr  # 1-second windows
    frames = stems.shape[-1] // win
    if frames < 1:
        return {s: {"active": 1.0, "share": 0.25} for s in sources}
    mono = stems.mean(1)[:, : frames * win].reshape(len(sources), frames, win)  # [src, frame, sample]
    rms = np.sqrt((mono ** 2).mean(-1))                                          # [src, frame]
    loud = np.percentile(rms.sum(0), 95) + 1e-9   # reference: the loud parts of the whole song
    energy = (rms ** 2).sum(1)
    return {s: {"active": float((rms[i] > 0.08 * loud).mean()),
                "share": float(energy[i] / (energy.sum() + 1e-12))} for i, s in enumerate(sources)}


def auto_parts(info):
    """Pick what to turn into piano. Returns (parts or None for 'use the original audio', reason)."""
    v, o, b, d = (info[k] for k in ("vocals", "other", "bass", "drums"))
    # Mostly a keyboard/instrumental track with no real drums or singing: the untouched audio
    # transcribes best (separation only adds artifacts).
    if d["share"] < 0.03 and v["active"] < 0.10 and o["share"] > 0.7:
        return None, "mostly piano/keys with no drums or singing - using the original audio"
    parts, why = [], []
    if v["active"] >= 0.15:
        parts.append("vocals"); why.append(f"singing in {v['active']:.0%} of the song -> melody")
    if o["active"] >= 0.15:
        parts.append("other"); why.append(f"instruments in {o['active']:.0%} -> chords")
    if "other" not in parts or o["share"] < 0.10:
        if b["active"] >= 0.15:
            parts.append("bass"); why.append("little else carrying the harmony -> keeping bass")
    else:
        why.append("bass left out (it muddies the chords)")
    if not parts:
        parts, why = ["vocals", "other"], ["nothing stood out - using melody + chords"]
    why.append("drums removed")
    return parts, "; ".join(why)


@contextlib.contextmanager
def transcribe_progress(report):
    """Temporarily make the piano model report how many audio segments it has done."""
    import torch
    from piano_transcription_inference import inference
    from piano_transcription_inference.pytorch_utils import move_data_to_device
    original = inference.forward

    def forward(model, x, batch_size):
        out, device = {}, next(model.parameters()).device
        for i in range(0, len(x), batch_size):
            with torch.no_grad():
                model.eval()
                res = model(move_data_to_device(x[i:i + batch_size], device))
            for k, v in res.items():
                out.setdefault(k, []).append(v.data.cpu().numpy())
            report(min(1.0, (i + batch_size) / len(x)))
        return {k: np.concatenate(v, axis=0) for k, v in out.items()}

    inference.forward = forward
    try:
        yield
    finally:
        inference.forward = original


def separate(audio, rate, parts, status=print, progress=True, on_progress=None):
    """Split with Demucs and return the chosen parts mixed to mono at `rate`.
    parts may be "auto", in which case they're chosen from what the song contains.
    Returns (mono, rate, description)."""
    import librosa
    import torch
    from demucs.apply import apply_model

    status("Splitting the song into parts (Demucs)...")
    model = demucs_model()
    sr = model.samplerate
    wav = librosa.resample(audio, orig_sr=rate, target_sr=sr) if rate != sr else audio
    if wav.shape[0] == 1:
        wav = np.repeat(wav, 2, axis=0)
    wav = torch.from_numpy(np.ascontiguousarray(wav[:2], dtype=np.float32))
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    t0 = time.time()
    cb = None
    if on_progress:
        subs = getattr(model, "models", [model])
        seg = int(subs[0].samplerate * float(subs[0].segment))
        total = len(range(0, wav.shape[-1], int(0.75 * seg))) * len(subs)
        done = [0]

        def cb(d):
            if d.get("state") == "end":
                done[0] += 1
                on_progress("split", min(1.0, done[0] / total))
    device = "cuda" if torch.cuda.is_available() else "cpu"
    with torch.no_grad():
        stems = apply_model(model, ((wav - mean) / std)[None], device=device,
                            split=True, overlap=0.25, progress=progress and not on_progress, callback=cb)[0]
    stems = (stems * std + mean).numpy()
    status(f"  split in {time.time() - t0:.0f}s")
    if parts == "auto":
        parts, reason = auto_parts(analyse_stems(stems, list(model.sources), sr))
        if parts is None:
            status(f"Auto: {reason}")
            return wav.numpy().mean(0), sr, "Auto picked: original audio (" + reason + ")"
        status(f"Auto: {reason}")
        desc = "Auto picked: " + " + ".join(PART_NAMES[p] for p in parts) + " (" + reason + ")"
    else:
        desc = "Kept: " + " + ".join(PART_NAMES[p] for p in parts)
    status(f"  keeping: {', '.join(parts)}")
    mix = sum(stems[model.sources.index(p)] for p in parts).mean(0)
    return mix, sr, desc


def clean_notes(notes, min_len=0.06, min_vel=20, max_poly=8):
    """Drop blips, ghost notes and pile-ups that come from non-piano sounds."""
    # Re-join notes that got chopped by holes where drum hits were removed:
    # same key, restarts right as the previous one ends, and noticeably softer.
    notes = sorted((dict(n) for n in notes), key=lambda n: n["onset_time"])
    last, merged = {}, []
    for n in notes:
        p = last.get(n["midi_note"])
        if p and n["onset_time"] - p["offset_time"] < 0.04 and n["velocity"] < 0.8 * p["velocity"]:
            p["offset_time"] = max(p["offset_time"], n["offset_time"])
            continue
        last[n["midi_note"]] = n
        merged.append(n)
    notes = [n for n in merged
             if n["offset_time"] - n["onset_time"] >= min_len and n["velocity"] >= min_vel]
    # Limit how many notes can start at (nearly) the same moment: keep the loudest
    notes.sort(key=lambda n: n["onset_time"])
    kept, i = [], 0
    while i < len(notes):
        j = i
        while j < len(notes) and notes[j]["onset_time"] - notes[i]["onset_time"] < 0.03:
            j += 1
        group = sorted(notes[i:j], key=lambda n: -n["velocity"])[:max_poly]
        kept.extend(group)
        i = j
    return sorted(kept, key=lambda n: n["onset_time"])


def output_path(name, mode):
    """A safe, unused file name in the output folder (never overwrites an earlier song)."""
    OUT.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in name if c not in '<>:"/\\|?*' and ord(c) >= 32).strip(" .") or "song"
    if safe.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)),
                                      *(f"LPT{i}" for i in range(10))}:
        safe = "song " + safe  # Windows reserved device names
    if mode in ("pop", "auto"):
        safe += f" ({mode})"
    path, n = OUT / f"{safe}.mid", 2
    while path.exists():
        path, n = OUT / f"{safe} ({n}).mid", n + 1
    return path


def convert(audio, rate, mode, parts, midi_path, status=print, progress=True, on_progress=None):
    """audio: [channels, samples] float array. Writes midi_path, returns a summary string."""
    import librosa
    from piano_transcription_inference.utilities import write_events_to_midi

    status(f"Mode: {MODE_NAMES[mode]}")
    desc = ""
    try:   # remember what the original sounds like, so a later piano check can compare against it
        import librosa
        import piano_check
        piano_check.save_reference(librosa.resample(np.asarray(audio.mean(0), dtype=np.float32), orig_sr=rate,
                                                    target_sr=piano_check.SR), Path(midi_path).name)
    except Exception as e:
        status(f"(couldn't save the song reference for piano checks: {e})")
    if mode in ("pop", "auto"):
        mono, rate, desc = separate(audio, rate, "auto" if mode == "auto" else parts, status, progress, on_progress)
    else:
        mono = audio.mean(0)
    mono = librosa.resample(np.asarray(mono, dtype=np.float32), orig_sr=rate, target_sr=SR)

    # Normalise loudness so quiet recordings still trigger notes
    peak = np.abs(mono).max()
    if peak > 0:
        mono = mono / peak * 0.9
    # Short silent lead-in so a note right at the start isn't missed
    mono = np.concatenate([np.zeros(SR // 2, dtype=mono.dtype), mono])

    status(f"Transcribing {len(mono) / SR:.0f}s of audio (this takes a little while on CPU)...")
    model = piano_model()
    t0 = time.time()
    report = (lambda f: on_progress("transcribe", f)) if on_progress else (lambda f: None)
    with quiet(), transcribe_progress(report):
        result = model.transcribe(mono, str(midi_path))
    notes = result["est_note_events"]
    msg = f"{len(notes)} notes"
    if mode in ("pop", "auto"):
        cleaned = clean_notes(list(notes))
        msg = f"{len(cleaned)} notes (removed {len(notes) - len(cleaned)} stray ones)"
        write_events_to_midi(start_time=0, note_events=cleaned,
                             pedal_events=result["est_pedal_events"], midi_path=str(midi_path))
    status(f"Done in {time.time() - t0:.0f}s - {msg}")
    return f"{msg}. {desc}" if desc else msg


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", help="audio file (mp3/wav/flac/...) - omit to record from the mic")
    ap.add_argument("--mode", choices=("auto", "piano", "pop"), default="piano")
    ap.add_argument("--parts", default="vocals,other,bass",
                    help="pop mode: parts to turn into piano (vocals, other, bass, drums)")
    ap.add_argument("--seconds", type=float, help="record for this many seconds")
    ap.add_argument("--name", help="output file name (without .mid)")
    args = ap.parse_args()

    parts = [p.strip() for p in args.parts.split(",") if p.strip()]
    bad = [p for p in parts if p not in PARTS]
    if bad or not parts:
        sys.exit(f"--parts must be from: {', '.join(PARTS)}")

    if args.file:
        src = Path(args.file)
        if not src.exists():
            sys.exit(f"Can't find {src}")
        print(f"Loading {src.name}...")
        audio, rate = load_file(str(src))
        name = args.name or src.stem
    else:
        audio, rate = record(args.seconds)
        name = args.name or input("Name for this song (Enter for a timestamp): ").strip() \
            or datetime.now().strftime("recording-%Y%m%d-%H%M%S")

    midi_path = output_path(name, args.mode)
    convert(audio, rate, args.mode, parts, midi_path)
    print(f"Saved: {midi_path}")
    print("Drag it into Piano Jukebox -> My Music to play it.")
    if os.name == "nt":
        os.startfile(OUT)


if __name__ == "__main__":
    main()
