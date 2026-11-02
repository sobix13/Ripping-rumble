# RipCars Rumble operations

This package is prepared for a reviewed GitHub source repository and a Linux VPS. Source, assets and the virtual environment are read-only to the service. SQLite, logs, credentials and backups stay outside versioned releases. The deployment scripts do not pull or execute an arbitrary GitHub update.

## Paths

- `/opt/ripcars-rumble/releases/VERSION`: verified source and its tested isolated environment.
- `/opt/ripcars-rumble/current`: active release symlink.
- `/opt/ripcars-rumble/previous`: last successful release for code rollback.
- `/opt/ripcars-rumble/shared/.env`: root-owned, group-readable credentials.
- `/opt/ripcars-rumble/shared/data`: database, instance lock and health file.
- `/opt/ripcars-rumble/shared/logs`: rotating application logs.
- `/opt/ripcars-rumble/shared/backups`: verified SQLite snapshots and `latest.json`.

The service wrapper fixes runtime paths under `shared`. Historical DB_PATH or LOG_DIR entries in an imported environment file do not redirect the managed service. Direct `python bot.py` remains available for development. Use the same database path when testing the process lock.

## First installation

Install Python with venv support. Place the reviewed source outside the installation directory. From that source:

```bash
sudo bash scripts/install.sh
```

Installation verifies the release manifest, creates an isolated environment, installs exact dependencies, runs dependency checks, pytest and content validation, then creates the `rumble` service user and unit files. It leaves the service stopped. Edit the printed `shared/.env` path and set DISCORD_TOKEN. Set DEV_GUILD_ID for the private acceptance server. Do not paste credentials into GitHub or chat.

Activate the tested candidate printed by the installer:

```bash
sudo python3 scripts/deploy.py apply /opt/ripcars-rumble/releases/1.2.0
sudo systemctl enable ripcars-rumble.service
sudo systemctl enable --now ripcars-rumble-backup.timer
```

Run `/rumble setup`, review the private diagnostics, and run a non-admin Join-only acceptance game. Leave the optional prize role empty for the first game. No privileged intents are required by this game.

## Reviewed update

Stage the reviewed new source before stopping the running bot:

```bash
sudo bash /path/to/reviewed/source/scripts/update.sh /path/to/reviewed/source
```

A process lock serializes deployment commands. A new version is required. Existing release directories are never updated in place. Staging failure leaves the running release untouched. Activation stops the old process, takes and verifies a snapshot after shutdown has drained result work, switches the code pointer, and starts the candidate. It requires fresh healthy state with the expected version and actual systemd MainPID within the bounded startup window. Missing, stale, unhealthy or foreign-process health does not count as success.

If startup fails, the code pointer returns to the previous release and its service is started. SQLite and credentials are preserved. The installer never restores an old database automatically. An initial installation has no previous release and remains stopped after failure. Inspect logs after any failed update.

The units supplied by each candidate are installed during activation and systemd is reloaded. On failed activation, the previous release's unit templates are restored before restarting its code. Administrator drop-in files remain separate from these generated units.

## Code rollback

```bash
sudo bash /opt/ripcars-rumble/current/scripts/rollback.sh
```

The rollback path uses the same backup and readiness checks. It changes source only. Database migrations in a later version must remain compatible with the retained old release before code rollback is relied on. A destructive schema change requires a separate reviewed migration plan.

## Backups

The persistent timer runs daily at 03:15 UTC, approximately 06:45 Tehran time, with up to five minutes of randomized delay. It retains fourteen verified snapshots. The panel's manual backup uses the same implementation, process lock and fourteen-snapshot retention.

Backups use SQLite's online backup API, including committed WAL transactions. Each snapshot has integrity checks, row counts for relevant tables, size, SHA-256 and metadata. `latest.json` changes only after verification. Failed snapshots do not remove older backups. A shared process lock prevents timer and panel retention races. Snapshots stay on this VPS until the operator configures an off-host copy.

