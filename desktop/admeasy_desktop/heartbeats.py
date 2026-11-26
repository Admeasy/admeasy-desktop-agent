"""Progress heartbeats on long-running tool calls (keeps the backend tunnel from timing out)."""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

SendFn = Callable[[dict], Awaitable[None]]

DEFAULT_INTERVAL_S = 15.0


class HeartbeatRunner:
    def __init__(self, job_id: str, send: SendFn, interval_s: float = DEFAULT_INTERVAL_S):
        self.job_id = job_id
        self.send = send
        self.interval_s = max(5.0, float(interval_s))
        self._task: asyncio.Task | None = None
        self._started = time.monotonic()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval_s)
            await self.send(
                {
                    "type": "heartbeat",
                    "job_id": self.job_id,
                    "elapsed_s": round(time.monotonic() - self._started, 1),
                }
            )

    def start(self) -> None:
        if self._task is None:

            async def _kick() -> None:
                await self.send(
                    {
                        "type": "heartbeat",
                        "job_id": self.job_id,
                        "elapsed_s": 0.0,
                    }
                )

            asyncio.create_task(_kick())
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


async def run_with_heartbeat(
    job_id: str,
    send: SendFn,
    coro: Awaitable,
    *,
    interval_s: float = DEFAULT_INTERVAL_S,
):
    hb = HeartbeatRunner(job_id, send, interval_s)
    hb.start()
    try:
        return await coro
    finally:
        await hb.stop()