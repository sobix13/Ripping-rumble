import json

from scripts.build_release import build
from tools.check_release import check


def source(root):
    (root / 'rumble').mkdir()
    (root / 'rumble/__init__.py').write_text('__version__ = "1.2.0"\n')
    for name in ('bot.py', 'requirements.txt', 'requirements-dev.txt'):
        (root / name).write_text('')


def test_release_excludes_runtime_and_scans_declared_secrets(tmp_path):
    source(tmp_path)
    (tmp_path / '.env').write_text('DISCORD_TOKEN=not-for-release')
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/private.db').write_bytes(b'private')
    manifest = build(tmp_path)
    assert '.env' not in manifest['files'] and 'data/private.db' not in manifest['files']
    assert not check(tmp_path)
    (tmp_path / 'leak.txt').write_text('ghp_' + 'x' * 40)
    build(tmp_path)
    assert any('credential-shaped' in issue for issue in check(tmp_path))


def test_release_flags_non_english_source_documentation(tmp_path):
    source(tmp_path)
    (tmp_path / 'README.md').write_text('\u0646')
    build(tmp_path)
    assert any('non-English' in issue for issue in check(tmp_path))
