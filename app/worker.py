"""Worker interno (asyncio, un solo processo). Compiti automatici: backup, consegna webhook e avvisi
(garanzie in scadenza, promemoria manutenzioni), che non modificano dati di magazzino."""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy.orm import Session

from .services import alerts, backup, outbox
from .timeutil import local_zone

log = logging.getLogger("magazzino.worker")


class Worker:
    def __init__(self, app):
        self.app = app
        self.jobs: list[tuple[float, Callable[[], Awaitable[None]]]] = [
            (60.0, self.backup_job),
            (5.0, self.outbox_job),
            (86400.0, self.purge_job),
            (3600.0, self.alerts_job),
        ]

    async def outbox_job(self) -> None:
        await outbox.deliver_due(self.app.state.engine, self.app.state.http)

    async def alerts_job(self) -> None:
        def go():
            with Session(self.app.state.engine) as db:
                return alerts.run(db, self.app.state.settings.app_name)
        await asyncio.to_thread(go)

    async def purge_job(self) -> None:
        await asyncio.to_thread(outbox.purge_old, self.app.state.engine)

    async def backup_job(self) -> None:
        now_local = datetime.now(local_zone()).replace(tzinfo=None)
        path = await asyncio.to_thread(backup.daily_backup, self.app.state.settings, now_local)
        if path:
            log.info("Backup giornaliero: %s", path)

    async def _loop(self, interval: float, job, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await job()
            except Exception:  # un errore non deve fermare il worker
                log.exception("Errore nel job %s", getattr(job, "__name__", job))
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except TimeoutError:
                pass

    async def run(self, stop: asyncio.Event) -> None:
        await asyncio.gather(*(self._loop(i, j, stop) for i, j in self.jobs))
