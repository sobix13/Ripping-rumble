"""Offline confirmation of an uncertain Discord delivery. Stop the service first."""
import argparse
import fcntl
import sqlite3
from pathlib import Path
from urllib.parse import quote


def reconcile(db_path, action, game_id=None, message_id=None, schedule_id=None, occurrence=None):
    path = Path(db_path).resolve(strict=True)
    with open(str(path) + '.lock', 'a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Stop the bot before reconciling delivery records.') from None
        with sqlite3.connect('file:' + quote(str(path), safe='/') + '?mode=rw', uri=True) as conn:
            if action == 'release-schedule':
                row = conn.execute('SELECT status FROM schedule_occurrences WHERE schedule_id=? AND occurrence_at=?',
                                   (schedule_id, occurrence)).fetchone()
                if row is None or row[0] != 'unknown':
                    raise ValueError('Only an uncertain startup is eligible for explicit release.')
                conn.execute("DELETE FROM schedule_occurrences WHERE schedule_id=? AND occurrence_at=? AND status='unknown'",
                             (schedule_id, occurrence))
            else:
                row = conn.execute('SELECT announcement_message_id FROM game_results WHERE game_id=?', (game_id,)).fetchone()
                if row is None:
                    raise ValueError('No committed result exists for that game.')
                if row[0] is not None:
                    raise ValueError('That result already has a confirmed announcement.')
                if action == 'confirm-announcement':
                    if not message_id or message_id <= 0:
                        raise ValueError('A positive Discord message ID is required.')
                    conn.execute("UPDATE game_results SET announcement_state='sent',announcement_message_id=?,delivery_error=NULL WHERE game_id=?",
                                 (message_id, game_id))
                elif action == 'retry-announcement':
                    conn.execute("UPDATE game_results SET announcement_state='pending',delivery_error=NULL WHERE game_id=?", (game_id,))
                else:
                    raise ValueError('Unknown reconciliation action.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    commands = parser.add_subparsers(dest='action', required=True)
    confirm = commands.add_parser('confirm-announcement')
    confirm.add_argument('--game', type=int, required=True)
    confirm.add_argument('--message-id', type=int, required=True)
    retry = commands.add_parser('retry-announcement')
    retry.add_argument('--game', type=int, required=True)
    retry.add_argument('--confirmed-not-sent', action='store_true', required=True)
    release = commands.add_parser('release-schedule')
    release.add_argument('--schedule', type=int, required=True)
    release.add_argument('--occurrence', type=int, required=True)
    release.add_argument('--confirmed-no-lobby', action='store_true', required=True)
    args = parser.parse_args()
    try:
        reconcile(args.db, args.action, getattr(args, 'game', None), getattr(args, 'message_id', None),
                  getattr(args, 'schedule', None), getattr(args, 'occurrence', None))
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        parser.exit(1, str(error) + '\n')
    print('Confirmation saved. Restart the bot to process pending work. Stats were not recounted.')


if __name__ == '__main__':
    main()
