import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import time

import pytest

from rumble import maintenance
from scripts import deploy
from scripts.verify_release import verify


def database(path, rows=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('CREATE TABLE IF NOT EXISTS stats (user_id INTEGER)')
    connection.executemany('INSERT INTO stats VALUES (?)', [(i,) for i in range(rows)])
    connection.commit()
    return connection


def release(path, version):
    path.mkdir(parents=True)
    files = {'bot.py': 'print("entry")\n', 'requirements.txt': '', 'requirements-dev.txt': '',
             'rumble/__init__.py': '__version__ = ' + repr(version) + '\n'}
    for name, text in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    manifest = {'version': version, 'files': {name: {'bytes': len(text.encode()), 'sha256': hashlib.sha256(text.encode()).hexdigest()}
                                           for name, text in files.items()}}
    (path / 'RELEASE_MANIFEST.json').write_text(json.dumps(manifest))
    return path


def test_online_backup_contains_committed_wal_and_verified_restore(tmp_path):
    live = tmp_path / 'data/db.sqlite3'
    connection = database(live, 3)
    try:
        assert Path(str(live) + '-wal').stat().st_size > 0
        result = maintenance.create_backup(live, tmp_path / 'backups')
        assert result['database']['rows']['stats'] == 3
        restored = maintenance.restore_database(result['metadata_path'], tmp_path / 'restore/db.sqlite3')
        with sqlite3.connect(restored) as db:
            assert db.execute('SELECT COUNT(*) FROM stats').fetchone()[0] == 3
        latest = json.loads((tmp_path / 'backups/latest.json').read_text())
        assert latest['sha256'] == result['sha256']
    finally:
        connection.close()


def test_retention_runs_only_after_success(tmp_path, monkeypatch):
    live = tmp_path / 'db.sqlite3'
    database(live).close()
    first = maintenance.backup_database(live, tmp_path / 'backups', keep=2)
    second = maintenance.backup_database(live, tmp_path / 'backups', keep=2)
    latest = (tmp_path / 'backups/latest.json').read_bytes()
    original = maintenance._inspect
    monkeypatch.setattr(maintenance, '_inspect', lambda path: (_ for _ in ()).throw(RuntimeError('injected integrity failure')))
    with pytest.raises(RuntimeError):
        maintenance.backup_database(live, tmp_path / 'backups', keep=1)
    assert first.exists() and second.exists()
    assert (tmp_path / 'backups/latest.json').read_bytes() == latest
    monkeypatch.setattr(maintenance, '_inspect', original)
    third = maintenance.backup_database(live, tmp_path / 'backups', keep=1)
    assert third.exists() and not first.exists() and not second.exists()


def test_restore_refuses_corruption_running_writer_and_existing_destination(tmp_path):
    live = tmp_path / 'db.sqlite3'
    database(live).close()
    metadata = maintenance.backup_database(live, tmp_path / 'backups')
    with maintenance.offline_lock(live), pytest.raises(RuntimeError, match='Stop the bot'):
        maintenance.restore_database(metadata, live, replace=True)
    with pytest.raises(ValueError, match='Destination exists'):
        maintenance.restore_database(metadata, live)
    data, _ = maintenance.verify_backup(metadata)
    data.write_bytes(data.read_bytes() + b'corrupt')
    with pytest.raises(ValueError, match='hash or size'):
        maintenance.restore_database(metadata, tmp_path / 'restored.sqlite3')


def test_backup_process_lock_and_bad_metadata_are_rejected(tmp_path):
    live = tmp_path / 'db.sqlite3'
    database(live).close()
    backup_dir = tmp_path / 'backups'
    backup_dir.mkdir()
    with (backup_dir / '.backup.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match='Another backup'):
            maintenance.backup_database(live, backup_dir)
    metadata = maintenance.backup_database(live, backup_dir)
    payload = json.loads(metadata.read_text())
    payload['backup_file'] = '../db.sqlite3'
    metadata.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='metadata filename'):
        maintenance.verify_backup(metadata)


def test_release_verifier_rejects_hash_changes_and_traversal(tmp_path):
    source = release(tmp_path / 'source', '1.2.0')
    assert verify(source)['version'] == '1.2.0'
    (source / 'bot.py').write_text('altered')
    with pytest.raises(ValueError, match='hash'):
        verify(source)
    manifest = json.loads((source / 'RELEASE_MANIFEST.json').read_text())
    manifest['files'] = {'../escape': {'bytes': 0, 'sha256': ''}, **manifest['files']}
    (source / 'RELEASE_MANIFEST.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Unsafe'):
        verify(source)


def test_stage_failure_keeps_running_release_untouched(tmp_path):
    source = release(tmp_path / 'source', '1.2.0')
    base = tmp_path / 'installation'
    previous = release(base / 'releases/1.1.1', '1.1.1')
    (base / 'current').symlink_to(previous)
    calls = []

    def runner(argv, **kwargs):
        calls.append([str(v) for v in argv])
        if 'pytest' in argv:
            raise subprocess.CalledProcessError(1, argv)
        return subprocess.CompletedProcess(argv, 0, stdout='')

    with pytest.raises(subprocess.CalledProcessError):
        deploy.stage_release(source, base, runner)
    assert (base / 'current').resolve() == previous
    assert not (base / 'releases/1.2.0').exists()
    assert not any('systemctl' in call for call in calls)


def test_failed_activation_rolls_back_code_and_preserves_new_database_rows(tmp_path):
    base = tmp_path / 'installation'
    old = release(base / 'releases/1.1.1', '1.1.1')
    new = release(base / 'releases/1.2.0', '1.2.0')
    for path, version in ((old, '1.1.1'), (new, '1.2.0')):
        (path / 'STAGED_OK.json').write_text(json.dumps({'version': version,
            'manifest_sha256': hashlib.sha256((path / 'RELEASE_MANIFEST.json').read_bytes()).hexdigest()}))
    (base / 'current').symlink_to(old)
    shared = base / 'shared'
    shared.mkdir()
    (shared / '.env').write_text('DISCORD_TOKEN=private-fixture')
    live = shared / 'data/rumble.sqlite3'
    database(live).close()
    calls = []

    def runner(argv, **kwargs):
        calls.append(list(argv))
        if argv[1] == 'start':
            version = (base / 'current').resolve().name
            if version == '1.2.0':
                with sqlite3.connect(live) as db:
                    db.execute('INSERT INTO stats VALUES (999)')
            maintenance.atomic_json(shared / 'data/health.json', {'ok': version != '1.2.0', 'pid': 1234,
                                                                  'updated_at': time.time(), 'version': version})
        stdout = 'active' if argv[1] == 'is-active' else '1234' if argv[1] == 'show' else ''
        return subprocess.CompletedProcess(argv, 0, stdout=stdout)

    with pytest.raises(RuntimeError, match='readiness'):
        deploy.activate_release(new, base, runner=runner, timeout=0.02)
    assert (base / 'current').resolve() == old
    assert (shared / '.env').read_text() == 'DISCORD_TOKEN=private-fixture'
    with sqlite3.connect(live) as db:
        assert db.execute('SELECT COUNT(*) FROM stats').fetchone()[0] == 2
    assert (shared / 'backups/latest.json').exists()


def test_readiness_rejects_stale_or_foreign_pid(tmp_path):
    (tmp_path / 'shared/data').mkdir(parents=True)
    report = {'ok': True, 'pid': 999, 'updated_at': time.time(), 'version': '1.2.0'}
    maintenance.atomic_json(tmp_path / 'shared/data/health.json', report)
    def runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout='active' if argv[1] == 'is-active' else '1234')
    with pytest.raises(RuntimeError, match='readiness'):
        deploy.wait_ready(tmp_path, '1.2.0', 'systemctl', runner, timeout=0.01)
    report['pid'] = 1234
    report['updated_at'] = time.time() - 3600
    maintenance.atomic_json(tmp_path / 'shared/data/health.json', report)
    with pytest.raises(RuntimeError, match='readiness'):
        deploy.wait_ready(tmp_path, '1.2.0', 'systemctl', runner, timeout=0.01)


