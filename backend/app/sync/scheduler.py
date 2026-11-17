"""Run the catalogue sync on a timer inside the API process.

Turned on by SYNC_INTERVAL_HOURS. The time of the last finished run is read
from the database, so restarting the server (which `--reload` does often)
does not trigger an extra run.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import timedelta

from sqlalchemy import select

from ..config import Settings
from ..db import SessionLocal
from ..models import SyncRun, utcnow
from .catalogue import run_sync

log = logging.getLogger(__name__)
STARTUP_DELAY_SECONDS = 30
RETRY_AFTER_FAILURE = timedelta(hours=1)


def seconds_until_due(interval_hours: float) -> float:
    """Wait a full interval after a good run, but only an hour after a failed one."""
    finished = SyncRun.finished_at.is_not(None)
    with SessionLocal() as db:
        last_any = db.scalar(
            select(SyncRun.finished_at)
            .where(finished)
            .order_by(SyncRun.finished_at.desc())
            .limit(1)
        )
        last_ok = db.scalar(
            select(SyncRun.finished_at)
            .where(finished, (SyncRun.error == "") | (SyncRun.added > 0))
            .order_by(SyncRun.finished_at.desc())
            .limit(1)
        )
    if last_any is None:
        return 0.0
    due = last_any + RETRY_AFTER_FAILURE
    if last_ok is not None:
        due = max(due, last_ok + timedelta(hours=interval_hours))
    return max(0.0, (due - utcnow()).total_seconds())


def _run_once(settings: Settings, stop: threading.Event) -> None:
    with SessionLocal() as db:
        report = run_sync(db, settings, trigger="schedule", should_stop=stop.is_set)
    log.info("Scheduled catalogue sync finished: %s", report.summary())


async def run_forever(settings: Settings, stop: threading.Event) -> None:
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while not stop.is_set():
        wait = seconds_until_due(settings.sync_interval_hours)
        if wait > 0:
            await asyncio.sleep(min(wait, 3600))  # re-check hourly
            continue
        try:
            await asyncio.to_thread(_run_once, settings, stop)
        except Exception:
            log.exception("Scheduled catalogue sync failed; will try again next interval")
            await asyncio.sleep(min(settings.sync_interval_hours * 3600, 3600))


class Scheduler:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.stop = threading.Event()
        self.task: asyncio.Task | None = None

    def start(self) -> None:
        if self.settings.sync_interval_hours > 0:
            log.info("Catalogue sync scheduled every %s hours", self.settings.sync_interval_hours)
            self.task = asyncio.create_task(run_forever(self.settings, self.stop))

    async def shutdown(self) -> None:
        self.stop.set()  # a run in progress finishes its current book, then stops
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
