"""SQLite storage with atomic results and durable delivery recovery."""
import asyncio
import json
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from .config import GuildConfig

SCHEMA_VERSION = 2
SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id INTEGER PRIMARY KEY, data TEXT NOT NULL, updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS stats (
    guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, name TEXT NOT NULL DEFAULT '',
    wins INTEGER NOT NULL DEFAULT 0, games INTEGER NOT NULL DEFAULT 0, kills INTEGER NOT NULL DEFAULT 0,
    best_place INTEGER, last_win_at INTEGER, PRIMARY KEY (guild_id, user_id));
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, world TEXT NOT NULL,
    started_at INTEGER NOT NULL, ended_at INTEGER, players INTEGER NOT NULL DEFAULT 0, winner_id INTEGER,
    rounds INTEGER, status TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'manual');
CREATE TABLE IF NOT EXISTS winner_roles (
    guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, role_id INTEGER NOT NULL, expires_at INTEGER,
    PRIMARY KEY (guild_id, user_id, role_id));
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, world TEXT NOT NULL,
    kind TEXT NOT NULL, run_at INTEGER, weekdays TEXT, time_hm TEXT, enabled INTEGER NOT NULL DEFAULT 1,
    last_run_at INTEGER, created_by INTEGER, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS game_results (
    game_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
    payload TEXT NOT NULL, finalized_at INTEGER NOT NULL,
    announcement_state TEXT NOT NULL DEFAULT 'pending', announcement_message_id INTEGER,
    role_done INTEGER NOT NULL DEFAULT 0, delivery_error TEXT);
