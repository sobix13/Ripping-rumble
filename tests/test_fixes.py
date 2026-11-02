"""Regression tests for the independent review findings."""
import asyncio
import time

import pytest

from rumble.bot import RumbleBot, RumbleCog, STOP_TEXT
from rumble.config import GuildConfig
from rumble.engine import Game, Settings, plan_rounds
from rumble.content import get_world
from rumble.runner import GameRunner
from rumble.text import clean_name
from tests.fakes import FakeClock, FakeGuild, FakePerms


@pytest.fixture
async def rbot(tmp_path):
    bot = RumbleBot(str(tmp_path / "fx.sqlite3"))
    await bot.db.open()
    yield bot
    await bot.db.close()


class _T:
    def __init__(self, done=False):
        self._done = done
        self.cancelled = False

    def done(self):
        return self._done

    def cancel(self):
        self.cancelled = True


class _R:
    def __init__(self, state):
        self.state = state
        self.task = _T()


def test_stop_refused_once_the_winner_is_decided(tmp_path):
    bot = RumbleBot(str(tmp_path / "x.sqlite3"))
    bot.games[1] = _R("finishing")
    assert bot.stop_game(1) == "finishing" and not bot.games[1].task.cancelled
    bot.games[2] = _R("running")
    assert bot.stop_game(2) == "stopped" and bot.games[2].task.cancelled
    assert bot.stop_game(3) == "none"
    assert set(STOP_TEXT) == {"stopped", "finishing", "none"}


async def test_winner_role_rules(rbot):
    g = FakeGuild()
    champ = g.add_role("Rumble Champion", 3)
    cfg = GuildConfig(guild_id=g.id, winner_role_id=champ.id, winner_role_hours=24)
    await rbot.db.approve_winner_role(g.id, champ.id)
    had = g.add_member("had_it", roles=[champ])
    assert await rbot.grant_winner_role(g, had.id, cfg)
    assert had.added == [] and await rbot.db.active_winner_roles(g.id) == []      # pre-existing: untouched
    new = g.add_member("newbie")
    assert await rbot.grant_winner_role(g, new.id, cfg)
    rows = await rbot.db.active_winner_roles(g.id)
    assert new.added == [champ] and rows[0]["user_id"] == new.id
    first_exp = rows[0]["expires_at"]
    await asyncio.sleep(1.1)
    assert await rbot.grant_winner_role(g, new.id, cfg)                             # repeat winner: expiry pushed
    assert (await rbot.db.active_winner_roles(g.id))[0]["expires_at"] > first_exp
    assert new.added == [champ]


async def test_schedule_waits_while_a_rumble_runs(rbot, monkeypatch):
    g = FakeGuild()
    ch = g.add_channel()
    cfg = GuildConfig(guild_id=g.id, channel_id=ch.id, setup_done=True)
    await rbot.db.save_config(cfg)
    now = int(time.time())
    sid = await rbot.db.add_schedule(g.id, "garage", "once", run_at=now - 30)
    monkeypatch.setattr(rbot, "get_guild", lambda gid: g if gid == g.id else None)
    started = []

    async def fake_start(guild, cfg, world=None, host=None, source="manual"):
        started.append(world)
        return object(), []
    monkeypatch.setattr(rbot, "start_game", fake_start)
    cog = RumbleCog(rbot)
    rbot.games[g.id] = _R("running")
    await cog._run_schedules()
    assert started == [] and (await rbot.db.schedules(g.id))[0]["last_run_at"] is None   # not lost
    rbot.games.pop(g.id)
    await cog._run_schedules()
    rows = await rbot.db.schedules(g.id)
    assert started == ["garage"] and rows[0]["enabled"] == 0 and rows[0]["last_run_at"]


def test_bidi_and_control_characters_stripped():
    assert clean_name("evil‮name⁦x") == "evilnamex"
    assert clean_name("line\nbreak") == "line break"


def test_tiny_max_laps_cannot_cram_a_big_lobby():
    s = Settings(min_rounds=2, max_rounds=2).clamp()
    assert plan_rounds(250, s) >= 8
    g = Game(get_world("garage"), [(i, f"p{i}") for i in range(250)], Settings(min_rounds=2, max_rounds=2,
                                                                               hazards=False), seed=1)
    g.run_all()
    assert max(len(rd.events) for rd in g.history) <= 25


def test_redline_has_no_gacha_or_wallet_lines():
    w = get_world("redline")
    for pool in w.pools.values():
        for ln in pool:
            assert "rc" not in ln.tags and "onchain" not in ln.tags


async def test_stop_during_automatic_second_chance_needs_no_button(tmp_path):
    from rumble.db import Database
    from tests.fakes import FakeBot
    db = Database(str(tmp_path / "sc.sqlite3"))
    await db.open()
    try:
        bot = FakeBot(db)
        g = FakeGuild()
        ch = g.add_channel()
        cfg = GuildConfig(guild_id=g.id, channel_id=ch.id, setup_done=True, second_chance_seconds=30).clamp()
        runner = GameRunner(bot, g, ch, cfg, world_key="garage", clock=FakeClock(), seed=3)
        bot.games[g.id] = runner
        for i in range(14):
            runner.try_join(g.add_member(f"r{i}"))
        gate = asyncio.Event()
        original_send = ch.send

        async def hold_automatic_return(**kwargs):
            embed = kwargs.get("embed")
            if embed and embed.footer.text.endswith("Second Chance"):
                assert kwargs.get("view") is None
                gate.set()
                await asyncio.Event().wait()
            return await original_send(**kwargs)

        ch.send = hold_automatic_return
        task = asyncio.create_task(runner.run())
        runner.task = task
        await asyncio.wait_for(gate.wait(), 2)
        assert runner.game.second_chance_done
        task.cancel()
        await asyncio.wait_for(task, 10)
        assert runner.sc_view is None
        assert all(m.kwargs.get("view") is None for m in ch.sent[1:])
        assert runner.state == "stopped" and runner.sc_open is False
    finally:
        await db.close()
