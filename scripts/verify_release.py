"""Verify every declared release file before installation."""
import hashlib
import json
from pathlib import Path
import re
import sys


def verify(root):
    root = Path(root).resolve()
    manifest = json.loads((root / 'RELEASE_MANIFEST.json').read_text())
    version = manifest['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:[a-zA-Z0-9.-]*)', version):
        raise ValueError('Invalid release version.')
    files = manifest['files']
    required = {'bot.py', 'requirements.txt', 'requirements-dev.txt', 'rumble/__init__.py'}
    if not required <= files.keys():
        raise ValueError('Release manifest is missing required files.')
    for name, expected in files.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or name == 'RELEASE_MANIFEST.json':
            raise ValueError('Unsafe release path.')
        path = root / relative
        if any(part.is_symlink() for part in (path, *path.parents) if part != root.parent):
            raise ValueError('Release files must not be symlinks.')
        if root not in path.resolve().parents or not path.is_file():
            raise ValueError('Release file is missing or outside source.')
        data = path.read_bytes()
        if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise ValueError('Release file failed hash verification: ' + name)
    version_source = (root / 'rumble/__init__.py').read_text()
    if not re.search(r'__version__\s*=\s*[\'\"]' + re.escape(version) + r'[\'\"]', version_source):
        raise ValueError('Package and manifest versions differ.')
    return manifest


if __name__ == '__main__':
    try:
        result = verify(sys.argv[1] if len(sys.argv) > 1 else '.')
        print('Verified ' + result['version'] + ': ' + str(len(result['files'])) + ' files')
    except (ValueError, KeyError, OSError) as error:
        print('FAILED: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
