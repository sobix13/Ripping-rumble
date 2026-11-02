"""Embed builders. All text limits are enforced here (4096 per description, 6000 per message, 10 embeds)."""
import io
import time

import discord

from .assets import glyph
from .content import world_choices, get_world

DESC_LIMIT = 3900
MSG_LIMIT = 5600
BRAND_RED = 0xDF0100


def _footer(world, extra=""):
    return f"RipCars Rumble · {world.name}" + (f" · {extra}" if extra else "")


def line_text(ev, guild_emoji=None):
    if ev.kind == "ambient":
        return f"*{ev.text.replace('*', '')}*"
    return f"{glyph(ev.kind, guild_emoji)} {ev.text}"


def lobby_embed(world, line, names, ends_at, max_players, min_players, host=None, locked=False, rounds=None):
    e = discord.Embed(title=f"{world.emoji} {world.banner}", color=world.color)
    count = len(names)
    if locked:
        e.description = f"**The grid is locked.** {count} rippers, {rounds} laps. Engines on.\n\n*{world.tagline}*"
    else:
        e.description = (f"{line}\n\n*{world.tagline}*\n\n"
                         f"Starts <t:{int(ends_at)}:R> · needs {min_players}+ rippers")
    shown = names[-15:]
    roster = ", ".join(shown) if shown else "Nobody yet. Be first."
    if count > len(shown):
        roster = f"…and {count - len(shown)} more, " + roster
    e.add_field(name=f"Rippers ({count}/{max_players})", value=roster[:1024], inline=False)
    e.set_footer(text=_footer(world, f"hosted by {host}" if host else ""))
    return e


def round_messages(world, rd, guild_emoji=None, thumb_url=None, total_rounds=None, game=None):
    """Return a list of messages, each a list of embeds."""
    lines = [line_text(ev, guild_emoji) for ev in rd.events]
    if game is not None:
        if rd.eliminated:
            lines.append("**Out:** " + ", ".join(f"**{game.name(pid)}**" for pid in rd.eliminated))
        if rd.revived:
            lines.append("**Back in:** " + ", ".join(f"**{game.name(pid)}**" for pid in rd.revived))
        alive = game.alive_ids()
        if len(alive) <= 10:
            lines.append("**Still in:** " + ", ".join(f"**{game.name(pid)}**" for pid in alive))
        if game.items:
            lines.append("**Holding:** " + " · ".join(f"{game.name(pid)}: {item}" for pid, item in game.items.items()))
    chunks, cur = [], ""
    for ln in lines:
        add = ln if not cur else "\n" + ln
        if len(cur) + len(add) > DESC_LIMIT:
            chunks.append(cur)
            cur = ln
        else:
            cur += add
    if cur:
        chunks.append(cur)
    if not chunks:
        chunks = ["*A quiet lap. Engines idle.*"]
    lap = f"Lap {rd.number}/{total_rounds}" if total_rounds else f"Lap {rd.number}"
    embeds = []
    for i, ch in enumerate(chunks):
        e = discord.Embed(description=ch, color=world.color)
        if i == 0:
            e.title = f"{world.emoji} {rd.title}"
            if thumb_url:
                e.set_thumbnail(url=thumb_url)
        embeds.append(e)
    left = "1 ripper left" if rd.alive_after == 1 else f"{rd.alive_after} rippers left"
    embeds[-1].set_footer(text=_footer(world, f"{lap} · {left}"))
    messages, cur_msg, size = [], [], 0
    for e in embeds:
        n = len(e.description or "") + len(e.title or "") + 120
        if cur_msg and (size + n > MSG_LIMIT or len(cur_msg) >= 10):
            messages.append(cur_msg)
            cur_msg, size = [], 0
        cur_msg.append(e)
        size += n
    if cur_msg:
        messages.append(cur_msg)
    return messages


def second_chance_embed(world, seconds_left_until, thumb_url=None, result=None):
    sc = world.second_chance
    e = discord.Embed(title=sc["title"], color=world.color)
    if result is None:
        e.description = "One fallen ripper returns automatically."
    else:
        e.description = result
    if thumb_url:
        e.set_thumbnail(url=thumb_url)
    e.set_footer(text=_footer(world, "Second Chance"))
    return e


