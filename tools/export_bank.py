"""Export the whole scenario bank (generic + six worlds) and a sample game per world to JSON."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rumble.content import KINDS, get_world, world_keys
from rumble.content.generic import BANK
from rumble.content.expansion import ADDITIONS
from rumble.content.worlds import WORLDS, FACTS
from rumble.engine import Game, Settings
from rumble.assets import AssetPicker, round_mood, lobby_asset, MOODS
import random

NAMES = ["gulfkid", "redline_rex", "porschepilled", "blisterbandit", "jdm.ghost", "wafflehunter", "cardcorner",
         "sti_steve", "pegwarmer", "rollcage", "nitro.nina", "claw_whisperer", "mint_mike", "peg_queen"]


def main(out):
    data = {"generic": {k: [dict(l, id=f"g.{k}.{i}") for i, l in enumerate(BANK[k])] for k in KINDS}, "worlds": []}
    for w in WORLDS:
        wc = get_world(w["key"])
        g = Game(wc, list(enumerate(NAMES)), Settings(), seed=21 + len(w["key"]))
        picker = AssetPicker(random.Random(5 + len(w["key"])))
        rounds = []
        while not g.finished:
            rd = g.next_round()
            sc = None
            if rd.second_chance:
                sc = g.resolve_auto_second_chance()[0]
            mood = round_mood(rd)
            rounds.append({"title": rd.title, "events": [{"id": e.line_id, "kind": e.kind, "text": e.text} for e in rd.events],
                           "alive": len(g.alive_ids()), "second_chance": sc, "mood": mood, "asset": picker.pick(mood),
                           "sc_asset": picker.pick("second_chance") if sc else None})
        data["worlds"].append({
            "key": w["key"], "name": w["name"], "banner": w["banner"], "emoji": w["emoji"], "tagline": w["tagline"],
            "color": "#%06X" % w["color"], "slots": w["slots"], "laps": w["laps"], "final": w["final_title"],
            "overtime": w["overtime_title"], "sequential": bool(w.get("sequential")), "lobby": w["lobby"],
            "second_chance": w["second_chance"], "exclude": w.get("exclude_tags", []),
            "lines": {k: [dict(l, id=f"{w['key']}.{k}.{i}") for i, l in enumerate(v)] for k, v in w["lines"].items()},
            "expansion_lines": {k: [dict(l, id=f"x.{w['key']}.{k}.{i}") for i, l in enumerate(v)]
                                for k, v in ADDITIONS.get(w["key"], {}).items()},
            "pool_sizes": {k: len(wc.pools[k]) for k in KINDS}, "facts": FACTS.get(w["key"], []),
            "sample": {"rounds": rounds, "win": g.win_text, "total": g.total_rounds,
                       "lobby_line": wc.lobby[0], "lobby_asset": lobby_asset(wc), "win_asset": picker.pick("winner")},
        })
    data["moods"] = MOODS
    json.dump(data, open(out, "w"), ensure_ascii=False, indent=1)
    print("lines:", sum(len(v) for v in BANK.values()) + sum(len(v) for w in WORLDS for v in w["lines"].values())
          + sum(len(v) for kinds in ADDITIONS.values() for v in kinds.values()))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "bank_export.json")
