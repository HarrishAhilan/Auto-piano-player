# Piano Jukebox

Play songs on a MIDI player piano (PianoDisc or any MIDI piano) from a Spotify-style web app,
and turn any recording into a piano MIDI file.

## What's here

| Folder / file | What it is |
|---|---|
| `piano-jukebox/` | The web app (also deployed on Vercel). Library of free/public-domain MIDI songs, *My Music* for your own files, and the **Convert a song to MIDI** panel. |
| `piano_web.py`, `Piano Jukebox.bat` | Runs the web app locally on http://localhost:8765 and acts as the bridge that sends notes to the piano. |
| `piano_player.py` | Command-line MIDI player for the piano. |
| `song-to-midi/` | Song → piano MIDI converter (AI transcription + Demucs source separation). `Start Converter.bat` runs it on http://localhost:8770. |
| `tools/` | Scripts that download the free song library and build `catalog.json`. |

## Quick start

**Play songs on the piano**
1. Connect the piano (USB-MIDI or Bluetooth MIDI) to this PC.
2. Double-click `Piano Jukebox.bat` (needs Python 3.11 + `pip install mido python-rtmidi`).
3. Open http://localhost:8765, pick a song, and press play.

**Convert a song to MIDI**
1. One-time setup: see `song-to-midi/requirements.txt`.
2. Double-click `song-to-midi/Start Converter.bat` - it opens the jukebox at http://localhost:8770.
3. Go to **My Music** -> **Convert a song to MIDI**, drop an mp3 (or record from the mic), and wait.
   The finished MIDI is added to My Music and saved in `song-to-midi/output/`.

**Check how the real piano sounds**
1. In **My Music**, turn on **Analyse mode** (in the converter panel) and put the laptop near the piano.
2. Play a song from the jukebox. It records automatically and shows, live, how the song *should* sound
   (from the original mp3) above what the mic hears.
3. Pause or let the song end: it lines the recording up with the song and reports, with timestamps,
   where the melody gets buried, stretches run late, soft notes lag, notes don't sound, or the piano
   plays notes the song doesn't have. Click an issue to jump there. Reports are saved in
   `song-to-midi/output/checks/`. Command line: `python song-to-midi/piano_check.py --midi <file.mid> --seconds 60`.

## Song → MIDI modes

- **Auto** (default): a full piano **arrangement** fitted to your player piano - the singer's tune, the real bass line and the band's keys part on a steady beat, choruses found automatically and made bigger, light breaks thinned, intro/outro kept as played. Everything in it was calibrated on a real piano: see [docs/CALIBRATION.md](docs/CALIBRATION.md) and [docs/calibration-runs.md](docs/calibration-runs.md). Your piano's numbers live in `song-to-midi/piano_profile.json`.
- **Piano recording**: transcribes the audio as-is. Best for solo piano.
- **Pop / Film**: removes drums and lets you choose the parts.

See `song-to-midi/requirements.txt` for setup. Runs on CPU (slow: ~10–15 min per song); an NVIDIA GPU makes it ~20x faster.
