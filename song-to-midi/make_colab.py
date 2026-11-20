"""Builds Song_to_MIDI_Colab.ipynb from the current song2midi.py.

Run this whenever song2midi.py changes so the Colab (free GPU) version stays in sync:
    .venv\\Scripts\\python make_colab.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
code = (HERE / "song2midi.py").read_text(encoding="utf-8")
files = {name: (HERE / name).read_text(encoding="utf-8") for name in ("arranger.py", "piano_check.py", "piano_profile.json")}


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip("\n").splitlines(True)}


def py(text, title=None, hide=False):
    meta = {}
    if title: meta["cellView"] = "form"
    src = (f"#@title {title}\n" if title else "") + text.strip("\n")
    return {"cell_type": "code", "execution_count": None, "metadata": meta, "outputs": [],
            "source": src.splitlines(True)}


cells = [
    md("""
# 🎹 Song → Piano MIDI (free Google GPU)

Turns any song into a MIDI file your player piano can play - in about a minute instead of 15.

**First time only:** menu **Runtime → Change runtime type → T4 GPU → Save**.

**Then:** press **Runtime → Run all** (or Ctrl+F9). Step 3 shows an **upload button** - pick your mp3(s).
When each song is done, its `.mid` downloads automatically. Drag it into **Piano Jukebox → My Music**.

Your song is only processed inside your own Colab session and is deleted when the session ends.
"""),
    py("""
import subprocess, sys, os, torch
gpu = torch.cuda.is_available()
print("GPU:", torch.cuda.get_device_name(0) if gpu else "NONE - turn it on: Runtime > Change runtime type > T4 GPU, then Run all again")
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "piano_transcription_inference", "demucs", "audioread", "mido", "scipy"], check=True)
ckpt_dir = os.path.expanduser("~/piano_transcription_inference_data")
ckpt = os.path.join(ckpt_dir, "note_F1=0.9677_pedal_F1=0.9186.pth")
if not os.path.exists(ckpt) or os.path.getsize(ckpt) < 1.6e8:
    os.makedirs(ckpt_dir, exist_ok=True)
    print("Downloading the piano model (165 MB)...")
    subprocess.run(["wget", "-q", "-O", ckpt,
                    "https://zenodo.org/record/4034264/files/CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1"], check=True)
print("Ready.")
""", title="1. Set up (takes ~1 minute)"),
    py("%%writefile song2midi.py\n" + code, title=None),
    *[py(f"%%writefile {name}\n" + text, title=None) for name, text in files.items()],
    py("""
mode = "auto"  #@param ["auto", "piano", "pop"]
#@markdown **auto** - arranges the song for your player piano (recommended; uses piano_profile.json) ·
#@markdown **piano** - for songs that are only piano · **pop** - drums removed, you pick the parts below
keep_melody = True  #@param {type:"boolean"}
keep_chords = True  #@param {type:"boolean"}
keep_bass = False  #@param {type:"boolean"}
parts = [p for p, on in (("vocals", keep_melody), ("other", keep_chords), ("bass", keep_bass)) if on] or ["vocals", "other"]
print("Mode:", mode, "| parts (pop mode):", parts)
""", title="2. Settings"),
    py("""
import importlib, time, warnings
warnings.filterwarnings("ignore")
from google.colab import files
import song2midi; importlib.reload(song2midi)
song2midi.OUT = song2midi.Path("/content/output")

uploaded = files.upload()
for fname in uploaded:
    t0 = time.time()
    print(f"\\n=== {fname} ===")
    audio, rate = song2midi.load_file(fname)
    midi_path = song2midi.output_path(song2midi.Path(fname).stem, mode)
    summary = song2midi.convert(audio, rate, mode, parts, midi_path, progress=False)
    print(f"Finished in {time.time() - t0:.0f}s: {summary}")
    files.download(str(midi_path))
    os.remove(fname)
""", title="3. Upload songs and convert"),
]

nb = {"cells": cells, "metadata": {"accelerator": "GPU", "colab": {"provenance": [], "gpuType": "T4"},
                                   "kernelspec": {"name": "python3", "display_name": "Python 3"},
                                   "language_info": {"name": "python"}},
      "nbformat": 4, "nbformat_minor": 0}
out = HERE / "Song_to_MIDI_Colab.ipynb"
out.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print("wrote", out)
