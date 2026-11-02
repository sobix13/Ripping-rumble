"""Control panel: one private message that navigates in place. Hosts see Start, Stop, Schedule and the
leaderboard. Admins also see Settings and Diagnostics."""
import asyncio
import dataclasses
import io
import json
import time

import discord

from .. import __version__, render
from ..config import DELAY_CHOICES, LOBBY_CHOICES, WINNER_HOURS_CHOICES, valid_timezone
from ..content import get_world, world_choices
from ..diagnostics import checks_embed, run_checks
from ..perms import describe_roles, is_admin, is_host, winner_role_problem
from ..scheduler import ScheduleError, describe, describe_plain, next_run, parse_once, parse_weekly

RED = 0xDF0100


def fmt_secs(s):
    return f"{s // 60} min" if s >= 60 and s % 60 == 0 else f"{s} s"


def fmt_hours(h):
    if not h:
        return "until removed"
    return f"{h // 24} days" if h >= 48 and h % 24 == 0 else f"{h} h"


def world_label(key):
    return "Random world" if key == "random" else get_world(key).name


def world_options(selected):
    opts = [discord.SelectOption(label="Random world", value="random", emoji="🎲", default=selected == "random")]
    for key, name in world_choices():
        w = get_world(key)
        opts.append(discord.SelectOption(label=name, value=key, emoji=w.emoji, description=w.tagline[:100],
                                         default=selected == key))
    return opts


def _channel(guild, cid):
    ch = guild.get_channel(cid) if cid else None
    return ch.mention if ch else "not set"


def _role(guild, rid, empty="none"):
    r = guild.get_role(rid) if rid else None
    return r.mention if r else empty


class PanelBase(discord.ui.View):
    title = "Control Panel"
    admin_only = False

    def __init__(self, bot, user, cfg, timeout=900):
        super().__init__(timeout=timeout)
        self.bot, self.user, self.cfg = bot, user, cfg

    async def ack(self, interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()

    async def reject(self, interaction, message):
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    def require_access(self, interaction, cfg, admin_only=None):
        if interaction.guild_id != self.cfg.guild_id or interaction.user.id != self.user.id:
            raise PermissionError("This panel belongs to another member or server. Open /rumble panel.")
        if self.is_finished():
            raise PermissionError("This panel expired. Open /rumble panel again.")
        if getattr(self.bot, "closing", False):
            raise PermissionError("The bot is restarting. Open a fresh panel after it returns.")
        admin_only = self.admin_only if admin_only is None else admin_only
        allowed = is_admin(interaction.user, cfg) if admin_only else is_host(interaction.user, cfg)
        if not allowed:
            raise PermissionError("Your access changed. Open /rumble panel again.")

    async def authorize(self, interaction, *, modal_open=False, admin_only=None):
        try:
            if interaction.guild_id != self.cfg.guild_id or interaction.user.id != self.user.id:
                raise PermissionError("This panel belongs to another member or server. Open /rumble panel.")
            if not modal_open:
                await self.ack(interaction)
            # A modal must be the initial response. Bound its fresh-policy read instead of deferring it.
            read = self.bot.db.get_config(interaction.guild_id)
            self.cfg = await asyncio.wait_for(read, 1.5) if modal_open else await read
            self.require_access(interaction, self.cfg, admin_only)
        except asyncio.TimeoutError:
            await self.reject(interaction, "Settings are busy. Try opening the form again.")
            return False
        except PermissionError as error:
            await self.reject(interaction, str(error))
            return False
        self.message = getattr(interaction, "message", None) or getattr(self, "message", None)
        return True

    async def interaction_check(self, interaction):
        custom_id = (getattr(interaction, "data", None) or {}).get("custom_id", "")
        return await self.authorize(interaction, modal_open=custom_id.startswith("rumble:modal:"))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        self.stop()
        message = getattr(self, "message", None)
        if message is not None:
            try:
                await message.edit(view=self)
            except discord.HTTPException:
                pass

    async def on_error(self, interaction, error, item):
        self.bot.record_error(interaction.guild_id, f"Panel error: {type(error).__name__}: {error}")
        msg = str(error) if isinstance(error, PermissionError) else "That did not work. Details are in /rumble diagnose."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass

    def base_embed(self, description=""):
        e = discord.Embed(title=f"🏎️ RipCars Rumble · {self.title}", description=description, color=RED)
        e.set_footer(text=f"RipCars Rumble {__version__} · Panel closes after 15 min idle. Reopen /rumble panel.")
        return e

    async def render(self, guild):
        return self.base_embed()

    async def go(self, interaction, view_cls, note=None, **kw):
        await self.ack(interaction)
        v = view_cls(self.bot, self.user, self.cfg, **kw)
        v.message = getattr(interaction, "message", None) or getattr(self, "message", None)
        e = await v.render(interaction.guild)
        if note:
            e.add_field(name="\u200b", value=note, inline=False)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=e, view=v)
        else:
            await interaction.response.edit_message(embed=e, view=v)
        self.stop()

    async def refresh(self, interaction, note=None):
        await self.ack(interaction)
        e = await self.render(interaction.guild)
        if note:
            e.add_field(name="​", value=note, inline=False)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=e, view=self)
        else:
            await interaction.response.edit_message(embed=e, view=self)

    async def mutate(self, interaction, change):
        await self.ack(interaction)
        def checked(current):
            self.require_access(interaction, current)
            change(current)
            if current.winner_role_id in current.host_role_ids + current.admin_role_ids + current.player_role_ids:
                raise PermissionError("The prize role must remain separate from access roles.")
        self.cfg = await self.bot.db.mutate_config(interaction.guild_id, checked)
        return self.cfg

    async def save(self, interaction, *fields):
        changes = {name: getattr(self.cfg, name) for name in fields}
        def apply(current):
            for name, value in changes.items():
                setattr(current, name, value)
        return await self.mutate(interaction, apply)


