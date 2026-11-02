"""Who may do what, and what the bot itself is missing."""
import discord


def _role_ids(member):
    return {r.id for r in getattr(member, "roles", [])}


def is_admin(member, cfg):
    p = getattr(member, "guild_permissions", None)
    if p and (p.administrator or p.manage_guild):
        return True
    return bool(_role_ids(member) & set(cfg.admin_role_ids))


def is_host(member, cfg):
    return is_admin(member, cfg) or bool(_role_ids(member) & set(cfg.host_role_ids))


def can_join(member, cfg):
    if getattr(member, "bot", False):
        return False
    if not cfg.player_role_ids:
        return True
    return is_host(member, cfg) or bool(_role_ids(member) & set(cfg.player_role_ids))


CHANNEL_PERMS = [("view_channel", "View Channel"), ("send_messages", "Send Messages"),
                 ("embed_links", "Embed Links"), ("attach_files", "Attach Files"),
                 ("read_message_history", "Read Message History")]


def channel_problems(channel, me):
    if channel is None:
        return ["No game channel is set. Run /rumble setup."]
    if me is None:
        return ["Bot member is unavailable. Try again after the connection is ready."]
    channel_type = getattr(channel, "type", None)
    if channel_type is not None and channel_type not in (discord.ChannelType.text, discord.ChannelType.news):
        return ["Pick a standard text or announcement channel."]
    perms = channel.permissions_for(me)
    missing = [label for attr, label in CHANNEL_PERMS if not getattr(perms, attr, False)]
    return [f"Missing in #{channel.name}: {', '.join(missing)}"] if missing else []


def _cosmetic_role_problems(guild, role, me):
    out = []
    if me is None or not getattr(me.guild_permissions, "manage_roles", False):
        out.append("The bot needs Manage Roles for the winner role.")
    elif role >= me.top_role:
        out.append(f"Move the bot role above @{role.name}.")
    if role.managed or role.is_default():
        out.append("Winner roles must be ordinary dedicated roles.")
    if getattr(getattr(role, "permissions", None), "value", 0):
        out.append("The winner role must have zero server permissions.")
    for channel in getattr(guild, "channels", ()):
        overwrite = getattr(channel, "overwrites_for", None)
        if overwrite and any(part.value for part in overwrite(role).pair()):
            out.append("The winner role must have no channel permission overrides.")
            break
    return out


def winner_role_problem(guild, member, role):
    """Reject privilege-bearing or unmanageable award roles at each UI mutation."""
    if role is None:
        return "That winner role no longer exists."
    owner = getattr(guild, "owner_id", None) == member.id
    permissions = getattr(member, "guild_permissions", None)
    if not owner and not (permissions and (permissions.manage_roles or permissions.administrator)):
        return "Manage Roles is required to select or create a winner role."
    top = getattr(member, "top_role", None)
    if not owner and (top is None or role >= top):
        return "Select a winner role below your highest role."
    problems = _cosmetic_role_problems(guild, role, guild.me)
    return "\n".join(problems) if problems else None


def role_problems(guild, role_id, me, purpose="winner role"):
    if not role_id:
        return []
    role = guild.get_role(role_id)
    if role is None:
        return [f"The {purpose} no longer exists. Pick a new one in the panel."]
    out = []
    if purpose == "winner role":
        out.extend(_cosmetic_role_problems(guild, role, me))
    elif purpose == "ping role":
        if not role.mentionable and not me.guild_permissions.mention_everyone:
            out.append(f"@{role.name} is not mentionable. Turn on 'Allow anyone to mention' or give the bot "
                       f"Mention Everyone.")
    return out


def describe_roles(guild, ids, empty="none"):
    names = []
    for rid in ids:
        r = guild.get_role(rid)
        names.append(r.mention if r else f"(deleted role {rid})")
    return ", ".join(names) if names else empty


def member_label(user):
    if isinstance(user, discord.abc.User):
        return user.display_name
    return str(user)
