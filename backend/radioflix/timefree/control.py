"""Dedicated service. No Docker API, shell, public TCP port or request metadata."""
import asyncio
import logging
import os
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

    def dispatch(self, ident):
        job_id(ident)
        if not self.gate():
            raise HTTPException(409, detail={'code': 'writes_disabled'})
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
        return {'job_id': ident, 'accepted': True}

    def tick(self):
        self.worker.reconcile()  # Also checks completed files while capture is OFF.
        if not self.gate() or not getattr(self.worker.transport, 'ready', False):
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
        await asyncio.to_thread(controller.worker.reconcile)
        stopped = asyncio.Event()
        async def loop():
            while not stopped.is_set():
                controller.wake.clear()
                try:
                    await asyncio.to_thread(controller.tick)
                except Exception:
                    logging.getLogger(__name__).error('timefree worker cycle failed')
                await asyncio.to_thread(controller.wake.wait, 5)
        task = asyncio.create_task(loop())
        try:
            yield
        finally:
            stopped.set()
            controller.wake.set()
            # One worker per service. The worker holds a file lock until the
            # thread exits; a forced container stop is handled by reconcile.
            await task

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get('/health')
    def health():
        return {'capture_ready': bool(getattr(controller.worker.transport, 'ready', False)),
                'writes_enabled': controller.gate()}

    @app.post('/dispatch', status_code=202)
    def dispatch(request: Dispatch):
        return controller.dispatch(request.job_id)

    return app


def production_app():
    store = TimefreeStore(os.getenv('RADIOFLIX_DB_PATH', '/data/radioflix.sqlite3'))
    root = Path('/timefree')  # Fixed managed root, no request-selected paths.
    guard = Preflight(store, '/native-reservations', ['/recordings', '/native-timefree'], root)
    manifest = Path(__file__).with_name('bootstrap-source-manifest.json')
    capture = ProductionBootstrap(source_root=Path('/rfriends-source'), manifest=manifest)
    return create_app(Controller(TimefreeWorker(store, root, capture, preflight=guard)))


def main():
    import uvicorn
    os.umask(0o007)
    # Shared only with backend; socket directory mode 0770 protects access.
    directory = Path('/run/timefree')
    directory.mkdir(mode=0o770, parents=True, exist_ok=True)
    directory.chmod(0o770)
    uvicorn.run(production_app(), uds=str(directory / 'control.sock'),
                access_log=False, log_level='warning', workers=1)


if __name__ == '__main__':
    main()