class PanelModal(discord.ui.Modal):
    async def interaction_check(self, interaction):
        return await self.panel.authorize(interaction)

    async def authorized_submit(self, interaction):
        # Also check here so direct callbacks and old form submissions use current policy.
        return await self.panel.authorize(interaction)

    async def on_error(self, interaction, error):
        self.panel.bot.record_error(interaction.guild_id, f"Form error: {type(error).__name__}: {error}")
        note = str(error) if isinstance(error, PermissionError) else "The form was not saved. Open /rumble panel and retry."
        await self.panel.reject(interaction, note)


def set_winner_role(cfg, guild, member, role_id):
    if role_id is not None:
        problem = winner_role_problem(guild, member, guild.get_role(role_id))
        if problem:
            raise PermissionError(problem)
        if role_id in cfg.host_role_ids + cfg.admin_role_ids + cfg.player_role_ids:
            raise PermissionError("The prize role must be separate from host, admin and player access roles.")
    cfg.winner_role_id = role_id


def require_role_creation(guild, member):
    perms = member.guild_permissions
    if not (getattr(perms, "manage_roles", False) or getattr(perms, "administrator", False)
            or member.id == getattr(guild, "owner_id", None)):
        raise PermissionError("Manage Roles is required to create a prize role.")


class BackButton(discord.ui.Button):
    def __init__(self, target_cls, label="Back", row=4):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=row, emoji="↩️")
        self.target_cls = target_cls

    async def callback(self, interaction):
        await self.view.go(interaction, self.target_cls)


# ------------------------------------------------------------------ home
class PanelHome(PanelBase):
    title = "Control Panel"

    def __init__(self, bot, user, cfg):
        super().__init__(bot, user, cfg)
        admin = is_admin(user, cfg)
        running = bot.games.get(getattr(user.guild, "id", 0)) is not None
        self.btn_stop.disabled = not running
        self.btn_settings.disabled = not admin
        self.btn_diag.disabled = not admin
        self.btn_maintenance.disabled = not admin

    async def render(self, guild):
        c = self.cfg
        runner = self.bot.games.get(guild.id)
        if runner is None:
            live = "No rumble running."
        elif runner.state == "lobby":
            live = f"Lobby open · {runner.world.name} · {len(runner.players)} joined"
        else:
            g = runner.game
            lap = f" · lap {g.round_no}/{g.total_rounds}" if g else ""
            live = f"{runner.state.title()} · {runner.world.name}{lap}"
        rows = await self.bot.db.schedules(guild.id, enabled_only=True)
        nxt = [t for t in (next_run(r, c.timezone, int(time.time())) for r in rows) if t]
        lines = [
            f"**Live** · {live}",
            f"**Channel** · {_channel(guild, c.channel_id)}",
            f"**Hosts** · {describe_roles(guild, c.host_role_ids, 'Manage Server only')}",
            f"**Players** · {describe_roles(guild, c.player_role_ids, 'everyone')}",
            f"**Winner role** · {_role(guild, c.winner_role_id)} ({fmt_hours(c.winner_role_hours)})",
            f"**Default** · {world_label(c.default_world)} · lobby {fmt_secs(c.lobby_seconds)} · "
            f"base pause {fmt_secs(c.round_delay)}",
            f"**Next scheduled** · " + (f"<t:{min(nxt)}:R>" if nxt else "none"),
        ]
        if not c.setup_done:
            lines.insert(0, "⚠️ Setup is not finished. Run **/rumble setup** first.")
        return self.base_embed("\n".join(lines))

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success, emoji="🏁", row=0)
    async def btn_start(self, interaction, button):
        await self.go(interaction, StartPanel)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️", row=0)
    async def btn_stop(self, interaction, button):
        from ..bot import STOP_TEXT
        res = self.bot.stop_game(interaction.guild_id)
        button.disabled = res != "finishing"
        await self.refresh(interaction, STOP_TEXT[res])

    @discord.ui.button(label="Schedule", style=discord.ButtonStyle.primary, emoji="🗓️", row=0)
    async def btn_sched(self, interaction, button):
        await self.go(interaction, SchedulePanel)

    @discord.ui.button(label="Settings", style=discord.ButtonStyle.secondary, emoji="⚙️", row=1)
    async def btn_settings(self, interaction, button):
        if not is_admin(interaction.user, self.cfg):
            return await self.reject(interaction, "Settings are for admins.")
        await self.go(interaction, SettingsHome)

    @discord.ui.button(label="Leaderboard", style=discord.ButtonStyle.secondary, emoji="🏆", row=1)
    async def btn_lb(self, interaction, button):
        await self.go(interaction, LeaderboardPanel)

    @discord.ui.button(label="Diagnostics", style=discord.ButtonStyle.secondary, emoji="🩺", row=1)
    async def btn_diag(self, interaction, button):
        if not is_admin(interaction.user, self.cfg):
            return await self.reject(interaction, "Diagnostics are for admins.")
        await self.ack(interaction)
        v = DiagnosticsPanel(self.bot, self.user, self.cfg)
        await interaction.edit_original_response(embed=await v.render(interaction.guild), view=v)

    @discord.ui.button(label="Guides", style=discord.ButtonStyle.secondary, emoji="📖", row=2)
    async def btn_guides(self, interaction, button):
        from ..guides import GuideView
        await self.go(interaction, GuideView)

    @discord.ui.button(label="Maintenance", style=discord.ButtonStyle.secondary, emoji="🛠️", row=2)
    async def btn_maintenance(self, interaction, button):
        if not await self.authorize(interaction, admin_only=True):
            return
        await self.go(interaction, MaintenancePanel)


