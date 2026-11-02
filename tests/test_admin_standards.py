"""Shared admin standards: private destinations, read-only guides, safe mutations and UI bounds."""
from types import SimpleNamespace

import discord
import pytest

from rumble.bot import RumbleBot
from rumble.config import GuildConfig
from rumble.guides import GuideView
from rumble.ui import panel as P
from rumble.ui.reporting import private_report_channel_problem
from rumble.ui.setup import SetupWizard, STEPS
from tests.fakes import FakeGuild, FakePerms
from tests.test_ui_bot import Inter, _check_view


@pytest.fixture
async def env(tmp_path):
    bot = RumbleBot(str(tmp_path / 'admin.db'))
    await bot.db.open()
    guild = FakeGuild()
    guild.default_role = guild.add_role('@everyone')
    guild.owner_id = 123
    channel = guild.add_channel()
    channel.guild = guild
    channel.overwrites = {}
    original = channel.permissions_for
    visible = {'everyone': False}
    channel.permissions_for = lambda target: SimpleNamespace(view_channel=visible['everyone']) if target is guild.default_role else original(target)
    admin = guild.add_member('admin', perms=FakePerms(manage_guild=True))
    member = guild.add_member('member')
    cfg = GuildConfig(guild_id=guild.id, channel_id=channel.id, setup_done=True)
    await bot.db.save_config(cfg)
    yield bot, guild, channel, admin, member, cfg, visible
    await bot.db.close()


async def test_private_channel_rechecked_against_visibility_and_unrelated_grants(env):
    _, guild, channel, _, member, cfg, visible = env
    assert private_report_channel_problem(guild, channel, cfg) is None
    visible['everyone'] = True
    assert '@everyone' in private_report_channel_problem(guild, channel, cfg)
    visible['everyone'] = False
    channel.overwrites[member] = discord.PermissionOverwrite(view_channel=True)
    assert 'unrelated' in private_report_channel_problem(guild, channel, cfg)
    channel.overwrites.clear()
    role = guild.add_role('observer')
    channel.overwrites[role] = discord.PermissionOverwrite(view_channel=True)
    assert 'unrelated' in private_report_channel_problem(guild, channel, cfg)
    cfg.host_role_ids = [role.id]
    assert private_report_channel_problem(guild, channel, cfg) is None
    cfg.host_role_ids = []
    role.tags = SimpleNamespace(bot_id=guild.me.id)
    assert private_report_channel_problem(guild, channel, cfg) is None
    role.tags.bot_id = 98765
    assert 'unrelated' in private_report_channel_problem(guild, channel, cfg)
    channel.overwrites.clear()
    channel.overwrites[discord.Object(id=7654321, type=discord.User)] = discord.PermissionOverwrite(view_channel=True)
    assert 'unrelated' in private_report_channel_problem(guild, channel, cfg)


async def test_reports_picker_preserves_destination_on_rejected_change(env):
    bot, guild, channel, admin, _, cfg, visible = env
    view = P.ReportsPanel(bot, admin, cfg)
    view.select._values = [channel]
    visible['everyone'] = True
    with pytest.raises(PermissionError):
        await view.choose(Inter(admin, guild))
    assert (await bot.db.get_config(guild.id)).report_channel_id is None
    visible['everyone'] = False
    await view.choose(Inter(admin, guild))
    assert (await bot.db.get_config(guild.id)).report_channel_id == channel.id


async def test_member_guide_is_read_only_and_admin_guide_rechecks_access(env):
    bot, guild, _, admin, member, cfg, _ = env
    view = GuideView(bot, member, cfg)
    assert await view.interaction_check(Inter(member, guild))
    assert view.btn_admin.disabled
    embed = await view.render(guild)
    assert 'Join' in embed.description and 'RipCars inventory' in embed.description
    assert not await view.interaction_check(Inter(admin, guild))
    denied = Inter(member, guild)
    await view.btn_admin.callback(denied)
    assert denied.followup.sent
    admin_view = GuideView(bot, admin, cfg, admin=True)
    admin.guild_permissions.manage_guild = False
    assert not await admin_view.interaction_check(Inter(admin, guild))
    assert (await bot.db.get_config(guild.id)).to_json() == cfg.to_json()


async def test_new_panels_and_every_wizard_step_fit_discord_limits(env):
    bot, guild, _, admin, member, cfg, _ = env
    async def status():
        return {'ok': True, 'checks': {'database': True}, 'backup': {'created_at': 1234567890, 'verified': True, 'recent': False}}
    bot.operational_status = status
    for cls in (P.ReportsPanel, P.ScenarioTextPanel, P.MaintenancePanel):
        view = cls(bot, admin, cfg)
        _check_view(view)
        assert len(await view.render(guild)) <= 6000
    for user in (admin, member):
        view = GuideView(bot, user, cfg)
        _check_view(view)
        assert len(await view.render(guild)) <= 6000
    assert len(STEPS) == 6
    for step in range(len(STEPS)):
        wizard = SetupWizard(bot, admin, cfg, step=step)
        _check_view(wizard)
        assert len(wizard.render(guild)) <= 6000


