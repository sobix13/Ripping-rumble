"""Setup wizard: five short steps, saved as you go, ends with a health check."""
import discord

from ..config import DELAY_CHOICES, LOBBY_CHOICES, WINNER_HOURS_CHOICES
from ..diagnostics import run_checks, ICON
from ..perms import describe_roles
from .panel import (RED, PanelBase, PanelHome, _role_defaults, fmt_hours, fmt_secs, world_label, world_options, set_winner_role, require_role_creation)

STEPS = ["Game channel", "Host roles", "Player roles", "Winner role", "Defaults", "Private reports"]


class SetupWizard(PanelBase):
    title = "Setup"
    admin_only = True

    def __init__(self, bot, user, cfg, step=0, note=None):
        super().__init__(bot, user, cfg)
        self.step = step
        self.note = note
        self.guild = user.guild
        self._build()

    # ---- rendering ----
    def render(self, guild=None):
        g = guild or self.guild
        c = self.cfg
        n = self.step + 1
        bar = " ".join("●" if i <= self.step else "○" for i in range(len(STEPS)))
        e = discord.Embed(title=f"🏎️ RipCars Rumble setup · step {n} of {len(STEPS)}: {STEPS[self.step]}",
                          color=RED)
        text = {
            0: "Where should rumbles run? Pick the channel for lobbies and laps.\n"
               "The bot needs: View Channel, Send Messages, Embed Links, Attach Files, Read Message History.",
            1: "Pick the roles for starting, stopping and scheduling rumbles. Usually your mods.\n"
               "Manage Server also grants these controls.",
            2: "Pick player roles, or leave them empty to open the grid to everyone.",
            3: "Pick the **temporary winner role** and how long winners keep it. Or create one now.\n"
               "The bot's role must sit above it in Server Settings → Roles.",
            4: "Pick the **default world**, lobby time and minimum pause between laps. Dense laps receive extra reading time. Change these later in "
               "/rumble panel.",
            5: "Optionally choose a private staff channel for operational reports. Hide it from @everyone and "
               "unrelated members or roles. Leave it empty to disable delivery. Privacy is checked again before each report.",
        }[self.step]
        current = {
            0: f"Current: {g.get_channel(c.channel_id).mention if c.channel_id and g.get_channel(c.channel_id) else 'not set'}",
            1: f"Current: {describe_roles(g, c.host_role_ids, 'Manage Server only')}",
            2: f"Current: {describe_roles(g, c.player_role_ids, 'everyone')}",
            3: f"Current: {g.get_role(c.winner_role_id).mention if c.winner_role_id and g.get_role(c.winner_role_id) else 'none'}"
               f" · kept {fmt_hours(c.winner_role_hours)}",
            4: f"Current: {world_label(c.default_world)} · lobby {fmt_secs(c.lobby_seconds)} · "
               f"base pause {fmt_secs(c.round_delay)}",
            5: f"Current: {g.get_channel(c.report_channel_id).mention if c.report_channel_id and g.get_channel(c.report_channel_id) else 'disabled'}",
        }[self.step]
        e.description = f"{text}\n\n{current}\n\n`{bar}`"
        e.set_footer(text="Setup closes after 15 min idle. Reopen /rumble setup.")
        if self.note:
            e.add_field(name="​", value=self.note, inline=False)
        return e

    async def _show(self, interaction, note=None):
        await self.ack(interaction)
        self.note = note
        self._build()
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=self.render(interaction.guild), view=self)
        else:
            await interaction.response.edit_message(embed=self.render(interaction.guild), view=self)

    # ---- items per step ----
    def _build(self):
        self.clear_items()
        c, g = self.cfg, self.guild
        if self.step == 0:
            ch = g.get_channel(c.channel_id) if c.channel_id else None
            s = discord.ui.ChannelSelect(placeholder="Game channel", min_values=1, max_values=1, row=0,
                                         channel_types=[discord.ChannelType.text, discord.ChannelType.news],
                                         default_values=[discord.Object(ch.id)] if ch else [])

            async def cb(interaction):
                self.cfg.channel_id = s.values[0].id
                await self.save(interaction, "channel_id")
                await self._show(interaction, f"✅ Channel set to <#{self.cfg.channel_id}>.")
            s.callback = cb
            self.add_item(s)
        elif self.step == 1:
            s = discord.ui.RoleSelect(placeholder="Host roles", min_values=0, max_values=10, row=0,
                                      default_values=_role_defaults(g, c.host_role_ids))

            async def cb(interaction):
                self.cfg.host_role_ids = [r.id for r in s.values]
                await self.save(interaction, "host_role_ids")
                await self._show(interaction, "✅ Host roles saved.")
            s.callback = cb
            self.add_item(s)
        elif self.step == 2:
            s = discord.ui.RoleSelect(placeholder="Player roles (optional)", min_values=0, max_values=10, row=0,
                                      default_values=_role_defaults(g, c.player_role_ids))

            async def cb(interaction):
                self.cfg.player_role_ids = [r.id for r in s.values]
                await self.save(interaction, "player_role_ids")
                await self._show(interaction, "✅ Player roles saved.")
            s.callback = cb
            self.add_item(s)
            b = discord.ui.Button(label="Everyone joins", style=discord.ButtonStyle.secondary, emoji="🌍", row=1)

            async def everyone(interaction):
                self.cfg.player_role_ids = []
                await self.save(interaction, "player_role_ids")
                await self._show(interaction, "✅ Everyone joins.")
            b.callback = everyone
            self.add_item(b)
        elif self.step == 3:
            s = discord.ui.RoleSelect(placeholder="Winner role (optional)", min_values=0, max_values=1, row=0,
                                      default_values=_role_defaults(g, [c.winner_role_id] if c.winner_role_id else []))

            async def cb(interaction):
                role_id = s.values[0].id if s.values else None
                await self.mutate(interaction, lambda current: set_winner_role(current, interaction.guild, interaction.user, role_id))
                if role_id is not None:
                    await self.bot.db.approve_winner_role(interaction.guild_id, role_id)
                await self._show(interaction, "✅ Winner role saved." if self.cfg.winner_role_id else "Winner role cleared.")
            s.callback = cb
            self.add_item(s)
            h = discord.ui.Select(placeholder="How long winners keep it", row=1, options=[
                discord.SelectOption(label=f"Keep it {fmt_hours(x)}" if x else "Keep it until removed by hand",
                                     value=str(x), default=x == c.winner_role_hours) for x in WINNER_HOURS_CHOICES])

            async def hcb(interaction):
                self.cfg.winner_role_hours = int(h.values[0])
                await self.save(interaction, "winner_role_hours")
                await self._show(interaction, f"✅ Winners keep it {fmt_hours(self.cfg.winner_role_hours)}.")
            h.callback = hcb
            self.add_item(h)
            mk = discord.ui.Button(label="Create 'Rumble Champion' role", style=discord.ButtonStyle.success,
                                   emoji="➕", row=2)

            async def create(interaction):
                if not await self.authorize(interaction):
                    return
                require_role_creation(interaction.guild, interaction.user)
                try:
                    role = await interaction.guild.create_role(name="Rumble Champion", colour=discord.Colour(RED), permissions=discord.Permissions.none(),
                                                               reason="RipCars Rumble winner role")
                except discord.HTTPException:
                    return await self._show(interaction, "❌ The bot needs Manage Roles to create a role.")
                await self.mutate(interaction, lambda current: set_winner_role(current, interaction.guild, interaction.user, role.id))
                await self.bot.db.approve_winner_role(interaction.guild_id, role.id)
                await self._show(interaction, f"✅ Created {role.mention}. Drag the bot's role above it if needed.")
            mk.callback = create
            self.add_item(mk)
        elif self.step == 4:
            w = discord.ui.Select(placeholder="Default world", row=0, options=world_options(c.default_world))
            lob = discord.ui.Select(placeholder="Lobby time", row=1, options=[
                discord.SelectOption(label=f"Lobby {fmt_secs(x)}", value=str(x), default=x == c.lobby_seconds)
                for x in LOBBY_CHOICES])
            dl = discord.ui.Select(placeholder="Minimum lap pause", row=2, options=[
                discord.SelectOption(label=f"Base pause {fmt_secs(x)}", value=str(x), default=x == c.round_delay)
                for x in DELAY_CHOICES])

            async def wcb(interaction):
                self.cfg.default_world = w.values[0]
                await self.save(interaction, "default_world")
                await self._show(interaction)

            async def lcb(interaction):
                self.cfg.lobby_seconds = int(lob.values[0])
                await self.save(interaction, "lobby_seconds")
                await self._show(interaction)

            async def dcb(interaction):
                self.cfg.round_delay = int(dl.values[0])
                await self.save(interaction, "round_delay")
                await self._show(interaction)
            w.callback, lob.callback, dl.callback = wcb, lcb, dcb
            for x in (w, lob, dl):
                self.add_item(x)
        elif self.step == 5:
            channel = g.get_channel(c.report_channel_id) if c.report_channel_id else None
            selector = discord.ui.ChannelSelect(
                placeholder="Optional private report channel", min_values=0, max_values=1, row=0,
                channel_types=[discord.ChannelType.text, discord.ChannelType.news],
                default_values=[discord.Object(channel.id)] if channel else [])

            async def reports_cb(interaction):
                from .reporting import private_report_channel_problem
                selected = selector.values[0] if selector.values else None
                selected = interaction.guild.get_channel(selected.id) if selected else None
                def change(current):
                    if selected:
                        problem = private_report_channel_problem(interaction.guild, selected, current)
                        if problem:
                            raise PermissionError(problem)
                    current.report_channel_id = selected.id if selected else None
                await self.mutate(interaction, change)
                await self._show(interaction)
            selector.callback = reports_cb
            self.add_item(selector)
        # navigation row
        if self.step > 0:
            back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji="↩️", row=4)
            back.callback = self._back
            self.add_item(back)
        last = self.step == len(STEPS) - 1
        nxt = discord.ui.Button(label="Finish" if last else "Next", emoji="🏁" if last else "➡️", row=4,
                                style=discord.ButtonStyle.success if last else discord.ButtonStyle.primary,
                                disabled=(self.step == 0 and not c.channel_id))
        nxt.callback = self._finish if last else self._next
        self.add_item(nxt)

    async def _back(self, interaction):
        self.step = max(0, self.step - 1)
        await self._show(interaction)

    async def _next(self, interaction):
        if self.step == 0 and not self.cfg.channel_id:
            return await self._show(interaction, "❌ Pick a channel first.")
        self.step = min(len(STEPS) - 1, self.step + 1)
        await self._show(interaction)

    async def _finish(self, interaction):
        self.cfg.setup_done = True
        await self.save(interaction, "setup_done")
        await self.ack(interaction)
        results = await run_checks(self.bot, interaction.guild, self.cfg)
        bad = [r for r in results if r[0] != "ok" and r[1] not in ("Setup", "Recent errors", "Scheduler")]
        e = discord.Embed(title="🏁 RipCars Rumble is set up", color=RED)
        c = self.cfg
        g = interaction.guild
        e.description = (
            f"**Channel** <#{c.channel_id}>\n**Hosts** {describe_roles(g, c.host_role_ids, 'Manage Server only')}\n"
            f"**Players** {describe_roles(g, c.player_role_ids, 'everyone')}\n"
            f"**Winner role** {g.get_role(c.winner_role_id).mention if c.winner_role_id and g.get_role(c.winner_role_id) else 'none'}"
            f" · {fmt_hours(c.winner_role_hours)}\n**Default** {world_label(c.default_world)} · lobby "
            f"{fmt_secs(c.lobby_seconds)} · base pause {fmt_secs(c.round_delay)}\n"
            f"**Private reports** {g.get_channel(c.report_channel_id).mention if c.report_channel_id and g.get_channel(c.report_channel_id) else 'disabled'}\n\n"
            "Start one with **/rumble start**, or open **/rumble panel** for schedules and settings.")
        if bad:
            e.add_field(name="Fix these first", value="\n".join(f"{ICON[s]} **{t}** · {d}" for s, t, d in bad)[:1024],
                        inline=False)
        else:
            e.add_field(name="Local checks", value="✅ Local checks passed. Run a private Discord acceptance game next.", inline=False)
        v = PanelHome(self.bot, self.user, self.cfg)
        await interaction.edit_original_response(embed=e, view=v)
        self.stop()