# ------------------------------------------------------------------ start
class StartPanel(PanelBase):
    title = "Start a rumble"

    def __init__(self, bot, user, cfg):
        super().__init__(bot, user, cfg)
        self.world = cfg.default_world
        self.lobby = cfg.lobby_seconds
        self.sel_world.options = world_options(self.world)
        self.sel_lobby.options = [discord.SelectOption(label=f"Lobby {fmt_secs(s)}", value=str(s),
                                                       default=s == self.lobby) for s in LOBBY_CHOICES]
        if self.lobby not in LOBBY_CHOICES:
            self.sel_lobby.options.append(discord.SelectOption(label=f"Lobby {fmt_secs(self.lobby)}",
                                                               value=str(self.lobby), default=True))
        self.add_item(BackButton(PanelHome, row=2))

    async def render(self, guild):
        return self.base_embed(f"Pick a world and a lobby time, then press **Start rumble**.\n\n"
                               f"The lobby opens in {_channel(guild, self.cfg.channel_id)}.")

    @discord.ui.select(placeholder="World", row=0)
    async def sel_world(self, interaction, select):
        self.world = select.values[0]
        for o in select.options:
            o.default = o.value == self.world
        await self.ack(interaction)

    @discord.ui.select(placeholder="Lobby time", row=1)
    async def sel_lobby(self, interaction, select):
        self.lobby = int(select.values[0])
        for o in select.options:
            o.default = o.value == select.values[0]
        await self.ack(interaction)

    @discord.ui.button(label="Start rumble", style=discord.ButtonStyle.success, emoji="🏁", row=2)
    async def btn_go(self, interaction, button):
        await self.ack(interaction)
        cfg = dataclasses.replace(self.cfg, lobby_seconds=self.lobby).clamp()
        runner, probs = await self.bot.start_game(interaction.guild, cfg, self.world,
                                                  host=interaction.user.display_name)
        if probs:
            return await self.refresh(interaction, "\n".join(f"❌ {p}" for p in probs))
        v = PanelHome(self.bot, self.user, self.cfg)
        e = await v.render(interaction.guild)
        e.add_field(name="​", value=f"{runner.world.emoji} **{runner.world.name}** lobby is open in "
                                         f"<#{cfg.channel_id}>.", inline=False)
        await interaction.edit_original_response(embed=e, view=v)


# ------------------------------------------------------------------ schedule
class OnceModal(PanelModal, title="One-time rumble"):
    date = discord.ui.TextInput(label="Date (YYYY-MM-DD)", placeholder="2026-11-07", max_length=10)
    at = discord.ui.TextInput(label="Time (24-hour)", placeholder="20:30", max_length=5)

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    async def on_submit(self, interaction):
        if not await self.authorized_submit(interaction):
            return
        p = self.panel
        try:
            ts = parse_once(str(self.date), str(self.at), p.cfg.timezone, int(time.time()))
        except ScheduleError as e:
            return await p.refresh(interaction, f"❌ {e}")
        await p.bot.db.add_schedule(interaction.guild_id, p.world, "once", run_at=ts, created_by=interaction.user.id)
        await p.reload_and_refresh(interaction, f"✅ One-time rumble added for <t:{ts}:F>.")


class WeeklyModal(PanelModal, title="Weekly rumble"):
    days = discord.ui.TextInput(label="Days", placeholder="Mon, Wed, Fri  (or daily)", max_length=60)
    at = discord.ui.TextInput(label="Time (24-hour)", placeholder="20:30", max_length=5)

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    async def on_submit(self, interaction):
        if not await self.authorized_submit(interaction):
            return
        p = self.panel
        try:
            days, hm = parse_weekly(str(self.days), str(self.at))
        except ScheduleError as e:
            return await p.refresh(interaction, f"❌ {e}")
        await p.bot.db.add_schedule(interaction.guild_id, p.world, "weekly", weekdays=days, time_hm=hm,
                                    created_by=interaction.user.id)
        await p.reload_and_refresh(interaction, "✅ Weekly rumble added.")


class SchedulePanel(PanelBase):
    title = "Schedule"

    def __init__(self, bot, user, cfg):
        super().__init__(bot, user, cfg)
        self.world = cfg.default_world
        self.rows = []
        self.sel_world.options = world_options(self.world)
        self.sel_remove.options = [discord.SelectOption(label="No schedules yet", value="none")]
        self.sel_remove.disabled = True
        self.add_item(BackButton(PanelHome, row=3))

    def rebuild(self):
        if self.rows:
            self.sel_remove.options = [
                discord.SelectOption(label=f"#{r['id']} · {world_label(r['world'])}"[:100],
                                     description=describe_plain(r, self.cfg.timezone)[:100],
                                     value=str(r["id"])) for r in self.rows[:25]]
            self.sel_remove.disabled = False
        else:
            self.sel_remove.options = [discord.SelectOption(label="No schedules yet", value="none")]
            self.sel_remove.disabled = True

    async def render(self, guild):
        self.rows = await self.bot.db.schedules(guild.id, enabled_only=True)
        self.rebuild()
        now = int(time.time())
        if self.rows:
            lines = []
            for r in self.rows[:20]:
                nr = next_run(r, self.cfg.timezone, now)
                lines.append(f"**#{r['id']}** · {world_label(r['world'])} · {describe(r, self.cfg.timezone)}"
                             + (f" · next <t:{nr}:R>" if nr else ""))
            body = "\n".join(lines)
        else:
            body = "No scheduled rumbles yet."
        return self.base_embed(f"{body}\n\nTimezone: **{self.cfg.timezone}** (change it in Settings).\n"
                               f"Pick a world, then add a one-time or weekly rumble.\n"
                               "DST: repeated local hours use the first occurrence. Missing hours are skipped for weekly runs.")

    async def reload_and_refresh(self, interaction, note):
        await self.refresh(interaction, note)

    @discord.ui.select(placeholder="World for the new schedule", row=0)
    async def sel_world(self, interaction, select):
        self.world = select.values[0]
        for o in select.options:
            o.default = o.value == self.world
        await self.ack(interaction)

    @discord.ui.button(label="One-time…", style=discord.ButtonStyle.primary, emoji="📅", row=1, custom_id="rumble:modal:once")
    async def btn_once(self, interaction, button):
        await interaction.response.send_modal(OnceModal(self))

    @discord.ui.button(label="Weekly…", style=discord.ButtonStyle.primary, emoji="🔁", row=1, custom_id="rumble:modal:weekly")
    async def btn_weekly(self, interaction, button):
        await interaction.response.send_modal(WeeklyModal(self))

    @discord.ui.select(placeholder="Remove a schedule", row=2)
    async def sel_remove(self, interaction, select):
        await self.ack(interaction)
        if select.values[0] == "none":
            return await self.ack(interaction)
        ok = await self.bot.db.remove_schedule(interaction.guild_id, int(select.values[0]))
        await self.refresh(interaction, f"🗑️ Schedule #{select.values[0]} removed." if ok else "Already gone.")


