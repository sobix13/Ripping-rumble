import asyncio

import discord
import pytest

from rumble.config import GuildConfig
from rumble.db import Database
from rumble.runner import GameRunner
from tests.fakes import FakeBot, FakeClock, FakeGuild, FakePerms


_OPEN = []


@pytest.fixture(autouse=True)
async def _close_dbs():
    yield
    while _OPEN:
        await _OPEN.pop().close()


async def setup(tmp_path, n=8, world="garage", **cfgkw):
    db = Database(str(tmp_path / "r.sqlite3"))
    await db.open()
    _OPEN.append(db)
    bot = FakeBot(db)
    guild = FakeGuild()
    ch = guild.add_channel()
    champ = guild.add_role("Rumble Champion", 5)
    kw = dict(guild_id=guild.id, channel_id=ch.id, setup_done=True, winner_role_id=champ.id, lobby_seconds=30)
    kw.update(cfgkw)
    cfg = GuildConfig(**kw).clamp()
    clock = FakeClock()
    runner = GameRunner(bot, guild, ch, cfg, world_key=world, host="mod", clock=clock, seed=4)
    bot.games[guild.id] = runner
    members = [guild.add_member(f"ripper_{i}") for i in range(n)]
    return db, bot, guild, ch, cfg, runner, members, clock


async def _wait_lobby(runner):
    for _ in range(1000):
        if runner.lobby_msg is not None:
            return
        await asyncio.sleep(0.005)
    raise AssertionError("lobby never opened")


async def test_full_rumble_with_second_chance(tmp_path):
    db, bot, guild, ch, cfg, runner, members, clock = await setup(tmp_path, n=12)
    for m in members:
        ok, _ = runner.try_join(m)
        assert ok
    assert runner.try_join(members[0])[0] is False            # already in
    task = asyncio.create_task(runner.run())
    await asyncio.wait_for(task, 20)
    g = runner.game
    assert runner.state == "finished" and g.finished
    assert g.second_chance_done
    assert sum(p.revives for p in g.players.values()) >= 1
    assert runner.sc_view is None and runner.sc_open is False
    assert not runner.try_second_chance(members[0])[0]
    lobby = ch.sent[0]
    assert lobby.kwargs.get("view") is not None and lobby.kwargs.get("file") is not None
    assert lobby.edits and "locked" in lobby.edits[-1]["embed"].description
    final = ch.sent[-1]
    assert f"<@{g.winner}>" in final.kwargs["content"]
    assert final.kwargs["allowed_mentions"].users[0].id == g.winner
    round_msgs = [m for m in ch.sent[1:-1] if m.kwargs.get("embeds")]
    assert len(round_msgs) >= g.total_rounds
    sc_posts = [m for m in ch.sent[1:-1] if m.kwargs.get("embed") and
                m.kwargs["embed"].footer.text.endswith("Second Chance")]
    assert len(sc_posts) == 1
    assert all(m.kwargs.get("view") is None for m in ch.sent[1:]), "Join-only games must not ask for extra clicks"
    lb = await db.leaderboard(guild.id, 50)
    assert len(lb) == 12 and lb[0]["user_id"] == g.winner and lb[0]["wins"] == 1
    assert bot.granted == [(guild.id, g.winner, cfg.winner_role_id)]
    assert guild.id not in bot.games
    assert not bot.errors, bot.errors
    games = await db.recent_games(guild.id)
    assert games[0]["status"] == "finished" and games[0]["winner_id"] == g.winner
    await db.close()


async def test_cancel_when_not_enough(tmp_path):
    db, bot, guild, ch, cfg, runner, members, clock = await setup(tmp_path, n=1, min_players=3)
    runner.try_join(members[0])
    task = asyncio.create_task(runner.run())
    await asyncio.wait_for(task, 10)
    assert runner.state == "cancelled"
    assert "Not enough" in ch.sent[-1].kwargs["embed"].title
    assert (await db.recent_games(guild.id))[0]["status"] == "cancelled"
    assert guild.id not in bot.games
    await db.close()


