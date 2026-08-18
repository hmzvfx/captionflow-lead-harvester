from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

from .config import Config
from .enrichment.instagram import find_instagram_from_email
from .persistence.sheets import SheetRepository, SheetStateStore
from .runtime.budget import RequestBudget
from .runtime.metrics import RunMetrics
from .runtime.network import AsyncHttpClient


def _cache_is_fresh(entry: dict, now: datetime) -> bool:
    if not entry:
        return False
    if entry.get("url"):
        return True
    checked = str(entry.get("checked_at", ""))
    try:
        checked_at = datetime.fromisoformat(checked)
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=UTC)
        return now - checked_at <= timedelta(days=7)
    except (TypeError, ValueError):
        return False


async def run_backfill() -> dict:
    config = Config.from_env()
    if not config.google_spreadsheet_id:
        raise ValueError("GOOGLE_SPREADSHEET_ID is required")

    limit = max(1, int(os.getenv("MAX_INSTAGRAM_BACKFILL_PER_RUN", "100")))
    repository = SheetRepository(config.google_spreadsheet_id)
    repository.bootstrap()
    state = SheetStateStore(repository)
    cache = dict(state.get("instagram_lookup_cache", {}) or {})
    rows = repository.client.values_get("'LEADS'!A2:Z")
    padded_rows = [list(row) + [""] * max(0, 26 - len(row)) for row in rows]

    now = datetime.now(UTC)
    now_iso = now.replace(microsecond=0).isoformat()
    metrics = RunMetrics(run_id=f"instagram-backfill-{now.strftime('%Y%m%dT%H%M%SZ')}", started_at=now_iso)
    budget = RequestBudget({"web_requests": max(200, limit * 3)})

    eligible: list[tuple[int, list]] = []
    for index, row in enumerate(padded_rows):
        email = str(row[9]).strip()
        email_status = str(row[10]).strip()
        instagram_url = str(row[23]).strip()
        if not email or email_status != "VERIFIED_PUBLIC_SOURCE" or instagram_url:
            continue
        cached = cache.get(email, {})
        if _cache_is_fresh(cached, now):
            if cached.get("url"):
                row[23] = str(cached.get("url", ""))
                row[24] = str(cached.get("status", "FOUND_SEARCH_RESULT"))
                row[25] = str(cached.get("query", ""))
            continue
        eligible.append((index, row))
        if len(eligible) >= limit:
            break

    async with AsyncHttpClient(
        budget=budget,
        metrics=metrics,
        timeout=config.http_timeout_seconds,
        user_agent=config.user_agent,
        max_bytes=config.max_page_bytes,
        per_host_delay=config.per_host_delay_seconds,
        concurrency=min(config.worker_count, 20),
    ) as http:
        for _, row in eligible:
            email = str(row[9]).strip()
            metrics.instagram_lookups += 1
            lookup = await find_instagram_from_email(
                http,
                email=email,
                lead_name=str(row[4]).strip(),
                lead_username=str(row[5]).strip(),
            )
            row[23] = lookup.url
            row[24] = lookup.status
            row[25] = lookup.query
            if lookup.url:
                metrics.instagram_found += 1
            cache[email] = {
                "url": lookup.url,
                "status": lookup.status,
                "query": lookup.query,
                "confidence": lookup.confidence,
                "checked_at": now_iso,
            }

    # Single non-destructive table rewrite after the current harvest job has finished.
    repository.client.values_clear("'LEADS'!A2:Z")
    if padded_rows:
        repository.client.values_update("'LEADS'!A2", padded_rows)
    repository.refresh_views(padded_rows)
    state.set("instagram_lookup_cache", cache)
    state.flush()

    metrics.finish()
    report = metrics.to_dict()
    report.update({
        "eligible_rows": len(eligible),
        "total_rows": len(padded_rows),
        "mode": "INSTAGRAM_EMAIL_LOCALPART_SEARCH_BACKFILL",
    })
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> int:
    try:
        asyncio.run(run_backfill())
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
