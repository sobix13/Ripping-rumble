"""Managed service entry point keeps credentials and mutable files outside releases."""
import os
from pathlib import Path
import runpy
import sys

base = Path(os.environ.get('RUMBLE_BASE', '/opt/ripcars-rumble')).resolve()
shared = base / 'shared'
os.environ.update(DB_PATH=str(shared / 'data/rumble.sqlite3'), LOG_DIR=str(shared / 'logs'),
                  RUMBLE_HEALTH_FILE=str(shared / 'data/health.json'), RUMBLE_BACKUP_DIR=str(shared / 'backups'))
# The service supplies the token through EnvironmentFile. Direct source runs use bot.py.
source = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(source))
runpy.run_path(str(source / 'bot.py'), run_name='__main__')
