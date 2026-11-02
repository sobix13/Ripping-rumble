"""Rumble engine: pure game logic, no Discord. Deterministic for a given seed.

Rules
- Round targets scale with lobby size. A field reduced to two finishes on the next lap.
  Large lobbies use a readability floor when a configured target is too small.
- Each round keeps alive ** ((rounds_left - 1) / rounds_left) players (with jitter), so the field shrinks on a
  smooth curve and the last round is always the final. Non-final rounds never drop below 2 alive.
- Every alive ripper appears at most once per round. Killers survive, victims go out.
- Hazards (world mass events) clear several rippers in one line when the field is big, so rounds stay readable.
- Passive revives: random, capped per game, never in the last two rounds. One automatic Second Chance per game.
- Items: a Find gives a ripper an item. Callbacks only fire while a holder is still in. Transfers move items.
  A holder who goes out loses the item. At most two items exist at once.
- No line repeats inside a game until its pool runs dry.
"""
import math
import random
from dataclasses import dataclass, field

from .text import fill

HAZARD_MIN_ALIVE = 16
HAZARD_MAX = 8
MAX_ITEMS = 2
SECOND_CHANCE_MIN_PLAYERS = 8


@dataclass
class Settings:
    min_rounds: int = 2
    max_rounds: int = 16
    revive_rate: float = 0.12
    max_lines: int = 12
    hazards: bool = True
    second_chance: bool = True

    def clamp(self):
        self.min_rounds = max(2, min(12, int(self.min_rounds)))
        self.max_rounds = max(self.min_rounds, min(25, int(self.max_rounds)))
        self.revive_rate = max(0.0, min(0.5, float(self.revive_rate)))
        self.max_lines = max(6, min(20, int(self.max_lines)))
        return self


@dataclass
class Player:
    id: int
    name: str
    alive: bool = True
    kills: int = 0
    revives: int = 0
    out_seq: int = 0
    out_round: int = 0
    out_group: int = 0


@dataclass
class Event:
    kind: str
    line_id: str
    text: str
    actors: list
    out: list = field(default_factory=list)
    killer: int = None
    revived: int = None


@dataclass
class Round:
    number: int
    title: str
    events: list
    eliminated: list
    revived: list
    alive_after: int
    final: bool
    kinds: list
    second_chance: bool = False


def plan_rounds(n, s: Settings):
    if n < 2:
        return 1
    r = int(round(1 + 1.5 * math.log2(n)))
    r = max(s.min_rounds, min(s.max_rounds, r))
    # A tiny configured limit must not turn a large field into an unreadable final.
    capacity = 2 * s.max_lines + (2 * (HAZARD_MAX - 2) if s.hazards else 0)
    return min(25, max(r, 1 + math.ceil((n - 2) / capacity)))