# ------------------------------------------------------------------ settings
class SettingsHome(PanelBase):
    title = "Settings"
    admin_only = True

    def __init__(self, bot, user, cfg):
        super().__init__(bot, user, cfg)
        self.add_item(BackButton(PanelHome, row=2))

    async def render(self, guild):
        c = self.cfg
        e = self.base_embed("Pick a section. Changes save right away.")
        e.add_field(name="Channel & roles", inline=False, value=(
            f"Channel {_channel(guild, c.channel_id)}\nHosts {describe_roles(guild, c.host_role_ids, 'Manage Server only')}"
            f"\nPlayers {describe_roles(guild, c.player_role_ids, 'everyone')}"
            f"\nAdmins {describe_roles(guild, c.admin_role_ids, 'Manage Server only')}")[:1024])
        e.add_field(name="Winner & ping", inline=False, value=(
            f"Winner role {_role(guild, c.winner_role_id)} · {fmt_hours(c.winner_role_hours)}\n"
            f"Lobby ping {_role(guild, c.ping_role_id)}")[:1024])
        e.add_field(name="Game rules", inline=False, value=(
            f"{world_label(c.default_world)} · lobby {fmt_secs(c.lobby_seconds)} · base pause {fmt_secs(c.round_delay)}\n"
            f"{c.min_players}–{c.max_players} rippers · {c.min_rounds}–{c.max_rounds} laps · "
            f"revive chance {int(c.revive_rate * 100)}% per lap"))
        onoff = lambda b: "on" if b else "off"  # noqa: E731
        e.add_field(name="Extras", inline=False, value=(
            f"Automatic Second Chance {onoff(c.second_chance)} · "
            f"Hazards {onoff(c.hazards)} · Images {onoff(c.images)} · Server emoji {onoff(c.server_emoji)}\n"
            f"Timezone {c.timezone}"))
        e.add_field(name="Private reports & text", inline=False,
                    value=f"Reports {_channel(guild, c.report_channel_id)} · {len(c.text_overrides)} scenario overrides")
        return e

    @discord.ui.button(label="Channel & roles", style=discord.ButtonStyle.primary, emoji="📍", row=0)
    async def b1(self, interaction, button):
        await self.go(interaction, ChannelRolesPanel)

    @discord.ui.button(label="Winner & ping", style=discord.ButtonStyle.primary, emoji="🏆", row=0)
    async def b2(self, interaction, button):
        await self.go(interaction, WinnerPanel)

    @discord.ui.button(label="Game rules", style=discord.ButtonStyle.primary, emoji="🎲", row=0)
    async def b3(self, interaction, button):
        await self.go(interaction, RulesPanel)

    @discord.ui.button(label="Extras", style=discord.ButtonStyle.primary, emoji="✨", row=1)
    async def b4(self, interaction, button):
        await self.go(interaction, ExtrasPanel)

    @discord.ui.button(label="Timezone…", style=discord.ButtonStyle.secondary, emoji="🕒", row=1, custom_id="rumble:modal:timezone")
    async def b5(self, interaction, button):
        await interaction.response.send_modal(TimezoneModal(self))

    @discord.ui.button(label="Private reports", style=discord.ButtonStyle.secondary, row=2)
    async def b_reports(self, interaction, button):
        await self.go(interaction, ReportsPanel)

    @discord.ui.button(label="Scenario text", style=discord.ButtonStyle.secondary, row=2)
    async def b_text(self, interaction, button):
        await self.go(interaction, ScenarioTextPanel)


def _role_defaults(guild, ids):
    return [discord.Object(r.id) for r in (guild.get_role(i) for i in ids if i) if r is not None][:25]


