"""Private report destination checks, reused before configuration and delivery."""
import discord

from ..perms import is_host


def private_report_channel_problem(guild, channel, cfg):
    if channel is None:
        return "The report channel no longer exists."
    if getattr(channel, "type", discord.ChannelType.text) not in (discord.ChannelType.text, discord.ChannelType.news):
        return "Choose a standard private text channel."
    if getattr(getattr(channel, "guild", guild), "id", None) != guild.id:
        return "Choose a report channel in this server."
    everyone = getattr(guild, "default_role", None)
    if everyone is None or channel.permissions_for(everyone).view_channel:
        return "Hide the report channel from @everyone first."
    me = getattr(guild, "me", None)
    if me is None:
        return "The bot member is unavailable."
    permissions = channel.permissions_for(me)
    if not all(getattr(permissions, name, False) for name in ("view_channel", "send_messages", "embed_links")):
        return "The bot needs View Channel, Send Messages and Embed Links in the report channel."
    allowed_roles = set(cfg.admin_role_ids + cfg.host_role_ids)
    for target, overwrite in getattr(channel, "overwrites", {}).items():
        if getattr(overwrite, "view_channel", None) is not True:
            continue
        if target.id in (me.id, getattr(guild, "owner_id", None)):
            continue
        role_permissions = getattr(target, "permissions", None)
        if role_permissions is not None:
            if getattr(getattr(target, "tags", None), "bot_id", None) == me.id:
                continue
            if target.id in allowed_roles or role_permissions.administrator or role_permissions.manage_guild:
                continue
        elif is_host(target, cfg):
            continue
        return "Remove report-channel access for unrelated members or roles."
    return None
