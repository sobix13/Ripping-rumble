"""Troubleshooting: everything that can stop a rumble, checked in one place."""
import os
import time

import discord

from . import __version__
from .assets import missing_assets, all_assets
from .content.validate import validate_all
from .perms import channel_problems, role_problems
from .scheduler import next_run


async def run_checks(bot, guild, cfg):
    """Return list of (status, title, detail). status: ok | warn | fail"""
    out = []
    me = guild.me
    # database
    try:
        await bot.db.ping()
        out.append(("ok", "Database", "Connected"))
    except Exception as e:  # noqa: BLE001
        out.append(("fail", "Database", f"{type(e).__name__}: {e}"))
    # setup
    if not cfg.setup_done:
        out.append(("warn", "Setup", "Setup has not been finished. Run /rumble setup."))
    channel = guild.get_channel(cfg.channel_id) if cfg.channel_id else None
    probs = channel_problems(channel, me) if me else ["Bot member not cached yet"]
    out.append(("fail" if probs else "ok", "Game channel", " | ".join(probs) if probs else channel.mention))
    # roles
    if not cfg.host_role_ids:
        out.append(("warn", "Host roles", "No host roles. Starting rumbles requires Manage Server."))
    else:
        gone = [r for r in cfg.host_role_ids if guild.get_role(r) is None]
        out.append(("warn" if gone else "ok", "Host roles",
                    f"{len(gone)} deleted role(s), pick again in Settings" if gone else f"{len(cfg.host_role_ids)} set"))
    if cfg.winner_role_id:
        rp = role_problems(guild, cfg.winner_role_id, me, "winner role")
        approved = await bot.db.approved_winner_role(guild.id, cfg.winner_role_id)
        if not approved:
            rp.append("Re-select the dedicated cosmetic role in Settings to approve it.")
        out.append(("fail" if rp else "ok", "Winner role", " | ".join(rp) if rp else
                    f"<@&{cfg.winner_role_id}> for {cfg.winner_role_hours or 'unlimited'}"
                    f"{' h' if cfg.winner_role_hours else ''}"))
        wr = guild.get_role(cfg.winner_role_id)
        if wr is not None and getattr(getattr(wr, "permissions", None), "value", 0):
            out.append(("warn", "Winner role permissions", f"@{wr.name} carries permissions. A cosmetic role with "
                                                            f"no permissions is safer for a prize."))
    else:
        out.append(("warn", "Winner role", "Not set. Winners still go on the leaderboard."))
    if cfg.ping_role_id:
        pp = role_problems(guild, cfg.ping_role_id, me, "ping role")
        out.append(("warn" if pp else "ok", "Ping role", " | ".join(pp) if pp else f"<@&{cfg.ping_role_id}>"))
    # assets and content
    miss = missing_assets()
    out.append(("fail" if miss else "ok", "Images",
                f"Missing: {', '.join(miss[:5])}" if miss else f"{len(all_assets())} images ready"))
    issues = [i for i in validate_all(near_dupes=False) if i[0] == "ERROR"]
    out.append(("fail" if issues else "ok", "Scenario bank",
                f"{len(issues)} errors, first: {issues[0][1]} {issues[0][2]}" if issues else "All lines valid"))
    # scheduler and roles loop
    cog = bot.get_cog("RumbleCog")
    for name, label, stale_after in (("scheduler", "Scheduler", 120), ("roles", "Winner roles and recovery", 900)):
        loop = getattr(cog, name + "_loop", None)
        running = loop is not None and loop.is_running()
        success = getattr(bot, "loop_success", {}).get(name, 0)
        healthy = running and success > time.time() - stale_after
        out.append(("ok" if healthy else "fail", label,
                    "Running with a recent successful pass" if healthy else "No recent successful pass. Check recent errors."))
    pending = [r for r in await bot.db.pending_deliveries() if r["guild_id"] == guild.id]
    detail = "\n".join(
        f"#{r['game_id']} · announcement {r['announcement_state']} · role {'done' if r['role_done'] else 'pending'}"
        + (f" · {r['delivery_error'][:100]}" if r.get("delivery_error") else "") for r in pending[:5])
    out.append(("warn" if pending else "ok", "Pending result delivery", detail or "None"))
    rows = await bot.db.schedules(guild.id, enabled_only=True)
    nxt = [t for t in (next_run(r, cfg.timezone, int(time.time())) for r in rows) if t]
    out.append(("ok", "Schedules", f"{len(rows)} active · next <t:{min(nxt)}:R>" if nxt else f"{len(rows)} active"))
    blocked = await bot.db.blocked_schedule_occurrences(guild.id)
    if blocked:
        out.append(("warn", "Schedule startup confirmation needed", "\n".join(
            f"Schedule #{row['schedule_id']} · <t:{row['occurrence_at']}:F> · lobby delivery unknown"
            for row in blocked[:5])))
    # live game
    runner = bot.games.get(guild.id)
    out.append(("ok", "Live rumble", f"{runner.state} · {runner.world.name} · {len(runner.players)} rippers"
                if runner else "None running"))
    # latency and errors
    lat = bot.latency * 1000 if bot.latency == bot.latency else -1
    out.append(("ok" if 0 <= lat < 800 else "warn", "Latency", f"{lat:.0f} ms"))
    errs = bot.errors_for(guild.id)
    if errs:
        last = "\n".join(f"<t:{int(t)}:R> {m[:150]}" for t, m in errs[-5:])
        out.append(("warn", "Recent errors", last))
    else:
        out.append(("ok", "Recent errors", "None"))
    out.append(("ok", "Version", f"RipCars Rumble {__version__} · discord.py {discord.__version__} · pid {os.getpid()}"))
    return out


ICON = {"ok": "✅", "warn": "⚠️", "fail": "❌"}


def checks_embed(results, guild_name):
    fails = sum(1 for r in results if r[0] == "fail")
    warns = sum(1 for r in results if r[0] == "warn")
    color = 0xD83C3E if fails else (0xE8A33D if warns else 0x3BA55D)
    head = "Local checks passed." if not fails and not warns else f"{fails} problem(s), {warns} warning(s)."
    e = discord.Embed(title=f"🩺 Rumble diagnostics · {guild_name}"[:256], description=head, color=color)
    for status, title, detail in results[:24]:
        e.add_field(name=f"{ICON[status]} {title}", value=(detail or "-")[:1024], inline=False)
    return e
