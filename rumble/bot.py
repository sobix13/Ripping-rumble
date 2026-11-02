"""The bot: slash commands, background loops, winner roles and game bookkeeping."""
import asyncio
import logging
import json
import os
from pathlib import Path
import random
import time
from collections import defaultdict, deque

import discord
from discord import app_commands
from discord.ext import commands, tasks

from . import render
from .assets import AssetPicker
from .content import world_choices, world_keys
from .db import Database
from .diagnostics import checks_embed, run_checks
from .perms import channel_problems, is_admin, is_host, role_problems
from .runner import GameRunner
from .redaction import redact
from .scheduler import GRACE, _weekly_occurrences_around, is_due

log = logging.getLogger("rumble.bot")
REPORT_SEND_TIMEOUT = 5

STOP_TEXT = {"stopped": "Stopping the rumble.", "none": "No rumble is running.",
             "finishing": "Too late to stop: the winner is already decided."}

WORLD_CHOICES = [app_commands.Choice(name="Random world", value="random")] + [
    app_commands.Choice(name=name, value=key) for key, name in world_choices()]


class RumbleBot(commands.Bot):
    def __init__(self, db_path, dev_guild_id=None):
        intents = discord.Intents.default()      # no privileged intents needed
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, help_command=None)
        self.db = Database(db_path)
        self.games = {}
        self._errors = defaultdict(lambda: deque(maxlen=25))
        self.loop_heartbeat = {}
        self.loop_success = {}
        self.closing = False
        self._close_task = None
        self.finish_tasks = set()
        self.role_locks = defaultdict(asyncio.Lock)
        self.start_locks = defaultdict(asyncio.Lock)
        self.recovery_lock = asyncio.Lock()
        self.dev_guild_id = dev_guild_id
        self.health = None
        self.health_status = dict(ok=False, checks={})
        self.report_queue = deque(maxlen=100)
        self.report_last_sent = {}
        self.report_cursor = 0
        self.backup_lock = asyncio.Lock()

    async def setup_hook(self):
        await self.db.open()
        await self.add_cog(RumbleCog(self))
        from .health import HealthMonitor
        health_file = os.environ.get('RUMBLE_HEALTH_FILE', str(Path(self.db.path).parent / 'health.json'))
        self.health = HealthMonitor(self, health_file, int(os.environ.get('HEALTH_PORT', '8093')))
        await self.health.start()
        if self.dev_guild_id:
            guild = discord.Object(self.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("commands synced to dev guild %s", self.dev_guild_id)
        else:
            await self.tree.sync()
            log.info("commands synced globally (can take up to an hour to show everywhere)")

    async def on_ready(self):
        log.info("logged in as %s (%s) in %d servers", self.user, self.user.id, len(self.guilds))
        if not self.closing:
            await self.recover_pending()

    async def close(self):
        if self._close_task is None:
            self.closing = True
            self._close_task = asyncio.create_task(self._close_all(), name="rumble-close")
        await asyncio.shield(self._close_task)

    def track_finish_task(self, task):
        self.finish_tasks.add(task)
        task.add_done_callback(self.finish_tasks.discard)
        return task

    async def recover_pending(self):
        from .runner import recover_pending
        async with self.recovery_lock:
            if not self.closing:
                await recover_pending(self)

    async def _close_all(self):
        if self.health is not None:
            try:
                await self.health.stop()
            except Exception as error:
                log.warning('Health monitor shutdown failed: %s', type(error).__name__)
        background = []
        for cog in self.cogs.values():
            for name in ("scheduler_loop", "roles_loop"):
                loop = getattr(cog, name, None)
                if loop is not None:
                    task = loop.get_task()
                    loop.cancel()
                    if task is not None:
                        background.append(task)
        if background:
            await asyncio.gather(*background, return_exceptions=True)
        tasks_ = set(self.finish_tasks)
        for runner in list(self.games.values()):
            if runner.task and not runner.task.done():
                runner.shutdown = True
                decided = getattr(getattr(runner, "game", None), "finished", False)
                if runner.state not in ("finishing", "finished") and not decided:
                    runner.task.cancel()
                tasks_.add(runner.task)
            finish = getattr(runner, "finish_task", None)
            if finish is not None:
                tasks_.add(finish)
        if tasks_:
            await asyncio.gather(*tasks_, return_exceptions=True)
        while self.finish_tasks:
            await asyncio.gather(*list(self.finish_tasks), return_exceptions=True)
        async with self.recovery_lock:
            await self.db.close()
        await super().close()

    # ---------- errors ----------
    def record_error(self, guild_id, msg):
        msg = redact(msg)
        log.warning("guild %s: %s", guild_id, msg)
        visible = msg if guild_id else 'A background check failed. Check the private service log.'
        self._errors[guild_id or 0].append((time.time(), visible))
        if guild_id:
            self.report_queue.append((time.time(), guild_id, msg))
        else:
            for guild in self.guilds:
                self.report_queue.append((time.time(), guild.id, 'A background check failed. Check Diagnostics and the service log.'))

    def errors_for(self, guild_id):
        return sorted(list(self._errors.get(guild_id, [])) + list(self._errors.get(0, [])))

    async def flush_error_reports(self):
        from .ui.reporting import private_report_channel_problem
        now = time.time()
        guild_ids = sorted({row[1] for row in self.report_queue})
        if not guild_ids:
            return
        start = self.report_cursor % len(guild_ids)
        selected = (guild_ids[start:] + guild_ids[:start])[:2]
        self.report_cursor = (start + len(selected)) % len(guild_ids)
        for guild_id in selected:
            if now - self.report_last_sent.get(guild_id, 0) < 60:
                continue
            guild = self.get_guild(guild_id)
            if guild is None:
                continue
            cfg = await asyncio.wait_for(self.db.get_config(guild_id), 3)
            channel = guild.get_channel(getattr(cfg, 'report_channel_id', None))
            if channel is None or private_report_channel_problem(guild, channel, cfg):
                continue
            batch = [row for row in self.report_queue if row[1] == guild_id][:3]
            body = '\n'.join(f'<t:{int(t)}:R> {redact(msg)[:400]}' for t, _, msg in batch)
            self.report_last_sent[guild_id] = now
            try:
                await asyncio.wait_for(channel.send(content='RipCars Rumble operational report\n' + body,
                                       allowed_mentions=discord.AllowedMentions.none()), REPORT_SEND_TIMEOUT)
            except (discord.Forbidden, discord.NotFound):
                continue
            except Exception:
                # Unknown delivery is retained in the file log, never blindly resent to Discord.
                log.warning('Private report delivery uncertain for guild %s', guild_id)
            for row in batch:
                try:
                    self.report_queue.remove(row)
                except ValueError:
                    pass

    def backup_directory(self):
        return Path(os.environ.get('RUMBLE_BACKUP_DIR', str(Path(self.db.path).parent.parent / 'backups')))

    async def create_backup(self):
        from .maintenance import create_backup
        async with self.backup_lock:
            return await asyncio.to_thread(create_backup, self.db.path, self.backup_directory())

    async def operational_status(self):
        result = dict(self.health_status)
        marker = self.backup_directory() / 'latest.json'
        try:
            result['backup'] = json.loads(marker.read_text())
            name = result['backup'].get('metadata_file', '')
            if not name or Path(name).name != name:
                raise ValueError('Invalid backup metadata')
            from .maintenance import verify_backup
            await asyncio.to_thread(verify_backup, marker.parent / name)
            result['backup']['verified'] = True
            result['backup']['recent'] = time.time() - result['backup'].get('created_at', 0) <= 172800
        except Exception:
            result['backup'] = {}
        result['pending_reports'] = len(self.report_queue)
        return result

    # ---------- games ----------
    def preflight(self, guild, cfg):
        """Problems that block a rumble from starting, as a list of strings."""
        if self.closing:
            return ["The bot is shutting down. Try again after it reconnects."]
        if not cfg.setup_done or not cfg.channel_id:
            return ["Rumble is not set up yet. Ask an admin to run /rumble setup."]
        channel = guild.get_channel(cfg.channel_id)
        probs = channel_problems(channel, guild.me)
        probs.extend(role_problems(guild, cfg.winner_role_id, guild.me))
        if cfg.winner_role_id and cfg.winner_role_id in set(cfg.host_role_ids + cfg.admin_role_ids + cfg.player_role_ids):
            probs.append("The winner role must be separate from access and staff roles.")
        if guild.id in self.games:
            probs.append("A rumble is already running in this server.")
        return probs

    async def start_game(self, guild, cfg, world_key=None, host=None, source="manual"):
        async with self.start_locks[guild.id]:
            probs = self.preflight(guild, cfg)
            if probs:
                return None, probs
            channel = guild.get_channel(cfg.channel_id)
            runner = GameRunner(self, guild, channel, cfg, world_key=world_key, host=host, source=source)
            self.games[guild.id] = runner
            runner.task = asyncio.create_task(runner.run(), name=f"rumble-{guild.id}")
        started = asyncio.create_task(runner.started_event.wait())
        try:
            done, _ = await asyncio.wait({started, runner.task}, timeout=30, return_when=asyncio.FIRST_COMPLETED)
            if not done or not runner.startup_ok:
                if not runner.task.done():
                    runner.task.cancel()
                await asyncio.gather(runner.task, return_exceptions=True)
                await self._schedule_start_failure(source, runner)
                return None, [getattr(runner, "startup_error", None) or "The lobby did not open. Check diagnostics."]
        except BaseException:
            if not runner.task.done() and not getattr(getattr(runner, "game", None), "finished", False):
                runner.task.cancel()
            await asyncio.gather(runner.task, return_exceptions=True)
            await self._schedule_start_failure(source, runner)
            raise
        finally:
            started.cancel()
            await asyncio.gather(started, return_exceptions=True)
        return runner, []

    async def _schedule_start_failure(self, source, runner):
        if source.startswith("schedule:"):
            _, schedule_id, occurrence = source.split(":")
            await self.db.complete_schedule_occurrence(
                int(schedule_id), int(occurrence), success=False,
                uncertain=bool(getattr(runner, "startup_ambiguous", False)))

    def stop_game(self, guild_id):
        """Return 'stopped', 'finishing' (winner already decided, too late) or 'none'."""
        runner = self.games.get(guild_id)
        if not runner or not runner.task or runner.task.done():
            return "none"
        if runner.state in ("finishing", "finished") or getattr(getattr(runner, "game", None), "finished", False):
            return "finishing"
        if not getattr(runner, "stop_requested", False):
            runner.stop_requested = True
            runner.task.cancel()
        return "stopped"

    async def grant_winner_role(self, guild, user_id, cfg):
        async with self.role_locks[(guild.id, user_id, cfg.winner_role_id)]:
            return await self._grant_winner_role(guild, user_id, cfg)

    async def _grant_winner_role(self, guild, user_id, cfg):
        role = guild.get_role(cfg.winner_role_id)
        if role is None:
            self.record_error(guild.id, "Winner role is missing. Pick a new one in the panel.")
            return False
        if not await self.db.approved_winner_role(guild.id, role.id):
            self.record_error(guild.id, "Winner role needs approval in Settings before use.")
            return False
        problems = role_problems(guild, role.id, guild.me)
        current_cfg = await self.db.get_config(guild.id)
        access_roles = cfg.host_role_ids + cfg.admin_role_ids + cfg.player_role_ids
        access_roles += current_cfg.host_role_ids + current_cfg.admin_role_ids + current_cfg.player_role_ids
        if role.id in set(access_roles):
            problems.append("The award role is also an access or staff role.")
        if problems:
            self.record_error(guild.id, "Winner role rejected: " + " | ".join(problems))
            return False
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            self.record_error(guild.id, "The winner left the server before the role delivery.")
            return True
        already = any(r.id == role.id for r in getattr(member, "roles", []))
        tracked = await self.db.get_winner_role(guild.id, user_id, role.id)
        if already and tracked is None:
            return True          # they had this role before the rumble: never add an expiry that would remove it
        expires = int(time.time()) + cfg.winner_role_hours * 3600 if cfg.winner_role_hours else None
        if tracked and tracked["expires_at"] is None:
            expires = None
        await self.db.add_winner_role(guild.id, user_id, role.id, expires)   # row first, so a crash cannot strand it
        if already:
            return True          # repeat winner: the expiry is pushed back
        try:
            await member.add_roles(role, reason="RipCars Rumble winner")
        except discord.HTTPException as e:
            self.record_error(guild.id, f"Winner role delivery failed for @{role.name}. Pending result will retry "
                                        f"({type(e).__name__}).")
            return False
        return True


def _deny(text):
    return render.notice_embed(None, "Not allowed", text, color=0xD83C3E)


class RumbleCog(commands.Cog):
    rumble = app_commands.Group(name="rumble", description="RipCars Rumble", guild_only=True)

    def __init__(self, bot: RumbleBot):
        self.bot = bot
        self._schedule_retry = {}

    async def cog_load(self):
        self.scheduler_loop.start()
        self.roles_loop.start()

    async def cog_unload(self):
        self.scheduler_loop.cancel()
        self.roles_loop.cancel()

    async def cog_app_command_error(self, interaction, error):
        orig = getattr(error, "original", error)
        if isinstance(orig, app_commands.CommandOnCooldown):
            text = f"Try again in {orig.retry_after:.0f} seconds."
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
            return
        log.exception("command error", exc_info=orig)
        self.bot.record_error(interaction.guild_id, f"/{interaction.command.qualified_name if interaction.command else '?'}"
                                                    f": {type(orig).__name__}: {orig}")
        msg = "Something went wrong. Ask an admin to check /rumble diagnose."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass

    # ---------- commands ----------
    @rumble.command(name="start", description="Open a rumble lobby in the game channel")
    @app_commands.describe(world="Which world to play (default from settings)")
    @app_commands.choices(world=WORLD_CHOICES)
    async def start(self, interaction: discord.Interaction, world: app_commands.Choice[str] = None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        cfg = await self.bot.db.get_config(interaction.guild_id)
        if not is_host(interaction.user, cfg):
            return await interaction.edit_original_response(embed=_deny("Starting rumbles is for hosts only."))
        runner, probs = await self.bot.start_game(interaction.guild, cfg, world.value if world else None,
                                                  host=interaction.user.display_name)
        if probs:
            return await interaction.edit_original_response(content="\n".join(f"• {p}" for p in probs))
        await interaction.edit_original_response(
            content=f"{runner.world.emoji} **{runner.world.name}** lobby is open in <#{cfg.channel_id}>.")

    @rumble.command(name="stop", description="Stop the rumble that is running now")
    async def stop(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        cfg = await self.bot.db.get_config(interaction.guild_id)
        if not is_host(interaction.user, cfg):
            return await interaction.edit_original_response(embed=_deny("Stopping rumbles is for hosts only."))
        res = self.bot.stop_game(interaction.guild_id)
        await interaction.edit_original_response(content=STOP_TEXT[res])

    @rumble.command(name="panel", description="Open the control panel")
    async def panel(self, interaction: discord.Interaction):
        from .ui.panel import PanelHome
        await interaction.response.defer(ephemeral=True, thinking=True)
        cfg = await self.bot.db.get_config(interaction.guild_id)
        if not is_host(interaction.user, cfg):
            return await interaction.edit_original_response(embed=_deny("The panel is for rumble hosts and admins."))
        view = PanelHome(self.bot, interaction.user, cfg)
        await interaction.edit_original_response(embed=await view.render(interaction.guild), view=view)

    @rumble.command(name="setup", description="Step-by-step setup: channel, roles, winner role, defaults")
    async def setup(self, interaction: discord.Interaction):
        from .ui.setup import SetupWizard
        await interaction.response.defer(ephemeral=True, thinking=True)
        cfg = await self.bot.db.get_config(interaction.guild_id)
        if not is_admin(interaction.user, cfg):
            return await interaction.edit_original_response(embed=_deny("Setup needs Manage Server or a rumble admin role."))
        view = SetupWizard(self.bot, interaction.user, cfg)
        await interaction.edit_original_response(embed=view.render(interaction.guild), view=view)

    @rumble.command(name="leaderboard", description="Top rumble winners in this server")
    @app_commands.checks.cooldown(1, 15, key=lambda interaction: interaction.guild_id)
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        rows = await self.bot.db.leaderboard(interaction.guild_id, 10)
        e = render.leaderboard_embed(rows, interaction.guild.name)
        kw = {"embed": e, "allowed_mentions": discord.AllowedMentions.none()}
        rel = AssetPicker().pick("leaderboard")
        if rel:
            kw["file"], url = AssetPicker.file(rel)
            e.set_thumbnail(url=url)
        await interaction.followup.send(**kw)

    @rumble.command(name="stats", description="Rumble stats for you or another member")
    async def stats(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        member = member or interaction.user
        row = await self.bot.db.user_stats(interaction.guild_id, member.id)
        await interaction.edit_original_response(embed=render.stats_embed(member, row))

    @rumble.command(name="worlds", description="The six rumble worlds")
    async def worlds(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=render.worlds_embed(), ephemeral=True)

    @rumble.command(name="guide", description="Read the player guide or administrator guide")
    async def guide(self, interaction: discord.Interaction, admin: bool = False):
        from .guides import GuideView
        await interaction.response.defer(ephemeral=True, thinking=True)
        cfg = await self.bot.db.get_config(interaction.guild_id)
        if admin and not is_admin(interaction.user, cfg):
            return await interaction.edit_original_response(embed=_deny('The admin guide needs rumble admin access.'))
        view = GuideView(self.bot, interaction.user, cfg, admin=admin)
        await interaction.edit_original_response(embed=await view.render(interaction.guild), view=view)

    @rumble.command(name="diagnose", description="Check permissions, roles, schedules and recent errors")
    async def diagnose(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        cfg = await self.bot.db.get_config(interaction.guild_id)
        if not is_admin(interaction.user, cfg):
            return await interaction.edit_original_response(embed=_deny("Diagnostics need Manage Server or a rumble admin role."))
        results = await run_checks(self.bot, interaction.guild, cfg)
        await interaction.edit_original_response(embed=checks_embed(results, interaction.guild.name))

    # ---------- loops ----------
    @tasks.loop(seconds=30)
    async def scheduler_loop(self):
        self.bot.loop_heartbeat["scheduler"] = time.time()
        try:
            await self._run_schedules()
            self.bot.loop_success["scheduler"] = time.time()
        except Exception as e:  # noqa: BLE001  (the loop must never die)
            log.exception("scheduler pass failed")
            self.bot.record_error(0, f"Scheduler error: {type(e).__name__}: {e}")

    async def _run_schedules(self):
        if self.bot.closing:
            return
        now = int(time.time())
        for sched in await self.bot.db.schedules(enabled_only=True):
            guild = self.bot.get_guild(sched["guild_id"])
            if guild is None:
                continue
            cfg = await self.bot.db.get_config(guild.id)
            due, missed = is_due(sched, cfg.timezone, now)
            if missed:
                await self.bot.db.mark_schedule_run(sched["id"], now, disable=True)
                self.bot.record_error(guild.id, f"Scheduled rumble #{sched['id']} was missed (bot offline).")
                continue
            if not due:
                continue
            if guild.id in self.bot.games:
                continue          # another rumble is running: try again next pass, inside the grace window
            occurrence = sched["run_at"] if sched["kind"] == "once" else max(
                t for t in _weekly_occurrences_around(sched, cfg.timezone, now) if t <= now)
            key = (sched["id"], occurrence)
            attempts, retry_at = self._schedule_retry.get(key, (0, 0))
            if now < retry_at:
                continue
            self._schedule_retry = {k: v for k, v in self._schedule_retry.items() if now <= k[1] + GRACE}
            problems = self.bot.preflight(guild, cfg)
            if problems:
                if attempts == 0:
                    self.bot.record_error(guild.id, f"Scheduled rumble #{sched['id']} is waiting: " + " | ".join(problems))
                self._schedule_retry[key] = (attempts + 1, now + min(120, 30 * 2 ** min(attempts, 2)))
                continue
            if not await self.bot.db.claim_schedule_occurrence(sched["id"], occurrence):
                continue
            world = sched["world"] if sched["world"] in world_keys() else random.choice(world_keys())
            try:
                runner, probs = await self.bot.start_game(
                    guild, cfg, world, host="schedule", source=f"schedule:{sched['id']}:{occurrence}")
            except BaseException:
                await self.bot.db.complete_schedule_occurrence(sched["id"], occurrence, success=False)
                raise
            if probs:
                await self.bot.db.complete_schedule_occurrence(sched["id"], occurrence, success=False)
                self._schedule_retry[key] = (attempts + 1, now + min(120, 30 * 2 ** min(attempts, 2)))
                self.bot.record_error(guild.id, f"Scheduled rumble #{sched['id']} did not start: {' | '.join(probs)}")
                continue
            await self.bot.db.complete_schedule_occurrence(sched["id"], occurrence, game_id=getattr(runner, "game_id", None))
            await self.bot.db.mark_schedule_run(sched["id"], occurrence, disable=sched["kind"] == "once")
            self._schedule_retry.pop(key, None)

    @scheduler_loop.before_loop
    async def _wait_ready_sched(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def roles_loop(self):
        self.bot.loop_heartbeat["roles"] = time.time()
        try:
            await self._expire_roles()
            await self.bot.recover_pending()
            self.bot.loop_success["roles"] = time.time()
        except Exception as e:  # noqa: BLE001
            log.exception("winner role pass failed")
            self.bot.record_error(0, f"Winner role loop error: {type(e).__name__}: {e}")

    async def _expire_roles(self):
        for row in await self.bot.db.expired_winner_roles():
            async with self.bot.role_locks[(row["guild_id"], row["user_id"], row["role_id"])]:
                await self._expire_role(row)

    async def _expire_role(self, row):
        current = await self.bot.db.get_winner_role(row["guild_id"], row["user_id"], row["role_id"])
        if current is None or current["expires_at"] is None or current["expires_at"] > time.time():
            return
        row = current
        guild = self.bot.get_guild(row["guild_id"])
        if guild is None:
            return
        role = guild.get_role(row["role_id"])
        try:
            member = await guild.fetch_member(row["user_id"])
            if role and role in member.roles:
                await member.remove_roles(role, reason="RipCars Rumble winner role expired")
        except discord.NotFound:
            pass
        except discord.Forbidden:
            self.bot.record_error(guild.id, "Expired winner role removal was refused. Check role order.")
            return
        except discord.HTTPException as e:
            self.bot.record_error(guild.id, f"Winner role removal failed: {e}")
            return
        await self.bot.db.drop_winner_role(row["guild_id"], row["user_id"], row["role_id"],
                                           expected_expires_at=row["expires_at"])


    @roles_loop.before_loop
    async def _wait_ready_roles(self):
        await self.bot.wait_until_ready()
