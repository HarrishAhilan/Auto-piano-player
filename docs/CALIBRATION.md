# Song → player piano: the calibration guide

This is what we learned turning **Dancing in the Moonlight** into a piano arrangement for the PianoDisc,
over 18 arrangement versions and 12 recordings of the real piano (19 Nov 2026). Every rule below is
now built into the converter's **Auto** mode (`song-to-midi/arranger.py`) and the piano profile
(`song-to-midi/piano_profile.json`), so the next song starts where this one finished.

The run-by-run numbers are in [calibration-runs.md](calibration-runs.md).

---

## How to read this

Each lesson is **symptom → how we proved the cause → the fix (now default)**.
"Checked on the real piano" means a recording through the piano check (`song-to-midi/piano_check.py`):
a mic next to the piano, lined up with the MIDI that was sent, compared note by note and against the
original mp3.

---

## 1. Transcribing ≠ arranging

| Symptom | Cause | Fix |
|---|---|---|
| First version (piano model on the whole mix): choppy, "random keys" | A piano-transcription model hears guitars, drums and vocals as piano notes | Split the song (Demucs) and treat each part differently |
| Middle of the song got progressively more jumbled | Copying every instrument note: density swung 1–7 notes/s, chord match fell from 85% → 47% | **Arrange**: melody + bass + a part built from the song's own harmony |
| "Sounds like a remake, not a song"; backing dropped out at random | The backing copied whatever the band played: 54 of 398 beats had no backing note | **Steady pulse**: every beat has something (bass on 1 & 3, chord on 2 & 4 where the band leaves a gap); crowded beats trimmed to 4 |

## 2. The melody

| Symptom | Cause | Fix |
|---|---|---|
| Melody wrong / weak (≈30% right) | The piano model reading a *voice* | Melody from the **singer's pitch track** (pYIN), not the piano model |
| Melody "overlapping", "jumbled", timing "off" | (a) notes stretched to the next one: keys held while the singer was silent 31% of the time; (b) the **sustain pedal** held 96% of the song made each 0.23 s note ring ~2 s, 87% of the time two tune notes rang together | Notes **start on the real syllable** (consonants come before pitch, snap ≤150 ms) and **end when the singer stops**; pedal changed at every tune note (see §5) |
| Random blips in the tune | Pitch-tracker slips (vibrato, breaths, backing vocals) | Merge <0.1 s one-off jumps into a neighbour; move notes the song doesn't contain to a neighbouring pitch the song does have; drop short ones the song has none of |
| Re-strikes at wrong moments (80% wrong) | Re-striking at every detected vocal onset (noise, breaths) | Re-strike only on **clear** syllables (strong onsets) |
| Last part "choppy" | Accurate but detached notes | Join gaps ≤0.2 s (≤0.3 s in the last 15%) so it sounds sung |
| Melody buried | Backing 1–7 semitones under the tune at nearly the same loudness | **Nothing within 5 semitones under the tune**; backing struck with a tune note follows it by **35 ms** (melody lead) and is capped at 52 |

## 3. The backing

| Symptom | Cause | Fix |
|---|---|---|
| Too many wrong notes (mostly B♭) | Chord *templates* guessed full chord shapes the band doesn't play | Chords from the pitches the instruments actually play; drop any the song doesn't contain |
| Missing "small notes", not continuous | Bass = one note per chord; small licks lost | **Real bass line** (pitch-tracked bass guitar, one strike per pluck); the band's **keys/guitar part** (piano model on the "other" stem) under the tune |
| Fewer notes, lost the "magic" (v13: 5.9 notes/s) | Over-correcting toward an error metric removed a third of the notes | Keep the keys part everywhere (v14: 8.3 notes/s, *and* fewer wrong notes) |
| **Choruses emptier than verses** (6.6 vs 8.2 notes/s, melody +37 dB alone) | "Is this note in the song?" was judged against the whole mix, where the **singer dominates** the chorus | Judge the keys part against the **instruments only** (wrong notes in choruses halved) |
| Jumbled where tune and backing are both busy | 2.5× more "melody buried" in those seconds | The 5-semitone rule + melody lead (above); never more than ~12 keys ringing |

