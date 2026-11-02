"""Small stand-ins for Discord objects, so the runner and the panel can be tested without a network."""
import itertools
import os

import discord

_ids = itertools.count(1000)


class FakePerms:
    def __init__(self, **kw):
        self.administrator = kw.get("administrator", False)
        self.manage_guild = kw.get("manage_guild", False)
        self.manage_roles = kw.get("manage_roles", True)
        self.mention_everyone = kw.get("mention_everyone", False)
        for a in ("view_channel", "send_messages", "embed_links", "attach_files", "read_message_history"):
            setattr(self, a, kw.get(a, True))


class FakeRole:
    def __init__(self, name, position=1, rid=None, mentionable=True):
        self.id = rid or next(_ids)
        self.name = name
        self.position = position
        self.managed = False
        self.mentionable = mentionable
        self.mention = f"<@&{self.id}>"
        self.permissions = discord.Permissions.none()

    def is_default(self):
        return False

    def __ge__(self, other):
        return self.position >= other.position

    def __lt__(self, other):
        return self.position < other.position


class FakeMember:
    def __init__(self, name, roles=(), perms=None, bot=False, guild=None, uid=None):
        self.id = uid or next(_ids)
        self.name = name
        self.display_name = name
        self.roles = list(roles)
        self.guild_permissions = perms or FakePerms()
        self.bot = bot
        self.guild = guild
        self.mention = f"<@{self.id}>"
        self.added = []
        self.top_role = max(self.roles, key=lambda role: role.position) if self.roles else FakeRole("member", 10)

    async def add_roles(self, *roles, reason=None):
        self.added += roles
        self.roles += [r for r in roles if r not in self.roles]

    async def remove_roles(self, *roles, reason=None):
        self.roles = [r for r in self.roles if r not in roles]


class FakeAttachment:
    def __init__(self, filename):
        self.filename = filename


class FakeMessage:
    def __init__(self, channel, kwargs):
        self.channel = channel
        self.kwargs = kwargs
        self.edits = []
        f = kwargs.get("file")
        self.attachments = [FakeAttachment(f.filename)] if f else []
        self.id = next(_ids)

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        return self


class FakeChannel:
    def __init__(self, name="rumble", perms=None):
        self.id = next(_ids)
        self.name = name
        self.mention = f"<#{self.id}>"
        self.sent = []
        self._perms = perms or FakePerms()

    def permissions_for(self, member):
        return self._perms

    async def send(self, **kwargs):
        _check_message_limits(kwargs)
        m = FakeMessage(self, kwargs)
        self.sent.append(m)
        return m


def _check_message_limits(kw):
    embeds = list(kw.get("embeds") or ([] if kw.get("embed") is None else [kw["embed"]]))
    assert len(embeds) <= 10, "more than 10 embeds"
    total = 0
    for e in embeds:
        assert isinstance(e, discord.Embed)
        assert len(e.description or "") <= 4096, "description over 4096"
        assert len(e.title or "") <= 256, "title over 256"
        assert len(e.fields) <= 25
        for f in e.fields:
            assert len(f.name) <= 256 and len(f.value) <= 1024, "field over limit"
        total += len(e) if hasattr(e, "__len__") else 0
    assert total <= 6000, f"message over 6000 chars ({total})"
    f = kw.get("file")
    if f is not None:
        assert os.path.exists(f.fp.name) if hasattr(f.fp, "name") else True
        for e in embeds[:1]:
            if e.thumbnail and e.thumbnail.url:
                assert e.thumbnail.url == f"attachment://{f.filename}", "thumbnail does not match the file"
    if kw.get("content"):
        assert len(kw["content"]) <= 2000


class FakeEmoji:
    def __init__(self, name):
        self.name = name
        self.available = True
        self.id = next(_ids)

    def __str__(self):
        return f"<:{self.name}:{self.id}>"


class FakeGuild:
    def __init__(self, name="RipCars"):
        self.id = next(_ids)
        self.name = name
        self.roles = {}
        self.channels = {}
        self.members = {}
        self.emojis = []
        self.me = FakeMember("RipCars Rumble", perms=FakePerms(manage_roles=True), bot=True, guild=self)
        self.me.top_role = FakeRole("bot", position=50)

    def add_role(self, name, position=1, mentionable=True):
        r = FakeRole(name, position, mentionable=mentionable)
        self.roles[r.id] = r
        return r

    def add_channel(self, name="rumble", perms=None):
        c = FakeChannel(name, perms)
        self.channels[c.id] = c
        return c

    def add_member(self, name, roles=(), perms=None):
        m = FakeMember(name, roles, perms, guild=self)
        self.members[m.id] = m
        return m

    def get_role(self, rid):
        return self.roles.get(rid)

    def get_channel(self, cid):
        return self.channels.get(cid)

    def get_member(self, uid):
        return self.members.get(uid)

    async def fetch_member(self, uid):
        if uid in self.members:
            return self.members[uid]
        raise discord.NotFound(_FakeResp(), "unknown member")

    async def create_role(self, **kw):
        return self.add_role(kw.get("name", "role"))


class _FakeResp:
    status = 404
    reason = "Not Found"


class FakeClock:
    def __init__(self):
        self.t = 1_800_000_000.0
        self.slept = 0.0

    def now(self):
        return self.t

    async def sleep(self, s):
        import asyncio
        self.t += s
        self.slept += s
        await asyncio.sleep(0)


class FakeBot:
    """The parts of RumbleBot the runner uses."""
    def __init__(self, db):
        self.db = db
        self.games = {}
        self.errors = []
        self.granted = []

    def record_error(self, gid, msg):
        self.errors.append((gid, msg))

    async def grant_winner_role(self, guild, user_id, cfg):
        self.granted.append((guild.id, user_id, cfg.winner_role_id))
        return True
