"""Background auto-scan loop."""

import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)


class AutoScanManager:
    def __init__(self, interval_seconds: int, scan_callback: Callable[[], dict]):
        self.interval_seconds = interval_seconds
        self._scan_callback = scan_callback
        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def enabled(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Auto-scan started (interval=%ss)", self.interval_seconds)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Auto-scan stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.to_thread(self._scan_callback)
            except Exception:
                logger.exception("Auto-scan iteration failed")
            try:
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                break

    def update_interval(self, seconds: int) -> None:
        self.interval_seconds = max(10, seconds)
