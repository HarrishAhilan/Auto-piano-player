# Calibration runs: Dancing in the Moonlight

Every version, what changed, and (from v6) what the **real piano** measured with the piano check.
Lessons drawn from these are in [CALIBRATION.md](CALIBRATION.md).

## Versions

| Version | What changed | Why (from listening or the check) |
|---|---|---|
| dm (Piano mode) | Piano model on the whole mix | First attempt: intro great, rest choppy/random |
| auto | Demucs split; vocals + instruments only | Less choppy, still jumbled in full-band parts |
| tuned | Melody from the singer's pitch track; pedal per chord | 43% → 2% silence; but pedal smear |
| arranged | Chord detection → bass + chord pattern; literal keys-only intro | Consistent chord match (78–84% every section) |
| arranged v2 | Melody louder than backing; licks in the singer's rests | Melody was quieter than backing |
| arranged v3 | Tuned for jukebox Volume 0.65 / Softest 35; real bass line; re-strike syllables | Settings squashed contrast; small notes missing |
| arranged v4 | Melody starts on syllables, ends when the singer stops | Keys held while singer silent 31% |
| arranged v5 | No pedal after the intro; no licks under singing | Pedal made notes ring 2 s → overlap |
| arranged v6 | Intro locked (from v4) | User: "keep the intro" |
| arranged v7 | 80 ms key reset; chords from the song's own pitches; licks clear of the tune | Re-strikes 5–16 ms after release didn't sound |
| arranged v8 | Intro key-reset; backing ≥41; soft notes 13 ms early; melody lead | Notes at 35 didn't sound; soft notes late |
| arranged v9 | Late stretches pre-corrected; soft notes +14 ms; backing ≥45 | Later shown to double-correct (see v12) |
| arranged v10 | Every note ≥0.15 s; pitch vote (pYIN/CREPE/model) | Short notes failed 10.7% |
| arranged v11 | Arrangement corrected against the original song | Wrong/missing vs song |
| arranged v12 | Undo stretch correction; pedal changes at tune notes + bass; backing 50; weak keys 55 | Over-correction; dry sound; melody too dominant |
| arranged v13 | Gentler pedal; half-strength timing fix; fill missing G/D | Sympathetic ringing; late sections |
| arranged v14 | Band's keys part back (filtered by the song); pedal wash back | "Fewer notes, lost the magic" |
| arranged v15 | Riffs 58, weak keys 62, 120 ms reset, ≤10 ringing | 53 notes didn't sound (riffs too soft, 80 ms reset) |
| arranged v16 | Choruses: keys part judged vs instruments, tune in octaves, bass octaves, swell | Choruses were emptier than verses |
| arranged v17 | Nothing within 5 semitones under the tune; cap 55 under tune strikes | Riffs 1–7 semitones under the tune buried it |
| arranged v18 | Steady pulse (fill empty beats, trim crowded); light break thinned; clean transitions; legato tune | "Backing drops", "1:55 too busy", "last 30 s choppy" |
| **Auto (arranger)** | All of the above, automatically, on any song | First try on this song ≈ v18 (wrong 46 vs 59, match 58% vs 56% on the bench) |

## Real-piano checks

Volume = jukebox volume; "melody dB" = melody louder than the backing on the real instrument;
"buried" = melody notes quieter than a backing note struck with them; "wrong"/"missing" = pitches the
piano plays that the song doesn't / the song has that the piano doesn't (a piano can't hold a whole
band, so these never reach zero); "soft lag" = how much later soft notes land than loud ones;
"timing ±" = spread of 2-second stretches.

| time | version | vol | melody dB | melody on top | didn't sound | buried | wrong | missing | soft lag ms | timing ms | pitch match | like the song |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 18:18 | v6 | 0.35 | +2 | 70% | 28 | 41 | 177 | 130 | 5.7 | ±9.1 | 35% | 77% |
| 18:41 | v7 | 0.6 | +6 | 77% | 51 | 34 | 146 | 121 | 13.2 | ±11.3 | 37% | 79% |
| 18:59 | v8 | 0.6 | +6 | 71% | 40 | 35 | 151 | 120 | 25.6 | ±13.3 | 37% | 79% |
| 19:07 | v8 (close mic) | 0.6 | +11 | 88% | 35 | 15 | 156 | 133 | 14.0 | ±12.4 | 35% | 78% |
| 19:31 | v10 † | 0.6 | +15 | 87% | 30 | 13 | 158 | 143 | 16.4 | ±11.8 | 35% | 78% |
| 19:35 | v11 | 0.6 | +20 | 93% | 35 | 6 | 102 | 104 | 21.7 | ±12.4 | 41% | 81% |
| 19:48 | v12 | 0.6 | +15 | 90% | 15 | 10 | 113 | 99 | 15.3 | ±11.9 | 39% | 82% |
| 20:05 | v13 | 0.6 | +17 | 89% | 31 | 11 | 105 | 89 | 12.5 | ±11.1 | 40% | 81% |
| 20:22 | v14 | 0.6 | +12 | 84% | 53 | 18 | 102 | 87 | 16.0 | ±14.1 | 42% | 84% |
| 20:36 | v15 | 0.6 | +14 | 82% | 16 | 19 | 103 | 87 | 14.0 | ±9.6 | 43% | 83% |
| 20:58 | v16 | 0.6 | +15 | 70% | 28 | 18 | 111 | 82 | 9.3 | ±8.6 | 43% | 84% |
| 21:22 | v18 † | 0.6 | +23 | 80% | 22 | 18 | 115 | 92 | 7.0 | ±8.2 | 42% | 84% |

† Re-analysed with the consensus alignment: the original reports were lined up ~2 s off (the repetitive
intro fooled a single alignment), which showed as hundreds of false "didn't sound" notes.
