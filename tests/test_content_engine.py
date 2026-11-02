import collections
import random
import re

import pytest

from rumble.content import KINDS, get_world, world_keys
from rumble.content.validate import validate_all
from rumble.engine import Game, Settings, plan_rounds
from rumble.text import clean_name, fill, needs_an

NAMES = ["gulfkid", "redline_rex", "porsche*pilled", "@everyone", "a`b", "x" * 60, "ripper fam", "_under_"]


def test_content_has_no_errors():
    errs = [i for i in validate_all(near_dupes=True) if i[0] == "ERROR"]
    assert not errs, errs[:5]


@pytest.mark.parametrize("key", world_keys())
def test_every_line_fills_in_every_world(key):
    w = get_world(key)
    rng = random.Random(1)
    names = {"A": "aaa", "B": "bbb", "C": "ccc", "H": "hhh"}
    for kind in KINDS:
        assert w.pools[kind], f"{key} has no {kind} lines"
        for ln in w.pools[kind]:
            for _ in range(3):
                text, _ = fill(ln.text, names, w, rng, item="Twin Mill", lap=3, hazard_names=["x", "y", "z"])
                assert "{" not in text and "}" not in text, text
                assert not re.search(r"\ba [AEIOU]", text), text
                assert " a NFT" not in text, text
                assert "toy" not in text.lower().split(), text


def test_world_exclusions():
    for key in ("redline", "hunt", "gulf", "convention"):
        w = get_world(key)
        for kind in KINDS:
            for ln in w.pools[kind]:
                assert "onchain" not in ln.tags, (key, ln.id)


def test_clean_name_is_safe():
    for n in NAMES:
        c = clean_name(n)
        assert "*" not in c and "`" not in c and "\n" not in c
        assert len(c) <= 64
    assert "@​everyone" in clean_name("@everyone") or "everyone" in clean_name("@everyone")
    assert clean_name("") == "ripper"


def test_needs_an():
    assert needs_an("Audi Sport Quattro S1") and needs_an("NFT Garage pack")
    assert not needs_an("Ferrari F40") and not needs_an("'67 Camaro")


def _check(g, n):
    s = g.summary()
    assert g.finished and g.round_no == g.total_rounds
    assert g.alive_ids() == [s["winner"]]
    assert len(s["ranking"]) == n and len(set(s["ranking"])) == n
    assert s["ranking"][0] == s["winner"]
    for rd in g.history:
        c = collections.Counter(a for e in rd.events for a in e.actors)
        assert all(v == 1 for v in c.values()), f"round {rd.number} has a ripper twice"
        if not rd.final:
            assert rd.alive_after >= 2
        for e in rd.events:
            assert "{" not in e.text
            for pid in e.out:
                assert not g.players[pid].alive or pid in rd.revived or g.players[pid].revives > 0
    assert sum(s["kills"].values()) <= n - 1 + s["revives"]


@pytest.mark.parametrize("key", world_keys())
@pytest.mark.parametrize("n", [2, 3, 4, 7, 16, 30, 75, 160, 250])
def test_engine_invariants(key, n):
    w = get_world(key)
    for seed in range(12):
        g = Game(w, [(i, f"p{i}") for i in range(n)], Settings(), seed=seed * 31 + n)
        g.run_all()
        _check(g, n)
        assert max(len(rd.events) for rd in g.history) <= 20


def test_rounds_scale_and_caps():
    s = Settings()
    assert plan_rounds(2, s) == 2
    assert plan_rounds(250, s) <= s.max_rounds
    assert plan_rounds(10, Settings(min_rounds=9)) == 9
    s2 = Settings(min_rounds=30, max_rounds=1).clamp()
    assert 2 <= s2.min_rounds <= s2.max_rounds <= 25


def test_determinism():
    w = get_world("garage")
    def transcript(seed):
        g = Game(w, [(i, f"p{i}") for i in range(20)], Settings(), seed=seed)
        g.run_all(second_chance_pick=lambda dead: dead[0])
        return [e.text for rd in g.history for e in rd.events]
    assert transcript(5) == transcript(5)
    assert transcript(5) != transcript(6)


def test_second_chance_rules():
    w = get_world("garage")
    g = Game(w, [(i, f"p{i}") for i in range(12)], Settings(), seed=3)
    assert g.second_chance_round is not None
    while not g.finished:
        rd = g.next_round()
        if rd.second_chance:
            alive = g.alive_ids()[0]
            text, uid = g.resolve_second_chance(alive)          # an alive ripper cannot use it
            assert uid is None
            break
    g2 = Game(w, [(i, f"p{i}") for i in range(12)], Settings(), seed=3)
    while not g2.finished:
        rd = g2.next_round()
        if rd.second_chance:
            dead = g2.dead_ids()[0]
            text, uid = g2.resolve_second_chance(dead)
            assert uid == dead and g2.players[dead].alive and "p" in text
            break
    small = Game(w, [(1, "a"), (2, "b"), (3, "c")], Settings(), seed=1)
    assert small.second_chance_round is None and small.revive_cap == 0


def test_sequential_titles_keep_order():
    w = get_world("redline")
    for seed in range(30):
        g = Game(w, [(i, f"p{i}") for i in range(40)], Settings(), seed=seed)
        years = [int(t[:4]) for t in g.titles]
        assert years == sorted(years) and g.titles[0] == w.laps[0]
    gw = get_world("gulf")
    g = Game(gw, [(i, f"p{i}") for i in range(40)], Settings(), seed=2)
    assert g.titles[0] == gw.laps[0]


def test_items_and_callbacks_consistent():
    w = get_world("convention")
    calls = 0
    for seed in range(60):
        g = Game(w, [(i, f"p{i}") for i in range(30)], Settings(), seed=seed)
        while not g.finished:
            before = dict(g.items)
            rd = g.next_round()
            for e in rd.events:
                if e.kind == "call":
                    calls += 1
                    assert e.actors[0] in before, "callback holder had no item"
            assert len(g.items) <= 2
            for h in g.items:
                assert g.players[h].alive
    assert calls > 20


def test_hazard_names_and_big_round_sizes():
    w = get_world("hunt")
    g = Game(w, [(i, f"ripper{i}") for i in range(250)], Settings(), seed=9)
    g.run_all()
    for rd in g.history:
        body = "\n".join(e.text for e in rd.events)
        assert len(body) < 3900
        for e in rd.events:
            if e.kind == "hazard":
                assert 1 <= len(e.out) <= 15