def results_embed(world, game, duration_s, image_url=None, names=None):
    s = game.summary()
    names = names or {pid: p.name for pid, p in game.players.items()}
    win = s["winner"]
    e = discord.Embed(title=f"🏆 {world.name} · winner", color=world.color)
    e.description = game.win_text
    rank = s["ranking"]
    podium = []
    medals = ["🥇", "🥈", "🥉"]
    for i, pid in enumerate(rank[:3]):
        place = s.get("places", {}).get(pid, i + 1)
        medal = medals[place - 1] if place <= 3 else str(place)
        podium.append(f"{medal} **{names.get(pid, '?')}** · {s['kills'].get(pid, 0)} eliminations")
    e.add_field(name="Podium", value="\n".join(podium)[:1024] or "-", inline=False)
    rank_text = ranking_text(game, names)
    if len(rank_text) <= 1024:
        e.add_field(name="Full standings", value=rank_text, inline=False)
    else:
        e.add_field(name="Full standings", value="Complete standings are attached to this result.", inline=False)
    if s["top_killer"] is not None:
        tk = s["top_killer"]
        e.add_field(name="Most eliminations", value=f"**{names.get(tk, '?')}** · {s['kills'][tk]}", inline=True)
    e.add_field(name="Revives", value=str(s["revives"]), inline=True)
    mins, secs = divmod(int(duration_s), 60)
    e.add_field(name="Race", value=f"{s['players']} rippers · {s['rounds']} laps · {mins}m {secs:02d}s", inline=True)
    if image_url:
        e.set_thumbnail(url=image_url)
    e.set_footer(text=_footer(world, "LFRIP 🏎️"))
    return e


def notice_embed(world, title, text, thumb_url=None, color=None):
    e = discord.Embed(title=title, description=text, color=color or (world.color if world else BRAND_RED))
    if thumb_url:
        e.set_thumbnail(url=thumb_url)
    e.set_footer(text=_footer(world) if world else "RipCars Rumble")
    return e


def leaderboard_embed(rows, guild_name, thumb_url=None):
    e = discord.Embed(title=f"🏆 Rumble leaderboard · {guild_name}"[:256], color=BRAND_RED)
    if not rows:
        e.description = "No rumbles finished yet. The first winner gets the top spot."
    else:
        out = []
        for i, r in enumerate(rows, 1):
            out.append(f"**{i}.** <@{r['user_id']}> · **{r['wins']}** wins · {r['kills']} kills · {r['games']} games")
        e.description = "\n".join(out)[:4000]
    if thumb_url:
        e.set_thumbnail(url=thumb_url)
    e.set_footer(text="RipCars Rumble · wins, then kills")
    return e


def stats_embed(user, row):
    e = discord.Embed(title=f"{user.display_name} · rumble stats"[:256], color=BRAND_RED)
    if not row:
        e.description = "No rumbles yet. Join the next one."
        return e
    e.add_field(name="Wins", value=str(row["wins"]))
    e.add_field(name="Games", value=str(row["games"]))
    e.add_field(name="Kills", value=str(row["kills"]))
    if row.get("best_place"):
        e.add_field(name="Best finish", value=f"#{row['best_place']}")
    if row.get("last_win_at"):
        e.add_field(name="Last win", value=f"<t:{row['last_win_at']}:R>")
    return e


def worlds_embed():
    e = discord.Embed(title="🌍 Rumble worlds", color=BRAND_RED,
                      description="Each world has its own lobby, laps, hazards, revive and winners.")
    for key, name in world_choices():
        w = get_world(key)
        e.add_field(name=f"{w.emoji} {w.name}", value=f"{w.tagline}\nSecond Chance: {w.second_chance['name']}",
                    inline=False)
    return e


def now():
    return int(time.time())


def ranking_text(game, names=None):
    summary = game.summary()
    names = names or {pid: p.name for pid, p in game.players.items()}
    places = summary.get("places", {})
    return "\n".join(
        f"{places.get(pid, i)}. {names.get(pid, '?')} · {summary['kills'].get(pid, 0)} eliminations · ID {pid}"
        for i, pid in enumerate(summary["ranking"], 1))


def result_payload(world, game, duration_s):
    return {"embed": results_embed(world, game, duration_s).to_dict(),
            "ranking_text": ranking_text(game), "winner_id": game.winner}


def result_delivery_kwargs(payload, game_id):
    embed = discord.Embed.from_dict(payload["embed"])
    old_footer = embed.footer.text or "RipCars Rumble"
    embed.set_footer(text=f"{old_footer} · Rumble #{game_id}")
    winner = int(payload["winner_id"])
    kwargs = {"embed": embed, "content": f"🏁 <@{winner}> wins the rumble. LFRIP 🏎️",
              "allowed_mentions": discord.AllowedMentions(users=[discord.Object(winner)], roles=False, everyone=False)}
    if len(payload["ranking_text"]) > 1024:
        kwargs["file"] = discord.File(io.BytesIO(payload["ranking_text"].encode("utf-8")),
                                      filename=f"rumble-{game_id}-standings.txt")
    return kwargs
