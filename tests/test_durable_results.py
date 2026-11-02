"""Fault tests for durable outcomes, lifecycle ownership and restart recovery."""
import asyncio
import sqlite3
from types import SimpleNamespace

import discord
import pytest

from rumble.bot import RumbleBot
from rumble.config import GuildConfig
from rumble.db import Database, SCHEMA_VERSION
from rumble.runner import GameRunner, recover_pending
from tests.fakes import FakeBot, FakeClock, FakeGuild


def result_rows():
    return [dict(user_id=i, name=f'p{i}', place=i + 1, kills=0, won=i == 0) for i in range(3)]


async def prepared_db(path):
    db = Database(str(path))
    await db.open()
    gid = await db.game_started(99, 'garage', 'manual')
    return db, gid


def payload():
    return dict(channel_id=100, winner_id=0, winner_role_id=None,
                embed={'title': 'Winner', 'description': 'p0 wins.'}, ranking_text='1. p0')


async def test_finalize_is_atomic_and_idempotent(tmp_path):
    db, gid = await prepared_db(tmp_path / 'atomic.db')
    original = db.conn.execute
    calls = 0

    async def second_row_fails(sql, parameters=()):
        nonlocal calls
        if 'INSERT INTO stats' in sql:
            calls += 1
            if calls == 2:
                raise sqlite3.OperationalError('injected row failure')
        return await original(sql, parameters)

    db.conn.execute = second_row_fails
    try:
        with pytest.raises(sqlite3.OperationalError):
            await db.finalize_game(gid, 99, result_rows(), 0, 3, payload())
        with sqlite3.connect(db.path) as observer:
            assert observer.execute('SELECT COUNT(*) FROM stats').fetchone()[0] == 0
            assert observer.execute('SELECT status FROM games').fetchone()[0] == 'lobby'
            assert observer.execute('SELECT COUNT(*) FROM game_results').fetchone()[0] == 0
        db.conn.execute = original
        assert await db.finalize_game(gid, 99, result_rows(), 0, 3, payload())
        assert not await db.finalize_game(gid, 99, result_rows(), 0, 3, payload())
        assert len(await db.leaderboard(99)) == 3
        assert sum(r['wins'] for r in await db.leaderboard(99)) == 1
        assert all(r['games'] == 1 for r in await db.leaderboard(99))
        await db.game_status(gid, 'error')
        assert (await db.recent_games(99))[0]['status'] == 'finished'
    finally:
        await db.close()


async def test_reset_waits_for_complete_transaction(tmp_path):
    db, gid = await prepared_db(tmp_path / 'reset.db')
    gate, release = asyncio.Event(), asyncio.Event()
    original, calls = db.conn.execute, 0

    async def pause_second(sql, parameters=()):
        nonlocal calls
        if 'INSERT INTO stats' in sql:
            calls += 1
            if calls == 2:
                gate.set()
                await release.wait()
        return await original(sql, parameters)

    db.conn.execute = pause_second
    recording = asyncio.create_task(db.finalize_game(gid, 99, result_rows(), 0, 3, payload()))
    try:
        await asyncio.wait_for(gate.wait(), 2)
        resetting = asyncio.create_task(db.reset_leaderboard(99))
        await asyncio.sleep(0)
        assert not resetting.done()
        release.set()
        await asyncio.gather(recording, resetting)
        db.conn.execute = original
        assert await db.leaderboard(99) == []
        assert await db.result_for_game(gid) is not None
    finally:
        release.set()
        await asyncio.gather(recording, return_exceptions=True)
        await db.close()


async def test_atomic_config_updates_preserve_other_fields(tmp_path):
    db = Database(str(tmp_path / 'config.db'))
    await db.open()
    try:
        await asyncio.gather(db.mutate_config(99, lambda c: setattr(c, 'images', False)),
                             db.mutate_config(99, lambda c: setattr(c, 'round_delay', 20)))
        config = await db.get_config(99)
        assert config.images is False and config.round_delay == 20
    finally:
        await db.close()


