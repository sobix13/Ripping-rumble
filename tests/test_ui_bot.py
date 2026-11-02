import discord
import pytest

from rumble.bot import RumbleBot, RumbleCog
from rumble.config import GuildConfig
from rumble.render import round_messages
from rumble.ui import panel as P
from rumble.ui.setup import SetupWizard
from tests.fakes import FakeGuild, FakePerms


class Resp:
    def __init__(self):
        self.calls = []
        self.done = False

    def is_done(self):
        return self.done

    async def edit_message(self, **kw):
        self.calls.append(("edit", kw))
        self.done = True

    async def send_message(self, *a, **kw):
        self.calls.append(("send", a, kw))
        self.done = True

    async def send_modal(self, modal):
        self.calls.append(("modal", modal))
        self.done = True

    async def defer(self, **kw):
        self.calls.append(("defer", kw))
        self.done = True


class Followup:
    def __init__(self):
        self.sent = []

    async def send(self, *a, **kw):
        self.sent.append((a, kw))


class Inter:
    def __init__(self, user, guild):
        self.user = user
        self.guild = guild
        self.guild_id = guild.id
        self.response = Resp()
        self.followup = Followup()
        self.edited = []

    async def edit_original_response(self, **kw):
        self.edited.append(kw)


@pytest.fixture
async def env(tmp_path):
    bot = RumbleBot(str(tmp_path / "ui.sqlite3"))
    await bot.db.open()
    guild = FakeGuild()
    ch = guild.add_channel()
    host_role = guild.add_role("Mods")
    admin = guild.add_member("admin", perms=FakePerms(manage_guild=True))
    host = guild.add_member("mod", roles=[host_role])
    cfg = GuildConfig(guild_id=guild.id, channel_id=ch.id, host_role_ids=[host_role.id], setup_done=True)
    await bot.db.save_config(cfg)
    yield bot, guild, ch, admin, host, cfg
    await bot.db.close()


def _check_view(view):
    comps = view.to_components()
    assert len(comps) <= 5
    for row in comps:
        assert 1 <= len(row["components"]) <= 5
        for c in row["components"]:
            if c["type"] == 3:
                assert 1 <= len(c["options"]) <= 25
                for o in c["options"]:
                    assert len(o["label"]) <= 100 and len(o.get("description", "")) <= 100
            if c["type"] == 2:
                assert len(c.get("label", "")) <= 80
            assert len(c.get("placeholder", "")) <= 150


async def test_command_tree(env):
    bot, *_ = env
    cog = RumbleCog(bot)
    names = {c.name for c in cog.rumble.commands}
    assert names == {"start", "stop", "panel", "setup", "leaderboard", "stats", "worlds", "diagnose", "guide"}
    payload = cog.rumble.to_dict(bot.tree)
    assert payload["name"] == "rumble" and len(payload["options"]) == 9


async def test_every_panel_builds_and_renders(env):
    bot, guild, ch, admin, host, cfg = env
    for cls in (P.PanelHome, P.StartPanel, P.SchedulePanel, P.SettingsHome, P.ChannelRolesPanel, P.WinnerPanel,
                P.RulesPanel, P.ExtrasPanel, P.LeaderboardPanel, P.DiagnosticsPanel):
        v = cls(bot, admin, cfg)
        _check_view(v)
        e = await v.render(guild)
        assert isinstance(e, discord.Embed) and len(e) <= 6000
    v = P.LeaderboardPanel(bot, admin, cfg, confirm=True)
    _check_view(v)
    from rumble.ui.setup import STEPS
    for step in range(len(STEPS)):
        w = SetupWizard(bot, admin, cfg, step=step)
        _check_view(w)
        assert len(w.render(guild)) <= 6000


async def test_host_sees_limited_home(env):
    bot, guild, ch, admin, host, cfg = env
    v = P.PanelHome(bot, host, cfg)
    assert v.btn_settings.disabled and v.btn_diag.disabled and not v.btn_start.disabled
    i = Inter(host, guild)
    assert await v.interaction_check(i) is True
    s = P.SettingsHome(bot, host, cfg)
    i2 = Inter(host, guild)
    assert await s.interaction_check(i2) is False          # admin-only screen refuses hosts
    stranger = guild.add_member("random")
    assert await v.interaction_check(Inter(stranger, guild)) is False


