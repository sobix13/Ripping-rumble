# RipCars Rumble 1.2.0

A Discord last-player-standing community game. Members press **Join** in the lobby. Every later scene, elimination, return and final runs automatically. No player vote, wallet connection, signature or purchase is required.

Scenes draw on the wider Hot Wheels hobby, history and collector culture. A model in a scene does not claim that RipCars stocks, owns, sells or awards it. This is an independent community game with no official Hot Wheels or Mattel collaboration. Fictional items do not move real assets. A configured Discord winner role is a real bot action.

## Game

Six worlds: RipCars Garage, Treasure Hunt, Convention Night, Redline Era, Gulf and NFT Garage. The shipped bank has 591 scenarios:543 original records and 48 adapted additions. Redline takes place in a fictional 1971 shop. The 48 additions comprise 44 independent adapters and 4 item/capsule adapters. The full 300-text expansion and 30 branching stories are not implemented.

- Members join or leave before the lobby closes. Hosts also have Start now. Games then run automatically.
- Small fields finish early. Two members receive an introduction and a final. Large fields use a readability floor rather than forcing every elimination into a crowded final.
- Hazards obey their switch, including the final, and remove at most 8 members per group event. Event and Discord message limits are checked separately.
- Each member returns at most once. Passive revives are capped. Automatic Second Chance requires 8+ entrants, its sampled lap, at least half the original field eliminated, at least 3 alive and at least 2 planned laps left. Some games never open a suitable window.
- The configured base pause is a minimum. Text receives a 180-words/minute reading allowance, capped at 30 seconds, while a larger host minimum remains in force. Dense rounds still need private spectator testing.
- Up to 2 fictional items have unique identities. Transfers retain identity and elimination drops the item. Callbacks and item finals provide narrative recall. They are not player-controlled strategy.
- The selector avoids event IDs from the last 3 completed guild games where alternatives exist. Titles, winner templates and the fixed item-final format still repeat.
- Results are stored atomically before announcement. Retries do not recount a win. Uncertain delivery is reconciled or held for operator review. Interrupted games do not resume midway after restart.
- Default capacity is 60. Up to 250 is supported by local engine checks, without certification of live performance.

## Controls

| Command | Access | Purpose |
| --- | --- | --- |
| /rumble guide | everyone | Read-only player guide |
| /rumble guide admin:true | admins | Administrator guide |
| /rumble panel | hosts/admins | Start, stop, schedule and management |
| /rumble setup | admins | Six-step setup with review |
| /rumble start, /rumble stop | hosts/admins | Host controls |
| /rumble leaderboard, /rumble stats | everyone | Results |
| /rumble worlds | everyone | World descriptions |
| /rumble diagnose | admins | Permissions, loops and delivery checks |

Manage Server or configured admin roles grant administration. Host roles grant hosting. Prize roles must be dedicated, permission-free and separate from access roles, with suitable bot/operator hierarchy. Award properties are rechecked at delivery. No privileged gateway intents are required.

Setup configures the game channel, hosts, players, optional winner role, defaults and optional private reports. Panels expire after 15 minutes. Forms recheck owner, server and current authority. Settings mutations preserve concurrent changes to other fields.

Maintenance shows runtime and verified-backup state. Destructive leaderboard reset is blocked during a game and requires a successful backup and fresh authorization. Backup files are never posted to Discord. User/Admin Guides and the admin-only scenario catalog are available inside Discord.

Scenario wording overrides preserve stable IDs, placeholders and engine contracts. The editor checks writing rules, world context, unsupported braces and links. Blank text restores the shipped line. It is not a branching-story editor. A human admin still needs to review narrative meaning. Running games keep their initial wording snapshot.

## Deployment

Use Linux and Python 3.10+, with Python 3.12 used for local release verification. Install Python venv support. No token is included. Detailed install, update, backup, restore and legacy migration instructions are in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

From a reviewed, extracted source directory outside the installation path:

```bash
sudo bash scripts/install.sh
# Edit the printed shared/.env path. Set DISCORD_TOKEN and DEV_GUILD_ID for private acceptance.
sudo python 3 scripts/deploy.py apply /opt/ripcars-rumble/releases/1.2.0
sudo systemctl enable ripcars-rumble.service
sudo systemctl enable --now ripcars-rumble-backup.timer
```

Source and environment live in immutable releases. Credentials, data, logs and backups stay under shared/. The installer stages tests before activation. Update failure rolls back code and unit templates while preserving databases and credentials. No automatic database rewind is performed. Flat 1.1.1 installations need the documented migration, preserving old data and service files.

For local development:

```bash
python 3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env
# Configure credentials locally.
.venv/bin/python bot.py
```

The loopback health endpoint defaults to http://127.0.0.1:8093/healthz. HEALTH_PORT changes its port. The runtime also writes an atomic health.json beside the database, or at RUMBLE_HEALTH_FILE. Readiness checks gateway, SQLite and background work. systemd receives readiness and watchdog signals. Health responses contain no settings or credentials. Register this service and signal with your existing supervisor rather than adding another recovery controller.

Private report destinations are checked before configuration and each delivery. Public or unrelated access stops reports. At most 2 guild destinations are inspected per 15-second health pass, with per-guild cooldown and bounded sends. Optional notices are best-effort. Unknown delivery is not blindly resent. Full local logs remain the operational record. Credential redaction applies to stored errors and formatted tracebacks.

The backup timer retains 14 verified SQLite snapshots and metadata. Configure off-host encrypted coverage through your existing backup system. Local snapshots alone do not provide that coverage. Operational status verifies the latest snapshot and flags snapshots older than 48 hours.

## Uncertain result delivery

Inspect Diagnostics and channel history for the exact result footer and the bot author. Stop the service before reconciling. This changes delivery status without recounting results:

```bash
sudo systemctl stop ripcars-rumble.service
sudo -u rumble /opt/ripcars-rumble/current/.venv/bin/python /opt/ripcars-rumble/current/tools/reconcile.py --db /opt/ripcars-rumble/shared/data/rumble.sqlite3 confirm-announcement --game 42 --message-id 123456789012345678
```

For a confirmed absent announcement, use `retry-announcement --game 42 --confirmed-not-sent`. For a confirmed absent scheduled lobby, use `release-schedule --schedule 3 --occurrence TIMESTAMP --confirmed-no-lobby`. The occurrence is its stored scheduled instant. Past the grace window, create a new schedule. Restart after reconciliation.

## Verification

```bash
python -m pip install -r requirements-dev.txt
python -m pip check
python scripts/build_release.py
python tools/check_release.py
python -m pytest -q
python -m rumble.content.validate
python tools/export_bank.py docs/bank_export.json
python tools/simulate.py --games 200
python tools/verify_experience.py --games 200 --out docs/verification
```

Rebuild the manifest after intentional source/documentation changes. Verify the final archive after extraction. GitHub CI checks pushes/PRs on Python 3.10 and 3.12 using SHA-pinned official actions and read-only repository permissions. CI has not run until this source is pushed to a selected repository.

Tests use real SQLite, WAL, local HTTP sockets, files and subprocesses. Discord transport and systemd orchestration remain test fixtures. A working local suite does not certify the actual VPS, role hierarchy, image edits or real interaction deadlines. Complete [docs/LIVE_ACCEPTANCE.md](docs/LIVE_ACCEPTANCE.md) before public operation. See the [admin guide](docs/ADMIN_GUIDE.md) and [user guide](docs/USER_GUIDE.md).
