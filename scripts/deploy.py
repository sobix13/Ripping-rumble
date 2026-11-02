"""Stage a verified release, activate it, or roll back code without restoring databases."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rumble.maintenance import backup_database, offline_lock
from scripts.verify_release import verify

SERVICE = 'ripcars-rumble.service'


def run(argv, **kwargs):
    kwargs.setdefault('umask', 0o022)
    return subprocess.run([str(x) for x in argv], check=True, text=True, capture_output=True,
                          timeout=kwargs.pop('timeout', 600), **kwargs)


def link_to(link, destination):
    temporary = link.with_name('.' + link.name + '-' + str(os.getpid()))
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(destination)
    os.replace(temporary, link)


def stage_release(source, base, runner=run, python=sys.executable):
    source, base = Path(source).resolve(), Path(base).resolve()
    manifest = verify(source)
    if not (base / 'current').exists() and ((base / 'bot.py').exists() or (base / 'data/rumble.sqlite3').exists()):
        raise ValueError('Legacy installation detected. Follow docs/DEPLOYMENT.md migration before staging.')
    releases = base / 'releases'
    releases.mkdir(parents=True, exist_ok=True)
    base.chmod(0o755)
    releases.chmod(0o755)
    destination = releases / manifest['version']
    if destination.exists():
        raise ValueError('This version already exists. Use a new version rather than changing an installed release.')
    temporary = destination
    temporary.mkdir()
    temporary.chmod(0o755)
    try:
        for name in [*manifest['files'], 'RELEASE_MANIFEST.json']:
            target = temporary / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, target)
            target.chmod(0o755 if name.startswith('scripts/') and name.endswith('.sh') else 0o644)
        for directory in temporary.rglob('*'):
            if directory.is_dir() and not directory.is_symlink():
                directory.chmod(0o755)
        verify(temporary)
        runner([python, '-m', 'venv', str(temporary / '.venv')])
        interpreter = temporary / '.venv/bin/python'
        runner([interpreter, '-m', 'pip', 'install', '-r', str(temporary / 'requirements-dev.txt')], cwd=temporary)
        runner([interpreter, '-m', 'pip', 'check'], cwd=temporary)
        runner([interpreter, '-m', 'pytest', '-q'], cwd=temporary)
        runner([interpreter, '-m', 'rumble.content.validate'], cwd=temporary)
        verify(temporary)
        (temporary / 'STAGED_OK.json').write_text(json.dumps({'version': manifest['version'], 'tested_at': time.time(),
              'manifest_sha256': hashlib.sha256((temporary / 'RELEASE_MANIFEST.json').read_bytes()).hexdigest()}))
        return destination
    except BaseException:
        shutil.rmtree(temporary)
        raise


def staged(candidate, base):
    candidate, base = Path(candidate).resolve(), Path(base).resolve()
    if candidate.parent != base / 'releases' or not (candidate / 'STAGED_OK.json').is_file():
        raise ValueError('Candidate must be a tested release inside this installation.')
    manifest = verify(candidate)
    marker = json.loads((candidate / 'STAGED_OK.json').read_text())
    if (marker['version'] != manifest['version'] or marker.get('manifest_sha256') !=
            hashlib.sha256((candidate / 'RELEASE_MANIFEST.json').read_bytes()).hexdigest()):
        raise ValueError('Stage marker version differs from release.')
    return candidate, manifest['version']


def wait_ready(base, version, systemctl, runner=run, timeout=120):
    deadline, started = time.monotonic() + timeout, time.time()
    while time.monotonic() < deadline:
        try:
            active = runner([systemctl, 'is-active', SERVICE], timeout=10).stdout.strip()
            pid = int(runner([systemctl, 'show', SERVICE, '--property=MainPID', '--value'], timeout=10).stdout.strip())
            report = json.loads((Path(base) / 'shared/data/health.json').read_text())
            updated = float(report['updated_at'])
            if (active == 'active' and pid > 0 and report.get('ok') is True and report['version'] == version
                    and int(report['pid']) == pid and started - 1 <= updated <= time.time() + 5
                    and time.time() - updated < 30):
                return
        except (subprocess.SubprocessError, OSError, ValueError, KeyError):
            pass
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise RuntimeError('Service readiness was not confirmed within the time limit.')



def install_units(source, base, unit_dir, systemctl='systemctl', runner=run):
    unit_dir = Path(unit_dir)
    payloads = {name: (Path(source) / 'deploy' / name).read_text().replace('/opt/ripcars-rumble', str(base))
                for name in ('ripcars-rumble.service', 'ripcars-rumble-backup.service', 'ripcars-rumble-backup.timer')}
    for name, text in payloads.items():
        fd, temporary = tempfile.mkstemp(prefix='.' + name, dir=unit_dir)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o644)
            os.replace(temporary, unit_dir / name)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    runner([systemctl, 'daemon-reload'])

def activate_release(candidate, base, systemctl='systemctl', runner=run, timeout=120, unit_dir=None):
    base = Path(base).resolve()
    candidate, version = staged(candidate, base)
    current = base / 'current'
    previous = current.resolve() if current.is_symlink() else None
    if previous is not None:
        staged(previous, base)
    if current.exists() and not current.is_symlink():
        raise ValueError('Current release pointer is not a symlink.')
    shared = base / 'shared'
    if not (shared / '.env').is_file():
        raise ValueError('Create shared/.env before activation.')
    database = shared / 'data/rumble.sqlite3'
    runner([systemctl, 'stop', SERVICE], timeout=150)
    try:
        if database.exists():
            directory = shared / 'backups'
            directory.mkdir(exist_ok=True)
            if os.geteuid() == 0 and directory.stat().st_uid != 0:
                runner(['runuser', '-u', 'rumble', '--', candidate / '.venv/bin/python', '-m',
                        'rumble.maintenance', 'backup', '--db', database, '--directory', directory], cwd=candidate)
            else:
                backup_database(database, directory)
        link_to(current, candidate)
        if unit_dir is not None:
            install_units(candidate, base, unit_dir, systemctl, runner)
        (shared / 'data/health.json').unlink(missing_ok=True)
        runner([systemctl, 'start', SERVICE], timeout=150)
        wait_ready(base, version, systemctl, runner, timeout)
    except BaseException:
        runner([systemctl, 'stop', SERVICE], timeout=150)
        if previous is not None:
            link_to(current, previous)
            if unit_dir is not None:
                install_units(previous, base, unit_dir, systemctl, runner)
            (shared / 'data/health.json').unlink(missing_ok=True)
            runner([systemctl, 'start', SERVICE], timeout=150)
            # A failed recovery is reported too. Database/config remain untouched.
            wait_ready(base, verify(previous)['version'], systemctl, runner, timeout)
        else:
            current.unlink(missing_ok=True)
        raise
    if previous is not None and previous != candidate:
        link_to(base / 'previous', previous)
    return candidate


def rollback_release(base, systemctl='systemctl', runner=run, timeout=120, unit_dir=None):
    previous = Path(base) / 'previous'
    if not previous.is_symlink():
        raise ValueError('No previous release is available.')
    return activate_release(previous.resolve(), base, systemctl, runner, timeout, unit_dir)


def prepare_install(source, base, unit_dir=Path('/etc/systemd/system'), runner=run, systemctl='systemctl'):
    base, source, unit_dir = Path(base).resolve(), Path(source).resolve(), Path(unit_dir)
    if not (base / 'current').exists() and ((base / 'bot.py').exists() or (base / 'data/rumble.sqlite3').exists()):
        raise ValueError('Legacy installation detected. Stop and preserve it, then follow docs/DEPLOYMENT.md migration before install.')
    try:
        account = pwd.getpwnam('rumble')
    except KeyError:
        runner(['useradd', '--system', '--user-group', '--home-dir', str(base), '--no-create-home', 'rumble'])
        account = pwd.getpwnam('rumble')
    base.mkdir(parents=True, exist_ok=True)
    shared = base / 'shared'
    shared.mkdir(exist_ok=True)
    shared.chmod(0o750)
    os.chown(shared, 0, account.pw_gid)
    for part in ('data', 'logs', 'backups'):
        path = shared / part
        path.mkdir(exist_ok=True)
        path.chmod(0o700)
        os.chown(path, account.pw_uid, account.pw_gid)
    env = shared / '.env'
    if not env.exists():
        shutil.copy2(source / '.env.example', env)
    env.chmod(0o640)
    os.chown(env, 0, account.pw_gid)
    install_units(source, base, unit_dir, systemctl, runner)
    return env


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=Path('/opt/ripcars-rumble'))
    parser.add_argument('--systemctl', default='systemctl')
    parser.add_argument('--unit-dir', type=Path, default=Path('/etc/systemd/system'))
    parser.add_argument('--timeout', type=float, default=120)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('stage', 'install'):
        item = sub.add_parser(action)
        item.add_argument('source', type=Path)
    sub.add_parser('apply').add_argument('candidate', type=Path)
    sub.add_parser('rollback')
    args = parser.parse_args(argv)
    try:
        with offline_lock(args.base / '.deploy', 'Another deployment is active.'):
            if args.action == 'stage':
                result = stage_release(args.source, args.base)
            elif args.action == 'install':
                if os.geteuid() != 0:
                    raise ValueError('Installation requires root for service and account setup.')
                result = stage_release(args.source, args.base)
                environment = prepare_install(args.source, args.base, args.unit_dir, systemctl=args.systemctl)
                print('Edit ' + str(environment) + ' and configure DISCORD_TOKEN, then apply ' + str(result))
            elif args.action == 'apply':
                result = activate_release(args.candidate, args.base, args.systemctl, timeout=args.timeout, unit_dir=args.unit_dir)
            else:
                result = rollback_release(args.base, args.systemctl, timeout=args.timeout, unit_dir=args.unit_dir)
        print(result)
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        # Do not print subprocess output: pip/service logs might contain configured credentials.
        print('FAILED: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
