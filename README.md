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

## Song → MIDI modes

- **Auto** (default): splits the song into vocals / drums / bass / instruments, decides what to keep from what it hears, and cleans up the notes.
- **Piano recording**: transcribes the audio as-is. Best for solo piano.
- **Pop / Film**: removes drums and lets you choose the parts.

See `song-to-midi/requirements.txt` for setup. Runs on CPU (slow: ~10–15 min per song); an NVIDIA GPU makes it ~20x faster.