class ChannelRolesPanel(PanelBase):
    title = "Channel & roles"
    admin_only = True

    def __init__(self, bot, user, cfg):
        super().__init__(bot, user, cfg)
        g = user.guild
        ch = g.get_channel(cfg.channel_id) if cfg.channel_id else None
        self.s_channel = discord.ui.ChannelSelect(placeholder="Game channel", row=0, min_values=1, max_values=1,
                                                  channel_types=[discord.ChannelType.text, discord.ChannelType.news],
                                                  default_values=[discord.Object(ch.id)] if ch else [])
        self.s_hosts = discord.ui.RoleSelect(placeholder="Host roles (start, stop, schedule)", row=1, min_values=0,
                                             max_values=10, default_values=_role_defaults(g, cfg.host_role_ids))
        self.s_players = discord.ui.RoleSelect(placeholder="Player roles (empty = everyone)", row=2,
                                               min_values=0, max_values=10,
                                               default_values=_role_defaults(g, cfg.player_role_ids))
        self.s_admins = discord.ui.RoleSelect(placeholder="Admin roles (settings, setup, diagnostics)", row=3,
                                              min_values=0, max_values=10,
                                              default_values=_role_defaults(g, cfg.admin_role_ids))
        for s, cb in ((self.s_channel, self._ch), (self.s_hosts, self._hosts), (self.s_players, self._players),
                      (self.s_admins, self._admins)):
            s.callback = cb
            self.add_item(s)
        self.add_item(BackButton(SettingsHome, row=4))

    async def render(self, guild):
        return self.base_embed("**Manage Server** grants access to setup and settings.\n"
                               "Hosts also join. Empty Player roles opens the grid to everyone.")

    async def _ch(self, interaction):
        self.cfg.channel_id = self.s_channel.values[0].id
        await self.save(interaction, "channel_id")
        await self.go(interaction, ChannelRolesPanel, note=f"✅ Game channel set to <#{self.cfg.channel_id}>.")

    async def _hosts(self, interaction):
        self.cfg.host_role_ids = [r.id for r in self.s_hosts.values]
        await self.save(interaction, "host_role_ids")
        await self.go(interaction, ChannelRolesPanel, note="✅ Host roles saved.")

    async def _players(self, interaction):
        self.cfg.player_role_ids = [r.id for r in self.s_players.values]
        await self.save(interaction, "player_role_ids")
        await self.go(interaction, ChannelRolesPanel, note="✅ Player roles saved.")

    async def _admins(self, interaction):
        self.cfg.admin_role_ids = [r.id for r in self.s_admins.values]
        await self.save(interaction, "admin_role_ids")
        await self.go(interaction, ChannelRolesPanel, note="✅ Admin roles saved.")


class WinnerPanel(PanelBase):
    title = "Winner & ping"
    admin_only = True

    def __init__(self, bot, user, cfg):
        super().__init__(bot, user, cfg)
        g = user.guild
        self.s_winner = discord.ui.RoleSelect(placeholder="Winner role (temporary)", row=0, min_values=0,
                                              max_values=1, default_values=_role_defaults(g, [cfg.winner_role_id] if cfg.winner_role_id else []))
        self.s_hours = discord.ui.Select(placeholder="How long winners keep it", row=1, options=[
            discord.SelectOption(label=f"Keep it {fmt_hours(h)}" if h else "Keep it until removed by hand",
                                 value=str(h), default=h == cfg.winner_role_hours) for h in WINNER_HOURS_CHOICES])
        self.s_ping = discord.ui.RoleSelect(placeholder="Role to ping when a lobby opens (optional)", row=2,
                                            min_values=0, max_values=1,
                                            default_values=_role_defaults(g, [cfg.ping_role_id] if cfg.ping_role_id else []))
        for s, cb in ((self.s_winner, self._winner), (self.s_hours, self._hours), (self.s_ping, self._ping)):
            s.callback = cb
            self.add_item(s)
        self.add_item(CreateWinnerRoleButton(row=3))
        self.add_item(BackButton(SettingsHome, row=3))

    async def render(self, guild):
        return self.base_embed("The winner role is given at the end of each rumble and removed after the time "
                               "you pick. The bot's own role must sit above it.")

    async def _winner(self, interaction):
        role_id = self.s_winner.values[0].id if self.s_winner.values else None
        await self.mutate(interaction, lambda current: set_winner_role(current, interaction.guild, interaction.user, role_id))
        if role_id is not None:
            await self.bot.db.approve_winner_role(interaction.guild_id, role_id)
        await self.go(interaction, WinnerPanel,
                      note="✅ Winner role saved." if self.cfg.winner_role_id else "Winner role cleared.")

    async def _hours(self, interaction):
        self.cfg.winner_role_hours = int(self.s_hours.values[0])
        for o in self.s_hours.options:
            o.default = o.value == self.s_hours.values[0]
        await self.save(interaction, "winner_role_hours")
        await self.go(interaction, WinnerPanel, note=f"✅ Winners keep the role {fmt_hours(self.cfg.winner_role_hours)}.")

    async def _ping(self, interaction):
        self.cfg.ping_role_id = self.s_ping.values[0].id if self.s_ping.values else None
        await self.save(interaction, "ping_role_id")
        await self.go(interaction, WinnerPanel,
                      note="✅ Lobby ping saved." if self.cfg.ping_role_id else "Lobby ping cleared.")


class CreateWinnerRoleButton(discord.ui.Button):
    def __init__(self, row):
        super().__init__(label="Create 'Rumble Champion' role", style=discord.ButtonStyle.success, emoji="➕", row=row)

    async def callback(self, interaction):
        view = self.view
        if not await view.authorize(interaction):
            return
        require_role_creation(interaction.guild, interaction.user)
        try:
            role = await interaction.guild.create_role(name="Rumble Champion", colour=discord.Colour(RED), permissions=discord.Permissions.none(),
                                                       reason="RipCars Rumble winner role")
        except discord.HTTPException:
            return await view.go(interaction, WinnerPanel, note="❌ The bot needs Manage Roles to create a role.")
        await view.mutate(interaction, lambda current: set_winner_role(current, interaction.guild, interaction.user, role.id))
        await view.bot.db.approve_winner_role(interaction.guild_id, role.id)
        await view.go(interaction, WinnerPanel, note=f"✅ Created {role.mention}. Keep the bot's role above it.")