def test_cli_deployment_lock_prevents_concurrent_mutations(tmp_path, monkeypatch):
    base = tmp_path / 'base'
    called = []
    monkeypatch.setattr(deploy, 'stage_release', lambda *args: called.append(args))
    with maintenance.offline_lock(base / '.deploy'):
        assert deploy.main(['--base', str(base), 'stage', str(tmp_path)]) == 1
    assert called == []


def test_stage_marker_is_bound_to_tested_manifest(tmp_path):
    candidate = release(tmp_path / 'base/releases/1.2.0', '1.2.0')
    (candidate / 'STAGED_OK.json').write_text(json.dumps({'version': '1.2.0', 'manifest_sha256': 'outdated'}))
    with pytest.raises(ValueError, match='marker'):
        deploy.staged(candidate, tmp_path / 'base')


def test_unit_replacement_is_atomic_and_base_paths_are_rendered(tmp_path):
    source = tmp_path / 'source'
    units = source / 'deploy'
    units.mkdir(parents=True)
    target = tmp_path / 'units'
    target.mkdir()
    for filename in ('ripcars-rumble.service', 'ripcars-rumble-backup.service', 'ripcars-rumble-backup.timer'):
        (units / filename).write_text('Path=/opt/ripcars-rumble/current\n')
    calls = []
    def runner(argv, **kwargs):
        calls.append(argv)
    deploy.install_units(source, tmp_path / 'install', target, runner=runner)
    assert str(tmp_path / 'install/current') in (target / 'ripcars-rumble.service').read_text()
    assert calls == [['systemctl', 'daemon-reload']]
    assert not list(target.glob('.*'))


