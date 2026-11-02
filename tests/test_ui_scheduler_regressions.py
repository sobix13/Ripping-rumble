"""Permission, acknowledgement, configuration and DST regressions from the launch audit."""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import discord
import pytest

from rumble.config import GuildConfig
from rumble.db import Database
from rumble.scheduler import ScheduleError, is_due, next_run, parse_once
from rumble.ui import panel as P
from rumble.ui.lobby import LobbyView
from tests.fakes import FakeGuild, FakePerms, FakeRole
from tests.test_ui_bot import Inter, Resp


class StrictResponse(Resp):
    def check(self):
        assert not self.done, "An interaction received two initial responses"

    async def defer(self, **kwargs):
        self.check()
        await super().defer(**kwargs)

    async def send_message(self, *args, **kwargs):
        self.check()
        await super().send_message(*args, **kwargs)

    async def send_modal(self, modal):
        self.check()
        await super().send_modal(modal)

    async def edit_message(self, **kwargs):
        self.check()
        await super().edit_message(**kwargs)


def interaction(user, guild, custom_id=""):
    result = Inter(user, guild)
    result.response = StrictResponse()
    result.data = {"custom_id": custom_id}
    return result


@pytest.fixture
async def ui_env(tmp_path):
    db = Database(str(tmp_path / "ui-regressions.db"))
    await db.open()
    guild = FakeGuild()
    channel = guild.add_channel()
    admin = guild.add_member("admin", perms=FakePerms(manage_guild=True, manage_roles=True))
    admin.top_role = FakeRole("admin", position=45)
    host_role = guild.add_role("host")
    host = guild.add_member("host", roles=[host_role])
    cfg = GuildConfig(guild_id=guild.id, channel_id=channel.id, host_role_ids=[host_role.id], setup_done=True)
    await db.save_config(cfg)
    errors = []
    bot = SimpleNamespace(db=db, games={}, closing=False,
                          record_error=lambda gid, message: errors.append((gid, message)))
    yield bot, guild, admin, host, cfg
    await db.close()


@pytest.mark.parametrize("modal_type", [P.TimezoneModal, P.NumbersModal])
async def test_admin_form_submit_rechecks_demotion(ui_env, modal_type):
    bot, guild, admin, _, cfg = ui_env
    form = modal_type(P.RulesPanel(bot, admin, cfg))
    if modal_type is P.TimezoneModal:
        form.tz._value = "UTC"
    admin.guild_permissions.manage_guild = False
    i = interaction(admin, guild)
    await form.on_submit(i)
    assert (await bot.db.get_config(guild.id)).timezone == "Asia/Tehran"
    assert "access changed" in str(i.followup.sent).lower()


@pytest.mark.parametrize("modal_type", [P.OnceModal, P.WeeklyModal])
async def test_schedule_form_rechecks_current_host_policy(ui_env, modal_type):
    bot, guild, _, host, cfg = ui_env
    form = modal_type(P.SchedulePanel(bot, host, cfg))
    await bot.db.mutate_config(guild.id, lambda current: setattr(current, "host_role_ids", []))
    i = interaction(host, guild)
    await form.on_submit(i)
    assert await bot.db.schedules(guild.id) == []
    assert i.followup.sent


async def test_form_rejects_another_owner_or_guild(ui_env):
    bot, guild, admin, host, cfg = ui_env
    form = P.TimezoneModal(P.RulesPanel(bot, admin, cfg))
    assert not await form.interaction_check(interaction(host, guild))
    other = FakeGuild()
    assert not await form.interaction_check(interaction(admin, other))


async def test_panel_acknowledges_before_slow_policy_io(ui_env, monkeypatch):
    bot, guild, admin, _, cfg = ui_env
    view = P.RulesPanel(bot, admin, cfg)
    original = bot.db.get_config
    entered, release = asyncio.Event(), asyncio.Event()
    async def slow(gid):
        entered.set()
        await release.wait()
        return await original(gid)
    monkeypatch.setattr(bot.db, "get_config", slow)
    i = interaction(admin, guild)
    task = asyncio.create_task(view.interaction_check(i))
    await entered.wait()
    assert i.response.calls[0][0] == "defer"
    release.set()
    assert await task
    await view._numbers(interaction(admin, guild, "rumble:modal:numbers"))


async def test_modal_opener_retains_initial_modal_response(ui_env):
    bot, guild, admin, _, cfg = ui_env
    view = P.RulesPanel(bot, admin, cfg)
    i = interaction(admin, guild, "rumble:modal:numbers")
    assert await view.interaction_check(i)
    assert not i.response.is_done()
    await view._numbers(i)
    assert [call[0] for call in i.response.calls] == ["modal"]


async def test_deferred_form_updates_original_panel_once(ui_env):
    bot, guild, admin, _, cfg = ui_env
    form = P.TimezoneModal(P.RulesPanel(bot, admin, cfg))
    form.tz._value = "UTC"
    i = interaction(admin, guild)
    assert await form.interaction_check(i)
    await form.on_submit(i)
    assert [call[0] for call in i.response.calls] == ["defer"]
    assert len(i.edited) == 1
    assert (await bot.db.get_config(guild.id)).timezone == "UTC"


