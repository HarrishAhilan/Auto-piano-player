"""Build piano-jukebox/catalog.json from the files in piano-jukebox/library.

    py -3.11 tools/build_catalog.py
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mido

SITE = Path(__file__).resolve().parent.parent / "piano-jukebox"
LIB = SITE / "library"

# Christmas files: filename -> (title, composer, source/credit)
CHRISTMAS = {
    "arr_silent_night.mid": ("Silent Night", "Franz Xaver Gruber", "Piano arrangement"),
    "arr_jingle_bells.mid": ("Jingle Bells", "James Lord Pierpont", "Piano arrangement"),
    "arr_deck_the_halls.mid": ("Deck the Halls", "Traditional Welsh", "Piano arrangement"),
    "arr_we_wish_you_a_merry_christmas.mid": ("We Wish You a Merry Christmas", "Traditional English", "Piano arrangement"),
    "arr_joy_to_the_world.mid": ("Joy to the World", "G. F. Handel / Lowell Mason", "Piano arrangement"),
    "first_noel.mid": ("The First Noel", "Traditional English", "Mutopia Project (public domain)"),
    "thehollyandtheivy.mid": ("The Holly and the Ivy", "Traditional English", "Mutopia Project (public domain)"),
    "GoodKingWenceslas.mid": ("Good King Wenceslas", "Traditional", "Mutopia Project (public domain)"),
    "carol.mid": ("It Came Upon the Midnight Clear", "Richard Storrs Willis", "Mutopia Project (public domain)"),
    "Nuz_my_dzis_krzescijani.mid": ("Nuż my dziś krześcijani (Polish carol)", "Traditional Polish", "Mutopia Project (public domain)"),
    "bortniansky-xmas-kontakion.mid": ("Kontakion of Christmas", "Dmitry Bortniansky", "Mutopia Project (public domain)"),
    "horetzky6.mid": ("Un Noël", "Felix Horetzky", "Mutopia Project (public domain)"),
}


def main():
    tracks = []
    for fname, (title, composer, credit) in CHRISTMAS.items():
        path = LIB / "christmas" / fname
        tracks.append({"id": "x:" + fname, "t": title, "a": composer,
                       "c": "christmas", "y": credit,
                       "d": round(mido.MidiFile(path).length),
                       "u": "library/christmas/" + fname})

    # free/public-domain songs fetched by tools/get_free_songs.py
    from get_free_songs import LIST, OUT, slug
    with open(LIST, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            fn = slug(r["composer"].split()[-1] + "_" + r["title"]) + ".mid"
            path = OUT / r["collection"] / fn
            if path.exists():
                tracks.append({"id": f"f:{r['collection']}/{fn}", "t": r["title"],
                               "a": r["composer"], "c": r["collection"],
                               "y": f"{r['source']} · {r['license']}",
                               "d": round(mido.MidiFile(path).length),
                               "u": f"library/free/{r['collection']}/{fn}"})

    root = LIB / "maestro" / "maestro-v3.0.0"
    with open(root / "maestro-v3.0.0.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            fn = row["midi_filename"]
            tracks.append({"id": "m:" + fn, "t": row["canonical_title"],
                           "a": row["canonical_composer"], "c": "classical",
                           "y": row["year"], "d": round(float(row["duration"])),
                           "u": "library/maestro/maestro-v3.0.0/" + fn})

    out = SITE / "catalog.json"
    out.write_text(json.dumps({"tracks": tracks}, ensure_ascii=False,
                              separators=(",", ":")), encoding="utf-8")
    print(f"{len(tracks)} tracks -> {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
