from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


async def bounded_map(items: Iterable[T], worker: Callable[[T], Awaitable[R]], concurrency: int) -> list[R | Exception]:
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def run(item: T) -> R:
        async with semaphore:
            return await worker(item)

    return await asyncio.gather(*(run(item) for item in items), return_exceptions=True)
