"""Dedicated service. No Docker API, shell, public TCP port or request metadata."""
import asyncio
import logging
import os
import socket
import stat
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from radioflix.timefree.bootstrap import ProductionBootstrap
from radioflix.timefree.preflight import Preflight
from radioflix.timefree.publisher import job_id
from radioflix.timefree.service import live_gate
from radioflix.timefree.store import TimefreeStore
from radioflix.timefree.worker import TimefreeWorker


class Dispatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    job_id: str = Field(pattern=r'^[a-f0-9]{32}$')


class Controller:
    def __init__(self, worker, *, gate=live_gate):
        self.worker, self.gate = worker, gate
        self.wake = threading.Event()
        self.notify_loop = None

    def dispatch(self, ident):
        job_id(ident)
        if not self.gate():
            raise HTTPException(409, detail={'code': 'writes_disabled'})
        if self.worker.read_only:
            raise HTTPException(409, detail={'code': 'boot_mode_disabled'})
        if not getattr(self.worker.transport, 'ready', False):
            raise HTTPException(503, detail={'code': 'capture_unavailable'})
        row = self.worker.store.get(ident)
        if row is None:
            raise HTTPException(404, detail={'code': 'not_found'})
        if row['execution_kind'] != self.worker.transport.kind:
            raise HTTPException(409, detail={'code': 'execution_kind'})
        # Persist only an ID, not a second copy of metadata or a command.
        with self.worker.store.transaction() as db:
            db.execute('''INSERT OR IGNORE INTO timefree_dispatches
                SELECT job_id FROM timefree_jobs WHERE job_id=? AND state='queued' AND execution_kind=?''',
                (ident, self.worker.transport.kind))
        self.wake.set()
        if self.notify_loop is not None:
            self.notify_loop()
        return {'job_id': ident, 'accepted': True}

    def tick(self):
        if not self.gate() or self.worker.read_only:
            return None
        self.worker.reconcile()
        if not getattr(self.worker.transport, 'ready', False):
            return None
        for ident in self.worker.store.pending_dispatches():
            row = self.worker.store.get(ident)
            if row and row['state'] == 'queued' and row['execution_kind'] == self.worker.transport.kind:
                return self.worker.run_once(ident)
            with self.worker.store.transaction() as db:
                db.execute('DELETE FROM timefree_dispatches WHERE job_id=?', (ident,))
        return None


def create_app(controller):
    @asynccontextmanager
    async def lifespan(app):
        if controller.gate() and not controller.worker.read_only:
            await asyncio.to_thread(controller.worker.reconcile)
        stopped = asyncio.Event()
        wakeup = asyncio.Event()
        event_loop = asyncio.get_running_loop()
        controller.notify_loop = lambda: event_loop.call_soon_threadsafe(wakeup.set)

        async def loop():
            while not stopped.is_set():
                controller.wake.clear()
                try:
                    await asyncio.to_thread(controller.tick)
                except Exception:
                    logging.getLogger(__name__).error('timefree worker cycle failed')
                if stopped.is_set():
                    break
                wakeup.clear()
                try:
                    await asyncio.wait_for(wakeup.wait(), timeout=5)
                except TimeoutError:
                    pass
        task = asyncio.create_task(loop())
        try:
            yield
        finally:
            stopped.set()
            controller.wake.set()
            wakeup.set()
            # One worker per service. The worker holds a file lock until the
            # thread exits; a forced container stop is handled by reconcile.
            await task

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.controller = controller

    @app.get('/health')
    def health():
        gate = controller.gate()
        enabled = bool(gate and not controller.worker.read_only)
        reason = (None if enabled else 'writes_disabled' if not gate else
                  'capture_unavailable' if not getattr(controller.worker.transport, 'ready', False) else
                  'boot_mode_disabled')
        return {'capture_ready': bool(getattr(controller.worker.transport, 'ready', False)),
                'writes_enabled': enabled,
                'boot_mode': 'enabled' if enabled else 'disabled_read_only',
                'reason': reason}

    @app.get('/status')
    def status():
        # Read-only boot intentionally avoids opening a write transaction or
        # creating the Timefree schema when inspecting an existing DB.
        return {'boot_mode': 'enabled' if controller.gate() and not controller.worker.read_only
                else 'disabled_read_only',
                'job_count': len(controller.worker.store.list())}

    @app.post('/dispatch', status_code=202)
    def dispatch(request: Dispatch):
        return controller.dispatch(request.job_id)

    return app


