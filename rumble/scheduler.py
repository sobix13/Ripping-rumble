"""Schedule math (pure). One-time and weekly rumbles in the server's timezone."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

GRACE = 15 * 60          # a run counts as due for 15 minutes after its time (covers restarts)
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_ALIASES = {"monday": "mon", "tuesday": "tue", "tues": "tue", "wednesday": "wed", "weds": "wed",
               "thursday": "thu", "thur": "thu", "thurs": "thu", "friday": "fri", "saturday": "sat",
               "sunday": "sun"}


class ScheduleError(ValueError):
    pass


def parse_time(s):
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", s or "")
    if not m:
        raise ScheduleError("Time must look like 20:30 (24-hour).")
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        raise ScheduleError("Time must be between 00:00 and 23:59.")
    return f"{h:02d}:{mi:02d}"


def _local_timestamp(local, zone):
    """Use the first occurrence of a repeated local hour. Reject a missing local hour."""
    aware = local.replace(tzinfo=zone, fold=0)
    stamp = int(aware.timestamp())
    if datetime.fromtimestamp(stamp, zone).replace(tzinfo=None) != local:
        raise ScheduleError("That local time does not exist because the clock moves forward. Pick another time.")
    return stamp


def parse_once(date_s, time_s, tz, now=None):
    hm = parse_time(time_s)
    m = re.fullmatch(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*", date_s or "")
    if not m:
        raise ScheduleError("Date must look like 2026-11-07.")
    try:
        local = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(hm[:2]), int(hm[3:]))
        zone = ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        raise ScheduleError("That timezone is not recognised. Use an IANA name such as Asia/Tehran.")
    except ValueError:
        raise ScheduleError("That date does not exist.")
    ts = _local_timestamp(local, zone)
    now = now if now is not None else int(datetime.now().timestamp())
    if ts <= now:
        raise ScheduleError("That time is already in the past.")
    if ts - now > 366 * 86400:
        raise ScheduleError("Pick a date within the next year.")
    return ts


def _day(token):
    t = token.strip().lower().rstrip(".")
    t = DAY_ALIASES.get(t, t)
    if t in DAYS:
        return DAYS.index(t)
    raise ScheduleError(f"Unknown day '{token}'. Use Mon, Tue, Wed, Thu, Fri, Sat, Sun, ranges like Mon-Fri, "
                        f"or daily, weekdays, weekends.")


def parse_weekly(days_s, time_s):
    hm = parse_time(time_s)
    text = (days_s or "").strip().lower()
    text = re.sub(r"\s*-\s*", "-", text)
    if not text:
        raise ScheduleError("Add at least one day, for example Mon, Fri.")
    idx = set()
    for part in [p for p in re.split(r"[,\s/&+]+", text.replace(" to ", "-").replace("–", "-")) if p]:
        if part in ("daily", "everyday", "all"):
            idx.update(range(7))
        elif part in ("weekdays", "weekday"):
            idx.update(range(5))
        elif part in ("weekends", "weekend"):
            idx.update((5, 6))
        elif "-" in part:
            a, _, b = part.partition("-")
            i, j = _day(a), _day(b)
            k = i
            while True:
                idx.add(k)
                if k == j:
                    break
                k = (k + 1) % 7
        else:
            idx.add(_day(part))
    days = sorted(idx)
    return ",".join(str(i) for i in days), hm


def _weekly_occurrences_around(sched, tz, now):
    z = ZoneInfo(tz)
    days = [int(x) for x in (sched["weekdays"] or "").split(",") if x != ""]
    h, m = int(sched["time_hm"][:2]), int(sched["time_hm"][3:])
    base = datetime.fromtimestamp(now, z).date()
    occ = []
    for off in range(-8, 9):
        d = base + timedelta(days=off)
        if d.weekday() in days:
            try:
                occ.append(_local_timestamp(datetime(d.year, d.month, d.day, h, m), z))
            except ScheduleError:
                continue  # A weekly time in the spring-forward gap is skipped, never shifted.
    return sorted(occ)


def next_run(sched, tz, now):
    if not sched["enabled"]:
        return None
    if sched["kind"] == "once":
        return sched["run_at"] if sched["run_at"] and not sched["last_run_at"] else None
    for t in _weekly_occurrences_around(sched, tz, now):
        if t > now:
            return t
    return None


def is_due(sched, tz, now):
    """Return (due, missed). missed = a one-time run whose window passed (it gets disabled)."""
    if not sched["enabled"]:
        return False, False
    if sched["kind"] == "once":
        t = sched["run_at"]
        if not t or sched["last_run_at"]:
            return False, False
        if t <= now <= t + GRACE:
            return True, False
        return False, now > t + GRACE
    last_ref = max(sched["last_run_at"] or 0, sched["created_at"] or 0)
    prev = [t for t in _weekly_occurrences_around(sched, tz, now) if t <= now]
    if not prev:
        return False, False
    t = prev[-1]
    return (t > last_ref and now - t <= GRACE), False


def describe(sched, tz):
    if sched["kind"] == "once":
        return f"One-time · <t:{sched['run_at']}:F>"
    days = ", ".join(DAYS[int(i)].title() for i in sched["weekdays"].split(","))
    return f"Weekly · {days} at {sched['time_hm']} ({tz})"


def describe_plain(sched, tz):
    """Same as describe() without Discord timestamp markup (for select menus)."""
    if sched["kind"] == "once":
        local = datetime.fromtimestamp(sched["run_at"], ZoneInfo(tz))
        return f"One-time · {local:%Y-%m-%d %H:%M} ({tz})"
    days = ", ".join(DAYS[int(i)].title() for i in sched["weekdays"].split(","))
    return f"Weekly · {days} at {sched['time_hm']}"
