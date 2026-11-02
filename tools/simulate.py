"""Simulate thousands of games per world and player count. Prints a balance table and fails on any broken rule.

usage: python tools/simulate.py [--games 300] [--sizes 2,3,5,8,12,20,35,60,100,150,250]
"""
import argparse, collections, os, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rumble.content import get_world, world_keys
from rumble.engine import Game, Settings


def check_game(g, n):
    errs = []
    s = g.summary()
    alive = g.alive_ids()
    if len(alive) != 1 or alive[0] != s["winner"]:
        errs.append("winner state broken")
    if g.round_no != g.total_rounds:
        errs.append(f"rounds {g.round_no} != planned {g.total_rounds}")
    for rd in g.history:
        seen = collections.Counter()
        for ev in rd.events:
            for a in ev.actors:
                seen[a] += 1
            if "{" in ev.text or "}" in ev.text:
                errs.append(f"unfilled placeholder: {ev.text}")
        dup = [k for k, v in seen.items() if v > 1]
        if dup:
            errs.append(f"round {rd.number}: ripper appears twice")
        if not rd.final and rd.alive_after < 2:
            errs.append(f"round {rd.number}: non-final round left {rd.alive_after}")
    kills = sum(s["kills"].values())
    if kills > n - 1 + s["revives"]:
        errs.append("kill accounting broken")
    if len(s["ranking"]) != n or len(set(s["ranking"])) != n:
        errs.append("ranking broken")
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=300)
    ap.add_argument("--sizes", default="2,3,5,8,12,20,35,60,100,150,250")
    ap.add_argument("--max-lines", type=int, default=12)
    a = ap.parse_args()
    sizes = [int(x) for x in a.sizes.split(",")]
    st = Settings(max_lines=a.max_lines)
    total_errs = 0
    print(f"{'world':11} {'n':>4} {'rounds':>7} {'lines/rd avg':>12} {'max lines':>9} {'quiet rds':>9} "
          f"{'revives':>7} {'2nd ch':>6} {'calls':>6} {'repeats':>7} {'hazards':>7} {'max chars':>9}")
    for key in world_keys():
        w = get_world(key)
        for n in sizes:
            R, avg_lines, max_lines, quiet, rev, calls, reps, haz, chars, sc = [], [], 0, [], [], [], [], [], 0, 0
            for gi in range(a.games):
                g = Game(w, [(i, f"ripper{i}") for i in range(n)], st, seed=gi * 7919 + n)
                g.run_all()
                errs = check_game(g, n)
                if errs:
                    total_errs += 1
                    if total_errs <= 10:
                        print("ERROR", key, n, gi, errs[:3])
                s = g.summary()
                R.append(g.round_no)
                lines = [len(rd.events) for rd in g.history]
                avg_lines.append(statistics.mean(lines))
                max_lines = max(max_lines, max(lines))
                quiet.append(sum(1 for rd in g.history if not rd.eliminated))
                rev.append(s["revives"])
                calls.append(sum(rd.kinds.count("call") for rd in g.history))
                reps.append(s["repeats"])
                haz.append(sum(rd.kinds.count("hazard") for rd in g.history))
                sc += int(g.second_chance_done)
                for rd in g.history:
                    body = "\n".join(e.text for e in rd.events)
                    chars = max(chars, len(body))
            print(f"{key:11} {n:>4} {statistics.mean(R):>7.1f} {statistics.mean(avg_lines):>12.1f} {max_lines:>9} "
                  f"{statistics.mean(quiet):>9.1f} {statistics.mean(rev):>7.2f} {sc / a.games:>6.0%} "
                  f"{statistics.mean(calls):>6.2f} {statistics.mean(reps):>7.2f} {statistics.mean(haz):>7.1f} {chars:>9}")
    print(f"\nbroken games: {total_errs}")
    return 1 if total_errs else 0


if __name__ == "__main__":
    sys.exit(main())