async def test_independent_stale_panels_preserve_both_edits(ui_env):
    bot, guild, admin, _, cfg = ui_env
    first = P.ExtrasPanel(bot, admin, await bot.db.get_config(guild.id))
    second = P.RulesPanel(bot, admin, await bot.db.get_config(guild.id))
    await first._make_toggle("images")(interaction(admin, guild))
    second.cfg.round_delay = 20
    await second.save(interaction(admin, guild), "round_delay")
    current = await bot.db.get_config(guild.id)
    assert current.images is False
    assert current.round_delay == 20


async def test_toggle_uses_fresh_value_not_panel_snapshot(ui_env):
    bot, guild, admin, _, cfg = ui_env
    views = [P.ExtrasPanel(bot, admin, await bot.db.get_config(guild.id)) for _ in range(2)]
    await asyncio.gather(*(v._make_toggle("images")(interaction(admin, guild)) for v in views))
    assert (await bot.db.get_config(guild.id)).images is True


async def test_award_selection_rejects_access_role(ui_env):
    bot, guild, admin, _, cfg = ui_env
    role = guild.get_role(cfg.host_role_ids[0])
    role.permissions = discord.Permissions.none()
    view = P.WinnerPanel(bot, admin, cfg)
    view.s_winner._values = [role]
    with pytest.raises(PermissionError, match="separate"):
        await view._winner(interaction(admin, guild))
    assert (await bot.db.get_config(guild.id)).winner_role_id is None


async def test_timeout_disables_buttons_when_message_is_available(ui_env):
    bot, guild, admin, _, cfg = ui_env
    view = P.RulesPanel(bot, admin, cfg)
    edits = []
    async def edit(**kwargs):
        edits.append(kwargs)
    view.message = SimpleNamespace(edit=edit)
    await view.on_timeout()
    assert all(item.disabled for item in view.children)
    assert edits[0]["view"] is view
    assert "Reopen /rumble panel" in (await view.render(guild)).footer.text


async def test_form_from_expired_panel_does_not_write(ui_env):
    bot, guild, admin, _, cfg = ui_env
    view = P.RulesPanel(bot, admin, cfg)
    form = P.TimezoneModal(view)
    form.tz._value = "UTC"
    await view.on_timeout()
    i = interaction(admin, guild)
    await form.on_submit(i)
    assert (await bot.db.get_config(guild.id)).timezone == "Asia/Tehran"
    assert "expired" in str(i.followup.sent).lower()


async def test_navigation_stops_old_view_timeout(ui_env):
    bot, guild, admin, _, cfg = ui_env
    old = P.RulesPanel(bot, admin, cfg)
    i = interaction(admin, guild)
    await old.go(i, P.SettingsHome)
    assert old.is_finished()
    assert not i.edited[0]["view"].is_finished()


async def test_lobby_uses_current_authorization_policy(ui_env):
    bot, guild, admin, _, cfg = ui_env
    received = []
    runner = SimpleNamespace(bot=bot,
                             try_join=lambda member, cfg: (received.append(cfg.player_role_ids) or (True, "Joined")))
    view = LobbyView(runner, timeout=60)
    await bot.db.mutate_config(guild.id, lambda current: setattr(current, "player_role_ids", [999]))
    i = interaction(admin, guild)
    await view.join.callback(i)
    assert received == [[999]]
    assert [call[0] for call in i.response.calls] == ["defer"]
    assert i.followup.sent


def test_once_rejects_nonexistent_dst_local_time():
    now = int(datetime(2027, 1, 1, tzinfo=ZoneInfo("UTC")).timestamp())
    with pytest.raises(ScheduleError, match="does not exist"):
        parse_once("2027-03-14", "02:30", "America/New_York", now)


def test_fall_back_uses_first_occurrence_and_never_runs_twice():
    zone = ZoneInfo("America/New_York")
    now = int(datetime(2027, 1, 1, tzinfo=ZoneInfo("UTC")).timestamp())
    first = parse_once("2027-11-07", "01:30", zone.key, now)
    assert datetime.fromtimestamp(first, zone).fold == 0
    weekly = dict(enabled=1, kind="weekly", weekdays="6", time_hm="01:30", created_at=now, last_run_at=None)
    assert is_due(weekly, zone.key, first + 10)[0]
    weekly["last_run_at"] = first + 10
    assert not is_due(weekly, zone.key, first + 3610)[0]


def test_weekly_gap_is_skipped_without_shifting_to_another_hour():
    zone = ZoneInfo("America/New_York")
    before = int(datetime(2027, 3, 14, 1, 0, tzinfo=zone).timestamp())
    weekly = dict(enabled=1, kind="weekly", weekdays="6", time_hm="02:30", created_at=before - 86400,
                  last_run_at=None)
    result = datetime.fromtimestamp(next_run(weekly, zone.key, before), zone)
    assert (result.day, result.hour, result.minute) == (21, 2, 30)
    assert not is_due(weekly, zone.key, before + 3 * 3600)[0]


def test_new_defaults_do_not_override_valid_saved_timezone():
    assert GuildConfig(guild_id=1).max_players == 60
    assert GuildConfig(guild_id=1).min_rounds == 2
    assert GuildConfig(guild_id=1).timezone == "Asia/Tehran"
    assert GuildConfig.from_json(1, '{"timezone":"UTC"}').timezone == "UTC"
