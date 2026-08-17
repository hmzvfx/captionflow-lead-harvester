from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import defaultdict
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from .budget import RequestBudget
from .metrics import RunMetrics

log = logging.getLogger(__name__)


class NetworkError(RuntimeError):
    pass


class AsyncHttpClient:
    def __init__(self, *, budget: RequestBudget, metrics: RunMetrics, timeout: float, user_agent: str, max_bytes: int, per_host_delay: float, concurrency: int = 20) -> None:
        self.budget = budget
        self.metrics = metrics
        self.max_bytes = max_bytes
        self.per_host_delay = per_host_delay
        self._sem = asyncio.Semaphore(max(1, concurrency))
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept": "text/html,application/json,application/xml,text/xml,*/*;q=0.5"},
            limits=httpx.Limits(max_connections=max(10, concurrency), max_keepalive_connections=max(5, concurrency // 2)),
        )
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_request: dict[str, float] = defaultdict(float)
        self._host_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def __aenter__(self) -> "AsyncHttpClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def _pace(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        async with self._host_locks[host]:
            elapsed = time.monotonic() - self._last_request[host]
            delay = self.per_host_delay - elapsed
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request[host] = time.monotonic()

    async def _raw_get(self, url: str, *, params: dict | None = None, budget_name: str, retries: int = 3) -> httpx.Response:
        if not self.budget.try_consume(budget_name):
            raise NetworkError(f"request budget exhausted: {budget_name}")
        if budget_name == "web_requests":
            self.metrics.web_requests += 1
        elif budget_name == "youtube_requests":
            self.metrics.youtube_requests += 1

        async with self._sem:
            for attempt in range(retries + 1):
                try:
                    await self._pace(url)
                    response = await self._client.get(url, params=params)
                    if response.status_code == 429:
                        self.metrics.http_429_count += 1
                    if response.status_code == 429 or 500 <= response.status_code < 600:
                        if attempt >= retries:
                            response.raise_for_status()
                        self.metrics.retry_count += 1
                        retry_after = response.headers.get("Retry-After")
                        try:
                            wait = float(retry_after) if retry_after else min(8.0, (2 ** attempt) + random.random())
                        except ValueError:
                            wait = min(8.0, (2 ** attempt) + random.random())
                        await asyncio.sleep(wait)
                        continue
                    response.raise_for_status()
                    return response
                except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                    if attempt >= retries:
                        raise NetworkError(f"GET failed for {url}: {type(exc).__name__}") from exc
                    self.metrics.retry_count += 1
                    await asyncio.sleep(min(8.0, (2 ** attempt) + random.random()))
        raise NetworkError(f"GET failed for {url}")

    async def _robots_allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            return False
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            robots_url = urljoin(origin + "/", "robots.txt")
            try:
                response = await self._raw_get(robots_url, budget_name="web_requests", retries=1)
                parser = RobotFileParser()
                parser.set_url(robots_url)
                parser.parse(response.text.splitlines())
                self._robots[origin] = parser
            except NetworkError:
                self._robots[origin] = None
        parser = self._robots[origin]
        return True if parser is None else parser.can_fetch(self._client.headers.get("User-Agent", "*"), url)

    async def get_text(self, url: str, *, respect_robots: bool = True) -> tuple[str, str, str]:
        if respect_robots and not await self._robots_allowed(url):
            raise NetworkError(f"robots.txt disallows: {url}")
        response = await self._raw_get(url, budget_name="web_requests")
        content_length = response.headers.get("Content-Length")
        if content_length and content_length.isdigit() and int(content_length) > self.max_bytes:
            raise NetworkError(f"response too large: {url}")
        body = response.content
        if len(body) > self.max_bytes:
            raise NetworkError(f"response too large: {url}")
        return response.text, str(response.url), response.headers.get("Content-Type", "")

    async def get_json(self, url: str, *, params: dict | None = None, youtube_search: bool = False) -> dict:
        if youtube_search:
            if not self.budget.try_consume("youtube_search_requests"):
                raise NetworkError("request budget exhausted: youtube_search_requests")
            self.metrics.youtube_search_requests += 1
        response = await self._raw_get(url, params=params, budget_name="youtube_requests")
        try:
            return response.json()
        except ValueError as exc:
            raise NetworkError(f"invalid JSON from {url}") from exc