def test_failed_activation_restores_previous_unit_templates(tmp_path):
    base = tmp_path / 'installation'
    units = tmp_path / 'systemd'
    units.mkdir()
    old = release(base / 'releases/1.1.1', '1.1.1')
    new = release(base / 'releases/1.2.0', '1.2.0')
    names = ('ripcars-rumble.service', 'ripcars-rumble-backup.service', 'ripcars-rumble-backup.timer')
    for path, version in ((old, '1.1.1'), (new, '1.2.0')):
        (path / 'deploy').mkdir()
        manifest = json.loads((path / 'RELEASE_MANIFEST.json').read_text())
        for name in names:
            data = ('Release=' + version).encode()
            (path / 'deploy' / name).write_bytes(data)
            manifest['files']['deploy/' + name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        (path / 'RELEASE_MANIFEST.json').write_text(json.dumps(manifest))
        (path / 'STAGED_OK.json').write_text(json.dumps({'version': version,
            'manifest_sha256': hashlib.sha256((path / 'RELEASE_MANIFEST.json').read_bytes()).hexdigest()}))
    (base / 'current').symlink_to(old)
    shared = base / 'shared'
    (shared / 'data').mkdir(parents=True)
    (shared / '.env').write_text('DISCORD_TOKEN=fixture')

    def runner(argv, **kwargs):
        if len(argv) > 1 and argv[1] == 'start':
            version = (base / 'current').resolve().name
            maintenance.atomic_json(shared / 'data/health.json', {'ok': version == '1.1.1', 'version': version,
                                                                  'pid': 1234, 'updated_at': time.time()})
        result = 'active' if argv[1] == 'is-active' else '1234' if argv[1] == 'show' else ''
        return subprocess.CompletedProcess(argv, 0, stdout=result)

    with pytest.raises(RuntimeError, match='readiness'):
        deploy.activate_release(new, base, runner=runner, timeout=0.01, unit_dir=units)
    assert (base / 'current').resolve() == old
    assert all((units / name).read_text() == 'Release=1.1.1' for name in names)