async def test_migration_preserves_legacy_stats_and_backup(tmp_path):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as old:
        old.executescript('CREATE TABLE stats (guild_id INTEGER NOT NULL,user_id INTEGER NOT NULL,name TEXT NOT NULL,'
                          'wins INTEGER NOT NULL,games INTEGER NOT NULL,kills INTEGER NOT NULL,best_place INTEGER,'
                          'last_win_at INTEGER,PRIMARY KEY(guild_id,user_id));'
                          "INSERT INTO stats VALUES (99,1,'old winner',2,3,4,1,123);")
    db = Database(str(path))
    await db.open()
    try:
        assert (await db.user_stats(99, 1))['wins'] == 2
        backup = await db.backup(tmp_path / 'backups' / 'copy.db')
        with sqlite3.connect(backup) as restored:
            assert restored.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert restored.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
            assert restored.execute('SELECT wins FROM stats').fetchone()[0] == 2
        with pytest.raises(ValueError):
            await db.backup(path)
    finally:
        await db.close()


async def test_expiry_delete_does_not_remove_renewed_lease(tmp_path):
    db = Database(str(tmp_path / 'lease.db'))
    await db.open()
    try:
        await db.add_winner_role(99, 1, 2, 10)
        await db.add_winner_role(99, 1, 2, 100)
        assert not await db.drop_winner_role(99, 1, 2, expected_expires_at=10)
        assert (await db.get_winner_role(99, 1, 2))['expires_at'] == 100
    finally:
        await db.close()


async def make_runner(tmp_path, name, n=12, real_bot=False):
    path = str(tmp_path / f'{name}.db')
    bot = RumbleBot(path) if real_bot else FakeBot(Database(path))
    await bot.db.open()
    guild = FakeGuild()
    channel = guild.add_channel()
    cfg = GuildConfig(guild_id=guild.id, channel_id=channel.id, setup_done=True,
                      images=False, second_chance=True)
    await bot.db.save_config(cfg)
    runner = GameRunner(bot, guild, channel, cfg, clock=FakeClock(), seed=4)
    bot.games[guild.id] = runner
    for i in range(n):
        assert runner.try_join(guild.add_member(f'p{i}'))[0]
    return SimpleNamespace(bot=bot, db=bot.db, guild=guild, channel=channel, runner=runner)


async def test_final_scene_failure_keeps_complete_result(tmp_path):
    env = await make_runner(tmp_path, 'final-failure')
    original = env.channel.send

    async def failed_final(**kwargs):
        if kwargs.get('embeds') and env.runner.game and env.runner.game.finished:
            raise RuntimeError('final scene unavailable')
        return await original(**kwargs)

    env.channel.send = failed_final
    try:
        await env.runner.run()
        assert env.runner.state == 'finished'
        assert len(await env.db.leaderboard(env.guild.id, 50)) == 12
        assert (await env.db.recent_games(env.guild.id))[0]['status'] == 'finished'
        assert await env.db.pending_deliveries() == []
    finally:
        await env.db.close()


async def test_failed_announcement_is_durable_and_recovers_once(tmp_path):
    env = await make_runner(tmp_path, 'announcement')
    original = env.channel.send

    async def forbidden_result(**kwargs):
        if 'wins the rumble' in kwargs.get('content', ''):
            raise discord.Forbidden(type('Response', (), {'status': 403, 'reason': 'Forbidden'})(), 'Missing access')
        return await original(**kwargs)

    env.channel.send = forbidden_result
    try:
        await env.runner.run()
        assert env.runner.state == 'finished'
        assert len(await env.db.leaderboard(env.guild.id, 50)) == 12
        assert len(await env.db.pending_deliveries()) == 1
        env.bot.get_guild = lambda gid: env.guild
        env.channel.send = original
        await recover_pending(env.bot)
        await recover_pending(env.bot)
        assert await env.db.pending_deliveries() == []
        assert sum('wins the rumble' in m.kwargs.get('content', '') for m in env.channel.sent) == 1
        assert all(row['games'] == 1 for row in await env.db.leaderboard(env.guild.id, 50))
    finally:
        await env.db.close()


async def test_uncertain_send_reconciles_history_without_duplicate(tmp_path):
    env = await make_runner(tmp_path, 'uncertain')
    original = env.channel.send

    async def accepted_then_timed_out(**kwargs):
        message = await original(**kwargs)
        if 'wins the rumble' in kwargs.get('content', ''):
            raise asyncio.TimeoutError('response lost after acceptance')
        return message

    env.channel.send = accepted_then_timed_out
    try:
        await env.runner.run()
        assert (await env.db.pending_deliveries())[0]['announcement_state'] == 'unknown'
        env.bot.get_guild = lambda gid: env.guild
        env.channel.send = original

        async def history(**kwargs):
            for m in reversed(env.channel.sent):
                yield SimpleNamespace(id=m.id, embeds=[m.kwargs['embed']] if m.kwargs.get('embed') else [])

        env.channel.history = history
        await recover_pending(env.bot)
        assert await env.db.pending_deliveries() == []
        assert sum('wins the rumble' in m.kwargs.get('content', '') for m in env.channel.sent) == 1
    finally:
        await env.db.close()


