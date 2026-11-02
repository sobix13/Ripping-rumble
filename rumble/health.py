"""Local health endpoint, atomic readiness file and systemd notification."""
import asyncio
import json
import logging
import os
from pathlib import Path
import socket
import tempfile
import time

from . import __version__

log = logging.getLogger('rumble.health')


def notify_systemd(message):
    address = os.environ.get('NOTIFY_SOCKET')
    if not address:
        return False
    if address.startswith('@'):
        address = '\0' + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(message.encode(), address)
        return True
    except OSError:
        return False


def atomic_health(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.health-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(payload, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class HealthMonitor:
    def __init__(self, bot, path, port=8093):
        self.bot, self.path, self.port = bot, Path(path), port
        self.server = self.task = None
        self.write_task = None
        self.ready_notified = False
        self.status = dict(ok=False, version=__version__, pid=os.getpid(), updated_at=0, checks={})

    async def sample(self):
        now = time.time()
        try:
            database = bool(await asyncio.wait_for(self.bot.db.ping(), 3))
        except Exception:
            database = False
        cog = self.bot.get_cog('RumbleCog')
        checks = dict(discord=self.bot.is_ready() and not self.bot.closing, database=database)
        for key, age in (('scheduler', 120), ('roles', 900)):
            loop = getattr(cog, key + '_loop', None)
            checks[key] = bool(loop and loop.is_running() and self.bot.loop_success.get(key, 0) > now - age)
        self.status = dict(ok=all(checks.values()), version=__version__, pid=os.getpid(),
                           updated_at=now, checks=checks)
        self.bot.health_status = self.status
        self.write_task = asyncio.create_task(asyncio.to_thread(atomic_health, self.path, self.status))
        await asyncio.shield(self.write_task)
        if self.status['ok'] and not self.ready_notified:
            notify_systemd('READY=1\nSTATUS=Rumble is ready')
            self.ready_notified = True
        if self.ready_notified and database and checks['scheduler'] and checks['roles']:
            notify_systemd('WATCHDOG=1')
        return self.status

    async def start(self):
        self.server = await asyncio.start_server(self.handle, '127.0.0.1', self.port, limit=4096)
        self.port = self.server.sockets[0].getsockname()[1]
        self.task = asyncio.create_task(self.run(), name='rumble-health')

    async def run(self):
        while not self.bot.closing:
            try:
                await self.sample()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.status = dict(self.status, ok=False)
                self.bot.health_status = self.status
                self.bot.record_error(0, f'Health check failed: {type(error).__name__}')
            try:
                await self.bot.flush_error_reports()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log.warning('Private report check failed: %s', type(error).__name__)
            await asyncio.sleep(15)

    async def handle(self, reader, writer):
        try:
            request = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 2)
            allowed = request.split(b'\r\n', 1)[0] in (b'GET /healthz HTTP/1.1', b'GET /healthz HTTP/1.0')
            fresh = time.time() - self.status['updated_at'] <= 45
            status = 200 if self.status['ok'] and fresh else 503
            if not allowed:
                status = 404
            payload = self.status if allowed else {'ok': False}
            if allowed and not fresh:
                payload = dict(payload, ok=False)
            data = json.dumps(payload).encode()
            reason = {200: 'OK', 503: 'Service Unavailable', 404: 'Not Found'}[status]
            writer.write(f'HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\nConnection: close\r\n\r\n'.encode() + data)
            await writer.drain()
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        if self.write_task:
            await asyncio.gather(self.write_task, return_exceptions=True)
        self.status = dict(self.status, ok=False, updated_at=time.time())
        self.bot.health_status = self.status
        try:
            await asyncio.to_thread(atomic_health, self.path, self.status)
        except OSError:
            pass
        finally:
            notify_systemd('STOPPING=1')
