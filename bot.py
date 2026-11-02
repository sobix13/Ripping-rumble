"""RipCars Rumble entry point.  python bot.py"""
import asyncio
import fcntl
import logging
import logging.handlers
import os
import signal
import sys

from rumble.bot import RumbleBot
from rumble.redaction import RedactingFormatter

HERE = os.path.dirname(os.path.abspath(__file__))


def acquire_instance_lock(db_path):
    """Manual and service runs using the same database share this process lock."""
    path = os.path.realpath(db_path) + ".lock"
    handle = open(path, "a+", encoding="utf-8")
    os.chmod(path, 0o600)
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("Another RipCars Rumble process already holds this database.") from None
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()) + "\n")
    handle.flush()
    return handle


def load_env(path):
    """Tiny .env reader (KEY=VALUE lines). Real environment variables win."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def setup_logging():
    level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    log_dir = os.environ.get("LOG_DIR", os.path.join(HERE, "logs"))
    os.makedirs(log_dir, exist_ok=True)
    fmt = RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    fh = logging.handlers.RotatingFileHandler(os.path.join(log_dir, "rumble.log"), maxBytes=2_000_000,
                                              backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(sh)
    root.addHandler(fh)
    logging.getLogger("discord").setLevel(logging.WARNING)


def main():
    os.umask(0o077)
    load_env(os.path.join(HERE, ".env"))
    setup_logging()
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        print("DISCORD_TOKEN is missing. Copy .env.example to .env and paste the bot token.", file=sys.stderr)
        return 2
    db_path = os.environ.get("DB_PATH", os.path.join(HERE, "data", "rumble.sqlite3"))
    if not os.path.isabs(db_path):
        db_path = os.path.join(HERE, db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    try:
        instance_lock = acquire_instance_lock(db_path)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 3
    dev = os.environ.get("DEV_GUILD_ID", "").strip()
    bot = RumbleBot(db_path, dev_guild_id=int(dev) if dev.isdigit() else None)
    try:
        asyncio.run(run(bot, token))
    except KeyboardInterrupt:
        pass
    finally:
        instance_lock.close()
    return 0


async def run(bot, token):
    """Start the bot and close it cleanly on SIGTERM (systemctl stop/restart) or Ctrl+C, so running rumbles
    get a proper notice and the database is closed."""
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    async with bot:
        starter = asyncio.create_task(bot.start(token))
        waiter = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait({starter, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if waiter in done:
            logging.getLogger("rumble").info("shutdown signal received, closing")
            await bot.close()
        else:
            waiter.cancel()
        try:
            await starter
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    sys.exit(main())
