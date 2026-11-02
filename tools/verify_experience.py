"""Offline experience checks, item outcomes and ten-game series through real SQLite.

Run from the project root: python tools/verify_experience.py --games 200 --out docs/verification
This measures engine/render behavior. It does not measure Discord latency or human enjoyment.
"""
import argparse
import asyncio
import collections
import json
import math
from pathlib import Path
import statistics
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rumble import render
from rumble.content import get_world, world_keys
from rumble.db import Database
from rumble.engine import Game, Settings
from rumble.text import reading_pause
from tools.simulate import check_game


class CheckedGame(Game):
    """Observe existing mutations without changing any random choices."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.item_outcomes = {}

    def check_items(self):
        assert set(self.items) == set(self.item_ids) == set(self.item_found_round)
        assert len(self.items) <= 2
        assert len(set(self.item_ids.values())) == len(self.item_ids)
        assert all(self.players[pid].alive for pid in self.items)

    def _eliminate(self, pid, killer=None):
        iid = self.item_ids.get(pid)
        super()._eliminate(pid, killer)
        if iid is not None:
            self.item_outcomes[iid]['dropped_round'] = self.round_no
        self.check_items()

    def _calm_event(self, avail, last_vibe):
        before = dict(self.item_ids)
        names = dict(self.items)
        ages = dict(self.item_found_round)
        event = super()._calm_event(avail, last_vibe)
        if event and event.kind == 'find':
            holder = event.actors[0]
            iid = self.item_ids[holder]
            assert iid not in self.item_outcomes
            self.item_outcomes[iid] = dict(found_round=self.round_no, callbacks=0, final=False, transfers=0)
        elif event and event.kind == 'transfer':
            holder, recipient = event.actors
            assert self.item_ids[recipient] == before[holder]
            assert self.items[recipient] == names[holder]
            assert self.item_found_round[recipient] == ages[holder]
            assert holder not in self.items
            self.item_outcomes[before[holder]]['transfers'] += 1
        self.check_items()
        return event

    def _elim_event(self, kind, avail, holders, last_vibe):
        before = dict(self.item_ids)
        names = dict(self.items)
        event, outs = super()._elim_event(kind, avail, holders, last_vibe)
        if event and event.kind == 'call':
            holder = event.actors[0]
            assert holder in before and names[holder] in event.text
            self.item_outcomes[before[holder]]['callbacks'] += 1
        self.check_items()
        return event, outs

    def _final_round(self):
        before = dict(self.item_ids)
        rd = super()._final_round()
        for event in rd.events:
            if event.line_id == 'story.final.item':
                holder = next(pid for pid in event.actors if pid in before)
                self.item_outcomes[before[holder]]['final'] = True
        self.check_items()
        return rd


def distribution(values):
    values = sorted(values)
    if not values:
        return None
    return dict(mean=round(statistics.mean(values), 3), min=values[0],
                p50=values[math.ceil(len(values) * 0.5) - 1],
                p95=values[math.ceil(len(values) * 0.95) - 1], max=values[-1])


def play(game, recent=(), transcript=None):
    sc_round = None
    counts = collections.Counter()
    recent_hits = 0
    eliminations = []
    round_chars = []
    reading_seconds = []
    pauses = []
    for _ in range(26):
        alive_before = set(game.alive_ids())
        rd = game.next_round()
        assert len(rd.events) <= game.s.max_lines
        for event in rd.events:
            if event.kind != 'revive':
                assert set(event.actors) <= alive_before
            if event.kind in ('kill', 'duel', 'multi'):
                assert event.out == event.actors[1:]
                assert event.killer == event.actors[0]
            elif event.kind in ('wipe', 'double', 'hazard'):
                assert event.out == event.actors
            elif event.kind == 'call':
                line = next(line for line in game.world.pools['call'] if line.id == event.line_id)
                assert event.out == (event.actors[:1] if line.out == 'H' else event.actors[1:])
            counts[event.kind] += 1
            recent_hits += int(event.line_id in recent and event.line_id != 'story.final.item')
        eliminations.append(len(rd.eliminated))
        messages = render.round_messages(game.world, rd, total_rounds=game.total_rounds, game=game)
        bodies = []
        for embeds in messages:
            assert len(embeds) <= 10 and sum(len(embed) for embed in embeds) <= 6000
            for embed in embeds:
                assert len(embed.description or '') <= 4096
                bodies.append(embed.description or '')
        body = '\n'.join(bodies)
        round_chars.append(len(body))
        reading_seconds.append(round(len(body.split()) / 3.0, 2))  # 180 words/minute assumption
        if transcript is not None:
            transcript.append(f'Lap {rd.number}: {rd.title}\n' + body)
        if rd.second_chance:
            assert game.round_no >= game.second_chance_round
            assert len(game.dead_ids()) >= game.n // 2 and len(game.alive_ids()) >= 3
            assert game.total_rounds - game.round_no >= 2
            text, uid = game.resolve_auto_second_chance()
            assert uid is not None
            sc_round = game.round_no
            if transcript is not None:
                transcript.append('Automatic Second Chance: ' + text)
            body += '\n' + text
            reading_seconds[-1] = round(len(body.split()) / 3.0, 2)
            round_chars[-1] = len(body)
        if not rd.final:
            pauses.append(reading_pause(body, 10))
        if game.finished:
            break
    assert game.finished, 'game did not finish within 26 laps'
    assert not check_game(game, game.n), check_game(game, game.n)
    assert all(player.revives <= 1 for player in game.players.values())
    assert not any(not rd.eliminated for rd in game.history[1:])
    if not game.s.hazards:
        assert counts['hazard'] == 0
    if not game.s.second_chance:
        assert sc_round is None
    outcomes = list(game.item_outcomes.values())
    return dict(rounds=game.round_no, quiet_rounds=sum(not n for n in eliminations),
                eliminations=eliminations, kinds=dict(counts), second_chance_round=sc_round,
                revives=sum(p.revives for p in game.players.values()),
                items_found=len(outcomes), items_recalled=sum(o['callbacks'] > 0 or o['final'] for o in outcomes),
                items_dropped_without_recall=sum('dropped_round' in o and not o['callbacks'] and not o['final'] for o in outcomes),
                item_final_count=sum(o['final'] for o in outcomes),
                round_chars=round_chars, reading_seconds=reading_seconds,
                recent_hits=recent_hits, repeats=game.repeats,
                scripted_seconds=3 + sum(pauses) + 2,
                fixed_10s_seconds=3 + 10 * (game.round_no - 1) + 2)


def summarize(records):
    kinds = collections.Counter()
    for record in records:
        kinds.update(record['kinds'])
    found = sum(r['items_found'] for r in records)
    recalled = sum(r['items_recalled'] for r in records)
    sc_rounds = [r['second_chance_round'] for r in records if r['second_chance_round'] is not None]
    return dict(games=len(records), rounds=distribution([r['rounds'] for r in records]),
                scripted_seconds=distribution([r['scripted_seconds'] for r in records]),
                fixed_10s_seconds=distribution([r['fixed_10s_seconds'] for r in records]),
                reading_seconds_per_round=distribution([v for r in records for v in r['reading_seconds']]),
                round_chars=distribution([v for r in records for v in r['round_chars']]),
                eliminations_per_round=distribution([v for r in records for v in r['eliminations']]),
                kinds=dict(kinds), second_chance_games=len(sc_rounds), second_chance_round=distribution(sc_rounds),
                revives=distribution([r['revives'] for r in records]),
                quiet_rounds=sum(r['quiet_rounds'] for r in records),
                items_found=found, items_recalled=recalled,
                item_recall_rate=round(recalled / found, 4) if found else None,
                item_finals=sum(r['item_final_count'] for r in records),
                items_dropped_without_recall=sum(r['items_dropped_without_recall'] for r in records),
                recent_hits=sum(r['recent_hits'] for r in records), repeats=sum(r['repeats'] for r in records))


async def series_check(out):
    records, traces = [], []
    with tempfile.TemporaryDirectory() as temp:
        db = Database(str(Path(temp) / 'series.sqlite3'))
        await db.open()
        try:
            for guild_id, key in enumerate(world_keys(), 1):
                baseline_hits = 0
                results = []
                for i, n in enumerate((2, 3, 4, 5, 8, 12, 20, 35, 60, 60)):
                    # Reopen SQLite each game to exercise persisted history, not a local deque.
                    await db.close()
                    await db.open()
                    recent = await db.recent_content_ids(guild_id)
                    g = CheckedGame(get_world(key), [(p, f'Ripper{p:03}') for p in range(n)],
                                    seed=100003 + i, recent_line_ids=recent)
                    traces.append(f'\nWORLD {key}, GAME {i + 1}, PLAYERS {n}, SEED {100003 + i}')
                    record = play(g, recent, traces)
                    record.update(world=key, game=i + 1, players=n)
                    results.append(record)
                    baseline = CheckedGame(get_world(key), [(p, f'Ripper{p:03}') for p in range(n)], seed=100003 + i)
                    baseline_hits += play(baseline, recent)['recent_hits']
                    places = g.ranking_places()
                    rows = [dict(user_id=pid, name=p.name, place=places[pid], kills=p.kills, won=pid == g.winner)
                            for pid, p in g.players.items()]
                    gid = await db.game_started(guild_id, key, 'offline-series')
                    await db.finalize_game(gid, guild_id, rows, g.winner, g.round_no,
                                           dict(channel_id=guild_id, line_ids=sorted(set(g.used) |
                                                {e.line_id for rd in g.history for e in rd.events})))
                    traces.append('WINNER: ' + g.win_text + '\nRANKING: ' + str(g.summary()['ranking']))
                summary = summarize(results)
                summary.update(world=key, baseline_recent_hits=baseline_hits)
                records.append(summary)
        finally:
            await db.close()
    (out / 'series_transcripts.txt').write_text('\n\n'.join(traces), encoding='utf-8')
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', type=int, default=200)
    parser.add_argument('--out', type=Path, default=Path('docs/verification'))
    args = parser.parse_args()
    if args.games < 1:
        parser.error('--games must be positive')
    args.out.mkdir(parents=True, exist_ok=True)
    matrix = []
    for key in world_keys():
        for n in (2, 3, 4, 5, 8, 12, 20, 35, 60, 100, 150, 250):
            records = [play(CheckedGame(get_world(key), [(p, f'Ripper{p:03}') for p in range(n)],
                                       seed=i * 7919 + n)) for i in range(args.games)]
            row = summarize(records)
            row.update(world=key, players=n)
            matrix.append(row)
    edge_games = 0
    for key in world_keys():
        for n in (2, 3, 4, 5, 6, 7, 8, 15, 16, 17, 35, 36, 60, 250):
            for options in (dict(hazards=False), dict(second_chance=False), dict(revive_rate=0),
                            dict(revive_rate=0.5), dict(min_rounds=2, max_rounds=2, max_lines=6)):
                for seed in range(10):
                    play(CheckedGame(get_world(key), [(p, f'Ripper{p:03}') for p in range(n)],
                                     Settings(**options), seed=seed))
                    edge_games += 1
    report = dict(matrix=matrix, edge_games=edge_games, series=asyncio.run(series_check(args.out)),
                  assumptions=dict(scripted_seconds='3 + sum(adaptive pauses, minimum10/cap30) + final_pause(2), excludes lobby/network',
                                   reading_seconds='180 English words/minute for round descriptions and SC results, estimation only'),
                  live_discord_tested=False)
    (args.out / 'experience.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'PASS: {len(matrix) * args.games} matrix games, {edge_games} edge games, 60 persisted series games')
    print('Item identity, transfers, callbacks, final references, return timing and rendered message limits checked.')
    print('Real Discord latency and spectator enjoyment were not tested.')


if __name__ == '__main__':
    main()
