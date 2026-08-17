from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from ..discovery.normalization import canonicalize_url
from ..discovery.query_expansion import QueryExpansionEngine
from ..models import Candidate, UNKNOWN
from ..runtime.network import NetworkError
from .base import DiscoveryProvider

log = logging.getLogger(__name__)
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"']+", re.I)
COUNTRY_TO_LANG = {"FR": "fr", "BE": "fr", "CA": "fr", "CH": "fr", "GB": "en", "US": "en", "NL": "nl"}


def _safe_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_links(text: str) -> list[str]:
    out: list[str] = []
    for match in URL_RE.findall(text or ""):
        url = canonicalize_url(match.rstrip(".,;!"))
        if url and url not in out:
            out.append(url)
    return out


def _official_website(links: list[str]) -> str:
    blocked = ("youtube.com", "youtu.be", "instagram.com", "tiktok.com", "facebook.com", "twitter.com", "x.com", "linkedin.com")
    for url in links:
        host = (urlsplit(url).hostname or "").lower()
        if host and not any(b in host for b in blocked):
            return url
    return ""


class YouTubeProvider(DiscoveryProvider):
    name = "YOUTUBE"

    async def discover(self) -> list[Candidate]:
        cfg = self.context.config
        if not cfg.youtube_api_key:
            return []

        engine = QueryExpansionEngine(cfg.target_niches, cfg.target_languages, cfg.creator_types)
        offset = int(self.context.state.get("youtube_query_offset", 0) or 0)
        batch = engine.next_batch(offset, min(cfg.max_youtube_search_requests_per_run, 20))
        self.context.state.set("youtube_query_offset", batch.next_offset)
        self.context.metrics.queries.extend(batch.queries)

        channel_ids: set[str] = set(self.context.state.get("youtube_known_channel_ids", []) or [])
        discovered_from_search: dict[str, dict] = {}
        tokens = dict(self.context.state.get("youtube_query_tokens", {}) or {})
        done_at = dict(self.context.state.get("youtube_query_done_at", {}) or {})
        now = datetime.now(UTC)

        for query in batch.queries:
            done_raw = done_at.get(query)
            if done_raw:
                try:
                    done_time = datetime.fromisoformat(done_raw)
                    if now - done_time < timedelta(days=7):
                        continue
                except ValueError:
                    pass
            params = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": 25,
                "order": "date",
                "safeSearch": "moderate",
                "key": cfg.youtube_api_key,
            }
            page_token = tokens.get(query)
            if page_token:
                params["pageToken"] = page_token
            try:
                data = await self.context.http.get_json(f"{YOUTUBE_API}/search", params=params, youtube_search=True)
            except NetworkError as exc:
                log.warning("YouTube search skipped for %r: %s", query, exc)
                continue
            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                channel_id = snippet.get("channelId")
                if not channel_id:
                    continue
                channel_ids.add(channel_id)
                current = discovered_from_search.setdefault(channel_id, {})
                published = snippet.get("publishedAt", "")
                if published and (not current.get("published_at") or published > current["published_at"]):
                    current["published_at"] = published
                current["query"] = query
                video_id = item.get("id", {}).get("videoId")
                if video_id:
                    current.setdefault("video_ids", []).append(video_id)
            next_token = data.get("nextPageToken")
            if next_token:
                tokens[query] = next_token
                done_at.pop(query, None)
            else:
                tokens.pop(query, None)
                done_at[query] = now.isoformat()

        self.context.state.set("youtube_query_tokens", tokens)
        self.context.state.set("youtube_query_done_at", done_at)
        self.context.state.set("youtube_known_channel_ids", sorted(channel_ids)[-5000:])

        # Refresh only a bounded subset. channels.list is cheap compared with search.list.
        refresh_ids = list(discovered_from_search.keys())
        if len(refresh_ids) < 50:
            checked_at = dict(self.context.state.get("channel_checked_at", {}) or {})
            older = [cid for cid in channel_ids if cid not in discovered_from_search]
            older.sort(key=lambda cid: checked_at.get(cid, ""))
            refresh_ids.extend(older[: 50 - len(refresh_ids)])
        refresh_ids = refresh_ids[:100]
        candidates: list[Candidate] = []
        for start in range(0, len(refresh_ids), 50):
            ids = refresh_ids[start : start + 50]
            if not ids:
                continue
            params = {
                "part": "snippet,statistics,brandingSettings",
                "id": ",".join(ids),
                "maxResults": 50,
                "key": cfg.youtube_api_key,
            }
            try:
                data = await self.context.http.get_json(f"{YOUTUBE_API}/channels", params=params)
            except NetworkError as exc:
                log.warning("YouTube channel refresh skipped: %s", exc)
                break
            for item in data.get("items", []):
                cid = item.get("id", "")
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                branding = item.get("brandingSettings", {}).get("channel", {})
                description = snippet.get("description", "") or branding.get("description", "") or ""
                links = _extract_links(description)
                custom = snippet.get("customUrl") or ""
                country = snippet.get("country") or branding.get("country") or UNKNOWN
                language = snippet.get("defaultLanguage") or snippet.get("defaultAudioLanguage") or COUNTRY_TO_LANG.get(country, UNKNOWN)
                search_meta = discovered_from_search.get(cid, {})
                published_at = search_meta.get("published_at", "")
                profile_url = f"https://www.youtube.com/channel/{cid}"
                candidates.append(Candidate(
                    source=self.name,
                    platform="YouTube",
                    provider_id=cid,
                    name=snippet.get("title") or UNKNOWN,
                    username=custom or UNKNOWN,
                    profile_url=profile_url,
                    website=_official_website(links),
                    niche=search_meta.get("query", UNKNOWN),
                    country=country,
                    language=language,
                    followers=_safe_int(stats.get("subscriberCount")),
                    recent_activity=published_at or UNKNOWN,
                    description=description,
                    published_at=published_at,
                    raw_links=links,
                    raw_text=description,
                    metadata={"video_ids": search_meta.get("video_ids", [])},
                ))
        return candidates
