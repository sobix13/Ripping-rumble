"""Content audit: placeholders, roles, slots, banned words, punctuation, duplicates and pool sizes.

Run:  python -m rumble.content.validate      (exit code 1 when an ERROR is found)
"""
import difflib
import re
import sys

from . import KINDS, get_world, world_keys
from .generic import BANK
from .expansion import ADDITIONS
from .worlds import WORLDS

TOKEN = re.compile(r"\{([A-Za-z]+)\}")
SLOTS = {"grail", "model", "pack"}

# required and allowed placeholders per kind (slots are always allowed except where noted)
ROLES = {
    "kill": ({"A", "B"}, {"A", "B"}),
    "wipe": ({"A"}, {"A"}),
    "multi": ({"A", "B", "C"}, {"A", "B", "C"}),
    "double": ({"A", "B"}, {"A", "B"}),
    "find": ({"A"}, {"A"}),
    "transfer": ({"A", "H", "item"}, {"A", "H", "item"}),
    "survive": ({"A"}, {"A"}),
    "moment": ({"A", "B"}, {"A", "B"}),
    "revive": ({"A"}, {"A"}),
    "duel": ({"A", "B"}, {"A", "B"}),
    "win": ({"A"}, {"A"}),
    "hazard": ({"names"}, {"names"}),
    "ambient": (set(), set()),
}
CALL_ROLES = {"B": ({"H", "item", "B"}, {"H", "item", "B"}),
              "H": ({"H", "item"}, {"H", "item", "B"}),
              "B+C": ({"H", "item", "B", "C"}, {"H", "item", "B", "C"})}

# SobiX's writing rules (sobix-writing banned list) plus RipCars rules
BANNED = ["can", "may", "just", "very", "really", "literally", "actually", "certainly", "probably", "basically",
          "could", "maybe", "delve", "embark", "enlightening", "esteemed", "shed light", "craft", "crafting",
          "imagine", "realm", "game changer", "unlock", "unlocked", "discover", "skyrocket", "abyss", "not alone",
          "in a world where", "revolutionize", "utilize", "dive deep", "tapestry", "illuminate", "unveil", "pivotal",
          "intricate", "elucidate", "hence", "furthermore", "however", "harness", "exciting", "groundbreaking",
          "cutting edge", "remarkable", "glimpse into", "navigating", "landscape", "stark", "testament",
          "in summary", "in conclusion", "moreover", "boost", "powerful", "inquiries", "ever evolving",
          "toy", "toys", "bro"]
MIN_POOL = {"kill": 40, "wipe": 40, "multi": 10, "double": 6, "find": 10, "call": 12, "transfer": 6, "survive": 10,
            "moment": 8, "revive": 10, "duel": 6, "win": 6, "hazard": 4, "ambient": 10}
MAX_CHARS = 240


def _tokens(text):
    return set(TOKEN.findall(text))


def _check_text(text, where, issues, real_vehicle=False):
    if text.count("{") != text.count("}"):
        issues.append(("ERROR", where, "unbalanced braces"))
    if re.search(r'[{}]', TOKEN.sub('', text)):
        issues.append(("ERROR", where, "unsupported placeholder or braces"))
    low = " " + re.sub(r"[^a-z0-9' ]", " ", text.lower().replace("-", " ")) + " "
    for w in BANNED:
        if f" {w} " in low:
            issues.append(("ERROR", where, f"banned word '{w}'"))
    if "—" in text or ";" in text:
        issues.append(("ERROR", where, "em dash or semicolon"))
    for c in ("can't", "couldn't", "cannot", "mayn't"):
        if c in text.lower():
            issues.append(("ERROR", where, f"banned word '{c}'"))
    if re.search(r"\bHot Wheels cars?\b", text, re.I):
        issues.append(("ERROR", where, "Hot Wheels are never 'cars'"))
    elif re.search(r"\bcars\b", text, re.I) and not real_vehicle:
        issues.append(("ERROR", where, "'cars' needs explicit real-vehicle context"))
    elif not real_vehicle and re.search(r"\bcar\b", text, re.I):
        issues.append(("WARN", where, "the word 'car': fine for real cars only"))
    if "  " in text:
        issues.append(("WARN", where, "double space"))
    if text != text.strip():
        issues.append(("WARN", where, "leading or trailing space"))
    if re.match(r"\{(grail|model|pack|item)\}", text):
        issues.append(("ERROR", where, "line starts with a lowercase slot"))


def validate_bank_lines(kind, src, where, issues):
    text = src["text"]
    real_vehicle = "real_vehicle" in src.get("tags", [])
    _check_text(text, where, issues, real_vehicle=real_vehicle)
    toks = _tokens(text)
    if kind == "call":
        out = src.get("out")
        if out not in CALL_ROLES:
            issues.append(("ERROR", where, f"callback needs out in {list(CALL_ROLES)}"))
            return
        req, allowed = CALL_ROLES[out]
    else:
        req, allowed = ROLES[kind]
    names = toks - SLOTS - {"item"} - {"names"}
    missing = req - toks
    extra = (toks - SLOTS) - allowed
    if missing:
        issues.append(("ERROR", where, f"missing {sorted(missing)}"))
    if extra:
        issues.append(("ERROR", where, f"placeholders not allowed here: {sorted(extra)}"))
    if kind == "hazard" and names:
        issues.append(("ERROR", where, "hazards use {names} only"))
    if kind == "find":
        holds = src.get("holds")
        if holds not in ("grail", "model"):
            issues.append(("ERROR", where, "find needs holds=grail|model"))
        elif "{" + holds + "}" not in text:
            issues.append(("ERROR", where, f"find holds {holds} but the text has no {{{holds}}}"))
    if kind != "call" and src.get("out"):
        issues.append(("ERROR", where, "'out' only belongs on callbacks"))
    if len(text) > MAX_CHARS:
        issues.append(("WARN", where, f"long line ({len(text)} chars)"))


