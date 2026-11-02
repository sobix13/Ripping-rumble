import asyncio
import io
import json
import logging
import time
import threading
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from rumble.bot import RumbleBot, RumbleCog
from rumble.config import GuildConfig
from rumble.content import get_world, world_keys
from rumble.content.overrides import apply_overrides, validate_override
from rumble.health import HealthMonitor, atomic_health
from rumble.redaction import RedactingFormatter, redact
from rumble.runner import GameRunner
from tests.fakes import FakeGuild
from tests.test_ui_bot import Inter


@pytest.mark.parametrize('line_id,text', [
    ('g.wipe.6', '{A} leaves the grid. Out.'),
    ('g.wipe.6', ''),
])
def test_wording_overrides_allow_known_id_and_reset(line_id, text):
    validate_override(line_id, text)


@pytest.mark.parametrize('line_id,text', [
    ('missing.line', ''),
    ('g.wipe.6', '{B} leaves the grid.'),
    ('g.wipe.6', '{A} can leave the grid.'),
    ('g.wipe.6', '{A} opens Discord in 2026.'),
    ('g.wipe.6', '{A} signs an onchain transaction.'),
    ('g.wipe.6', '{A} visits https://example.org.'),
    ('g.wipe.6', '{A} wins an official Hot Wheels collaboration.'),
    ('g.wipe.6', '{A} leaves {custom_1}. Out.'),
    ('g.wipe.6', '{{A}} leaves the grid. Out.'),
])
def test_wording_overrides_reject_contract_and_context_changes(line_id, text):
    with pytest.raises(ValueError):
        validate_override(line_id, text)


def test_overrides_do_not_mutate_cache_or_running_game():
    guild = FakeGuild()
    channel = guild.add_channel()
    cfg = GuildConfig(guild_id=guild.id, channel_id=channel.id,
                      text_overrides={'g.wipe.6': '{A} leaves the grid. Out.'})
    runner = GameRunner(SimpleNamespace(), guild, channel, cfg)
    cfg.text_overrides['g.wipe.6'] = '{A} misses the final entry. Out.'
    text = lambda world: next(line.text for line in world.pools['wipe'] if line.id == 'g.wipe.6')
    assert text(runner.world) == '{A} leaves the grid. Out.'
    assert text(get_world('garage')) != text(runner.world)
    next_world = apply_overrides(get_world('garage'), cfg.text_overrides)
    assert text(next_world) == cfg.text_overrides['g.wipe.6']


def test_redaction_covers_message_and_traceback(monkeypatch):
    secret = 'a-private-credential-value'
    monkeypatch.setenv('DISCORD_TOKEN', secret)
    monkeypatch.setenv('SERVICE_API_KEY', 'a-second-private-credential')
    assert secret not in redact(f'token={secret}')
    assert 'a-second-private-credential' not in redact('Failed for a-second-private-credential')
    assert 'unconfigured-secret' not in redact('Authorization: Bearer unconfigured-secret')
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter('%(message)s'))
    logger = logging.Logger('redaction-test')
    logger.addHandler(handler)
    try:
        raise ValueError(secret)
    except ValueError:
        logger.exception('Rejected credential %s', secret)
    assert secret not in stream.getvalue() and '[redacted]' in stream.getvalue()


async def test_health_checks_workers_and_gateway_and_serves_real_http(tmp_path, monkeypatch):
    bot = RumbleBot(str(tmp_path / 'health.sqlite3'))
    await bot.db.open()
    monkeypatch.setattr(bot, 'is_ready', lambda: True)
    loop = SimpleNamespace(is_running=lambda: True)
    monkeypatch.setattr(bot, 'get_cog', lambda _: SimpleNamespace(scheduler_loop=loop, roles_loop=loop))
    bot.loop_success.update(scheduler=time.time(), roles=time.time())
    monitor = HealthMonitor(bot, tmp_path / 'health.json', port=0)
    # Exclude its periodic task: the test drives transitions explicitly.
    monitor.server = await asyncio.start_server(monitor.handle, '127.0.0.1', 0, limit=4096)
    port = monitor.server.sockets[0].getsockname()[1]
    try:
        ready = await monitor.sample()
        assert ready['ok'] and json.loads(monitor.path.read_text())['pid'] == ready['pid']

        async def get():
            reader, writer = await asyncio.open_connection('127.0.0.1', port)
            writer.write(b'GET /healthz HTTP/1.1\r\nHost: localhost\r\n\r\n')
            await writer.drain()
            result = await reader.read()
            writer.close()
            await writer.wait_closed()
            return result

        assert b'200 OK' in await get()
        bot.loop_success['scheduler'] = 0
        assert not (await monitor.sample())['ok']
        assert b'503 Service Unavailable' in await get()
        bot.loop_success['scheduler'] = time.time()
        monkeypatch.setattr(bot, 'is_ready', lambda: False)
        assert not (await monitor.sample())['checks']['discord']
    finally:
        await monitor.stop()
        monkeypatch.setattr(bot, 'get_cog', lambda _: None)
        await bot.close()