class Game:
    def __init__(self, world, players, settings: Settings = None, seed=None, recent_line_ids=None):
        settings = (settings or Settings()).clamp()
        ids = [pid for pid, _ in players]
        if len(ids) < 2:
            raise ValueError("a rumble needs at least 2 rippers")
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate player ids")
        self.world = world
        self.s = settings
        self.rng = random.Random(seed)
        self.players = {pid: Player(pid, name) for pid, name in players}
        self.n = len(ids)
        self.total_rounds = plan_rounds(self.n, settings)
        self.round_no = 0
        self.used = set()
        self.recent_line_ids = set(recent_line_ids or [])
        self.capsule_used = False
        self.repeats = 0
        self.items = {}
        self.item_ids = {}
        self.item_serial = 0
        self.item_found_round = {}
        self.item_recalled = set()
        self.spotlight = set()
        self.revives_used = 0
        self.revive_cap = 0 if self.n < 4 else (1 if self.n <= 35 else 2)
        self.out_counter = 0
        self._event_group = 0
        self.last_hazard_round = -9
        self.finished = False
        self.winner = None
        self.win_text = ""
        self.history = []
        self.second_chance_round = None
        self.second_chance_done = False
        if settings.second_chance and self.total_rounds >= 4 and self.n >= SECOND_CHANCE_MIN_PLAYERS:
            lo = max(2, self.total_rounds // 3)
            hi = self.total_rounds - 2
            self.second_chance_round = self.rng.randint(lo, max(lo, hi))
        self.titles = self._plan_titles()
        self._vibes = {ln.id: ln.vibe for pool in world.pools.values() for ln in pool}

    # ---------- helpers ----------
    def alive_ids(self):
        return [p.id for p in self.players.values() if p.alive]

    def dead_ids(self):
        return [p.id for p in self.players.values() if not p.alive]

    def name(self, pid):
        return self.players[pid].name

    def _plan_titles(self):
        laps = list(self.world.laps)
        k = max(0, self.total_rounds - 1)
        if k == 0:
            return []
        if self.world.sequential:
            L = len(laps)
            if k <= L:
                # always open on the first title, then a random ordered pick of the rest
                idx = [0] + sorted(self.rng.sample(range(1, L), k - 1))
                return [laps[j] for j in idx]
            return laps + [f"Lap {{n}} · Overtime {i + 1}" for i in range(k - L)]
        if self.world.pin_first:
            first, rest = laps[0], laps[1:]
            self.rng.shuffle(rest)
            laps = [first] + rest
        else:
            self.rng.shuffle(laps)
        out = []
        while len(out) < k:
            out.extend(laps)
        return out[:k]

    def _pick(self, kind, pred=None, avoid_vibe=None):
        pool = self.world.pools[kind]
        ok = [ln for ln in pool if (pred is None or pred(ln))
              and not (self.capsule_used and "capsule" in ln.tags)]
        if not ok:
            return None
        cands = [ln for ln in ok if ln.id not in self.used]
        if not cands:
            self.repeats += 1
            for ln in ok:
                self.used.discard(ln.id)
            cands = ok
        fresh = [ln for ln in cands if ln.id not in self.recent_line_ids]
        if fresh:
            cands = fresh
        world_lines = [ln for ln in cands if not ln.id.startswith("g.")]
        if world_lines and self.rng.random() < 0.35:
            cands = world_lines
        weights = [ln.weight * (0.5 if avoid_vibe and ln.vibe == avoid_vibe else 1.0) for ln in cands]
        line = self.rng.choices(cands, weights)[0]
        self.used.add(line.id)
        if "capsule" in line.tags:
            self.capsule_used = True
        return line

    def _render(self, line, names, item="", lap=0, hazard_names=None):
        nm = {k: self.name(v) for k, v in names.items()}
        return fill(line.text, nm, self.world, self.rng, item=item, lap=lap, hazard_names=hazard_names)

    def _eliminate(self, pid, killer=None):
        p = self.players[pid]
        if not p.alive:
            raise RuntimeError("player already out")
        p.alive = False
        self.out_counter += 1
        p.out_seq = self.out_counter
        p.out_round = self.round_no
        p.out_group = self._event_group
        self.items.pop(pid, None)
        self.item_ids.pop(pid, None)
        self.item_found_round.pop(pid, None)
        if killer is not None:
            self.players[killer].kills += 1

    def _revive(self, pid):
        p = self.players[pid]
        p.alive = True
        p.revives += 1
        p.out_seq = 0
        p.out_round = 0
        p.out_group = 0

    def _singles_capacity(self):
        # eliminations that fit in one round as single lines (kills, wipes, multis average about 1.4 per line)
        return 2 * self.s.max_lines

    def _quota(self, alive, rem):
        target = alive ** ((rem - 1) / rem)
        q = int(round((alive - target) * self.rng.uniform(0.75, 1.25)))
        cap = self._singles_capacity()
        if self.s.hazards and alive >= HAZARD_MIN_ALIVE:
            cap += 2 * (HAZARD_MAX - 2)
        q = max(q, alive - 2 - max(0, rem - 2) * cap)
        if alive > 2:
            q = max(1, q)
        return max(0, min(alive - 2, q, cap))

    # ---------- rounds ----------
    def next_round(self) -> Round:
        if self.finished:
            raise RuntimeError("game is over")
        self.round_no += 1
        rem = self.total_rounds - self.round_no + 1
        if rem <= 1 or (self.round_no > 1 and len(self.alive_ids()) == 2):
            self.total_rounds = self.round_no
            return self._final_round()
        events, eliminated, revived = [], [], []
        last_vibe = [None]

        def add(ev, vibe):
            events.append(ev)
            last_vibe[0] = vibe

        # passive revive
        dead = [pid for pid in self.dead_ids() if self.players[pid].revives == 0]
        if (dead and self.round_no >= 2 and rem >= 3 and self.revives_used < self.revive_cap
                and self.rng.random() < self.s.revive_rate):
            pid = self.rng.choice(dead)
            line = self._pick("revive")
            self._revive(pid)
            self.revives_used += 1
            text, _ = self._render(line, {"A": pid})
            revive_ev = Event("revive", line.id, text, [pid], revived=pid)
            revived.append(pid)
        else:
            revive_ev = None

        alive = self.alive_ids()
        avail = [pid for pid in alive if pid not in revived]
        self.rng.shuffle(avail)
        need = self._quota(len(alive), rem)
        budget = self.s.max_lines - (1 if revive_ev else 0)

        # hazards: compress big fields so a round stays readable, plus the odd hazard for flavor
        if self.s.hazards and len(alive) >= HAZARD_MIN_ALIVE:
            singles = self._singles_capacity()
            hz = 0
            while need > 2 * (budget - len(events)) and hz < 2 and len(avail) > 2:
                h = min(HAZARD_MAX, need, len(avail) - 2)
                if h < 3:
                    break
                need -= self._hazard(avail, h, events, eliminated)
                hz += 1
            if (hz == 0 and need >= 5 and self.round_no - self.last_hazard_round >= 2
                    and self.rng.random() < 0.25):
                h = min(need, HAZARD_MAX, max(3, int(round(need * self.rng.uniform(0.4, 0.7)))))
                need -= self._hazard(avail, h, events, eliminated)
                hz += 1
            if hz:
                self.last_hazard_round = self.round_no
                last_vibe[0] = None

        while need > 0 and avail and len(events) < budget:
            lines_left = budget - len(events)
            pressure = need > max(1, lines_left - 1)
            holders = [h for h in avail if h in self.items]
            opts = []
            if len(avail) >= 2:
                opts.append(("kill", 44))
            opts.append(("wipe", 30))
            if need >= 2 and len(avail) >= 3:
                opts.append(("multi", 24 if pressure else 8))
            if need >= 2 and len(avail) >= 2:
                opts.append(("double", 15 if pressure else 5))
            if holders:
                if len(avail) >= 2:
                    opts.append(("call_B", 10))
                opts.append(("call_H", 3))
                if need >= 2 and len(avail) >= 3:
                    opts.append(("call_BC", 2))
            due = [h for h in holders if self.round_no - self.item_found_round.get(h, self.round_no) >= 2
                   and self.item_ids.get(h) not in self.item_recalled]
            if need > lines_left:
                opts = [(kind, weight) for kind, weight in opts if kind in ("multi", "double", "call_BC")]
                if not opts:
                    opts = [("wipe", 1)]
            if due and len(avail) >= 2 and need <= lines_left:
                kind, holders = "call_B", due
            else:
                kind = self.rng.choices([o[0] for o in opts], [o[1] for o in opts])[0]
            ev, outs = self._elim_event(kind, avail, holders, last_vibe[0])
            if ev is None:
                ev, outs = self._elim_event("wipe", avail, holders, last_vibe[0])
            eliminated += outs
            need -= len(outs)
            add(ev, self._vibe(ev))

        # non-lethal lines
        slots = self.s.max_lines - len(events) - (1 if revive_ev else 0)
        if need == 0 and not eliminated:
            target = min(len(avail), self.rng.randint(2, 4))
        else:
            target = min(3, max(1 if avail else 0, int(round(len(avail) * 0.15))))
        target = max(0, min(target, slots))
        made = 0
        while made < target and avail:
            ev = self._calm_event(avail, last_vibe[0])
            if ev is None:
                break
            add(ev, self._vibe(ev))
            made += 1

        if revive_ev:
            events.append(revive_ev)
        if len(events) < min(3, self.s.max_lines) and self.rng.random() < 0.35:
            events.insert(0, self._ambient())
        title = self.titles[self.round_no - 1] if self.round_no - 1 < len(self.titles) else "Lap {n}"
        title = title.replace("{n}", str(self.round_no))
        rd = Round(self.round_no, title, events, eliminated, revived, len(self.alive_ids()), False,
                   [e.kind for e in events])
        rd.second_chance = self._second_chance_due()
        self.spotlight.update(a for e in events if e.kind != "hazard" for a in e.actors)
        self.history.append(rd)
        return rd

    def _hazard(self, avail, h, events, eliminated):
        self._event_group += 1
        # Prefer members who already had an individual scene.
        avail.sort(key=lambda pid: pid in self.spotlight)
        victims = [avail.pop() for _ in range(h)]
        line = self._pick("hazard")
        text, _ = self._render(line, {}, hazard_names=[self.name(v) for v in victims])
        for v in victims:
            self._eliminate(v)
        eliminated += victims
        events.append(Event("hazard", line.id, text, list(victims), out=list(victims)))
        return h

    def _ambient(self):
        line = self._pick("ambient")
        text, _ = self._render(line, {})
        return Event("ambient", line.id, text, [])

    def _vibe(self, ev):
        return self._vibes.get(ev.line_id)

    def _elim_event(self, kind, avail, holders, last_vibe):
        self._event_group += 1
        rng = self.rng
        if kind == "kill":
            a, b = avail.pop(), avail.pop()
            line = self._pick("kill", avoid_vibe=last_vibe)
            text, _ = self._render(line, {"A": a, "B": b})
            self._eliminate(b, killer=a)
            return Event("kill", line.id, text, [a, b], out=[b], killer=a), [b]
        if kind == "wipe":
            a = avail.pop()
            line = self._pick("wipe", avoid_vibe=last_vibe)
            text, _ = self._render(line, {"A": a})
            self._eliminate(a)
            return Event("wipe", line.id, text, [a], out=[a]), [a]
        if kind == "multi":
            a, b, c = avail.pop(), avail.pop(), avail.pop()
            line = self._pick("multi", avoid_vibe=last_vibe)
            text, _ = self._render(line, {"A": a, "B": b, "C": c})
            self._eliminate(b, killer=a)
            self._eliminate(c, killer=a)
            return Event("multi", line.id, text, [a, b, c], out=[b, c], killer=a), [b, c]
        if kind == "double":
            a, b = avail.pop(), avail.pop()
            line = self._pick("double", avoid_vibe=last_vibe)
            text, _ = self._render(line, {"A": a, "B": b})
            self._eliminate(a)
            self._eliminate(b)
            return Event("double", line.id, text, [a, b], out=[a, b]), [a, b]
        if kind.startswith("call_") and holders:
            h = rng.choice(holders)
            item = self.items[h]
            self.item_recalled.add(self.item_ids.get(h))
            others = [x for x in avail if x != h]
            if kind == "call_B" and others:
                line = self._pick("call", pred=lambda ln: ln.out == "B", avoid_vibe=last_vibe)
                b = others[-1]
                avail.remove(h)
                avail.remove(b)
                text, _ = self._render(line, {"H": h, "B": b}, item=item)
                self._eliminate(b, killer=h)
                return Event("call", line.id, text, [h, b], out=[b], killer=h), [b]
            if kind == "call_H":
                line = self._pick("call", pred=lambda ln: ln.out == "H" and ("{B}" not in ln.text or others),
                                  avoid_vibe=last_vibe)
                if line is None:
                    return None, []
                names = {"H": h}
                avail.remove(h)
                if "{B}" in line.text:
                    b = others[-1]
                    avail.remove(b)
                    names["B"] = b
                text, _ = self._render(line, names, item=item)
                self._eliminate(h)
                return Event("call", line.id, text, list(names.values()), out=[h]), [h]
            if kind == "call_BC" and len(others) >= 2:
                line = self._pick("call", pred=lambda ln: ln.out == "B+C", avoid_vibe=last_vibe)
                b, c = others[-1], others[-2]
                for x in (h, b, c):
                    avail.remove(x)
                text, _ = self._render(line, {"H": h, "B": b, "C": c}, item=item)
                self._eliminate(b, killer=h)
                self._eliminate(c, killer=h)
                return Event("call", line.id, text, [h, b, c], out=[b, c], killer=h), [b, c]
        return None, []

    def _calm_event(self, avail, last_vibe):
        rng = self.rng
        holders = [h for h in avail if h in self.items]
        free = [x for x in avail if x not in self.items]
        opts = [("survive", 40)]
        if len(avail) >= 2:
            opts.append(("moment", 28))
        if len(self.items) < MAX_ITEMS and free:
            opts.append(("find", 14))
        if holders and free:
            opts.append(("transfer", 10))
        kind = rng.choices([o[0] for o in opts], [o[1] for o in opts])[0]
        if kind == "survive":
            a = avail.pop()
            line = self._pick("survive", avoid_vibe=last_vibe)
            text, _ = self._render(line, {"A": a})
            return Event("survive", line.id, text, [a])
        if kind == "moment":
            a, b = avail.pop(), avail.pop()
            line = self._pick("moment", avoid_vibe=last_vibe)
            text, _ = self._render(line, {"A": a, "B": b})
            return Event("moment", line.id, text, [a, b])
        if kind == "find":
            a = rng.choice(free)
            avail.remove(a)
            line = self._pick("find", avoid_vibe=last_vibe)
            text, model = self._render(line, {"A": a})
            self.items[a] = model if line.holds == "model" and model else self.world.grail
            self.item_serial += 1
            self.item_ids[a] = f"item-{self.item_serial}"
            self.item_found_round[a] = self.round_no
            return Event("find", line.id, text, [a])
        h = rng.choice(holders)
        a = rng.choice(free)
        avail.remove(h)
        avail.remove(a)
        line = self._pick("transfer", avoid_vibe=last_vibe)
        item = self.items.pop(h)
        text, _ = self._render(line, {"H": h, "A": a}, item=item)
        self.items[a] = item
        if h in self.item_ids:
            self.item_ids[a] = self.item_ids.pop(h)
            self.item_found_round[a] = self.item_found_round.pop(h)
        return Event("transfer", line.id, text, [h, a])

    def _final_round(self):
        alive = self.alive_ids()
        self.rng.shuffle(alive)
        events, eliminated = [], []
        overtime = len(alive) > 2
        title = self.world.overtime_title if overtime else self.world.final_title
        duel_a, duel_b = alive[0], alive[1]
        others = alive[2:]
        while others:
            need = len(others)
            self._event_group += 1
            if need >= 4 and self.s.hazards:     # a crowded final always sweeps in groups
                h = min(need, HAZARD_MAX)
                victims = [others.pop() for _ in range(h)]
                line = self._pick("hazard")
                text, _ = self._render(line, {}, hazard_names=[self.name(v) for v in victims])
                for v in victims:
                    self._eliminate(v)
                events.append(Event("hazard", line.id, text, victims, out=list(victims)))
                eliminated += victims
            elif need >= 2 and ((need + 1) // 2 + 1 >= self.s.max_lines - len(events)
                                or self.rng.random() < 0.35):
                a, b = others.pop(), others.pop()
                line = self._pick("double")
                text, _ = self._render(line, {"A": a, "B": b})
                self._eliminate(a)
                self._eliminate(b)
                events.append(Event("double", line.id, text, [a, b], out=[a, b]))
                eliminated += [a, b]
            else:
                a = others.pop()
                line = self._pick("wipe")
                text, _ = self._render(line, {"A": a})
                self._eliminate(a)
                events.append(Event("wipe", line.id, text, [a], out=[a]))
                eliminated.append(a)
        if not events and self.rng.random() < 0.7:
            events.append(self._ambient())
        item_holder = duel_a if duel_a in self.items else (duel_b if duel_b in self.items else None)
        if item_holder is not None:
            from .content import Line
            template = ("{A} launches the earlier {item} through the final loop. {B}'s entry stops short. {A} wins."
                        if item_holder == duel_a else
                        "{B}'s earlier {item} tips at the final loop. {A} crosses first. The final belongs to {A}.")
            if self.world.key == "gulf":
                template = ("{A} crosses first while the earlier {item} stays on the pit display. {B} finishes second."
                            if item_holder == duel_a else
                            "The earlier {item} sits on {B}'s pit display as {A} crosses the finish first. {B} leaves in second place.")
            elif self.world.key == "nft":
                template = ("{A} matches the earlier {item} to the final exhibit record. {B} submits the wrong edition. {A} wins."
                            if item_holder == duel_a else
                            "{B} brings the earlier {item} to the final comparison. {A} matches the requested edition first and wins.")
            line = Line("story.final.item", "duel", template, "race", (), 1)
            text, _ = self._render(line, {"A": duel_a, "B": duel_b}, item=self.items[item_holder])
            self.item_recalled.add(self.item_ids.get(item_holder))
        else:
            line = self._pick("duel")
            text, _ = self._render(line, {"A": duel_a, "B": duel_b})
        self._event_group += 1
        self._eliminate(duel_b, killer=duel_a)
        events.append(Event("duel", line.id, text, [duel_a, duel_b], out=[duel_b], killer=duel_a))
        eliminated.append(duel_b)
        self.winner = duel_a
        wl = self._pick("win")
        self.win_text, _ = self._render(wl, {"A": duel_a})
        self.finished = True
        rd = Round(self.round_no, title, events, eliminated, [], 1, True, [e.kind for e in events])
        self.history.append(rd)
        return rd

    # ---------- second chance ----------
    def _second_chance_due(self):
        return (self.second_chance_round is not None and not self.second_chance_done and not self.finished
                and self.round_no >= self.second_chance_round
                and len(self.dead_ids()) >= self.n // 2 and len(self.alive_ids()) >= 3
                and self.total_rounds - self.round_no >= 2
                and any(self.players[p].revives == 0 for p in self.dead_ids()))

    def resolve_second_chance(self, user_id):
        """Resolve the automatic return for an eligible fallen ripper, or record no return."""
        sc = self.world.second_chance
        if self.second_chance_done or self.finished:
            return sc["fail"][0], None
        self.second_chance_done = True
        if user_id is not None and user_id in self.players and not self.players[user_id].alive and self.players[user_id].revives == 0:
            self._revive(user_id)
            tmpl = self.rng.choice(sc["success"])
            text, _ = fill(tmpl, {"A": self.name(user_id)}, self.world, self.rng)
            return text, user_id
        return self.rng.choice(sc["fail"]), None

    def resolve_auto_second_chance(self):
        eligible = [pid for pid in self.dead_ids() if self.players[pid].revives == 0]
        return self.resolve_second_chance(self.rng.choice(eligible) if eligible else None)

    # ---------- results ----------
    def ranking(self):
        """Winner first, then by elimination order (last out = second place)."""
        alive = [p for p in self.players.values() if p.alive]
        out = sorted((p for p in self.players.values() if not p.alive), key=lambda p: -p.out_seq)
        return [p.id for p in alive] + [p.id for p in out]

    def ranking_places(self):
        places = {}
        groups = {}
        for pid in self.ranking():
            p = self.players[pid]
            key = (p.out_round, p.out_group) if not p.alive else ("winner", pid)
            if key not in groups:
                groups[key] = len(places) + 1
            places[pid] = groups[key]
        return places

    def summary(self):
        rank = self.ranking()
        best = max(self.players.values(), key=lambda p: (p.kills, -rank.index(p.id)))
        return {
            "winner": self.winner,
            "ranking": rank,
            "places": self.ranking_places(),
            "kills": {pid: p.kills for pid, p in self.players.items()},
            "top_killer": best.id if best.kills > 0 else None,
            "revives": sum(p.revives for p in self.players.values()),
            "rounds": self.round_no,
            "planned_rounds": self.total_rounds,
            "repeats": self.repeats,
            "players": self.n,
        }

    def run_all(self, second_chance_pick=None):
        """Play a whole game without delays (simulation and tests)."""
        while not self.finished:
            rd = self.next_round()
            if rd.second_chance:
                dead = self.dead_ids()
                if second_chance_pick:
                    self.resolve_second_chance(second_chance_pick(dead))
                else:
                    self.resolve_auto_second_chance()
        return self.summary()