def validate_world_meta(w, issues):
    k = w["key"]
    for i, t in enumerate(w["lobby"]):
        _check_text(t, f"{k}.lobby.{i}", issues)
        if _tokens(t):
            issues.append(("ERROR", f"{k}.lobby.{i}", "lobby lines take no placeholders"))
    for i, t in enumerate(w["laps"]):
        _check_text(t, f"{k}.laps.{i}", issues, real_vehicle=k == "gulf")
        if _tokens(t) - {"n"}:
            issues.append(("ERROR", f"{k}.laps.{i}", "laps only take {n}"))
    if len(set(w["laps"])) != len(w["laps"]):
        issues.append(("ERROR", f"{k}.laps", "duplicate lap titles"))
    for f in ("final_title", "overtime_title", "banner", "tagline", "name"):
        _check_text(w[f], f"{k}.{f}", issues)
    sc = w["second_chance"]
    for f in ("name", "title", "button", "body"):
        _check_text(sc[f], f"{k}.second_chance.{f}", issues)
    if len(sc["button"]) > 80:
        issues.append(("ERROR", f"{k}.second_chance.button", "button label over 80 chars"))
    for i, t in enumerate(sc["success"]):
        _check_text(t, f"{k}.second_chance.success.{i}", issues)
        if _tokens(t) != {"A"}:
            issues.append(("ERROR", f"{k}.second_chance.success.{i}", "success lines take {A} only"))
    for i, t in enumerate(sc["fail"]):
        _check_text(t, f"{k}.second_chance.fail.{i}", issues, real_vehicle=k == "gulf")
        if _tokens(t):
            issues.append(("ERROR", f"{k}.second_chance.fail.{i}", "fail lines take no placeholders"))
    s = w["slots"]
    if not s["models"] or len(set(s["models"])) != len(s["models"]):
        issues.append(("ERROR", f"{k}.slots", "models empty or duplicated"))
    for f in ("grail", "pack"):
        if not s[f]:
            issues.append(("ERROR", f"{k}.slots", f"{f} empty"))
    for kind in w["lines"]:
        if kind not in KINDS:
            issues.append(("ERROR", f"{k}.lines", f"unknown kind {kind}"))


def _norm(t):
    t = re.sub(r"\{[A-Za-z]+\}", "X", t.lower())
    return re.sub(r"[^a-z ]", "", t)


def validate_all(near_dupes=True):
    issues = []
    all_lines = []
    for kind, lines in BANK.items():
        if kind not in KINDS:
            issues.append(("ERROR", "bank", f"unknown kind {kind}"))
            continue
        for i, src in enumerate(lines):
            where = f"g.{kind}.{i}"
            validate_bank_lines(kind, src, where, issues)
            all_lines.append((where, src["text"]))
    for w in WORLDS:
        validate_world_meta(w, issues)
        for kind, lines in w["lines"].items():
            for i, src in enumerate(lines):
                where = f"{w['key']}.{kind}.{i}"
                validate_bank_lines(kind, src, where, issues)
                all_lines.append((where, src["text"]))
    for key, kinds in ADDITIONS.items():
        for kind, rows in kinds.items():
            for i, row in enumerate(rows):
                where = f"x.{key}.{kind}.{i}"
                validate_bank_lines(kind, row, where, issues)
                all_lines.append((where, row["text"]))
    # exact and near duplicates
    seen = {}
    for where, text in all_lines:
        n = _norm(text)
        if n in seen:
            issues.append(("ERROR", where, f"duplicate of {seen[n]}"))
        seen[n] = where
    if near_dupes:
        normed = [(w, _norm(t)) for w, t in all_lines]
        for i in range(len(normed)):
            for j in range(i + 1, len(normed)):
                a, b = normed[i][1], normed[j][1]
                if abs(len(a) - len(b)) > 25:
                    continue
                r = difflib.SequenceMatcher(None, a, b).ratio()
                if r > 0.82:
                    issues.append(("WARN", normed[j][0], f"near duplicate of {normed[i][0]} ({r:.2f})"))
    # pool sizes per world
    for key in world_keys():
        wc = get_world(key)
        for kind in KINDS:
            n = len(wc.pools[kind])
            if n < MIN_POOL[kind]:
                issues.append(("ERROR", f"{key}.pool.{kind}", f"only {n} lines, need {MIN_POOL[kind]}"))
        if len(wc.laps) < 10:
            issues.append(("ERROR", f"{key}.laps", "need at least 10 lap titles"))
    return issues


def main():
    issues = validate_all()
    errs = [i for i in issues if i[0] == "ERROR"]
    for lvl, where, msg in issues:
        print(f"{lvl:5} {where:28} {msg}")
    total = sum(len(v) for v in BANK.values()) + sum(len(v) for w in WORLDS for v in w["lines"].values()) + sum(len(rows) for kinds in ADDITIONS.values() for rows in kinds.values())
    print(f"\n{total} scenario lines, {len(errs)} errors, {len(issues) - len(errs)} warnings")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
