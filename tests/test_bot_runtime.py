"""Failure-path checks for shutdown, startup acknowledgement and cosmetic awards."""
import asyncio
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

from rumble.bot import RumbleBot, RumbleCog
from rumble.config import GuildConfig
from rumble.perms import winner_role_problem
from tests.fakes import FakeGuild, FakePerms
from tests.test_ui_bot import Inter


@pytest.fixture
async def live_bot(tmp_path):
    bot = RumbleBot(str(tmp_path / "runtime.sqlite3"))
    await bot.db.open()
    yield bot
    await bot.close()


async def test_close_waits_for_decided_finish_before_database_close(live_bot):
    gate = asyncio.Event()
    stored = []

    async def finish():
        await gate.wait()
        assert live_bot.db.conn is not None
        stored.append(await live_bot.db.ping())

    finish_task = live_bot.track_finish_task(asyncio.create_task(finish()))

    async def wrapper():
        await asyncio.shield(finish_task)

    runner = SimpleNamespace(task=asyncio.create_task(wrapper()), finish_task=finish_task,
                             state="running", game=SimpleNamespace(finished=True), shutdown=False)
    live_bot.games[1] = runner
    closing = asyncio.create_task(live_bot.close())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert live_bot.closing and not closing.done() and live_bot.db.conn is not None
    assert live_bot.preflight(FakeGuild(), GuildConfig(guild_id=1))
    gate.set()
    await asyncio.wait_for(closing, 2)
    await live_bot.close()
    assert stored == [True] and live_bot.db.conn is None


def test_stop_is_idempotent_and_checks_engine_finished(tmp_path):
    bot = RumbleBot(str(tmp_path / "unused"))
    task = SimpleNamespace(done=lambda: False, cancel_calls=0)
    task.cancel = lambda: setattr(task, "cancel_calls", task.cancel_calls + 1)
    runner = SimpleNamespace(task=task, state="running", game=SimpleNamespace(finished=False))
    bot.games[1] = runner
    assert bot.stop_game(1) == bot.stop_game(1) == "stopped"
    assert task.cancel_calls == 1
    runner.game.finished = True
    assert bot.stop_game(1) == "finishing" and task.cancel_calls == 1


async def test_start_failure_never_reports_an_open_lobby(live_bot):
    guild = FakeGuild()
    channel = guild.add_channel()
    cfg = GuildConfig(guild_id=guild.id, channel_id=channel.id, setup_done=True)

    async def broken_send(**kwargs):
        raise RuntimeError("attachment rejected")

    channel.send = broken_send
    runner, problems = await live_bot.start_game(guild, cfg)
    assert runner is None and "attachment rejected" in problems[0]
    assert guild.id not in live_bot.games


async def test_commands_acknowledge_before_database_wait(live_bot, monkeypatch):
    guild = FakeGuild()
    admin = guild.add_member("admin", perms=FakePerms(manage_guild=True))
    interaction = Inter(admin, guild)

    async def get_config(guild_id):
        assert interaction.response.is_done()
        return GuildConfig(guild_id=guild_id)

    monkeypatch.setattr(live_bot.db, "get_config", get_config)
    cog = RumbleCog(live_bot)
    await cog.stop.callback(cog, interaction)
    assert interaction.response.calls[0][0] == "defer"
    assert interaction.edited[-1]["content"] == "No rumble is running."


async def test_leaderboard_has_server_cooldown(live_bot):
    guild = FakeGuild()
    interaction = Inter(guild.add_member("reader"), guild)
    interaction.created_at = datetime.now(timezone.utc)
    command = RumbleCog(live_bot).leaderboard
    for check in command.checks:
        assert await check(interaction)
    with pytest.raises(discord.app_commands.CommandOnCooldown):
        for check in command.checks:
            await check(interaction)


async def test_awards_fail_closed_and_retry_failed_add(live_bot):
    guild = FakeGuild()
    role = guild.add_role("Champion", 2)
    user = guild.add_member("winner")
    cfg = GuildConfig(guild_id=guild.id, winner_role_id=role.id)
    assert not await live_bot.grant_winner_role(guild, user.id, cfg)
    await live_bot.db.approve_winner_role(guild.id, role.id)
    role.permissions = discord.Permissions(administrator=True)
    assert not await live_bot.grant_winner_role(guild, user.id, cfg)
    role.permissions = discord.Permissions.none()
    original = user.add_roles

    async def refused(*roles, **kwargs):
        raise discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "role refused")

    user.add_roles = refused
    assert not await live_bot.grant_winner_role(guild, user.id, cfg)
    assert await live_bot.db.get_winner_role(guild.id, user.id, role.id) is not None
    user.add_roles = original
    assert await live_bot.grant_winner_role(guild, user.id, cfg)
    assert user.added == [role]