class NumbersModal(PanelModal, title="Numbers"):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        c = panel.cfg
        self.minp = discord.ui.TextInput(label="Minimum rippers to start (2-50)", default=str(c.min_players), max_length=3)
        self.maxp = discord.ui.TextInput(label="Maximum rippers (2-250, default 60)", default=str(c.max_players), max_length=3)
        self.minr = discord.ui.TextInput(label="Minimum lap target (2-12)", default=str(c.min_rounds), max_length=2)
        self.maxr = discord.ui.TextInput(label="Maximum lap target (2-25)", default=str(c.max_rounds), max_length=2)
        self.rev = discord.ui.TextInput(label="Revive chance per lap, % (0-50)", default=str(int(c.revive_rate * 100)),
                                        max_length=2)
        for t in (self.minp, self.maxp, self.minr, self.maxr, self.rev):
            self.add_item(t)

    async def on_submit(self, interaction):
        if not await self.authorized_submit(interaction):
            return
        p = self.panel
        try:
            vals = [int(str(t.value).strip()) for t in (self.minp, self.maxp, self.minr, self.maxr, self.rev)]
        except ValueError:
            return await p.refresh(interaction, "❌ Use whole numbers only.")
        p.cfg = c = await p.bot.db.get_config(interaction.guild_id)      # fresh copy: never undo other edits
        c.min_players, c.max_players, c.min_rounds, c.max_rounds = vals[:4]
        c.revive_rate = vals[4] / 100
        c.clamp()
        await p.save(interaction, "min_players", "max_players", "min_rounds", "max_rounds", "revive_rate")
        await p.refresh(interaction, f"✅ Saved: {c.min_players}–{c.max_players} rippers, {c.min_rounds}–"
                                     f"{c.max_rounds} laps, {int(c.revive_rate * 100)}% revive chance.")


class TimezoneModal(PanelModal, title="Timezone"):
    tz = discord.ui.TextInput(label="Timezone (IANA name)", placeholder="Europe/Belgrade, Asia/Tehran, UTC",
                              max_length=64)

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.tz.default = panel.cfg.timezone

    async def on_submit(self, interaction):
        if not await self.authorized_submit(interaction):
            return
        p = self.panel
        name = str(self.tz.value).strip()
        if not valid_timezone(name):
            return await p.refresh(interaction, f"❌ '{name}' is not a timezone. Try Europe/Belgrade or UTC.")
        p.cfg = await p.bot.db.get_config(interaction.guild_id)
        p.cfg.timezone = name
        await p.save(interaction, "timezone")
        await p.refresh(interaction, f"✅ Timezone set to {name}.")


class RulesPanel(PanelBase):
    title = "Game rules"
    admin_only = True

    def __init__(self, bot, user, cfg):
        super().__init__(bot, user, cfg)
        self.s_world = discord.ui.Select(placeholder="Default world", row=0, options=world_options(cfg.default_world))
        self.s_lobby = discord.ui.Select(placeholder="Lobby time", row=1, options=[
            discord.SelectOption(label=f"Lobby {fmt_secs(s)}", value=str(s), default=s == cfg.lobby_seconds)
            for s in LOBBY_CHOICES])
        self.s_delay = discord.ui.Select(placeholder="Minimum lap pause", row=2, options=[
            discord.SelectOption(label=f"Base pause {fmt_secs(s)}", value=str(s), default=s == cfg.round_delay)
            for s in DELAY_CHOICES])
        for s, cb in ((self.s_world, self._world), (self.s_lobby, self._lobby), (self.s_delay, self._delay)):
            s.callback = cb
            self.add_item(s)
        nb = discord.ui.Button(label="Numbers…", style=discord.ButtonStyle.primary, emoji="🔢", row=3, custom_id="rumble:modal:numbers")
        nb.callback = self._numbers
        self.add_item(nb)
        self.add_item(BackButton(SettingsHome, row=3))

    async def render(self, guild):
        c = self.cfg
        return self.base_embed(
            f"**Default world** {world_label(c.default_world)}\n**Lobby** {fmt_secs(c.lobby_seconds)} · "
            f"**Base pause** {fmt_secs(c.round_delay)}\n**Rippers** {c.min_players}–{c.max_players} · "
            f"**Laps** {c.min_rounds}–{c.max_rounds} · **Revive chance** {int(c.revive_rate * 100)}%\n\n"
            "Lap targets scale with the lobby. The final starts when two remain. Large lobbies keep a minimum "
            "readable schedule. Group clearances are disabled when Hazards is off.")

    async def _world(self, interaction):
        self.cfg.default_world = self.s_world.values[0]
        await self.save(interaction, "default_world")
        await self.go(interaction, RulesPanel)

    async def _lobby(self, interaction):
        self.cfg.lobby_seconds = int(self.s_lobby.values[0])
        await self.save(interaction, "lobby_seconds")
        await self.go(interaction, RulesPanel)

    async def _delay(self, interaction):
        self.cfg.round_delay = int(self.s_delay.values[0])
        await self.save(interaction, "round_delay")
        await self.go(interaction, RulesPanel)

    async def _numbers(self, interaction):
        await interaction.response.send_modal(NumbersModal(self))


