"""Fills scenario templates with names and world slots."""
import math
import re
import unicodedata

import discord.utils

TOKEN = re.compile(r"\{([A-Za-z]+)\}")
NAME_KEYS = {"A", "B", "C", "H"}
SLOT_KEYS = {"grail", "model", "pack", "item"}


def reading_pause(text, minimum):
    """180 words/minute allowance, capped at 30s, with the host's minimum preserved."""
    return max(minimum, min(30, math.ceil(len(text.split()) / 3)))


def needs_an(word: str) -> bool:
    return bool(re.match(r"[AEIOUaeiou]", word)) or word.startswith("NFT")


def clean_name(raw: str, limit: int = 32) -> str:
    """Display name made safe for bold markdown: no markdown, no mentions, no line breaks."""
    s = re.sub(r"[\r\n\t\u2028\u2029]", " ", raw or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cf", "Cc"))
    s = " ".join(s.split())
    s = discord.utils.remove_markdown(s).replace("*", "").replace("`", "").strip()
    if not s:
        s = "ripper"
    if len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    s = discord.utils.escape_markdown(s)
    s = discord.utils.escape_mentions(s)
    return s


def join_names(names):
    names = [f"**{n}**" for n in names]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def fill(template: str, names: dict, world, rng, item: str = "", lap: int = 0, hazard_names=None) -> tuple:
    """Return (text, used_model). names maps A/B/C/H to plain (already cleaned) names."""
    out = []
    model_value = None
    pos = 0
    for m in TOKEN.finditer(template):
        out.append(template[pos:m.start()])
        key = m.group(1)
        if key in NAME_KEYS:
            if key not in names:
                raise KeyError(f"missing name {key} for: {template}")
            val = f"**{names[key]}**"
        elif key == "names":
            val = join_names(hazard_names or [])
        elif key == "n":
            val = str(lap)
        elif key in SLOT_KEYS:
            if key == "grail":
                val = world.grail
            elif key == "pack":
                val = world.pack
            elif key == "item":
                val = item or world.grail
            else:
                if model_value is None:
                    model_value = rng.choice(world.models)
                val = model_value
            prev = "".join(out)
            if prev.endswith(" a ") and needs_an(val):
                out = [prev[:-3] + " an "]
            elif prev.endswith(" an ") and not needs_an(val):
                out = [prev[:-4] + " a "]
            elif prev == "A " and needs_an(val):
                out = ["An "]
        else:
            raise KeyError(f"unknown placeholder {{{key}}} in: {template}")
        out.append(val)
        pos = m.end()
    out.append(template[pos:])
    return "".join(out), model_value
