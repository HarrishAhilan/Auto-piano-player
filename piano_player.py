"""
piano_player.py - play a MIDI file on a PianoDisc (or any MIDI piano).

Setup (once):
    pip install mido python-rtmidi

Usage:
    python piano_player.py --list                 show MIDI outputs
    python piano_player.py song.mid               play (auto-picks the adapter)
    python piano_player.py song.mid --port 2      play on output number 2
    python piano_player.py song.mid --volume 0.7  play softer (0.1 - 1.5)
    python piano_player.py --panic                release all keys and pedals

Press Ctrl+C to stop. All keys and pedals are released on exit.
"""
import argparse
import sys
import time

import mido

LOW_KEY, HIGH_KEY = 21, 108          # the 88 piano keys
SUSTAIN, SOFT = 64, 67               # pedal controllers
SKIP_NAMES = ("microsoft gs wavetable", "midi through")
PREFER_NAMES = ("widi", "ble", "bluetooth", "md-bt", "usb midi", "pianodisc")
DEFAULT_CHANNEL, DEFAULT_VOLUME, DEFAULT_FLOOR = 1, 0.8, 35   # tuned 2026-11-16


def list_ports():
    names = mido.get_output_names()
    if not names:
        print("No MIDI outputs found. Is the adapter paired and the Korg "
              "BLE-MIDI driver installed?")
    for i, name in enumerate(names):
        print(f"  [{i}] {name}")
    return names


def pick_port(choice):
    names = mido.get_output_names()
    if not names:
        sys.exit("No MIDI outputs found. Pair the adapter first "
                 "(see --list).")
    if choice is not None:
        if choice.isdigit() and int(choice) < len(names):
            return names[int(choice)]
        for name in names:
            if choice.lower() in name.lower():
                return name
        sys.exit(f"No output matching '{choice}'. Run with --list.")
    usable = [n for n in names if not any(s in n.lower() for s in SKIP_NAMES)]
    for name in usable:              # skip first: "wavetaBLE" contains "ble"
        if any(p in name.lower() for p in PREFER_NAMES):
            return name
    if len(usable) == 1:
        return usable[0]
    print("Could not tell which output is the piano:")
    list_ports()
    sys.exit("Re-run with --port <number>.")


def panic(port, channel):
    """Release pedals and every key so no solenoid stays energised."""
    port.send(mido.Message("control_change", channel=channel,
                           control=SUSTAIN, value=0))
    port.send(mido.Message("control_change", channel=channel,
                           control=SOFT, value=0))
    for note in range(LOW_KEY, HIGH_KEY + 1):
        port.send(mido.Message("note_off", channel=channel, note=note))
        time.sleep(0.002)            # gentle on Bluetooth


def convert(msg, channel, volume, floor):
    """Return the message to send to the piano, or None to drop it."""
    if msg.type == "note_on" and msg.velocity > 0:
        if not LOW_KEY <= msg.note <= HIGH_KEY:
            return None
        vel = max(floor, min(127, round(msg.velocity * volume)))
        return mido.Message("note_on", channel=channel,
                            note=msg.note, velocity=vel)
    if msg.type in ("note_off", "note_on"):          # note_on vel 0 = off
        if not LOW_KEY <= msg.note <= HIGH_KEY:
            return None
        return mido.Message("note_off", channel=channel, note=msg.note)
    if msg.type == "control_change" and msg.control in (SUSTAIN, SOFT):
        return mido.Message("control_change", channel=channel,
                            control=msg.control, value=msg.value)
    return None                                      # drop everything else


def play(path, port, channel, volume, floor, skip_drums=True, stop=None):
    """stop: optional threading.Event; set it to end playback early."""
    song = mido.MidiFile(path)
    print(f"Playing {path}  ({song.length:.0f} s)  - Ctrl+C to stop")
    sent = 0
    start, due = time.perf_counter(), 0.0
    for msg in song:                     # msg.time = seconds since last msg
        due += msg.time
        delay = due - (time.perf_counter() - start)
        if delay > 0:
            if stop is not None:
                if stop.wait(delay):     # wakes at once when stop is set
                    break
            else:
                time.sleep(delay)
        if msg.is_meta:
            continue
        if skip_drums and getattr(msg, "channel", None) == 9:
            continue
        out = convert(msg, channel, volume, floor)
        if out is not None:
            port.send(out)
            sent += 1
    print(f"Done. {sent} messages sent.")


def main():
    ap = argparse.ArgumentParser(description="Play a MIDI file on a piano.")
    ap.add_argument("file", nargs="?", help=".mid file to play")
    ap.add_argument("--list", action="store_true", help="list MIDI outputs")
    ap.add_argument("--port", help="output number or part of its name")
    ap.add_argument("--channel", type=int, default=DEFAULT_CHANNEL,
                    help="MIDI channel the piano listens on (default %(default)s)")
    ap.add_argument("--volume", type=float, default=DEFAULT_VOLUME,
                    help="velocity multiplier (default %(default)s)")
    ap.add_argument("--floor", type=int, default=DEFAULT_FLOOR,
                    help="softest velocity sent (default %(default)s)")
    ap.add_argument("--panic", action="store_true",
                    help="release all keys and pedals, then exit")
    args = ap.parse_args()

    if args.list:
        list_ports()
        return
    if not args.file and not args.panic:
        ap.error("give a .mid file, or use --list / --panic")
    if not 1 <= args.channel <= 16:
        ap.error("--channel must be 1-16")
    channel = args.channel - 1

    name = pick_port(args.port)
    print(f"Output: {name}")
    try:
        port = mido.open_output(name)
    except Exception:
        sys.exit(f"Couldn't open {name}: another program is using it. Only one "
                 "program can play at a time. If the jukebox website was just "
                 "playing, wait a few seconds and try again.")
    with port:
        try:
            if args.file:
                play(args.file, port, channel, args.volume, args.floor)
        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            panic(port, channel)


if __name__ == "__main__":
    main()