Manual snapshot and verification:

```bash
sudo -u rumble /opt/ripcars-rumble/current/.venv/bin/python -m rumble.maintenance backup --db /opt/ripcars-rumble/shared/data/rumble.sqlite3 --directory /opt/ripcars-rumble/shared/backups --keep 14
sudo -u rumble /opt/ripcars-rumble/current/.venv/bin/python -m rumble.maintenance verify /opt/ripcars-rumble/shared/backups/rumble-TIMESTAMP-ID.json
```

## Offline restore

Stop the service and all manual writers. Keep the current database, WAL and SHM together as a recovery copy. Choose a verified snapshot and restore into an empty location first:

```bash
sudo systemctl stop ripcars-rumble.service
sudo -u rumble /opt/ripcars-rumble/current/.venv/bin/python -m rumble.maintenance restore /opt/ripcars-rumble/shared/backups/rumble-TIMESTAMP-ID.json --db /opt/ripcars-rumble/shared/data/restored.sqlite3
```

Inspect the restored latest game and stats before replacing the active database. The helper checks hashes and integrity again, holds the same database sidecar process lock as the entrypoint, refuses existing destinations without `--replace`, and refuses destinations with WAL/SHM sidecars. It does not stop writers itself. An external writer that ignores the process lock must be stopped by the operator.

## Existing 1.1.1 installation

A flat installation is deliberately refused by the installer. Do not install over it or overwrite its data directory.

1. Stop the existing service and all manual writers.
2. Use the new maintenance helper against the old database to take a verified snapshot in a separate protected directory.
3. Preserve the complete old source directory, `.env`, database and sidecars as an offline rollback copy. Move the old installation to a distinct path before creating the new `/opt/ripcars-rumble` layout. Keep a copy of its old service unit too.
4. Run the new installer from a separate reviewed source directory. Leave it stopped.
5. Copy the old `.env` into `shared/.env` with root:rumble ownership and mode 0640. Restore the verified snapshot into the empty `shared/data/rumble.sqlite3` using the new helper as the rumble user.
6. Activate the staged release and perform private acceptance. The managed wrapper uses shared runtime paths regardless of legacy path overrides.
7. If migration acceptance fails, stop the new service. Review the new database and recorded outcomes before deciding whether to return to the offline legacy copy. Never silently replace the database with an older snapshot.

## Health and troubleshooting

The runtime publishes an atomic `shared/data/health.json` and loopback `/healthz` endpoint. Discord readiness, database access and successful scheduler/recovery passes determine readiness. systemd notification is sent by the main process. A 90-second watchdog detects stalled internal work. Ordinary network reconnects are distinguished from stalled database or background loops by the runtime health implementation.

```bash
sudo systemctl status ripcars-rumble.service
sudo journalctl -u ripcars-rumble.service -n 100 --no-pager
sudo systemctl status ripcars-rumble-backup.timer
sudo journalctl -u ripcars-rumble-backup.service -n 50 --no-pager
curl --fail --max-time 3 http://127.0.0.1:8093/healthz
```

A service process existing is insufficient proof of readiness. Check version, PID, freshness, pending deliveries and the last successful backup. Recovery instructions for uncertain Discord announcements remain in README. Use private operator logs and never publish tokens.

The service has a 512 MiB memory limit, 128-task limit, bounded startup/shutdown and bounded restarts. Resource settings are defaults for a small bot, not a certification of performance on the target VPS.

## Verification boundary

Local tests exercise real SQLite files and WAL, subprocess staging failures, snapshot verification, lock conflicts, readiness identity/freshness, and code-only rollback preserving database changes. Discord delivery and systemd orchestration are simulated in these tests. Fresh virtual environment and package extraction tests belong in the final release evidence. Actual VPS ownership, systemd notification/watchdog, API deadlines and live non-admin Discord acceptance still require the target environment.
