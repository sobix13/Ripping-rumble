"""One rumble in one channel: lobby, laps, Second Chance, results, stats and the winner role."""
import asyncio
import logging
import random
import time
from datetime import datetime, timezone

from .config import GuildConfig

import discord

from . import render
from .assets import AssetPicker, lobby_asset, round_mood
from .content import get_world, world_keys
from .content.overrides import apply_overrides
from .engine import Game
from .perms import can_join, describe_roles, is_host
from .text import clean_name, reading_pause

log = logging.getLogger("rumble.runner")


class Clock:
    """Real time. Tests swap in a fake clock so a whole rumble runs instantly."""
    def now(self):
        return time.time()

    def monotonic(self):
        return time.monotonic()

    async def sleep(self, s):
        await asyncio.sleep(s)


class GameRunner:
    def __init__(self, bot, guild, channel, cfg, world_key=None, host=None, source="manual", clock=None, seed=None):
        from .ui.lobby import LobbyView  # local import keeps engine-only imports light
        self._LobbyView = LobbyView
        self.bot = bot
        self.guild = guild
        self.channel = channel
        self.cfg = cfg
        key = world_key or cfg.default_world
        if key == "random" or key not in world_keys():
            key = random.choice(world_keys())
        self.world = apply_overrides(get_world(key), getattr(cfg, "text_overrides", {}))
        self.host = host
        self.source = source
        self.clock = clock or Clock()
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.players = {}
        self.state = "lobby"
        self.game = None
        self.game_id = None
        self.lobby_msg = None
        self.lobby_line = random.Random(self.seed).choice(self.world.lobby)
        self.lobby_view = None
        self.sc_view = None
        self.sc_msg = None
        self.sc_open = False
        self.shutdown = False
        self.sc_winner = None
        self.sc_event = None
        self.start_now = asyncio.Event()
        self.lobby_dirty = False
        self.task = None
        self.finish_task = None
        self.cleanup_task = None
        self.started_event = asyncio.Event()
        self.startup_ok = False
        self.startup_error = None
        self.startup_ambiguous = False
        self.lobby_deadline = 0
        self.started_at = None
        self.lobby_ends = 0
        self.picker = AssetPicker(random.Random(self.seed + 1))

    # ---------- join / leave (called by the lobby view) ----------
    def _lobby_open(self):
        now = getattr(self.clock, "monotonic", self.clock.now)()
        before_deadline = (now < self.lobby_deadline if self.lobby_deadline else
                           not self.lobby_ends or self.clock.now() < self.lobby_ends)
        return (self.state == "lobby" and not self.start_now.is_set()
                and before_deadline)

    def try_join(self, member, cfg=None):
        if not self._lobby_open():
            return False, "The grid is locked. Catch the next rumble."
        if getattr(member, "bot", False):
            return False, "Bots watch from the stands."
        policy = cfg or self.cfg
        if not can_join(member, policy):
            return False, f"Entry requires {describe_roles(self.guild, policy.player_role_ids)}."
        if member.id in self.players:
            return False, "You're already on the grid."
        if len(self.players) >= self.cfg.max_players:
            return False, "The grid is full."
        self.players[member.id] = clean_name(getattr(member, "display_name", None) or member.name)
        self.lobby_dirty = True
        return True, f"You're in, {self.players[member.id]}. Engines on. 🏎️"

    def try_leave(self, member):
        if not self._lobby_open():
            return False, "The race already started. No pit exit now."
        if member.id not in self.players:
            return False, "You're not on the grid."
        self.players.pop(member.id)
        self.lobby_dirty = True
        return True, "You left the grid."

    def try_start_now(self, member, cfg=None):
        if not self._lobby_open():
            return False, "The race already started."
        if not is_host(member, cfg or self.cfg):
            return False, "Early start is restricted to rumble hosts."
        if len(self.players) < self.cfg.min_players:
            return False, f"Need at least {self.cfg.min_players} rippers on the grid."
        self.start_now.set()
        return True, "Starting now."

    def try_second_chance(self, member):
        return False, "Second Chance runs automatically."

    # ---------- lifecycle ----------
    async def run(self):
        try:
            self.game_id = await self.bot.db.game_started(self.guild.id, self.world.key, self.source)
            await self._lobby()
            if len(self.players) < self.cfg.min_players:
                await self._cancel()
                return
            await self._play()
        except asyncio.CancelledError:
            await self._preserve_uncertain_startup()
            if self.finish_task is not None:
                await asyncio.shield(self.finish_task)
            else:
                if self.cleanup_task is None:
                    self.state = "stopping"
                    self.cleanup_task = asyncio.create_task(self._stopped(), name=f"rumble-cleanup-{self.guild.id}")
                    if hasattr(self.bot, "track_finish_task"):
                        self.bot.track_finish_task(self.cleanup_task)
                await asyncio.shield(self.cleanup_task)
        except Exception as e:
            log.exception("rumble failed in guild %s", self.guild.id)
            self.startup_error = str(e)
            await self._preserve_uncertain_startup()
            self.bot.record_error(self.guild.id, f"Rumble error: {type(e).__name__}: {e}")
            self.state = "error"
            await self._safe(self.channel.send(embed=render.notice_embed(
                self.world, "Rumble stopped", "The rumble stopped. Details are in /rumble diagnose.")))
            if self.game_id:
                await self._safe(self.bot.db.game_status(self.game_id, "error"))
        finally:
            self.started_event.set()
            if self.state == "error" and self.lobby_msg is not None and self.lobby_view is not None:
                self.lobby_view.disable()
                closed = await self._safe(self.lobby_msg.edit(view=self.lobby_view))
                if closed is not None and self.game_id:
                    await self._safe(self.bot.db.mark_messages_cleaned(self.game_id))
            for v in (self.lobby_view, self.sc_view):
                if v:
                    v.stop()
            if self.bot.games.get(self.guild.id) is self:
                self.bot.games.pop(self.guild.id, None)

    async def _safe(self, coro):
        try:
            return await coro
        except Exception as e:  # noqa: BLE001
            log.warning("ignored error: %s", e)
            self.bot.record_error(self.guild.id, f"{type(e).__name__}: {e}")
            return None

    async def _preserve_uncertain_startup(self):
        if self.startup_ambiguous and not self.startup_ok and self.source.startswith('schedule:'):
            _, sid, occurrence = self.source.split(':')
            await self.bot.db.complete_schedule_occurrence(int(sid), int(occurrence), success=False, uncertain=True)

    async def _lobby(self):
        cfg = self.cfg
        self.lobby_ends = self.clock.now() + cfg.lobby_seconds
        self.lobby_deadline = getattr(self.clock, "monotonic", self.clock.now)() + cfg.lobby_seconds
        self.lobby_view = self._LobbyView(self, timeout=cfg.lobby_seconds + 120)
        kwargs = {"embed": self._lobby_embed(), "view": self.lobby_view}
        rel = lobby_asset(self.world)
        if cfg.images:
            f, url = self.picker.file(rel)
            kwargs["embed"].set_thumbnail(url=url)
            kwargs["file"] = f
        if cfg.ping_role_id and self.guild.get_role(cfg.ping_role_id):
            kwargs["content"] = f"<@&{cfg.ping_role_id}> a rumble is starting."
            kwargs["allowed_mentions"] = discord.AllowedMentions(roles=[discord.Object(cfg.ping_role_id)],
                                                                 users=False, everyone=False)
        else:
            kwargs["allowed_mentions"] = discord.AllowedMentions.none()
        self.startup_ambiguous = True
        try:
            self.lobby_msg = await self.channel.send(**kwargs)
        except (discord.Forbidden, discord.NotFound):
            self.startup_ambiguous = False
            raise
        await self.bot.db.track_game_messages(self.game_id, self.guild.id, self.channel.id, self.lobby_msg.id)
        self.startup_ambiguous = False
        self.startup_ok = True
        self.started_event.set()
        last_edit = 0.0
        while self._lobby_open():
            await self.clock.sleep(1)
            if self.lobby_dirty and self.clock.now() - last_edit >= 2:
                self.lobby_dirty = False
                last_edit = self.clock.now()
                await self._safe(self.lobby_msg.edit(embed=self._lobby_embed(keep_thumb=True)))

    def _lobby_embed(self, keep_thumb=False, locked=False, rounds=None):
        e = render.lobby_embed(self.world, self.lobby_line, list(self.players.values()), self.lobby_ends,
                               self.cfg.max_players, self.cfg.min_players, host=self.host, locked=locked,
                               rounds=rounds)
        if keep_thumb and self.cfg.images and self.lobby_msg is not None:
            atts = getattr(self.lobby_msg, "attachments", None) or []
            if atts:
                e.set_thumbnail(url=f"attachment://{atts[0].filename}")
        return e

    async def _cancel(self):
        self.state = "cancelled"
        if self.lobby_view:
            self.lobby_view.disable()
        if self.lobby_msg is not None:
            closed = await self._safe(self.lobby_msg.edit(embed=self._lobby_embed(keep_thumb=True), view=self.lobby_view))
            if closed is not None:
                await self.bot.db.mark_messages_cleaned(self.game_id)
        kwargs = {"embed": render.notice_embed(
            self.world, "Not enough rippers",
            f"Only {len(self.players)} joined. A rumble needs {self.cfg.min_players}. Next time, fam.")}
        self._attach(kwargs, "cancel")
        await self._safe(self.channel.send(**kwargs))
        await self._safe(self.bot.db.game_status(self.game_id, "cancelled", players=len(self.players)))

    async def _stopped(self):
        self.state = "stopped"
        self.sc_open = False
        for v in (self.lobby_view, self.sc_view):
            if v:
                v.disable()
        if self.lobby_msg is not None and self.lobby_view is not None:
            closed = await self._safe(self.lobby_msg.edit(view=self.lobby_view))
            if closed is not None:
                await self.bot.db.mark_messages_cleaned(self.game_id)
        if self.sc_msg is not None and self.sc_view is not None:
            await self._safe(self.sc_msg.edit(
                embed=render.second_chance_embed(self.world, 0, None, result="Closed. The rumble was stopped."),
                view=self.sc_view, attachments=[]))
        text = ("The bot is restarting, so this rumble was stopped. No winner this time." if self.shutdown
                else "A host stopped this rumble. No winner this time.")
        kwargs = {"embed": render.notice_embed(self.world, "Rumble stopped", text)}
        self._attach(kwargs, "stopped")
        await self._safe(self.channel.send(**kwargs))
        if self.game_id:
            await self._safe(self.bot.db.game_status(self.game_id, "stopped", players=len(self.players)))

    def _attach(self, kwargs, mood):
        if not self.cfg.images:
            return None
        rel = self.picker.pick(mood)
        if not rel:
            return None
        f, url = self.picker.file(rel)
        kwargs["file"] = f
        kwargs["embed"].set_thumbnail(url=url)
        return rel

    async def _play(self):
        cfg = self.cfg
        self.state = "running"
        recent = await self.bot.db.recent_content_ids(self.guild.id)
        self.game = Game(self.world, list(self.players.items()), cfg.engine_settings(), seed=self.seed,
                         recent_line_ids=recent)
        self.started_at = self.clock.now()
        self.lobby_view.disable()
        closed = await self._safe(self.lobby_msg.edit(
            embed=self._lobby_embed(keep_thumb=True, locked=True, rounds=self.game.total_rounds),
            view=self.lobby_view))
        if closed is not None:
            await self.bot.db.mark_messages_cleaned(self.game_id)
        await self.bot.db.game_status(self.game_id, "running", players=len(self.players))
        emoji = {}
        if cfg.server_emoji:
            emoji = {e.name: str(e) for e in getattr(self.guild, "emojis", []) if getattr(e, "available", True)}
        await self.clock.sleep(3)
        while not self.game.finished:
            rd = self.game.next_round()
            if rd.final:
                # No await between the engine decision and making Stop refuse the game.
                self.state = "finishing"
                self.finish_task = asyncio.create_task(self._finish(rd, emoji), name=f"rumble-finish-{self.game_id}")
                if hasattr(self.bot, "track_finish_task"):
                    self.bot.track_finish_task(self.finish_task)
                await asyncio.shield(self.finish_task)
                return
            round_text = await self._send_round(rd, emoji)
            if rd.second_chance:
                round_text += "\n" + await self._second_chance()
            await self.clock.sleep(reading_pause(round_text, cfg.round_delay))

    async def _send_round(self, rd, emoji):
        rel = self.picker.pick(round_mood(rd)) if self.cfg.images else None
        thumb_url, file = None, None
        if rel:
            file, thumb_url = self.picker.file(rel)
        messages = render.round_messages(self.world, rd, emoji, thumb_url, self.game.total_rounds, game=self.game)
        for i, embeds in enumerate(messages):
            kwargs = {"embeds": embeds, "allowed_mentions": discord.AllowedMentions.none()}
            if i == 0 and file:
                kwargs["file"] = file
            await self.channel.send(**kwargs)

        return "\n".join(embed.description or "" for embeds in messages for embed in embeds)

    async def _second_chance(self):
        text, uid = self.game.resolve_auto_second_chance()
        kwargs = {"embed": render.second_chance_embed(self.world, 0, result=text),
                  "allowed_mentions": discord.AllowedMentions.none()}
        self._attach(kwargs, "second_chance")
        await self.channel.send(**kwargs)
        return text

    async def _finish(self, final_round=None, emoji=None):
        game = self.game
        summary = game.summary()
        duration = self.clock.now() - (self.started_at or self.clock.now())
        payload = render.result_payload(self.world, game, duration)
        payload.update(world=self.world.key, channel_id=self.channel.id,
                       winner_role_id=self.cfg.winner_role_id, winner_role_hours=self.cfg.winner_role_hours,
                       images=self.cfg.images,
                       line_ids=sorted(set(game.used) | {event.line_id for rd in game.history for event in rd.events}))
        places = summary.get("places", {})
        rows = [{"user_id": pid, "name": self.players.get(pid, ""), "place": places.get(pid, i),
                 "kills": summary["kills"].get(pid, 0), "won": pid == game.winner}
                for i, pid in enumerate(summary["ranking"], 1)]
        await self.bot.db.finalize_game(self.game_id, self.guild.id, rows, game.winner, summary["rounds"], payload)
        if final_round is not None:
            # The result is already durable if the final scene fails to reach Discord.
            await self._safe(self._send_round(final_round, emoji or {}))
        await self.clock.sleep(2)
        row = await self.bot.db.result_for_game(self.game_id)
        await deliver_pending_result(self.bot, self.guild, self.channel, row)
        self.state = "finished"


