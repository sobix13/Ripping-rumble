"""Verified SQLite snapshots and offline restore. No Discord connection required."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import uuid


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def offline_lock(db_path, message='Stop the bot and all writers before restoring.'):
    lock = Path(str(Path(db_path).resolve()) + '.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a+') as handle:
        os.chmod(lock, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(message) from None
        yield


def _digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else hashlib.sha256(stream.read()).hexdigest()


def _inspect(path):
    with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=10) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('SQLite integrity check failed.')
        counts = {}
        for table in ('games', 'stats', 'game_results'):
            if db.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?', ('table', table)).fetchone():
                counts[table] = db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
        return {'user_version': db.execute('PRAGMA user_version').fetchone()[0], 'rows': counts}


def verify_backup(metadata_path):
    metadata_path = Path(metadata_path).resolve()
    metadata = json.loads(metadata_path.read_text())
    filename = metadata.get('backup_file', '')
    if filename != metadata_path.stem + '.sqlite3' or not filename.startswith('rumble-'):
        raise ValueError('Invalid backup metadata filename.')
    database = metadata_path.parent / filename
    if database.is_symlink() or not database.is_file():
        raise ValueError('Backup database is missing or is a symlink.')
    if database.stat().st_size != metadata['bytes'] or _digest(database) != metadata['sha256']:
        raise ValueError('Backup hash or size differs from metadata.')
    if _inspect(database) != metadata['database']:
        raise ValueError('Backup contents differ from recorded database checks.')
    return database, metadata


def _backup_database(db_path, backup_dir, keep=14, timeout=60):
    if keep < 1 or timeout <= 0:
        raise ValueError('Retention and timeout must be positive.')
    source = Path(db_path).resolve()
    if not source.is_file():
        raise ValueError('Source database does not exist.')
    directory = Path(backup_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    name = 'rumble-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex[:8]
    destination = directory / (name + '.sqlite3')
    fd, temporary = tempfile.mkstemp(prefix='.snapshot-', dir=directory)
    os.close(fd)
    deadline = time.monotonic() + timeout

    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise TimeoutError('SQLite backup exceeded its time limit.')

    try:
        with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=min(timeout, 10)) as live:
            with sqlite3.connect(temporary) as target:
                live.backup(target, pages=128, progress=progress, sleep=0.05)
        checks = _inspect(temporary)
        os.chmod(temporary, 0o600)
        with open(temporary, 'rb') as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        metadata = {'format': 1, 'created_at': time.time(), 'backup_file': destination.name,
                    'bytes': destination.stat().st_size, 'sha256': _digest(destination), 'database': checks}
        metadata_path = directory / (name + '.json')
        atomic_json(metadata_path, metadata)
        verify_backup(metadata_path)
        atomic_json(directory / 'latest.json', {'metadata_file': metadata_path.name, **metadata})
        valid = []
        for entry in directory.glob('rumble-*.json'):
            try:
                _, item = verify_backup(entry)
                valid.append((item['created_at'], entry))
            except (ValueError, KeyError, OSError, sqlite3.Error):
                continue
        for _, entry in sorted(valid, reverse=True)[keep:]:
            database, _ = verify_backup(entry)
            database.unlink()
            entry.unlink()
        return metadata_path
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)



def backup_database(db_path, backup_dir, keep=14, timeout=60):
    directory = Path(backup_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.backup.lock').open('a+') as lock:
        os.chmod(directory / '.backup.lock', 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another backup is in progress.') from None
        return _backup_database(db_path, directory, keep, timeout)


def create_backup(db_path, backup_dir, keep=14):
    metadata_path = backup_database(db_path, backup_dir, keep)
    database, metadata = verify_backup(metadata_path)
    return {**metadata, 'path': str(database), 'metadata_path': str(metadata_path)}

def restore_database(metadata_path, destination, replace=False):
    source, metadata = verify_backup(metadata_path)
    destination = Path(destination).resolve()
    if destination == source:
        raise ValueError('Restore destination is the backup itself.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with offline_lock(destination):
        if destination.exists() and not replace:
            raise ValueError('Destination exists. Use --replace only after stopping writers and taking a backup.')
        if any(Path(str(destination) + suffix).exists() for suffix in ('-wal', '-shm')):
            raise ValueError('Destination has WAL/SHM sidecars. Keep them with the old database before restoring.')
        fd, temporary = tempfile.mkstemp(prefix='.restore-', dir=destination.parent)
        os.close(fd)
        try:
            with source.open('rb') as src, open(temporary, 'wb') as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)
                dst.flush()
                os.fsync(dst.fileno())
            if _digest(temporary) != metadata['sha256'] or _inspect(temporary) != metadata['database']:
                raise ValueError('Restored copy failed verification.')
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    backup = commands.add_parser('backup')
    backup.add_argument('--db', required=True, type=Path)
    backup.add_argument('--directory', required=True, type=Path)
    backup.add_argument('--keep', type=int, default=14)
    backup.add_argument('--timeout', type=float, default=60)
    verify = commands.add_parser('verify')
    verify.add_argument('metadata', type=Path)
    restore = commands.add_parser('restore')
    restore.add_argument('metadata', type=Path)
    restore.add_argument('--db', required=True, type=Path)
    restore.add_argument('--replace', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.action == 'backup':
            result = backup_database(args.db, args.directory, args.keep, args.timeout)
        elif args.action == 'verify':
            result, _ = verify_backup(args.metadata)
        else:
            result = restore_database(args.metadata, args.db, args.replace)
        print(result)
        return 0
    except (ValueError, RuntimeError, OSError, sqlite3.Error, KeyError) as error:
        print(f'FAILED: {error}', file=__import__('sys').stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
