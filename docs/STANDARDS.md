# Shared bot standards applied to Rumble

The shared Gate/Crew/Verifier and operations practices are adapted to this Join-only game. The bot does not acquire privileged gateway intents, cross-bot role ownership, a root repair agent, trading functionality or wallet actions.

| Standard | Implementation | Evidence and limit |
| --- | --- | --- |
| Unified setup and configuration | Six-step wizard, one host/admin panel, fresh authorization and atomic field updates | UI/admin regression tests. Live Discord still required |
| Separate user/admin guidance | Read-only player and administrator guides inside Discord and in docs | Ordinary-member and demotion tests |
| Editable text | Admin-only catalog export, per-guild stable-ID overrides, reset, contracts and writing checks | Editor integration tests and immutable active-game snapshot |
| Private operational reports | Privacy checked on save and delivery, no public fallback, bounded sends, redaction | Privacy-change, credential and timeout tests. Notices are best-effort |
| Data preservation | Additive JSON config fields, schema2, atomic/idempotent results, old-data migration tests | Stats/config remain outside releases |
| Verified checkpoints | WAL-aware SQLite snapshot, integrity, row counts, SHA-256, metadata and14-snapshot retention | Real backup/restore and failure tests. Off-host encryption belongs to enrolled backup service |
| Safe destructive administration | No active-game reset, checkpoint before deletion, access recheck after await | Backup failure/demotion/reset tests |
| Deployment staging | Manifest verification, isolated venv, dependency checks and tests before activation | Final archive extraction/staging gate recorded in bundle validation |
| Rollback | Code and unit templates, fresh version/PID/readiness checks, no automatic database restore | Failed-candidate tests preserve inserted DB rows |
| Service care | Atomic health JSON, loopback /healthz, main-process sd_notify, watchdog and bounded restart policy | Actual local HTTP tested. Actual systemd ownership/watchdog remain VPS acceptance |
| Shared supervision | Stable service/health/backup paths for enrollment in the existing supervisor | No duplicate host-recovery engine. Hourly/daily external reports need host enrollment |
| GitHub publication | English source/docs, runtime exclusions, credential-shaped scan, SHA-pinned read-only CI | Local commit/bundle prepared. Destination and remote CI are separate |

Health polling runs every15 seconds. Optional reporting inspects at most2 guilds per pass, uses a60-second per-guild cooldown and a5-second send bound. Healthy internal work continues through Discord reconnects. The external supervisor should check readiness rather than only a process name.

The database schema version remains2. New guild fields are additive JSON keys, allowing older code to ignore them during a code-only rollback. Future story-state schema changes require their own migration and rollback compatibility checks.

The scenario editor does not prove semantic truth, eliminate every period error or add branching stories. Review text meaning and perform live acceptance before a public event. Do not present fictional models as platform inventory or prizes.
