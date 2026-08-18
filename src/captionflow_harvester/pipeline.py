from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import Config
from .discovery.deduplication import deduplicate_candidates, stable_lead_id
from .enrichment.email import email_preference_score, extract_public_emails
from .enrichment.evidence import public_email_evidence
from .enrichment.instagram import find_instagram_from_email
from .enrichment.website import WebsiteEnricher
from .models import LeadRecord, UNKNOWN, utc_now_iso
from .persistence.sheets import SheetRepository, SheetStateStore
from .persistence.state import LocalJsonStateStore, StateStore
from .providers.base import ProviderContext
from .providers.public_web import PublicWebProvider
from .providers.rss import RSSProvider
from .providers.seed import SeedProvider
from .providers.sitemap import SitemapProvider
from .providers.youtube import YouTubeProvider
from .qualification.rules import infer_caption_opportunity, infer_content_type
from .qualification.scoring import score_candidate
from .runtime.budget import RequestBudget
from .runtime.metrics import RunMetrics
from .runtime.network import AsyncHttpClient

log = logging.getLogger(__name__)


def _run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]


def _state_failure(state: StateStore, key: str, error: str) -> None:
    failures = dict(state.get("failed_jobs", {}) or {})
    count = int(failures.get(key, {}).get("count", 0)) + 1
    failures[key] = {"count": count, "last_error": error[:200], "last_seen": utc_now_iso()}
    state.set("failed_jobs", failures)
    if count >= 3:
        dlq = list(state.get("dead_letter_queue", []) or [])
        if key not in dlq:
            dlq.append(key)
        state.set("dead_letter_queue", dlq[-1000:])
    else:
        retry = list(state.get("retry_queue", []) or [])
        if key not in retry:
            retry.append(key)
        state.set("retry_queue", retry[-1000:])


def _instagram_cache_is_fresh(entry: dict, now: datetime) -> bool:
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


