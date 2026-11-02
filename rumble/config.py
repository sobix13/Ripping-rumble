"""Per-server settings, stored as JSON in SQLite. Every value is clamped on load and on save."""
import json
from dataclasses import asdict, dataclass, field
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .content import world_keys
from .engine import Settings

LOBBY_CHOICES = [30, 45, 60, 90, 120, 180, 300]
DELAY_CHOICES = [6, 8, 10, 12, 15, 20]
WINNER_HOURS_CHOICES = [12, 24, 48, 72, 168, 0]   # 0 = keep the role until removed by hand


def valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def _ids(v):
    out = []
    for x in v or []:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            pass
    return list(dict.fromkeys(out))[:25]


def _opt_id(v):
    try:
        return int(v) if v else None
    except (TypeError, ValueError):
        return None


@dataclass
class GuildConfig:
    guild_id: int
    channel_id: int = None
    admin_role_ids: list = field(default_factory=list)    # can change settings (Manage Server always can)
    host_role_ids: list = field(default_factory=list)     # can start, stop and schedule games
    player_role_ids: list = field(default_factory=list)   # can join (empty = everyone)
    winner_role_id: int = None
    winner_role_hours: int = 24
    ping_role_id: int = None
    report_channel_id: int = None
    text_overrides: dict = field(default_factory=dict)
    default_world: str = "garage"                         # a world key or "random"
    lobby_seconds: int = 60
    round_delay: int = 10
    min_players: int = 2
    max_players: int = 60
    min_rounds: int = 2
    max_rounds: int = 16
    revive_rate: float = 0.12
    second_chance: bool = True
    second_chance_seconds: int = 10
    hazards: bool = True
    images: bool = True
    server_emoji: bool = True
    timezone: str = "Asia/Tehran"
    setup_done: bool = False

    def clamp(self):
        self.channel_id = _opt_id(self.channel_id)
        self.winner_role_id = _opt_id(self.winner_role_id)
        self.ping_role_id = _opt_id(self.ping_role_id)
        self.report_channel_id = _opt_id(self.report_channel_id)
        overrides = self.text_overrides if isinstance(self.text_overrides, dict) else {}
        self.text_overrides = {key: value for key, value in list(overrides.items())[:591]
                               if isinstance(key, str) and isinstance(value, str)
                               and 0 < len(key) <= 100 and 0 < len(value) <= 240}
        self.admin_role_ids = _ids(self.admin_role_ids)
        self.host_role_ids = _ids(self.host_role_ids)
        self.player_role_ids = _ids(self.player_role_ids)
        if self.default_world != "random" and self.default_world not in world_keys():
            self.default_world = "garage"
        self.lobby_seconds = max(15, min(600, int(self.lobby_seconds)))
        self.round_delay = max(4, min(60, int(self.round_delay)))
        self.min_players = max(2, min(50, int(self.min_players)))
        self.max_players = max(self.min_players, min(250, int(self.max_players)))
        self.min_rounds = max(2, min(12, int(self.min_rounds)))
        self.max_rounds = max(self.min_rounds, min(25, int(self.max_rounds)))
        self.revive_rate = round(max(0.0, min(0.5, float(self.revive_rate))), 3)
        self.second_chance_seconds = max(5, min(30, int(self.second_chance_seconds)))
        self.winner_role_hours = max(0, min(24 * 30, int(self.winner_role_hours)))
        for f in ("second_chance", "hazards", "images", "server_emoji", "setup_done"):
            setattr(self, f, bool(getattr(self, f)))
        if not valid_timezone(self.timezone):
            self.timezone = "Asia/Tehran"
        return self

    def engine_settings(self) -> Settings:
        return Settings(min_rounds=self.min_rounds, max_rounds=self.max_rounds, revive_rate=self.revive_rate,
                        hazards=self.hazards, second_chance=self.second_chance).clamp()

    def to_json(self):
        d = asdict(self)
        d.pop("guild_id")
        return json.dumps(d)

    @classmethod
    def from_json(cls, guild_id, raw):
        cfg = cls(guild_id=guild_id)
        try:
            data = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            data = {}
        for k, v in data.items():
            if hasattr(cfg, k) and k != "guild_id":
                setattr(cfg, k, v)
        try:
            return cfg.clamp()
        except (TypeError, ValueError):
            return cls(guild_id=guild_id).clamp()