CREATE TABLE IF NOT EXISTS game_messages (
    game_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
    lobby_message_id INTEGER, sc_message_id INTEGER, cleaned INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS approved_winner_roles (
    guild_id INTEGER NOT NULL, role_id INTEGER NOT NULL, PRIMARY KEY (guild_id, role_id));
CREATE TABLE IF NOT EXISTS schedule_occurrences (
    schedule_id INTEGER NOT NULL, occurrence_at INTEGER NOT NULL, game_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pending', PRIMARY KEY (schedule_id, occurrence_at));
"""


class Database:
    def __init__(self, path):
        self.path = path
        self.conn = None
        self._lock = asyncio.Lock()
        self._delivery_locks = {}

    @asynccontextmanager
    async def transaction(self):
        # One connection has one transaction, even when several coroutines use it.
        async with self._lock:
            if self.conn is None:
                raise RuntimeError('Database is closed')
            await self.conn.execute('BEGIN IMMEDIATE')
            try:
                yield self.conn
                await self.conn.commit()
            except BaseException:
                await self.conn.rollback()
                raise

    async def open(self):
        async with self._lock:
            if self.conn is not None:
                return
            self.conn = await aiosqlite.connect(self.path)
            self.conn.row_factory = aiosqlite.Row
            try:
                async with self.conn.execute('PRAGMA user_version') as cursor:
                    row = await cursor.fetchone()
                if row[0] > SCHEMA_VERSION:
                    raise RuntimeError('Database schema is newer than this bot')
                async with self.conn.execute('PRAGMA journal_mode=WAL') as cursor:
                    await cursor.fetchall()
                await self.conn.executescript('BEGIN IMMEDIATE;\n' + SCHEMA +
                                             f'\nPRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;')
                await self.conn.execute("UPDATE games SET status='interrupted', ended_at=? "
                                        "WHERE status IN ('lobby','running','finishing')",
                                        (int(time.time()),))
                # A persisted lobby is an admitted occurrence even if its ACK was interrupted.
                await self.conn.execute("UPDATE schedule_occurrences SET status='started' WHERE status='pending' "
                                        "AND game_id IN (SELECT game_id FROM game_messages WHERE lobby_message_id IS NOT NULL)")
                # A send accepted immediately before process death has no saved message ID.
                # Preserve that uncertainty instead of starting the same occurrence again.
                await self.conn.execute("UPDATE schedule_occurrences SET status='unknown' WHERE status='pending'")
                await self.conn.commit()
            except BaseException:
                await self.conn.close()
                self.conn = None
                raise

    async def close(self):
        async with self._lock:
            if self.conn is not None:
                await self.conn.close()
                self.conn = None

    async def _rows(self, sql, args=()):
        async with self._lock:
            if self.conn is None:
                raise RuntimeError('Database is closed')
            async with self.conn.execute(sql, args) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def _write(self, sql, args=()):
        async with self.transaction() as conn:
            cur = await conn.execute(sql, args)
            return cur.lastrowid, cur.rowcount

    async def ping(self):
        return bool(await self._rows('SELECT 1 AS ok'))

    async def get_config(self, guild_id):
        rows = await self._rows('SELECT data FROM guild_config WHERE guild_id=?', (guild_id,))
        return GuildConfig.from_json(guild_id, rows[0]['data'] if rows else None)

    async def _save_config(self, conn, cfg):
        cfg.clamp()
        await conn.execute('INSERT INTO guild_config (guild_id,data,updated_at) VALUES (?,?,?) '
                           'ON CONFLICT(guild_id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at',
                           (cfg.guild_id, cfg.to_json(), int(time.time())))

    async def save_config(self, cfg):
        async with self.transaction() as conn:
            await self._save_config(conn, cfg)

    async def mutate_config(self, guild_id, mutator):
        async with self.transaction() as conn:
            row = await (await conn.execute('SELECT data FROM guild_config WHERE guild_id=?', (guild_id,))).fetchone()
            cfg = GuildConfig.from_json(guild_id, row['data'] if row else None)
            mutator(cfg)
            await self._save_config(conn, cfg)
            return cfg

    async def game_started(self, guild_id, world, source):
        async with self.transaction() as conn:
            cur = await conn.execute("INSERT INTO games (guild_id,world,started_at,status,source) VALUES (?,?,?,'lobby',?)",
                                     (guild_id, world, int(time.time()), source))
            game_id = cur.lastrowid
            if source.startswith('schedule:'):
                _, sid, occurrence = source.split(':')
                await conn.execute('UPDATE schedule_occurrences SET game_id=? WHERE schedule_id=? AND occurrence_at=?',
                                   (game_id, int(sid), int(occurrence)))
            return game_id

    async def game_status(self, game_id, status, players=None, winner_id=None, rounds=None):
        sets, vals = ['status=?'], [status]
        for key, value in [('players', players), ('winner_id', winner_id), ('rounds', rounds)]:
            if value is not None:
                sets.append(f'{key}=?')
                vals.append(value)
        if status in ('finished', 'cancelled', 'stopped', 'error'):
            sets.append('ended_at=?')
            vals.append(int(time.time()))
        vals.extend([game_id, game_id])
        await self._write(f"UPDATE games SET {','.join(sets)} WHERE id=? "
                          'AND NOT EXISTS (SELECT 1 FROM game_results WHERE game_id=?)', vals)

    async def recent_games(self, guild_id, limit=5):
        return await self._rows('SELECT * FROM games WHERE guild_id=? ORDER BY id DESC LIMIT ?', (guild_id, limit))

    async def _record_results(self, conn, guild_id, results):
        now = int(time.time())
        for r in results:
            await conn.execute(
                'INSERT INTO stats (guild_id,user_id,name,wins,games,kills,best_place,last_win_at) '
                'VALUES (?,?,?,?,1,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET '
                'name=excluded.name,wins=wins+excluded.wins,games=games+1,kills=kills+excluded.kills,'
                'best_place=CASE WHEN best_place IS NULL OR excluded.best_place<best_place '
                'THEN excluded.best_place ELSE best_place END,'
                'last_win_at=COALESCE(excluded.last_win_at,last_win_at)',
                (guild_id, r['user_id'], r['name'][:64], int(r['won']), r['kills'], r['place'], now if r['won'] else None))

    async def record_results(self, guild_id, results):
        # Compatibility for callers without a game; production uses finalize_game.
        async with self.transaction() as conn:
            await self._record_results(conn, guild_id, results)

    async def finalize_game(self, game_id, guild_id, results, winner_id, rounds, payload):
        async with self.transaction() as conn:
            existing = await (await conn.execute('SELECT 1 FROM game_results WHERE game_id=?', (game_id,))).fetchone()
            if existing:
                return False
            game = await (await conn.execute('SELECT guild_id FROM games WHERE id=?', (game_id,))).fetchone()
            if not game or game['guild_id'] != guild_id:
                raise ValueError('Unknown game')
            if len({r['user_id'] for r in results}) != len(results) or sum(bool(r['won']) for r in results) != 1:
                raise ValueError('Invalid final results')
            if not any(r['user_id'] == winner_id and r['won'] for r in results):
                raise ValueError('Winner differs from final results')
            await self._record_results(conn, guild_id, results)
            now = int(time.time())
            await conn.execute('INSERT INTO game_results (game_id,guild_id,channel_id,payload,finalized_at,role_done) '
                               'VALUES (?,?,?,?,?,?)',
                               (game_id, guild_id, payload['channel_id'], json.dumps(payload), now,
                                int(not payload.get('winner_role_id'))))
            await conn.execute("UPDATE games SET status='finished',ended_at=?,players=?,winner_id=?,rounds=? WHERE id=?",
                               (now, len(results), winner_id, rounds, game_id))
            return True

    def delivery_lock(self, game_id):
        return self._delivery_locks.setdefault(game_id, asyncio.Lock())

    async def result_for_game(self, game_id):
        rows = await self._rows('SELECT * FROM game_results WHERE game_id=?', (game_id,))
        if not rows:
            return None
        rows[0]['payload'] = json.loads(rows[0]['payload'])
        return rows[0]

    async def pending_deliveries(self):
        rows = await self._rows('SELECT * FROM game_results WHERE announcement_message_id IS NULL OR role_done=0 '
                                'ORDER BY game_id')
        for row in rows:
            row['payload'] = json.loads(row['payload'])
        return rows

    async def recent_content_ids(self, guild_id, limit=3):
        rows = await self._rows('SELECT payload FROM game_results WHERE guild_id=? ORDER BY game_id DESC LIMIT ?',
                                (guild_id, limit))
        return {line_id for row in rows for line_id in json.loads(row['payload']).get('line_ids', [])}

    async def mark_announcement(self, game_id, message_id):
        await self._write("UPDATE game_results SET announcement_state='sent',announcement_message_id=?,delivery_error=NULL "
                          'WHERE game_id=?', (message_id, game_id))

    async def mark_announcement_attempt(self, game_id, state, error=None):
        if state not in ('pending', 'sending', 'unknown'):
            raise ValueError('Invalid announcement state')
        await self._write('UPDATE game_results SET announcement_state=?,delivery_error=? WHERE game_id=?',
                          (state, error, game_id))

    async def mark_role_delivered(self, game_id):
        await self._write('UPDATE game_results SET role_done=1 WHERE game_id=?', (game_id,))

    async def delivery_error(self, game_id, error):
        await self._write('UPDATE game_results SET delivery_error=? WHERE game_id=?', (str(error)[:1000], game_id))

    async def track_game_messages(self, game_id, guild_id, channel_id, lobby_message_id=None, sc_message_id=None):
        async with self.transaction() as conn:
            await conn.execute('INSERT INTO game_messages (game_id,guild_id,channel_id,lobby_message_id,sc_message_id) '
                               'VALUES (?,?,?,?,?) ON CONFLICT(game_id) DO UPDATE SET '
                               'lobby_message_id=COALESCE(excluded.lobby_message_id,lobby_message_id),'
                               'sc_message_id=COALESCE(excluded.sc_message_id,sc_message_id)',
                               (game_id, guild_id, channel_id, lobby_message_id, sc_message_id))
            if lobby_message_id:
                await conn.execute("UPDATE schedule_occurrences SET status='started' WHERE game_id=?", (game_id,))

    async def mark_messages_cleaned(self, game_id):
        await self._write('UPDATE game_messages SET cleaned=1 WHERE game_id=?', (game_id,))

    async def interrupted_messages(self):
        return await self._rows('SELECT m.*,g.world FROM game_messages m JOIN games g ON g.id=m.game_id '
                                "WHERE m.cleaned=0 AND g.status IN ('interrupted','error','stopped','cancelled','finished')")

    async def leaderboard(self, guild_id, limit=10):
        return await self._rows('SELECT * FROM stats WHERE guild_id=? AND games>0 '
                                'ORDER BY wins DESC,kills DESC,games ASC LIMIT ?', (guild_id, limit))

    async def user_stats(self, guild_id, user_id):
        rows = await self._rows('SELECT * FROM stats WHERE guild_id=? AND user_id=?', (guild_id, user_id))
        return rows[0] if rows else None

    async def reset_leaderboard(self, guild_id):
        await self._write('DELETE FROM stats WHERE guild_id=?', (guild_id,))

    async def add_winner_role(self, guild_id, user_id, role_id, expires_at):
        await self._write('INSERT INTO winner_roles (guild_id,user_id,role_id,expires_at) VALUES (?,?,?,?) '
                          'ON CONFLICT(guild_id,user_id,role_id) DO UPDATE SET expires_at=excluded.expires_at',
                          (guild_id, user_id, role_id, expires_at))

    async def get_winner_role(self, guild_id, user_id, role_id):
        rows = await self._rows('SELECT * FROM winner_roles WHERE guild_id=? AND user_id=? AND role_id=?',
                                (guild_id, user_id, role_id))
        return rows[0] if rows else None

    async def expired_winner_roles(self, now=None):
        return await self._rows('SELECT * FROM winner_roles WHERE expires_at IS NOT NULL AND expires_at<=?',
                                (int(time.time()) if now is None else now,))

    async def drop_winner_role(self, guild_id, user_id, role_id, expected_expires_at=...):
        sql = 'DELETE FROM winner_roles WHERE guild_id=? AND user_id=? AND role_id=?'
        args = [guild_id, user_id, role_id]
        if expected_expires_at is not ...:
            sql += ' AND expires_at IS ?'
            args.append(expected_expires_at)
        _, count = await self._write(sql, args)
        return count > 0

    async def active_winner_roles(self, guild_id):
        return await self._rows('SELECT * FROM winner_roles WHERE guild_id=?', (guild_id,))

    async def approve_winner_role(self, guild_id, role_id):
        await self._write('INSERT OR IGNORE INTO approved_winner_roles VALUES (?,?)', (guild_id, role_id))

    async def approved_winner_role(self, guild_id, role_id):
        return bool(await self._rows('SELECT 1 FROM approved_winner_roles WHERE guild_id=? AND role_id=?', (guild_id, role_id)))

    async def add_schedule(self, guild_id, world, kind, run_at=None, weekdays=None, time_hm=None, created_by=None):
        id_, _ = await self._write('INSERT INTO schedules (guild_id,world,kind,run_at,weekdays,time_hm,created_by,created_at) '
                                  'VALUES (?,?,?,?,?,?,?,?)',
                                  (guild_id, world, kind, run_at, weekdays, time_hm, created_by, int(time.time())))
        return id_

    async def schedules(self, guild_id=None, enabled_only=False):
        conditions, args = [], []
        if guild_id is not None:
            conditions.append('guild_id=?')
            args.append(guild_id)
        if enabled_only:
            conditions.append('enabled=1')
        return await self._rows('SELECT * FROM schedules' + (' WHERE ' + ' AND '.join(conditions) if conditions else '') +
                                ' ORDER BY id', args)

    async def remove_schedule(self, guild_id, sched_id):
        _, count = await self._write('DELETE FROM schedules WHERE guild_id=? AND id=?', (guild_id, sched_id))
        return count > 0

    async def mark_schedule_run(self, sched_id, when, disable=False):
        await self._write('UPDATE schedules SET last_run_at=?,enabled=CASE WHEN ? THEN 0 ELSE enabled END WHERE id=?',
                          (when, int(disable), sched_id))

    async def claim_schedule_occurrence(self, schedule_id, occurrence_at, game_id=None):
        _, count = await self._write('INSERT OR IGNORE INTO schedule_occurrences '
                                     '(schedule_id,occurrence_at,game_id) VALUES (?,?,?)',
                                     (schedule_id, occurrence_at, game_id))
        return count > 0

    async def complete_schedule_occurrence(self, schedule_id, occurrence_at, success=True, game_id=None, uncertain=False):
        if uncertain:
            await self._write("UPDATE schedule_occurrences SET status='unknown' WHERE schedule_id=? AND occurrence_at=? "
                              "AND status='pending'", (schedule_id, occurrence_at))
            return
        if success:
            await self._write("UPDATE schedule_occurrences SET status='started',game_id=COALESCE(?,game_id) "
                              'WHERE schedule_id=? AND occurrence_at=?', (game_id, schedule_id, occurrence_at))
        else:
            await self._write("DELETE FROM schedule_occurrences WHERE schedule_id=? AND occurrence_at=? AND status='pending'",
                              (schedule_id, occurrence_at))

    async def uncertain_schedule_occurrences(self):
        return await self._rows('SELECT o.*,s.guild_id FROM schedule_occurrences o '
                                "LEFT JOIN schedules s ON s.id=o.schedule_id WHERE o.status='unknown'")

    async def blocked_schedule_occurrences(self, guild_id):
        return await self._rows('SELECT o.* FROM schedule_occurrences o JOIN schedules s ON s.id=o.schedule_id '
                                "WHERE s.guild_id=? AND o.status='unknown'", (guild_id,))

    async def backup(self, destination):
        target_path = Path(destination).resolve()
        live = Path(self.path).resolve()
        if target_path in {live, Path(str(live) + '-wal'), Path(str(live) + '-shm')}:
            raise ValueError('Backup destination is the live database')
        target_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            if self.conn is None:
                raise RuntimeError('Database is closed')
            target = sqlite3.connect(str(target_path))
            try:
                await self.conn.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Backup integrity check failed')
            finally:
                target.close()
        return str(target_path)

    async def dump(self, guild_id):
        return json.dumps({'schedules': len(await self.schedules(guild_id)),
                           'players_with_stats': len(await self.leaderboard(guild_id, 1000))})