async def run_harvest(config: Config, *, report_dir: str | Path = "reports") -> dict:
    run_id = _run_id()
    started = datetime.now(UTC).replace(microsecond=0).isoformat()
    metrics = RunMetrics(run_id=run_id, started_at=started)
    budget = RequestBudget({
        "youtube_requests": config.max_youtube_requests_per_run,
        "youtube_search_requests": config.max_youtube_search_requests_per_run,
        "web_requests": max(100, config.max_websites_per_run * (config.max_pages_per_domain + 2)),
        "websites": config.max_websites_per_run,
        "enrichments": config.max_enrichments_per_run,
    })

    sheet_repo: SheetRepository | None = None
    if config.google_spreadsheet_id:
        sheet_repo = SheetRepository(config.google_spreadsheet_id)
        sheet_repo.bootstrap()
        state: StateStore = SheetStateStore(sheet_repo)
    else:
        state = LocalJsonStateStore()

    timeout_seconds = max(30, config.max_runtime_minutes * 60)
    try:
        async with AsyncHttpClient(
            budget=budget,
            metrics=metrics,
            timeout=config.http_timeout_seconds,
            user_agent=config.user_agent,
            max_bytes=config.max_page_bytes,
            per_host_delay=config.per_host_delay_seconds,
            concurrency=config.worker_count,
        ) as http:
            context = ProviderContext(config=config, budget=budget, http=http, state=state, metrics=metrics)
            providers = [YouTubeProvider(context), SeedProvider(context), PublicWebProvider(context), RSSProvider(context), SitemapProvider(context)]
            metrics.providers = [p.name for p in providers]

            async def discover_all() -> list:
                results = await asyncio.gather(*(p.discover() for p in providers), return_exceptions=True)
                candidates = []
                for provider, result in zip(providers, results):
                    if isinstance(result, Exception):
                        metrics.errors += 1
                        _state_failure(state, f"provider:{provider.name}", type(result).__name__)
                        log.warning("provider %s failed: %s", provider.name, result)
                    else:
                        candidates.extend(result)
                return candidates

            candidates = await asyncio.wait_for(discover_all(), timeout=timeout_seconds)
            metrics.candidates_found = len(candidates)
            unique, duplicates = deduplicate_candidates(candidates)
            metrics.unique_candidates = len(unique)
            metrics.duplicates_prevented += duplicates

            now = utc_now_iso()
            now_dt = datetime.now(UTC)
            website_checked = dict(state.get("website_checked_at", {}) or {})
            email_checked = dict(state.get("email_checked_at", {}) or {})
            instagram_cache = dict(state.get("instagram_lookup_cache", {}) or {})
            channel_checked = dict(state.get("channel_checked_at", {}) or {})
            processed_video_ids = set(state.get("processed_video_ids", []) or [])
            enricher = WebsiteEnricher(config, http, budget, metrics)
            leads: list[LeadRecord] = []

            async def process(candidate):
                result = score_candidate(candidate, config)
                if result.score < config.min_score:
                    return None
                metrics.qualified += 1
                evidences = []
                source_url = candidate.profile_url or candidate.website
                for email in extract_public_emails(candidate.raw_text):
                    evidences.append(public_email_evidence(email, source_url, f"{candidate.source.lower()}_public_text"))

                if candidate.website and budget.try_consume("enrichments"):
                    try:
                        web = await enricher.enrich(candidate.website)
                        if web.canonical_website:
                            candidate.website = web.canonical_website
                        evidences.extend(web.emails)
                        website_checked[candidate.website] = now
                    except Exception as exc:  # isolate lead failures
                        metrics.errors += 1
                        _state_failure(state, f"website:{candidate.website}", type(exc).__name__)

                best = max(evidences, key=lambda e: (email_preference_score(e.email), e.confidence), default=None)
                instagram_url = ""
                instagram_status = "NOT_CHECKED"
                instagram_search_query = ""

                if best:
                    metrics.emails_found += 1
                    if best.verification_status == "VERIFIED_PUBLIC_SOURCE":
                        metrics.verified_emails += 1
                    email_checked[best.email] = now

                    cached = instagram_cache.get(best.email, {})
                    if _instagram_cache_is_fresh(cached, now_dt):
                        instagram_url = str(cached.get("url", ""))
                        instagram_status = str(cached.get("status", "NOT_FOUND"))
                        instagram_search_query = str(cached.get("query", ""))
                    else:
                        metrics.instagram_lookups += 1
                        lookup = await find_instagram_from_email(
                            http,
                            email=best.email,
                            lead_name=candidate.name or "",
                            lead_username=candidate.username or "",
                        )
                        instagram_url = lookup.url
                        instagram_status = lookup.status
                        instagram_search_query = lookup.query
                        if instagram_url:
                            metrics.instagram_found += 1
                        instagram_cache[best.email] = {
                            "url": instagram_url,
                            "status": instagram_status,
                            "query": instagram_search_query,
                            "confidence": lookup.confidence,
                            "checked_at": now,
                        }

                if candidate.source == "YOUTUBE" and candidate.provider_id:
                    channel_checked[candidate.provider_id] = now
                    for vid in candidate.metadata.get("video_ids", []):
                        processed_video_ids.add(vid)

                return LeadRecord(
                    lead_id=stable_lead_id(candidate, best.email if best else ""),
                    discovered_at=now,
                    last_checked=now,
                    source=candidate.source,
                    name=candidate.name or UNKNOWN,
                    username=candidate.username or UNKNOWN,
                    platform=candidate.platform or UNKNOWN,
                    profile_url=candidate.profile_url,
                    website=candidate.website,
                    email=best.email if best else "",
                    email_status=best.verification_status if best else "UNKNOWN",
                    email_source_url=best.source_url if best else "",
                    niche=candidate.niche or UNKNOWN,
                    country=candidate.country or UNKNOWN,
                    language=candidate.language or UNKNOWN,
                    followers=candidate.followers,
                    recent_activity=candidate.recent_activity or UNKNOWN,
                    content_type=infer_content_type(candidate),
                    caption_opportunity=infer_caption_opportunity(candidate),
                    captionflow_score=result.score,
                    classification=result.classification,
                    why_qualified=result.why_qualified,
                    instagram_url=instagram_url,
                    instagram_status=instagram_status,
                    instagram_search_query=instagram_search_query,
                )

            semaphore = asyncio.Semaphore(max(1, config.worker_count))

            async def guarded(candidate):
                async with semaphore:
                    try:
                        return await process(candidate)
                    except Exception as exc:
                        metrics.errors += 1
                        _state_failure(state, f"lead:{candidate.source}:{candidate.provider_id or candidate.profile_url}", type(exc).__name__)
                        log.warning("candidate failed without aborting run: %s", exc)
                        return None

            tasks = [guarded(c) for c in unique[: config.target_prospects_per_run * 3]]
            processed = await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout_seconds)
            leads = [lead for lead in processed if lead is not None][: config.target_prospects_per_run]

            state.set("website_checked_at", website_checked)
            state.set("email_checked_at", email_checked)
            state.set("instagram_lookup_cache", instagram_cache)
            state.set("channel_checked_at", channel_checked)
            state.set("processed_video_ids", sorted(processed_video_ids)[-10000:])
            state.set("processed_queries", list(dict.fromkeys((state.get("processed_queries", []) or []) + metrics.queries))[-2000:])
            state.set("provider_state", {"last_run": run_id, "providers": metrics.providers})
            state.flush()

            all_rows = []
            if sheet_repo:
                new_count, updated_count, all_rows = sheet_repo.upsert_leads(leads)
                metrics.new_leads = new_count
                metrics.updated_leads = updated_count
            else:
                metrics.new_leads = len(leads)

    except asyncio.TimeoutError:
        metrics.errors += 1
        log.error("run reached MAX_RUNTIME_MINUTES and stopped cleanly")
    finally:
        metrics.youtube_requests = budget.counters.get("youtube_requests", metrics.youtube_requests)
        metrics.youtube_search_requests = budget.counters.get("youtube_search_requests", metrics.youtube_search_requests)
        metrics.finish()
        report = metrics.to_dict()
        report["ratios"] = {
            "qualified_per_youtube_search": round(metrics.qualified / max(1, metrics.youtube_search_requests), 3),
            "verified_emails_per_website": round(metrics.verified_emails / max(1, metrics.websites_crawled), 3),
            "instagram_found_per_lookup": round(metrics.instagram_found / max(1, metrics.instagram_lookups), 3),
        }
        report_path = Path(report_dir)
        report_path.mkdir(parents=True, exist_ok=True)
        (report_path / f"run_{run_id}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            state.flush()
        except Exception:
            pass
        if sheet_repo:
            try:
                rows = sheet_repo.client.values_get("'LEADS'!A2:Z")
                sheet_repo.update_stats(rows, report)
            except Exception as exc:
                log.warning("stats update failed: %s", exc)
    return report