def production_app():
    capture = ProductionBootstrap(source_root=Path(os.getenv('RADIOFLIX_TIMEFREE_SOURCE_ROOT', '/rfriends-source')),
                                  manifest=Path(__file__).with_name('bootstrap-source-manifest.json'))
    requested_mode = os.getenv('RADIOFLIX_TIMEFREE_BOOT_MODE', 'disabled')
    if requested_mode not in ('disabled', 'enabled'):
        requested_mode = 'disabled'
    can_write = (requested_mode == 'enabled' and live_gate() and
                 capture.ready is True and capture.bridge_approved is True)
    store = TimefreeStore(os.getenv('RADIOFLIX_DB_PATH', '/data/radioflix.sqlite3'),
                          read_only=not can_write)
    root = Path(os.getenv('RADIOFLIX_TIMEFREE_ROOT', '/timefree'))
    guard = Preflight(store, '/native-reservations', ['/recordings', '/native-timefree'], root)
    return create_app(Controller(TimefreeWorker(store, root, capture, preflight=guard,
                                                read_only=not can_write)))


def main():
    import uvicorn
    os.umask(0o007)
    socket_path = Path(os.getenv('RADIOFLIX_TIMEFREE_SOCKET', '/run/timefree/control.sock'))
    directory = socket_path.parent
    prepare_socket_directory(directory)
    prepare_socket_path(socket_path)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    identity = None
    try:
        listener.bind(str(socket_path))
        secure_socket_permissions(socket_path)
        listener.listen(2048)
        created = socket_path.lstat()
        identity = (created.st_dev, created.st_ino)
        server = uvicorn.Server(uvicorn.Config(production_app(),
                                               access_log=False, log_level='warning', workers=1))
        server.run(sockets=[listener])
    finally:
        listener.close()
        if identity is not None:
            try:
                current = socket_path.lstat()
                if (stat.S_ISSOCK(current.st_mode) and current.st_uid == os.geteuid() and
                        (current.st_dev, current.st_ino) == identity):
                    socket_path.unlink()
            except FileNotFoundError:
                pass


def prepare_socket_directory(directory):
    directory = Path(directory)
    if directory.is_symlink():
        raise RuntimeError('socket_directory_invalid')
    directory.mkdir(mode=0o770, parents=True, exist_ok=True)
    info = directory.stat(follow_symlinks=False)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or
            info.st_gid != os.getegid() or stat.S_IMODE(info.st_mode) != 0o770):
        raise RuntimeError('socket_directory_permissions')
    return directory


def prepare_socket_path(path):
    """Remove only an owned stale socket; refuse active or foreign paths."""
    import errno
    import stat
    path = Path(path)
    try:
        before = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(before.st_mode) or before.st_uid != os.geteuid():
        raise RuntimeError('socket_path_invalid')
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        try:
            probe.connect(str(path))
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ECONNREFUSED):
                raise RuntimeError('socket_path_active_or_unavailable') from None
        else:
            raise RuntimeError('socket_already_active')
    finally:
        probe.close()
    after = path.lstat()
    if (after.st_ino != before.st_ino or after.st_dev != before.st_dev or
            not stat.S_ISSOCK(after.st_mode) or after.st_uid != os.geteuid()):
        raise RuntimeError('socket_path_changed')
    path.unlink()


def secure_socket_permissions(path):
    """Restrict the live UDS to its owner and the shared backend group."""
    path = Path(path)
    info = path.lstat()
    if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid() or
            info.st_gid != os.getegid()):
        raise RuntimeError('socket_permissions')
    os.chmod(path, 0o660, follow_symlinks=False)
    secured = path.lstat()
    if (not stat.S_ISSOCK(secured.st_mode) or secured.st_uid != os.geteuid() or
            secured.st_gid != os.getegid() or stat.S_IMODE(secured.st_mode) != 0o660):
        raise RuntimeError('socket_permissions')


if __name__ == '__main__':
    main()