class ExtrasPanel(PanelBase):
    title = "Extras"
    admin_only = True
    TOGGLES = [("second_chance", "Second Chance", "🧇"), ("hazards", "Hazards", "⚠️"), ("images", "Images", "🖼️"),
               ("server_emoji", "Server emoji", "😀")]

    def __init__(self, bot, user, cfg):
        super().__init__(bot, user, cfg)
        for attr, label, emoji in self.TOGGLES:
            on = getattr(cfg, attr)
            b = discord.ui.Button(label=f"{label}: {'on' if on else 'off'}", emoji=emoji, row=0,
                                  style=discord.ButtonStyle.success if on else discord.ButtonStyle.secondary)
            b.callback = self._make_toggle(attr)
            self.add_item(b)
        self.add_item(BackButton(SettingsHome, row=2))

    async def render(self, guild):
        return self.base_embed(
            "**Second Chance** · the bot selects one eligible fallen ripper automatically. No extra click.\n"
            "**Hazards** · mass events that clear several rippers at once in big lobbies.\n"
            "**Images** · one RipCars sticker, GIF or emoji art per post.\n"
            "**Server emoji** · use this server's rip_ emoji as line icons when they exist.")

    def _make_toggle(self, attr):
        async def cb(interaction):
            await self.mutate(interaction, lambda current: setattr(current, attr, not getattr(current, attr)))
            await self.go(interaction, ExtrasPanel)
        return cb

# ------------------------------------------------------------------ leaderboard
class LeaderboardPanel(PanelBase):
    title = "Leaderboard"

    def __init__(self, bot, user, cfg, confirm=False):
        super().__init__(bot, user, cfg)
        self.confirm = confirm
        admin = is_admin(user, cfg)
        if confirm:
            yes = discord.ui.Button(label="Yes, reset everything", style=discord.ButtonStyle.danger, row=0)
            yes.callback = self._do_reset
            no = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, row=0)
            no.callback = self._cancel
            self.add_item(yes)
            self.add_item(no)
        else:
            r = discord.ui.Button(label="Reset leaderboard", style=discord.ButtonStyle.danger, emoji="🗑️", row=0,
                                  disabled=not admin)
            r.callback = self._ask
            self.add_item(r)
            self.add_item(BackButton(PanelHome, row=0))

    async def render(self, guild):
        rows = await self.bot.db.leaderboard(guild.id, 10)
        e = render.leaderboard_embed(rows, guild.name)
        if self.confirm:
            e.add_field(name="⚠️ Reset", value="This deletes every win, kill and game count in this server. "
                                              "This change is permanent.", inline=False)
        return e

    async def _ask(self, interaction):
        if not is_admin(interaction.user, self.cfg):
            return await self.reject(interaction, "Only admins reset this leaderboard.")
        await self.go(interaction, LeaderboardPanel, confirm=True)

    async def _do_reset(self, interaction):
        if not await self.authorize(interaction, admin_only=True):
            return
        async with self.bot.start_locks[interaction.guild_id]:
            if interaction.guild_id in self.bot.games:
                return await self.refresh(interaction, "Finish or stop the active rumble before resetting its leaderboard.")
            try:
                await self.bot.create_backup()
            except Exception as error:
                self.bot.record_error(interaction.guild_id, f"Leaderboard backup failed: {type(error).__name__}: {error}")
                return await self.refresh(interaction, "Reset stopped because a verified backup was not created.")
            if not await self.authorize(interaction, admin_only=True):
                return
            await self.bot.db.reset_leaderboard(interaction.guild_id)
        await self.go(interaction, LeaderboardPanel)

    async def _cancel(self, interaction):
        await self.go(interaction, LeaderboardPanel)


# ------------------------------------------------------------------ diagnostics
class DiagnosticsPanel(PanelBase):
    title = "Diagnostics"
    admin_only = True

    def __init__(self, bot, user, cfg):
        super().__init__(bot, user, cfg)
        self.add_item(BackButton(PanelHome, row=0))

    async def render(self, guild):
        results = await run_checks(self.bot, guild, self.cfg)
        return checks_embed(results, guild.name)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.primary, emoji="🔄", row=0)
    async def btn_refresh(self, interaction, button):
        await self.ack(interaction)
        await interaction.edit_original_response(embed=await self.render(interaction.guild), view=self)

    @discord.ui.button(label="Send test post", style=discord.ButtonStyle.secondary, emoji="🧪", row=0)
    async def btn_test(self, interaction, button):
        from ..assets import AssetPicker
        ch = interaction.guild.get_channel(self.cfg.channel_id) if self.cfg.channel_id else None
        if ch is None:
            return await self.reject(interaction, "No game channel set.")
        world = get_world(self.cfg.default_world if self.cfg.default_world != "random" else "garage")
        e = render.notice_embed(world, "🧪 Rumble test post",
                                "This text and sticker confirm the game channel post format.")
        kw = {"embed": e}
        rel = AssetPicker().pick("start")
        if rel and self.cfg.images:
            kw["file"], url = AssetPicker.file(rel)
            e.set_thumbnail(url=url)
        await self.ack(interaction)
        try:
            await ch.send(**kw)
            note = f"✅ Test post sent to {ch.mention}."
        except discord.Forbidden:
            note = f"❌ The bot has no posting access in {ch.mention}. Check its permissions there."
        except discord.HTTPException as ex:
            note = f"❌ Post failed: {ex}"
        await interaction.followup.send(note, ephemeral=True)


