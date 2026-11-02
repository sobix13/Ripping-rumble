"""Validated per-guild wording overrides. Roles and engine rules remain in the source bank."""
from dataclasses import replace
import re

from . import get_world, world_keys
from .validate import TOKEN, validate_bank_lines


def validate_override(line_id, text):
    matches = [(key, line) for key in world_keys() for pool in get_world(key).pools.values()
               for line in pool if line.id == line_id]
    if not matches:
        raise ValueError('Unknown scenario ID. Use an ID from docs/bank_export.json.')
    if not isinstance(text, str):
        raise ValueError('Scenario text must be text.')
    if not text:
        return
    base = matches[0][1]
    if set(TOKEN.findall(text)) != set(TOKEN.findall(base.text)):
        raise ValueError('Keep the original placeholders. Editing roles or item rules is not supported.')
    if len(text) > 240 or '\n' in text or '\r' in text:
        raise ValueError('Use one line with at most 240 characters.')
    if re.search(r'https?://|discord\.gg|@everyone|@here|<[@#]', text, re.I):
        raise ValueError('Links and mentions are not allowed in scenario overrides.')
    row = dict(text=text, tags=base.tags, holds=base.holds, out=base.out)
    issues = []
    validate_bank_lines(base.kind, row, line_id, issues)
    if issues:
        raise ValueError(issues[0][2])
    worlds = {key for key, _ in matches}
    if worlds - {'nft'} and re.search(r'\b(onchain|blockchain|airdrop|Solana|MetaMask|Phantom)\b|gas fee|seed phrase|mint transaction|on-chain', text, re.I):
        raise ValueError('This scenario also appears outside NFT Garage. Keep onchain references there.')
    if 'redline' in worlds:
        modern = re.search(r'\b(texted|smartphone|Discord|YouTube|TikTok|Instagram|NFT|email|WiFi)\b|QR code|wi-fi', text, re.I)
        future = any(int(year) > 1971 for year in re.findall(r'\b(?:19|20)\d{2}\b', text))
        if modern or future:
            raise ValueError('This scenario also appears in the 1971 Redline world. Keep its period.')
    if re.search(r'RipCars\s*[x×]\s*(Hot Wheels|Mattel)|official\s+(Hot Wheels|Mattel)\s+(collaboration|partner)', text, re.I):
        raise ValueError('Do not claim an official Hot Wheels or Mattel collaboration.')


def apply_overrides(world, overrides):
    if not overrides:
        return world
    for line_id, text in overrides.items():
        validate_override(line_id, text)
    pools = {kind: [replace(line, text=overrides[line.id]) if overrides.get(line.id) else line
                    for line in lines] for kind, lines in world.pools.items()}
    return replace(world, pools=pools)