async def test_navigation_and_modals(env):
    bot, guild, ch, admin, host, cfg = env
    home = P.PanelHome(bot, admin, cfg)
    i = Inter(admin, guild)
    await home.btn_sched.callback(i)
    assert i.response.calls[0][0] == "defer"
    sched = i.edited[0]["view"]
    assert isinstance(sched, P.SchedulePanel)
    m = P.WeeklyModal(sched)
    m.days._value, m.at._value = "Mon, Fri", "20:30"
    await m.on_submit(Inter(admin, guild))
    rows = await bot.db.schedules(guild.id)
    assert len(rows) == 1 and rows[0]["weekdays"] == "0,4"
    bad = P.OnceModal(sched)
    bad.date._value, bad.at._value = "2020-01-01", "10:00"
    i3 = Inter(admin, guild)
    await bad.on_submit(i3)
    assert "past" in i3.edited[0]["embed"].fields[-1].value
    await sched.render(guild)
    sched.sel_remove._values = [str(rows[0]["id"])]
    await sched.sel_remove.callback(Inter(admin, guild))
    assert await bot.db.schedules(guild.id) == []
    rules = P.RulesPanel(bot, admin, cfg)
    nm = P.NumbersModal(rules)
    for t, v in zip((nm.minp, nm.maxp, nm.minr, nm.maxr, nm.rev), ("3", "999", "1", "30", "25")):
        t._value = v
    await nm.on_submit(Inter(admin, guild))
    c = await bot.db.get_config(guild.id)
    assert (c.min_players, c.max_players, c.min_rounds, c.max_rounds, c.revive_rate) == (3, 250, 2, 25, 0.25)
    tz = P.TimezoneModal(rules)
    tz.tz._value = "Asia/Tehran"
    await tz.on_submit(Inter(admin, guild))
    assert (await bot.db.get_config(guild.id)).timezone == "Asia/Tehran"
    tz.tz._value = "Mars/Olympus"
    await tz.on_submit(Inter(admin, guild))
    assert (await bot.db.get_config(guild.id)).timezone == "Asia/Tehran"
    ex = P.ExtrasPanel(bot, admin, await bot.db.get_config(guild.id))
    toggle = [b for b in ex.children if isinstance(b, discord.ui.Button) and b.label.startswith("Hazards")][0]
    await toggle.callback(Inter(admin, guild))
    assert (await bot.db.get_config(guild.id)).hazards is False


async def test_channel_and_role_selects_save(env):
    bot, guild, ch, admin, host, cfg = env
    v = P.ChannelRolesPanel(bot, admin, cfg)
    new = guild.add_channel("rumble-2")
    v.s_channel._values = [new]
    changed_channel = Inter(admin, guild)
    await v._ch(changed_channel)
    v = changed_channel.edited[0]["view"]
    players = guild.add_role("Rippers")
    v.s_players._values = [players]
    await v._players(Inter(admin, guild))
    c = await bot.db.get_config(guild.id)
    assert c.channel_id == new.id and c.player_role_ids == [players.id]
    w = P.WinnerPanel(bot, admin, c)
    create = [b for b in w.children if isinstance(b, P.CreateWinnerRoleButton)][0]
    await create.callback(Inter(admin, guild))
    c = await bot.db.get_config(guild.id)
    assert guild.get_role(c.winner_role_id).name == "Rumble Champion"


async def test_leaderboard_reset_flow(env):
    bot, guild, ch, admin, host, cfg = env
    await bot.db.record_results(guild.id, [{"user_id": 1, "name": "a", "place": 1, "kills": 1, "won": True}])
    lb = P.LeaderboardPanel(bot, admin, cfg, confirm=True)
    await lb._do_reset(Inter(admin, guild))
    assert await bot.db.leaderboard(guild.id) == []


async def test_setup_wizard_flow(env):
    bot, guild, ch, admin, host, cfg = env
    fresh = GuildConfig(guild_id=guild.id)
    await bot.db.save_config(fresh)
    w = SetupWizard(bot, admin, fresh, step=0)
    nxt = [b for b in w.children if isinstance(b, discord.ui.Button) and b.label == "Next"][0]
    assert nxt.disabled                                   # no channel yet
    sel = [s for s in w.children if isinstance(s, discord.ui.ChannelSelect)][0]
    sel._values = [ch]
    await sel.callback(Inter(admin, guild))
    from rumble.ui.setup import STEPS
    for step in range(len(STEPS) - 1):
        nxt = [b for b in w.children if isinstance(b, discord.ui.Button) and b.label in ("Next", "Finish")][0]
        assert not nxt.disabled
        await nxt.callback(Inter(admin, guild))
    assert w.step == len(STEPS) - 1
    fin = [b for b in w.children if isinstance(b, discord.ui.Button) and b.label == "Finish"][0]
    i = Inter(admin, guild)
    await fin.callback(i)
    c = await bot.db.get_config(guild.id)
    assert c.setup_done and c.channel_id == ch.id
    assert i.edited and "set up" in i.edited[0]["embed"].title


async def test_preflight_blocks(env):
    bot, guild, ch, admin, host, cfg = env
    assert bot.preflight(guild, GuildConfig(guild_id=guild.id)) != []
    ch._perms = FakePerms(attach_files=False)
    probs = bot.preflight(guild, cfg)
    assert probs and "Attach Files" in probs[0]


def test_round_splitting_limits():
    from rumble.content import get_world
    from rumble.engine import Event, Round
    w = get_world("garage")
    evs = [Event("kill", "x", "**" + "a" * 30 + "** " + "b" * 300, [i]) for i in range(40)]
    rd = Round(3, "Lap 3 · Test", evs, [], [], 10, False, ["kill"] * 40)
    msgs = round_messages(w, rd, None, "attachment://x.png", 9)
    assert len(msgs) >= 2
    for embeds in msgs:
        assert len(embeds) <= 10 and sum(len(e) for e in embeds) <= 6000
        for e in embeds:
            assert len(e.description) <= 4096
    assert msgs[0][0].thumbnail.url == "attachment://x.png"
