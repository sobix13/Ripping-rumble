import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from rumble.config import GuildConfig
from rumble.db import Database
from rumble.scheduler import ScheduleError, describe_plain, is_due, next_run, parse_once, parse_weekly


def test_parse_time_and_once():
    now = int(datetime(2026, 11, 1, 12, 0, tzinfo=ZoneInfo("UTC")).timestamp())
    ts = parse_once("2026-11-07", "20:30", "Europe/Belgrade", now)
    assert datetime.fromtimestamp(ts, ZoneInfo("Europe/Belgrade")).strftime("%Y-%m-%d %H:%M") == "2026-11-07 20:30"
    for bad in [("2026-11-07", "25:00"), ("2026-13-01", "10:00"), ("07/11/2026", "10:00"), ("2026-10-01", "10:00"),
                ("2026-02-30", "10:00"), ("2030-01-01", "10:00")]:
        with pytest.raises(ScheduleError):
            parse_once(*bad, "UTC", now)


def test_parse_weekly():
    assert parse_weekly("Mon, Fri", "8:05") == ("0,4", "08:05")
    assert parse_weekly("friday monday fri", "20:00") == ("0,4", "20:00")
    assert parse_weekly("daily", "20:00")[0] == "0,1,2,3,4,5,6"
    with pytest.raises(ScheduleError):
        parse_weekly("Funday", "20:00")
    with pytest.raises(ScheduleError):
        parse_weekly("", "20:00")


def _sched(**kw):
    base = {"id": 1, "enabled": 1, "kind": "weekly", "run_at": None, "weekdays": "4", "time_hm": "20:00",
            "last_run_at": None, "created_at": 0}
    base.update(kw)
    return base


def test_weekly_due_once_per_occurrence():
    tz = "Asia/Tehran"
    fri = int(datetime(2026, 11, 6, 20, 0, tzinfo=ZoneInfo(tz)).timestamp())   # a Friday
    s = _sched(created_at=fri - 86400)
    assert is_due(s, tz, fri - 60) == (False, False)
    assert is_due(s, tz, fri + 30) == (True, False)
    s["last_run_at"] = fri + 30
    assert is_due(s, tz, fri + 90)[0] is False          # no double run in the same window
    assert is_due(_sched(created_at=fri - 86400), tz, fri + 16 * 60)[0] is False   # window passed
    assert next_run(_sched(created_at=0), tz, fri + 60) == fri + 7 * 86400
    assert "Fri" in describe_plain(s, tz)


def test_once_due_and_missed():
    t = int(time.time()) + 100
    s = _sched(kind="once", run_at=t, weekdays=None, time_hm=None)
    assert is_due(s, "UTC", t - 5) == (False, False)
    assert is_due(s, "UTC", t + 5) == (True, False)
    assert is_due(s, "UTC", t + 3600) == (False, True)
    s["last_run_at"] = t + 5
    assert is_due(s, "UTC", t + 10) == (False, False)
    assert next_run(s, "UTC", t) is None


def test_config_clamp_roundtrip():
    c = GuildConfig(guild_id=1, lobby_seconds=1, round_delay=999, min_players=1, max_players=9999, revive_rate=7,
                    default_world="nope", timezone="Mars/Base", host_role_ids=["12", "x", 12])
    c.clamp()
    assert c.lobby_seconds == 15 and c.round_delay == 60 and c.min_players == 2 and c.max_players == 250
    assert c.revive_rate == 0.5 and c.default_world == "garage" and c.timezone == "Asia/Tehran"
    assert c.host_role_ids == [12]
    c2 = GuildConfig.from_json(1, c.to_json())
    assert c2 == c
    assert GuildConfig.from_json(5, "{broken").guild_id == 5
    assert GuildConfig.from_json(5, '{"lobby_seconds": "abc"}').lobby_seconds == 60


async def test_database_roundtrip(tmp_path):
    db = Database(str(tmp_path / "t.sqlite3"))
    await db.open()
    cfg = await db.get_config(7)
    assert cfg.setup_done is False
    cfg.channel_id = 99
    cfg.setup_done = True
    await db.save_config(cfg)
    assert (await db.get_config(7)).channel_id == 99
    gid = await db.game_started(7, "garage", "manual")
    await db.game_status(gid, "running", players=3)
    await db.record_results(7, [{"user_id": 1, "name": "a", "place": 1, "kills": 2, "won": True},
                                {"user_id": 2, "name": "b", "place": 2, "kills": 1, "won": False},
                                {"user_id": 3, "name": "c", "place": 3, "kills": 0, "won": False}])
    await db.record_results(7, [{"user_id": 2, "name": "b", "place": 1, "kills": 3, "won": True},
                                {"user_id": 1, "name": "a", "place": 2, "kills": 0, "won": False}])
    await db.game_status(gid, "finished", winner_id=1, rounds=5)
    lb = await db.leaderboard(7)
    assert [r["user_id"] for r in lb][:2] == [2, 1]          # tie on wins, b has more kills
    assert (await db.user_stats(7, 2))["best_place"] == 1
    await db.add_winner_role(7, 1, 55, int(time.time()) - 5)
    await db.add_winner_role(7, 2, 55, None)
    exp = await db.expired_winner_roles()
    assert [(r["user_id"], r["role_id"]) for r in exp] == [(1, 55)]
    await db.drop_winner_role(7, 1, 55)
    assert len(await db.active_winner_roles(7)) == 1
    sid = await db.add_schedule(7, "redline", "weekly", weekdays="0,4", time_hm="20:00", created_by=1)
    assert len(await db.schedules(7, enabled_only=True)) == 1
    await db.mark_schedule_run(sid, 123, disable=True)
    assert len(await db.schedules(7, enabled_only=True)) == 0
    assert await db.remove_schedule(7, sid) and not await db.remove_schedule(7, sid)
    await db.reset_leaderboard(7)
    assert await db.leaderboard(7) == []
    await db.close()
    db2 = Database(str(tmp_path / "t.sqlite3"))
    await db2.open()      # reopen: running games get marked interrupted, data persists
    assert (await db2.get_config(7)).channel_id == 99
    await db2.close()


def test_weekly_ranges_and_strictness():
    assert parse_weekly("Mon-Fri", "20:00")[0] == "0,1,2,3,4"
    assert parse_weekly("Sunday-Thursday", "20:00")[0] == "0,1,2,3,6"
    assert parse_weekly("fri-mon", "20:00")[0] == "0,4,5,6"
    assert parse_weekly("weekends", "20:00")[0] == "5,6"
    assert parse_weekly("Mon, Wed & Fri", "20:00")[0] == "0,2,4"
    for bad in ("monkey", "Mon-Funday", "sundays-ish"):
        with pytest.raises(ScheduleError):
            parse_weekly(bad, "20:00")