async def test_stop_after_engine_final_is_refused_and_result_already_saved(tmp_path):
    env = await make_runner(tmp_path, 'stop-final', real_bot=True)
    original = env.channel.send
    gate, release = asyncio.Event(), asyncio.Event()

    async def held_final(**kwargs):
        if kwargs.get('embeds') and env.runner.game and env.runner.game.finished:
            gate.set()
            await release.wait()
        return await original(**kwargs)

    env.channel.send = held_final
    env.runner.task = asyncio.create_task(env.runner.run())
    try:
        await asyncio.wait_for(gate.wait(), 2)
        assert env.runner.state == 'finishing'
        assert env.bot.stop_game(env.guild.id) == 'finishing'
        assert len(await env.db.leaderboard(env.guild.id, 50)) == 12
        release.set()
        await env.runner.task
    finally:
        release.set()
        await env.bot.close()


async def test_close_waits_for_finish_before_closing_database(tmp_path):
    env = await make_runner(tmp_path, 'close-final', real_bot=True)
    original = env.channel.send
    gate, release = asyncio.Event(), asyncio.Event()

    async def held_result(**kwargs):
        if 'wins the rumble' in kwargs.get('content', ''):
            gate.set()
            await release.wait()
        return await original(**kwargs)

    env.channel.send = held_result
    env.runner.task = asyncio.create_task(env.runner.run())
    closing = None
    try:
        await asyncio.wait_for(gate.wait(), 2)
        closing = asyncio.create_task(env.bot.close())
        for _ in range(5):
            await asyncio.sleep(0)
        assert env.db.conn is not None
        assert not closing.done()
        release.set()
        await asyncio.wait_for(closing, 3)
        assert env.db.conn is None
        assert env.runner.finish_task.done()
    finally:
        release.set()
        if closing:
            await closing
        await env.bot.close()


async def test_lobby_deadline_and_start_now_close_admission(tmp_path):
    env = await make_runner(tmp_path, 'deadline', n=2)
    try:
        env.runner.lobby_ends = env.runner.clock.now() - 1
        assert not env.runner.try_join(env.guild.add_member('late'))[0]
        env.runner.lobby_ends = 0
        env.runner.start_now.set()
        assert not env.runner.try_join(env.guild.add_member('after-start'))[0]
    finally:
        await env.db.close()


async def test_schedule_claim_survives_successful_lobby_restart(tmp_path):
    path = tmp_path / 'occurrences.db'
    db = Database(str(path))
    await db.open()
    try:
        assert await db.claim_schedule_occurrence(1, 100)
        gid = await db.game_started(99, 'garage', 'schedule:1:100')
        await db.track_game_messages(gid, 99, 10, 11)
        assert await db.claim_schedule_occurrence(2, 200)
    finally:
        await db.close()
    reopened = Database(str(path))
    await reopened.open()
    try:
        assert not await reopened.claim_schedule_occurrence(1, 100)
        assert not await reopened.claim_schedule_occurrence(2, 200)
        assert (await reopened.uncertain_schedule_occurrences())[0]['occurrence_at'] == 200
        assert (await reopened.interrupted_messages())[0]['lobby_message_id'] == 11
    finally:
        await reopened.close()