class ReportsPanel(PanelBase):
    title = "Private reports"
    admin_only = True

    def __init__(self, bot, user, cfg):
        super().__init__(bot, user, cfg)
        channel = user.guild.get_channel(cfg.report_channel_id) if cfg.report_channel_id else None
        self.select = discord.ui.ChannelSelect(
            placeholder="Private staff report channel, or clear to disable", min_values=0, max_values=1, row=0,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            default_values=[discord.Object(channel.id)] if channel else [])
        self.select.callback = self.choose
        self.add_item(self.select)
        self.add_item(BackButton(SettingsHome, row=1))

    async def render(self, guild):
        return self.base_embed(
            f"Current: {_channel(guild, self.cfg.report_channel_id)}\n\n"
            "Choose a private staff channel. Hide it from @everyone and unrelated members or roles. "
            "Delivery checks privacy again and stops if access changes. Reports never fall back to a public channel.")

    async def choose(self, interaction):
        from .reporting import private_report_channel_problem
        channel = self.select.values[0] if self.select.values else None
        if channel is not None:
            channel = interaction.guild.get_channel(channel.id)
        def change(current):
            if channel is not None:
                problem = private_report_channel_problem(interaction.guild, channel, current)
                if problem:
                    raise PermissionError(problem)
            current.report_channel_id = channel.id if channel else None
        await self.mutate(interaction, change)
        await self.go(interaction, ReportsPanel, note="Private report destination saved.")


class ScenarioTextModal(PanelModal, title="Scenario text"):
    line_id = discord.ui.TextInput(label="Stable line ID", placeholder="g.wipe.0 or x.gulf.survive.0", max_length=100)
    replacement = discord.ui.TextInput(label="Replacement text, blank resets this ID", required=False,
                                       style=discord.TextStyle.paragraph, max_length=240)

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    async def on_submit(self, interaction):
        if not await self.authorized_submit(interaction):
            return
        from ..content.overrides import validate_override
        line_id, text = str(self.line_id).strip(), str(self.replacement).strip()
        try:
            validate_override(line_id, text)
        except ValueError as error:
            return await self.panel.refresh(interaction, f"Text was not saved: {error}")
        def change(current):
            if text:
                current.text_overrides[line_id] = text
            else:
                current.text_overrides.pop(line_id, None)
        await self.panel.mutate(interaction, change)
        await self.panel.go(interaction, ScenarioTextPanel, note=f"Saved {line_id}. Future games use the new snapshot.")


class ScenarioTextPanel(PanelBase):
    title = "Scenario text"
    admin_only = True

    def __init__(self, bot, user, cfg):
        super().__init__(bot, user, cfg)
        self.add_item(BackButton(SettingsHome, row=1))

    async def render(self, guild):
        ids = sorted(self.cfg.text_overrides)
        shown = ", ".join(ids[:25]) or "none"
        if len(ids) > 25:
            shown += f" and {len(ids) - 25} more"
        return self.base_embed(
            f"Saved overrides: **{len(ids)}**\n{shown}\n\n"
            "Download the scenario texts below to find stable IDs. A blank replacement restores the shipped text. "
            "Placeholder roles, item contracts, writing rules and world boundaries stay fixed. "
            "Running games keep their initial snapshot. Models belong to the wider Hot Wheels hobby. "
            "A scene does not claim RipCars inventory or a real item award.")

    @discord.ui.button(label="Edit or reset a line", style=discord.ButtonStyle.primary, row=0,
                       custom_id="rumble:modal:scenario-text")
    async def edit_line(self, interaction, button):
        await interaction.response.send_modal(ScenarioTextModal(self))

    @discord.ui.button(label="Download scenario texts", style=discord.ButtonStyle.secondary, row=0)
    async def download_texts(self, interaction, button):
        if not await self.authorize(interaction, admin_only=True):
            return
        rows = {}
        for key, _ in world_choices():
            for lines in get_world(key).pools.values():
                for line in lines:
                    rows[line.id] = dict(id=line.id, kind=line.kind,
                                         text=self.cfg.text_overrides.get(line.id, line.text))
        data = json.dumps([rows[key] for key in sorted(rows)], ensure_ascii=False, indent=2).encode()
        await interaction.followup.send(file=discord.File(io.BytesIO(data), filename="rumble-scenario-texts.json"),
                                        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


class MaintenancePanel(PanelBase):
    title = "Maintenance"
    admin_only = True

    def __init__(self, bot, user, cfg):
        super().__init__(bot, user, cfg)
        self.add_item(BackButton(PanelHome, row=1))

    async def render(self, guild):
        from .. import __version__
        status = await self.bot.operational_status()
        e = self.base_embed(
            "Review health and backup status here. Restore and code rollback are offline operator actions. "
            "Use Diagnostics for channel permissions and pending delivery.")
        e.add_field(name="Runtime", value=f"Version {__version__} · {'ready' if status.get('ok') else 'not ready'}", inline=False)
        checks = status.get("checks", {})
        if checks:
            e.add_field(name="Checks", value="\n".join(
                f"{str(key)[:40]}: {'ok' if value is True else 'not ready'}" for key, value in list(checks.items())[:10])[:1024], inline=False)
        backup = status.get("backup", {})
        if isinstance(backup, dict) and backup.get("verified") and isinstance(backup.get("created_at"), (int, float)):
            state = "recent" if backup.get("recent") else "overdue"
            text = f"Verified · {state}\n<t:{int(backup['created_at'])}:F> · <t:{int(backup['created_at'])}:R>"
        else:
            text = "No verified backup recorded"
        e.add_field(name="Latest verified backup", value=text[:200], inline=False)
        return e

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, row=0)
    async def refresh_status(self, interaction, button):
        if not await self.authorize(interaction, admin_only=True):
            return
        await self.refresh(interaction)

    @discord.ui.button(label="Create verified backup", style=discord.ButtonStyle.primary, row=0)
    async def backup(self, interaction, button):
        if not await self.authorize(interaction, admin_only=True):
            return
        try:
            await self.bot.create_backup()
        except Exception as error:
            self.bot.record_error(interaction.guild_id, f"Backup failed: {type(error).__name__}: {error}")
            return await self.refresh(interaction, "Backup failed. No success was recorded. Check Diagnostics.")
        await self.refresh(interaction, "A verified backup was created. No backup file is posted to Discord.")