async def test_private_errors_recheck_destination_and_redact(tmp_path, monkeypatch):
    bot = RumbleBot(str(tmp_path / 'errors.sqlite3'))
    await bot.db.open()
    guild = FakeGuild()
    guild.default_role = guild.add_role('@everyone')
    # Test reporting against an isolated channel fixture with real permission decisions.
    channel = guild.add_channel()
    channel.guild = guild
    channel.overwrites = {}
    channel.public = False
    original_permissions = channel.permissions_for
    channel.permissions_for = lambda target: SimpleNamespace(view_channel=channel.public) if target is guild.default_role else original_permissions(target)
    sent = []

    async def send(**kwargs):
        sent.append(kwargs)

    channel.send = send
    monkeypatch.setattr(bot, 'get_guild', lambda _: guild)
    original = guild.get_channel
    guild.get_channel = lambda cid: channel if cid == channel.id else original(cid)
    await bot.db.save_config(GuildConfig(guild_id=guild.id, report_channel_id=channel.id))
    monkeypatch.setenv('DISCORD_TOKEN', 'test-secret-long-value')
    try:
        bot.record_error(guild.id, 'token=test-secret-long-value')
        await bot.flush_error_reports()
        assert sent and 'test-secret-long-value' not in sent[0]['content']
        channel.public = True
        bot.report_last_sent.clear()
        bot.record_error(guild.id, 'second failure')
        await bot.flush_error_reports()
        assert len(sent) == 1 and bot.report_queue
        channel.public = False
        bot.report_last_sent.clear()
        monkeypatch.setattr('rumble.bot.REPORT_SEND_TIMEOUT', 0.01)

        async def stuck_send(**kwargs):
            await asyncio.Event().wait()

        channel.send = stuck_send
        await asyncio.wait_for(bot.flush_error_reports(), 0.5)
        assert not bot.report_queue
    finally:
        await bot.close()


async def test_health_file_failure_does_not_abort_database_shutdown(tmp_path, monkeypatch):
    bot = RumbleBot(str(tmp_path / 'shutdown.sqlite3'))
    await bot.db.open()
    bot.health = HealthMonitor(bot, tmp_path / 'health.json', port=0)

    def disk_full(*args):
        raise OSError('disk full')

    monkeypatch.setattr('rumble.health.atomic_health', disk_full)
    await bot.close()
    assert bot.db.conn is None


async def test_shutdown_waits_for_old_health_write_before_terminal_state(tmp_path, monkeypatch):
    bot = RumbleBot(str(tmp_path / 'race.sqlite3'))
    await bot.db.open()
    monkeypatch.setattr(bot, 'is_ready', lambda: True)
    loop = SimpleNamespace(is_running=lambda: True)
    monkeypatch.setattr(bot, 'get_cog', lambda _: SimpleNamespace(scheduler_loop=loop, roles_loop=loop))
    bot.loop_success.update(scheduler=time.time(), roles=time.time())
    monitor = HealthMonitor(bot, tmp_path / 'health.json', port=0)
    entered, release = threading.Event(), threading.Event()

    def delayed_write(path, status):
        if status['ok']:
            entered.set()
            assert release.wait(2)
        atomic_health(path, status)

    monkeypatch.setattr('rumble.health.atomic_health', delayed_write)
    monitor.task = asyncio.create_task(monitor.sample())
    stopping = None
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        stopping = asyncio.create_task(monitor.stop())
        await asyncio.sleep(0.01)
        assert not stopping.done()
        release.set()
        await asyncio.wait_for(stopping, 2)
        assert json.loads(monitor.path.read_text())['ok'] is False
    finally:
        release.set()
        if stopping:
            await stopping
        monkeypatch.setattr(bot, 'get_cog', lambda _: None)
        await bot.close()


def test_global_error_detail_stays_out_of_other_guild_diagnostics(tmp_path):
    bot = RumbleBot(str(tmp_path / 'unused.sqlite3'))
    bot.record_error(0, 'failure involving another-guild-private-detail')
    assert 'another-guild-private-detail' not in str(bot.errors_for(123))


def test_managed_entrypoint_imports_from_outside_source_and_uses_shared_paths(tmp_path):
    source = Path(__file__).resolve().parents[1]
    env = dict(os.environ, DISCORD_TOKEN='', RUMBLE_BASE=str(tmp_path / 'installation'), PYTHONPATH='')
    completed = subprocess.run([sys.executable, str(source / 'scripts/run.py')], env=env,
                               cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert completed.returncode == 2 and 'DISCORD_TOKEN is missing' in completed.stderr
    assert (tmp_path / 'installation/shared/logs/rumble.log').exists()