@pytest.mark.parametrize('history_mode', ['wrong_id', 'forged', 'overflow', 'absent'])
async def test_uncertain_delivery_never_blindly_repeats(tmp_path, history_mode):
    from rumble.runner import deliver_pending_result
    env = await make_runner(tmp_path, f'unknown-{history_mode}', n=3)
    try:
        gid = await env.db.game_started(env.guild.id, 'garage', 'manual')
        body = payload()
        body.update(channel_id=env.channel.id)
        await env.db.finalize_game(gid, env.guild.id, result_rows(), 0, 2, body)
        await env.db.mark_announcement_attempt(gid, 'unknown', 'previous HTTP response uncertain')
        env.bot.user = SimpleNamespace(id=12345)

        async def history(**kwargs):
            count = 200 if history_mode == 'overflow' else 1
            for index in range(count):
                embed = discord.Embed()
                marker = f'Rumble #{gid}0' if history_mode == 'wrong_id' else f'Rumble #{gid}'
                embed.set_footer(text=marker)
                author = 99999 if history_mode == 'forged' else 12345
                if history_mode == 'overflow':
                    embed.set_footer(text='Unrelated result')
                yield SimpleNamespace(id=100 + index, embeds=[embed], author=SimpleNamespace(id=author))

        if history_mode != 'absent':
            env.channel.history = history
        row = await env.db.result_for_game(gid)
        await deliver_pending_result(env.bot, env.guild, env.channel, row)
        assert env.channel.sent == []
        result = await env.db.result_for_game(gid)
        assert result['announcement_state'] == 'unknown'
        assert result['announcement_message_id'] is None
        assert result['delivery_error']
    finally:
        await env.db.close()


async def test_pending_role_retry_does_not_repeat_result(tmp_path):
    env = await make_runner(tmp_path, 'pending-role')
    role = env.guild.add_role('Champion')
    env.runner.cfg.winner_role_id = role.id
    calls = 0

    async def grant(*args):
        nonlocal calls
        calls += 1
        return calls > 1

    env.bot.grant_winner_role = grant
    env.bot.get_guild = lambda gid: env.guild
    try:
        await env.runner.run()
        pending = await env.db.pending_deliveries()
        assert len(pending) == 1 and pending[0]['announcement_message_id'] is not None
        assert not pending[0]['role_done']
        await recover_pending(env.bot)
        assert await env.db.pending_deliveries() == []
        assert calls == 2
        assert sum('wins the rumble' in m.kwargs.get('content', '') for m in env.channel.sent) == 1
    finally:
        await env.db.close()


async def test_restart_closes_saved_interrupted_lobby(tmp_path):
    env = await make_runner(tmp_path, 'restart', n=3)
    try:
        gid = await env.db.game_started(env.guild.id, 'garage', 'manual')
        message = await env.channel.send(embed=discord.Embed(title='Old lobby'), view=object())
        await env.db.track_game_messages(gid, env.guild.id, env.channel.id, message.id)
        await env.db.close()
        await env.db.open()
        env.bot.get_guild = lambda gid: env.guild

        async def fetch_message(mid):
            assert mid == message.id
            return message

        env.channel.fetch_message = fetch_message
        await recover_pending(env.bot)
        assert message.edits[-1]['view'] is None
        assert await env.db.interrupted_messages() == []
        assert (await env.db.recent_games(env.guild.id))[0]['status'] == 'interrupted'
    finally:
        await env.db.close()


async def test_double_stop_does_not_cancel_cleanup_twice(tmp_path):
    env = await make_runner(tmp_path, 'double-stop', real_bot=True)
    original = env.channel.send
    round_gate, cleanup_gate, cleanup_release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def held_messages(**kwargs):
        if kwargs.get('embeds'):
            round_gate.set()
            await asyncio.Event().wait()
        if kwargs.get('embed') and kwargs['embed'].title == 'Rumble stopped':
            cleanup_gate.set()
            await cleanup_release.wait()
        return await original(**kwargs)

    env.channel.send = held_messages
    env.runner.task = asyncio.create_task(env.runner.run())
    try:
        await asyncio.wait_for(round_gate.wait(), 2)
        assert env.bot.stop_game(env.guild.id) == 'stopped'
        await asyncio.wait_for(cleanup_gate.wait(), 2)
        count = env.runner.task.cancelling()
        env.bot.stop_game(env.guild.id)
        assert env.runner.task.cancelling() == count
        cleanup_release.set()
        await env.runner.task
        assert (await env.db.recent_games(env.guild.id))[0]['status'] == 'stopped'
    finally:
        cleanup_release.set()
        await env.bot.close()


async def test_recent_text_ids_are_persisted_across_restart(tmp_path):
    db, gid = await prepared_db(tmp_path / 'recent.db')
    body = payload()
    body['line_ids'] = ['g.kill.1', 'garage.find.0']
    await db.finalize_game(gid, 99, result_rows(), 0, 2, body)
    await db.close()
    await db.open()
    try:
        assert await db.recent_content_ids(99) == {'g.kill.1', 'garage.find.0'}
    finally:
        await db.close()
