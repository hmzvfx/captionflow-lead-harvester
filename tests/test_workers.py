import asyncio

import pytest

from captionflow_harvester.runtime.workers import bounded_map


@pytest.mark.asyncio
async def test_bounded_workers_return_results_and_isolate_failures():
    async def worker(value: int):
        await asyncio.sleep(0)
        if value == 2:
            raise RuntimeError("boom")
        return value * 2

    results = await bounded_map([1, 2, 3], worker, concurrency=2)
    assert results[0] == 2
    assert isinstance(results[1], RuntimeError)
    assert results[2] == 6