## 4. Song structure

Found automatically from the audio:

* **Keys-only intro/outro** (no singing, bass or drums): played exactly as the band's keys part was
  transcribed — this was the part that "sounded beautiful" from v1 on. A hand-approved intro can be
  locked in `song-to-midi/locks/<song>.intro.json`.
* **Choruses** = 2-bar patterns that repeat elsewhere + loudest + sung (found 0:56, 1:36, 2:25, 3:04 —
  the same as by ear). They get the fuller keys part, **the tune doubled an octave up** (held notes),
  **bass octaves** on each bar, louder backing, and **swell in over the bar before / settle after**.
* **Light instrumental breaks** (singing and bass drop out, instruments continue ≥4 s): only the high
  "twinkle" figure, softly (was 11–14 notes/s, now ~4).
* **Transitions**: the groove fades in over 2 bars after the intro; the end tapers to one chord per bar.

## 5. The player piano (measured, see `piano_profile.json`)

| Measured on the real piano | Rule |
|---|---|
| Jukebox **Volume 0.35** left the melody max 44 vs backing floored at 35 → "melody vs backing same volume" | Use Volume **0.6**; write *on-the-piano* levels (melody ~73, backing ~50) and convert |
| Notes below ~36 on the piano didn't sound **22%** of the time | Nothing below **45** |
| **Weak keys** C3 E♭3 F3 B♭3 C4 D4 E♭4 F4 failed repeatedly at 41–52 | Those keys ≥ **58** (E♭4 ≥ 62) |
| Notes shorter than 0.06 s failed **10.7%** (vs ~2% ≥0.15 s) | Every note ≥ **0.15 s** (tune notes ≥0.08 s and never past the next tune note) |
| Re-strikes 5–16 ms after release didn't sound; at an 80 ms reset most failures were *exactly* 79–80 ms | Keys get **120 ms** to reset; strikes of one key <0.2 s apart become one |
| Soft notes fire late (13–14 ms after a first 13 ms fix) | Send soft notes early: **27 ms** (≤45), **20 ms** (<60) — verified to land within **2 ms** |
| "Late stretches" | Mostly the soft-note lag; correcting both over-shot by 20–70 ms → **don't** shift sections |
| Pedal held through chords → smear; no pedal → dry | Pedal **changes at every tune note, tune-note end and bass note** (press 50 ms after, lift 20 ms before) |
| Pedal down → strings ring in sympathy (26 "wrong" notes nobody played) | Short presses, no presses <0.12 s |
| 13–18 keys ringing at once = "jumbled" | Cap at **12** (drop the softest keys-part notes) |

## 6. The tools that made this possible

* **Piano check** (`piano_check.py`, the jukebox's *Analyse mode*): records the piano while a song plays,
  lines it up with the MIDI (consensus of 30 s pieces — a repetitive intro once threw a single alignment
  2 s off), and reports per note and per section: did it sound, melody vs backing on the real instrument,
  timing by stretch and soft-vs-loud lag, and which pitches the song has that the piano doesn't / plays
  that the song doesn't.
* **Bench** (simulated piano at the jukebox's settings + the same checker) to try fixes in seconds.
  Lesson: the simulation was **harsher** than the real piano on melody balance (37% vs 70% "on top"),
  and once it pointed the wrong way — **always confirm on the real piano**.
* **Metrics we trust**: notes sounded, melody over backing (real piano), timing spread, soft lag,
  "sounds like the original". **Metrics to treat carefully**: "wrong/missing vs song" (a piano can't
  contain a whole band; chasing it to zero thinned the arrangement and lost the "magic").

## 7. Re-calibrating for a different piano or settings

1. Change `jukebox_volume` / `jukebox_softest` in `piano_profile.json` to match the jukebox Settings.
2. Play any converted song with **Analyse mode** on, laptop mic (better: a small mic on the piano, ~30–50 cm
   from the strings, centred on the keyboard).
3. In the report: keys that keep failing → `weak_keys`; "Soft notes lag" → `soft_note_lag`; notes failing
   just after release → raise `key_reset_seconds`; melody buried with low volume → raise `jukebox_volume`.
