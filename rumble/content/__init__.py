"""Builds per-world line pools from the generic bank and the world lines."""
from dataclasses import dataclass, field

from .generic import BANK
from .expansion import ADDITIONS
from .worlds import WORLDS, WORLD_BY_KEY

KINDS = ["kill", "wipe", "multi", "double", "find", "call", "transfer", "survive", "moment", "revive", "duel",
         "win", "hazard", "ambient"]
WORLD_LINE_WEIGHT = 2.0   # world lines show up twice as often as generic ones, so each world feels like itself


@dataclass(frozen=True)
class Line:
    id: str
    kind: str
    text: str
    vibe: str
    tags: tuple
    weight: float
    holds: str = ""      # finds: "grail" or "model"
    out: str = ""        # callbacks: "B", "H" or "B+C"


@dataclass
class WorldContent:
    key: str
    name: str
    banner: str
    emoji: str
    tagline: str
    color: int
    lobby_asset: str
    grail: str
    pack: str
    models: list
    laps: list
    sequential: bool
    pin_first: bool
    final_title: str
    overtime_title: str
    lobby: list
    second_chance: dict
    pools: dict = field(default_factory=dict)


def _line(src, kind, lid, weight):
    return Line(id=lid, kind=kind, text=src["text"], vibe=src.get("vibe", "slap"), tags=tuple(src.get("tags", [])),
                weight=weight, holds=src.get("holds", ""), out=src.get("out", ""))


def build_world(key):
    w = WORLD_BY_KEY[key]
    excl = set(w.get("exclude_tags", []))
    tag_w = w.get("tag_weights", {})
    pools = {}
    for kind in KINDS:
        pool = []
        for i, src in enumerate(BANK[kind]):
            tags = set(src.get("tags", []))
            if tags & excl:
                continue
            wt = 1.0
            for t in tags:
                wt *= tag_w.get(t, 1.0)
            pool.append(_line(src, kind, f"g.{kind}.{i}", wt))
        for i, src in enumerate(w["lines"].get(kind, [])):
            wt = WORLD_LINE_WEIGHT
            for t in src.get("tags", []):
                wt *= tag_w.get(t, 1.0)
            pool.append(_line(src, kind, f"{key}.{kind}.{i}", wt))
        for i, src in enumerate(ADDITIONS.get(key, {}).get(kind, [])):
            pool.append(_line(src, kind, f"x.{key}.{kind}.{i}", WORLD_LINE_WEIGHT))
        pools[kind] = pool
    s = w["slots"]
    return WorldContent(key=key, name=w["name"], banner=w["banner"], emoji=w["emoji"], tagline=w["tagline"],
                        color=w["color"], lobby_asset=w["lobby_asset"], grail=s["grail"], pack=s["pack"],
                        models=list(s["models"]), laps=list(w["laps"]), sequential=bool(w.get("sequential")), pin_first=bool(w.get("pin_first")),
                        final_title=w["final_title"], overtime_title=w["overtime_title"], lobby=list(w["lobby"]),
                        second_chance=dict(w["second_chance"]), pools=pools)


_CACHE = {}


def get_world(key):
    if key not in WORLD_BY_KEY:
        raise KeyError(f"unknown world: {key}")
    if key not in _CACHE:
        _CACHE[key] = build_world(key)
    return _CACHE[key]


def world_keys():
    return [w["key"] for w in WORLDS]


def world_choices():
    return [(w["key"], w["name"]) for w in WORLDS]
