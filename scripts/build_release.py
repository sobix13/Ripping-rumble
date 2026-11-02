"""Build a reproducible source manifest. Runtime files are never release inputs."""
import argparse
import hashlib
import json
from pathlib import Path

EXCLUDED_DIRS = {'.git', '.venv', 'venv', '.pytest_cache', '__pycache__', 'data', 'logs', 'backups'}


def build(root):
    root = Path(root).resolve()
    files = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if set(relative.parts) & EXCLUDED_DIRS or not path.is_file():
            continue
        name = relative.as_posix()
        if name in {'RELEASE_MANIFEST.json', 'bank_export.json', 'STAGED_OK.json'}:
            continue
        if path.name.startswith('.env') and path.name != '.env.example':
            continue
        if path.suffix in {'.pyc', '.sqlite3', '.db', '.lock', '.zip', '.bundle'}:
            continue
        if path.is_symlink():
            raise ValueError('Release source contains a symlink: ' + name)
        data = path.read_bytes()
        files[name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    scope = {}
    exec((root / 'rumble/__init__.py').read_text(), scope)
    result = dict(version=scope['__version__'], files=files)
    (root / 'RELEASE_MANIFEST.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', nargs='?', default='.', type=Path)
    args = parser.parse_args()
    manifest = build(args.root)
    print(f"Built {manifest['version']}: {len(manifest['files'])} source files")