async def test_backup_action_fails_closed_and_rechecks_demotion(env):
    bot, guild, _, admin, _, cfg, _ = env
    calls = []
    async def backup():
        calls.append('backup')
        raise OSError('test failure')
    async def status():
        return {'ok': False}
    bot.create_backup, bot.operational_status = backup, status
    view = P.MaintenancePanel(bot, admin, cfg)
    result = Inter(admin, guild)
    await view.backup.callback(result)
    assert calls == ['backup']
    assert 'Backup failed' in result.edited[-1]['embed'].fields[-1].value
    admin.guild_permissions.manage_guild = False
    await view.backup.callback(Inter(admin, guild))
    assert calls == ['backup']


def test_new_config_fields_survive_roundtrip_and_invalid_overrides_are_bounded():
    cfg = GuildConfig(guild_id=1, report_channel_id='123', text_overrides={'g.wipe.0': '{A} leaves.', 'bad': 12, 'large': 'x' * 241}).clamp()
    restored = GuildConfig.from_json(1, cfg.to_json())
    assert restored.report_channel_id == 123
    assert restored.text_overrides == {'g.wipe.0': '{A} leaves.'}
    assert GuildConfig.from_json(1, '{"text_overrides":null}').text_overrides == {}


async def test_scenario_editor_validates_reset_and_preserves_other_changes(env):
    bot, guild, _, admin, _, cfg, _ = env
    form = P.ScenarioTextModal(P.ScenarioTextPanel(bot, admin, cfg))
    form.line_id._value = 'g.wipe.6'
    form.replacement._value = '{A} misses the starting gate. Their deciding heat ends inside.'
    await bot.db.mutate_config(guild.id, lambda current: setattr(current, 'round_delay', 20))
    await form.on_submit(Inter(admin, guild))
    current = await bot.db.get_config(guild.id)
    assert current.round_delay == 20
    assert current.text_overrides == {'g.wipe.6': str(form.replacement)}
    demoted = P.ScenarioTextModal(P.ScenarioTextPanel(bot, admin, current))
    demoted.line_id._value = 'g.wipe.6'
    demoted.replacement._value = ''
    admin.guild_permissions.manage_guild = False
    await demoted.on_submit(Inter(admin, guild))
    assert (await bot.db.get_config(guild.id)).text_overrides == current.text_overrides
    admin.guild_permissions.manage_guild = True
    invalid = P.ScenarioTextModal(P.ScenarioTextPanel(bot, admin, current))
    invalid.line_id._value = 'does.not.exist'
    invalid.replacement._value = ''
    rejected = Inter(admin, guild)
    await invalid.on_submit(rejected)
    assert 'Unknown scenario ID' in rejected.edited[-1]['embed'].fields[-1].value
    assert (await bot.db.get_config(guild.id)).text_overrides == current.text_overrides
    reset = P.ScenarioTextModal(P.ScenarioTextPanel(bot, admin, current))
    reset.line_id._value = 'g.wipe.6'
    reset.replacement._value = ''
    await reset.on_submit(Inter(admin, guild))
    assert (await bot.db.get_config(guild.id)).text_overrides == {}


async def test_leaderboard_reset_requires_verified_backup(env):
    bot, guild, _, admin, _, cfg, _ = env
    await bot.db.record_results(guild.id, [dict(user_id=1, name='winner', place=1, kills=1, won=True)])
    async def failed_backup():
        raise OSError('no space')
    bot.create_backup = failed_backup
    view = P.LeaderboardPanel(bot, admin, cfg, confirm=True)
    result = Inter(admin, guild)
    await view._do_reset(result)
    assert len(await bot.db.leaderboard(guild.id)) == 1
    assert 'Reset stopped' in result.edited[-1]['embed'].fields[-1].value
    calls = []
    async def successful_backup():
        calls.append('backup')
    bot.create_backup = successful_backup
    await view._do_reset(Inter(admin, guild))
    assert calls == ['backup']
    assert await bot.db.leaderboard(guild.id) == []


async def test_scenario_catalog_export_is_private_and_admin_only(env):
    import json
    bot, guild, _, admin, member, cfg, _ = env
    view = P.ScenarioTextPanel(bot, admin, cfg)
    result = Inter(admin, guild)
    await view.download_texts.callback(result)
    args, kwargs = result.followup.sent[-1]
    assert kwargs['ephemeral'] is True
    uploaded = kwargs['file']
    rows = json.loads(uploaded.fp.getvalue())
    uploaded.close()
    assert len(rows) == 591 and len({row['id'] for row in rows}) == 591
    assert all(set(row) == {'id', 'kind', 'text'} for row in rows)
    denied = Inter(member, guild)
    await view.download_texts.callback(denied)
    assert not any('file' in kw for _, kw in denied.followup.sent)


async def test_reset_blocks_active_game_and_demotion_during_backup(env):
    bot, guild, _, admin, _, cfg, _ = env
    await bot.db.record_results(guild.id, [dict(user_id=1, name='winner', place=1, kills=1, won=True)])
    calls = []
    async def backup():
        assert bot.start_locks[guild.id].locked()
        calls.append('backup')
        admin.guild_permissions.manage_guild = False
    bot.create_backup = backup
    bot.games[guild.id] = SimpleNamespace(state='running')
    view = P.LeaderboardPanel(bot, admin, cfg, confirm=True)
    await view._do_reset(Inter(admin, guild))
    assert calls == []
    del bot.games[guild.id]
    await view._do_reset(Inter(admin, guild))
    assert calls == ['backup']
    assert len(await bot.db.leaderboard(guild.id)) == 1
