"""Check the declared GitHub release for runtime files, credentials and English-only source/docs."""
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.verify_release import verify


def check(root):
    root = Path(root)
    manifest = verify(root)
    issues = []
    for name in manifest['files']:
        path = Path(name)
        if ((path.name.startswith('.env') and path.name != '.env.example')
                or set(path.parts) & {'data', 'logs', 'backups', '.venv', '__pycache__', '.git'}
                or path.suffix in {'.sqlite3', '.db', '.pyc', '.pem', '.key'}):
            issues.append(name + ': private runtime file')
        if path.suffix not in {'.py', '.md', '.txt', '.json', '.csv', '.yml', '.yaml', '.sh'} and path.name != '.env.example':
            continue
        text = (root / path).read_text(encoding='utf-8')
        if re.search(r'[\u0600-\u06ff]', text):
            issues.append(name + ': non-English source or documentation')
        credential = (r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|'
                      r'\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bmfa\.[A-Za-z0-9_-]{30,}|'
                      r'\b[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{25,}\b')
        if re.search(credential, text):
            issues.append(name + ': credential-shaped value')
    return issues


if __name__ == '__main__':
    problems = check(Path(sys.argv[1]) if len(sys.argv) > 1 else Path('.'))
    for problem in problems:
        print('FAILED: ' + problem)
    if problems:
        raise SystemExit(1)
    print('PASS: declared release excludes runtime state and credential-shaped values. Source/docs are English.')