async def test_stop_mid_game(tmp_path):
    db, bot, guild, ch, cfg, runner, members, clock = await setup(tmp_path, n=20)
    for m in members:
        runner.try_join(m)
    task = asyncio.create_task(runner.run())
    runner.task = task
    gate = asyncio.Event()
    original_send = ch.send

    async def hold_round(**kwargs):
        if kwargs.get("embeds") and runner.game and not runner.game.finished:
            gate.set()
            await asyncio.Event().wait()
        return await original_send(**kwargs)

    ch.send = hold_round
    await asyncio.wait_for(gate.wait(), 2)
    task.cancel()
    await asyncio.wait_for(task, 10)
    assert runner.state == "stopped"
    assert ch.sent[-1].kwargs["embed"].title == "Rumble stopped"
    assert (await db.recent_games(guild.id))[0]["status"] == "stopped"
    assert guild.id not in bot.games
    await db.close()


async def test_join_rules_and_start_now(tmp_path):
    db, bot, guild, ch, cfg, runner, members, clock = await setup(tmp_path, n=3, max_players=2)
    vip = guild.add_role("VIP")
    runner.cfg.player_role_ids = [vip.id]
    ok, msg = runner.try_join(members[0])
    assert not ok and "Entry requires" in msg
    members[0].roles.append(vip)
    members[1].roles.append(vip)
    members[2].roles.append(vip)
    assert runner.try_join(members[0])[0] and runner.try_join(members[1])[0]
    assert runner.try_join(members[2]) == (False, "The grid is full.")
    botm = guild.add_member("otherbot", roles=[vip])
    botm.bot = True
    assert runner.try_join(botm)[0] is False
    assert runner.try_leave(members[2])[0] is False
    assert runner.try_leave(members[1])[0] is True and runner.try_join(members[1])[0] is True
    assert runner.try_start_now(members[0])[0] is False                    # not a host
    host = guild.add_member("mod", perms=FakePerms(manage_guild=True))
    assert runner.try_start_now(host)[0] is True
    task = asyncio.create_task(runner.run())
    await asyncio.wait_for(task, 20)
    assert runner.state == "finished"
    assert clock.slept < 30 + 200                                          # lobby ended early
    assert runner.try_join(members[2])[0] is False                         # locked after start
    await db.close()


@pytest.mark.parametrize("world", ["redline", "hunt", "nft", "gulf", "convention"])
async def test_every_world_runs_big_lobby(tmp_path, world):
    db, bot, guild, ch, cfg, runner, members, clock = await setup(tmp_path, n=130, world=world, max_players=200)
    guild.emojis = [__import__("tests.fakes", fromlist=["FakeEmoji"]).FakeEmoji("rip_jackpot")]
    for m in members:
        assert runner.try_join(m)[0]
    task = asyncio.create_task(runner.run())
    await asyncio.wait_for(task, 60)
    assert runner.state == "finished", bot.errors
    assert not bot.errors, bot.errors
    await db.close()


async def test_images_off_and_ping_role(tmp_path):
    db, bot, guild, ch, cfg, runner, members, clock = await setup(tmp_path, n=4, images=False)
    ping = guild.add_role("Rumble pings")
    runner.cfg.ping_role_id = ping.id
    for m in members:
        runner.try_join(m)
    task = asyncio.create_task(runner.run())
    await asyncio.wait_for(task, 20)
    lobby = ch.sent[0].kwargs
    assert f"<@&{ping.id}>" in lobby["content"]
    assert lobby["allowed_mentions"].roles[0].id == ping.id
    assert all(m.kwargs.get("file") is None for m in ch.sent)
    await db.close()


async def test_send_failure_is_reported_not_raised(tmp_path):
    db, bot, guild, ch, cfg, runner, members, clock = await setup(tmp_path, n=4)

    async def boom(**kw):
        raise discord.Forbidden(type("R", (), {"status": 403, "reason": "Forbidden"})(), "Missing Access")
    ch.send = boom
    await asyncio.wait_for(runner.run(), 10)
    assert runner.state == "error"
    assert bot.errors and guild.id not in bot.games
    await db.close()