async def _find_announced_message(channel, row, bot_user_id=None):
    marker = f"Rumble #{row['game_id']}"
    if not hasattr(channel, "history"):
        return None
    after = datetime.fromtimestamp(row["finalized_at"] - 5, timezone.utc)
    count = 0
    async for message in channel.history(limit=200, after=after, oldest_first=False):
        count += 1
        if bot_user_id is not None and getattr(getattr(message, "author", None), "id", None) != bot_user_id:
            continue
        if any((embed.footer.text or "").endswith(marker) for embed in message.embeds):
            return message
    if count == 200:
        raise RuntimeError("Uncertain result delivery exceeds the history reconciliation window")
    return None


async def deliver_pending_result(bot, guild, channel, row):
    """Retry side effects without ever recounting a committed result."""
    async with bot.db.delivery_lock(row["game_id"]):
        row = await bot.db.result_for_game(row["game_id"])
        payload, game_id = row["payload"], row["game_id"]
        if row["announcement_message_id"] is None:
            try:
                if row["announcement_state"] in ("sending", "unknown"):
                    if not hasattr(channel, "history"):
                        raise RuntimeError("Delivery confirmation needs channel message history")
                    prior = await _find_announced_message(channel, row, getattr(getattr(bot, "user", None), "id", None))
                    if prior is not None:
                        await bot.db.mark_announcement(game_id, prior.id)
                        row["announcement_message_id"] = prior.id
                    else:
                        raise RuntimeError("Uncertain result delivery awaits manual confirmation")
                if row["announcement_message_id"] is None:
                    await bot.db.mark_announcement_attempt(game_id, "sending")
                    kwargs = render.result_delivery_kwargs(payload, game_id)
                    if payload.get("images"):
                        picker = AssetPicker(random.Random(game_id))
                        rel = picker.pick("winner")
                        if rel:
                            image_file, url = picker.file(rel)
                            if "file" in kwargs:
                                kwargs["files"] = [kwargs.pop("file"), image_file]
                            else:
                                kwargs["file"] = image_file
                            kwargs["embed"].set_thumbnail(url=url)
                    message = await channel.send(**kwargs)
                    await bot.db.mark_announcement(game_id, message.id)
            except Exception as error:
                state = "pending" if isinstance(error, (discord.Forbidden, discord.NotFound)) else "unknown"
                await bot.db.mark_announcement_attempt(game_id, state, f"{type(error).__name__}: {error}")
                bot.record_error(guild.id, f"Result #{game_id} delivery pending: {type(error).__name__}: {error}")
        if not row["role_done"]:
            cfg = GuildConfig(guild_id=guild.id, winner_role_id=payload.get("winner_role_id"),
                              winner_role_hours=payload.get("winner_role_hours", 24))
            try:
                result = await bot.grant_winner_role(guild, int(payload["winner_id"]), cfg)
                # The old fake helper returns None after successfully recording the grant.
                if result is not False:
                    await bot.db.mark_role_delivered(game_id)
            except Exception as error:
                await bot.db.delivery_error(game_id, f"Role delivery: {type(error).__name__}: {error}")
                bot.record_error(guild.id, f"Result #{game_id} role pending: {type(error).__name__}: {error}")


async def recover_pending(bot):
    for row in await bot.db.interrupted_messages():
        guild = bot.get_guild(row["guild_id"])
        channel = guild.get_channel(row["channel_id"]) if guild else None
        if channel is None:
            continue
        try:
            for key in ("lobby_message_id", "sc_message_id"):
                if row[key]:
                    try:
                        message = await channel.fetch_message(row[key])
                        await message.edit(view=None, embed=render.notice_embed(get_world(row["world"]),
                            "Rumble closed", "This rumble has ended. Join the next grid."))
                    except discord.NotFound:
                        pass
            await bot.db.mark_messages_cleaned(row["game_id"])
        except Exception as error:
            bot.record_error(guild.id, f"Old rumble message cleanup pending: {type(error).__name__}: {error}")
    for row in await bot.db.pending_deliveries():
        active = bot.games.get(row["guild_id"])
        if active and active.game_id == row["game_id"] and active.finish_task and not active.finish_task.done():
            continue
        guild = bot.get_guild(row["guild_id"])
        channel = guild.get_channel(row["channel_id"]) if guild else None
        if guild and channel:
            await deliver_pending_result(bot, guild, channel, row)
