import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class SSEManager:
    def __init__(self):
        self._queues: list[asyncio.Queue] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def broadcast(self, data: dict) -> None:
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._enqueue(data), self._loop)

    async def _enqueue(self, data: dict) -> None:
        for q in list(self._queues):
            await q.put(data)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue]:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.append(q)
        try:
            yield q
        finally:
            if q in self._queues:
                self._queues.remove(q)


sse_manager = SSEManager()