def test_awards_reject_positive_channel_override_and_operator_hierarchy():
    guild = FakeGuild()
    role = guild.add_role("Champion", 2)
    operator = guild.add_member("operator")
    assert winner_role_problem(guild, operator, role) is None
    operator.top_role = role
    assert "below" in winner_role_problem(guild, operator, role)
    operator.top_role = guild.me.top_role
    guild.channels = [SimpleNamespace(overwrites_for=lambda _: discord.PermissionOverwrite(view_channel=True))]
    assert "overrides" in winner_role_problem(guild, operator, role)


async def test_stale_expiry_snapshot_does_not_remove_renewed_award(live_bot, monkeypatch):
    guild = FakeGuild()
    role = guild.add_role("Champion", 2)
    winner = guild.add_member("winner")
    cfg = GuildConfig(guild_id=guild.id, winner_role_id=role.id)
    await live_bot.db.approve_winner_role(guild.id, role.id)
    await live_bot.db.add_winner_role(guild.id, winner.id, role.id, int(time.time()) - 1)
    stale = (await live_bot.db.expired_winner_roles())[0]
    entered, release = asyncio.Event(), asyncio.Event()
    original = winner.add_roles

    async def held_add(*roles, **kwargs):
        entered.set()
        await release.wait()
        await original(*roles, **kwargs)

    async def expired_snapshot():
        return [stale]

    winner.add_roles = held_add
    monkeypatch.setattr(live_bot, "get_guild", lambda _: guild)
    monkeypatch.setattr(live_bot.db, "expired_winner_roles", expired_snapshot)
    grant = asyncio.create_task(live_bot.grant_winner_role(guild, winner.id, cfg))
    await entered.wait()
    expiry = asyncio.create_task(RumbleCog(live_bot)._expire_roles())
    await asyncio.sleep(0)
    release.set()
    await asyncio.wait_for(asyncio.gather(grant, expiry), 2)
    assert role in winner.roles
    assert (await live_bot.db.get_winner_role(guild.id, winner.id, role.id))["expires_at"] > time.time()


async def test_failed_schedule_is_retried_without_consuming_occurrence(live_bot, monkeypatch):
    guild = FakeGuild()
    channel = guild.add_channel()
    cfg = GuildConfig(guild_id=guild.id, channel_id=channel.id, setup_done=True)
    await live_bot.db.save_config(cfg)
    now = [int(time.time())]
    occurrence = now[0] - 30
    schedule_id = await live_bot.db.add_schedule(guild.id, "garage", "once", run_at=occurrence)
    monkeypatch.setattr(live_bot, "get_guild", lambda _: guild)
    monkeypatch.setattr("rumble.bot.time.time", lambda: now[0])
    calls = []

    async def startup(*args, **kwargs):
        calls.append(kwargs["source"])
        return (None, ["lobby upload failed"]) if len(calls) == 1 else (SimpleNamespace(game_id=None), [])

    monkeypatch.setattr(live_bot, "start_game", startup)
    cog = RumbleCog(live_bot)
    await cog._run_schedules()
    row = (await live_bot.db.schedules(guild.id))[0]
    assert row["enabled"] and row["last_run_at"] is None
    now[0] += 31
    await cog._run_schedules()
    row = (await live_bot.db.schedules(guild.id))[0]
    assert not row["enabled"] and row["last_run_at"] == occurrence
    await live_bot.db.mark_schedule_run(schedule_id, None)
    await live_bot.db.conn.execute("UPDATE schedules SET enabled=1 WHERE id=?", (schedule_id,))
    await live_bot.db.conn.commit()
    await cog._run_schedules()
    assert len(calls) == 2
    assert calls == [f"schedule:{schedule_id}:{occurrence}"] * 2


def test_manual_and_service_instances_share_database_lock(tmp_path):
    project = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project))
    from bot import acquire_instance_lock
    path = str(tmp_path / "rumble.sqlite3")
    held = acquire_instance_lock(path)
    command = [sys.executable, "-c", "from bot import acquire_instance_lock; import sys; acquire_instance_lock(sys.argv[1])", path]
    try:
        rejected = subprocess.run(command, cwd=project, capture_output=True, timeout=10)
        assert rejected.returncode != 0 and b"already holds" in rejected.stderr
    finally:
        held.close()
    assert subprocess.run(command, cwd=project, capture_output=True, timeout=10).returncode == 0
