"""RipCars asset picker: one light image (sticker, GIF or emoji art) per post, matched to what happened."""
import os
import random

import discord

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

MOODS = {
    "carnage": ["anim/rip_mindblown_a.gif", "st/20_Shake.webp", "emo/rip_mindblown.png", "st/02_Broke.webp"],
    "oops": ["anim/rip_oops_a.gif", "emo/rip_facepalm.png", "st/24_Lost.webp", "emo/rip_surrender.png",
             "emo/rip_lost.png", "emo/rip_emptypockets.png"],
    "kills": ["st/06_Tug.webp", "st/04_Come_On.webp", "emo/rip_lurk.png", "anim/rip_lurk_a.gif",
              "emo/rip_guard.png", "emo/rip_peek.png"],
    "find": ["st/14_Got_One.webp", "anim/rip_wpull_a.gif", "st/01_W_Pull.webp", "emo/rip_jackpot.png",
             "emo/rip_gotone.png", "st/16_Reveal.webp", "emo/rip_reveal.png"],
    "callback": ["st/15_Mine.webp", "emo/rip_guard.png", "emo/rip_secret.png", "emo/rip_hush.png", "st/22_Shade.webp"],
    "revive": ["st/19_Roof_Jump.webp", "emo/rip_jumpin.png", "anim/rip_wave_a.gif", "emo/rip_magic.png"],
    "quiet": ["st/26_Popcorn.webp", "st/23_Zen.webp", "emo/rip_lounge.png", "emo/rip_nap.png", "st/11_News.webp",
              "emo/rip_relax.png", "emo/rip_vibing.png"],
    "duel": ["anim/rip_vroom_a.gif", "st/13_Vroom.webp", "emo/rip_vroom.png", "emo/rip_driveout.png"],
    "winner": ["st/28_Trophy.webp", "anim/rip_gg_a.gif", "anim/rip_party_a.gif", "st/12_GG.webp",
               "emo/rip_trophy.png", "st/03_LFRIP.webp"],
    "second_chance": ["st/07_Catch.webp", "anim/rip_catch_a.gif"],
    "cancel": ["st/10_Rainy_Day.webp", "anim/rip_rain_a.gif", "emo/rip_late.png"],
    "stopped": ["emo/rip_surrender.png", "emo/rip_facepalm.png"],
    "leaderboard": ["st/28_Trophy.webp", "st/35_Ripper_Fam.webp"],
    "panel": ["anim/rip_logoverified_a.gif", "emo/rip_logo.png"],
    "lobby": ["anim/rip_announce_a.gif"],
    "start": ["anim/rip_lfrip_a.gif", "st/31_LFRIP.webp"],
}

# line glyphs: (server emoji name to use when the server has it, unicode fallback)
GLYPHS = {
    "kill": ("rip_lurk", "💥"), "multi": ("rip_mindblown", "💥"), "double": ("rip_oops", "💫"),
    "wipe": ("rip_oops", "💀"), "hazard": ("rip_mindblown", "⚠️"), "find": ("rip_jackpot", "💎"),
    "call": ("rip_guard", "🔁"), "transfer": ("rip_gift", "🔄"), "survive": ("rip_zen", "😮‍💨"),
    "moment": ("rip_hug", "🤝"), "revive": ("rip_jumpin", "✨"), "duel": ("rip_vroom", "🏁"), "ambient": (None, "·"),
}


def path(rel):
    return os.path.join(ROOT, rel)


def all_assets():
    rels = set()
    for v in MOODS.values():
        rels.update(v)
    from .content.worlds import WORLDS
    for w in WORLDS:
        rels.add(_with_ext(w["lobby_asset"]))
    return sorted(rels)


def _with_ext(rel):
    if os.path.splitext(rel)[1]:
        return rel
    for ext in (".webp", ".png", ".gif"):
        if os.path.exists(path(rel + ext)):
            return rel + ext
    return rel + ".webp"


def missing_assets():
    return [r for r in all_assets() if not os.path.exists(path(r))]


def round_mood(rd):
    k = rd.kinds
    if rd.final:
        return "duel"
    if "revive" in k:
        return "revive"
    if "hazard" in k or "multi" in k:
        return "carnage"
    if "find" in k:
        return "find"
    if "call" in k or "transfer" in k:
        return "callback"
    if not rd.eliminated:
        return "quiet"
    wipes = k.count("wipe") + k.count("double")
    kills = k.count("kill")
    return "oops" if wipes >= kills else "kills"


class AssetPicker:
    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.last = None

    def pick(self, mood):
        pool = [r for r in MOODS.get(mood, []) if os.path.exists(path(r))]
        if not pool:
            return None
        choices = [r for r in pool if r != self.last] or pool
        rel = self.rng.choice(choices)
        self.last = rel
        return rel

    @staticmethod
    def file(rel):
        """discord.File plus the attachment:// url for embeds."""
        name = rel.replace("/", "_")
        return discord.File(path(rel), filename=name), f"attachment://{name}"


def lobby_asset(world):
    return _with_ext(world.lobby_asset)


def glyph(kind, guild_emoji=None):
    name, fallback = GLYPHS.get(kind, (None, "•"))
    if name and guild_emoji and name in guild_emoji:
        return guild_emoji[name]
    return fallback
