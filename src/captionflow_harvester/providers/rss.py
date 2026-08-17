from __future__ import annotations

from ..discovery.normalization import canonicalize_domain, canonicalize_url
from ..models import Candidate, UNKNOWN
from ..runtime.network import NetworkError
from .base import DiscoveryProvider


class RSSProvider(DiscoveryProvider):
    name = "RSS"

    async def discover(self) -> list[Candidate]:
        try:
            import feedparser
        except ImportError as exc:
            raise RuntimeError("feedparser is required for RSS discovery") from exc
        out: list[Candidate] = []
        for feed_url in self.context.config.public_feed_urls:
            try:
                text, final_url, _ = await self.context.http.get_text(feed_url, respect_robots=True)
            except NetworkError:
                continue
            feed = feedparser.loads(text)
            site = canonicalize_url(feed.feed.get("link", "")) or canonicalize_url(final_url)
            domain = canonicalize_domain(site)
            if not domain:
                continue
            entries = list(feed.entries[:10])
            latest = entries[0] if entries else {}
            summary = " ".join(str(e.get("title", "")) for e in entries[:5])
            out.append(Candidate(
                source=self.name,
                platform="Web",
                provider_id=domain,
                name=feed.feed.get("title") or domain,
                profile_url=site,
                website=site,
                description=feed.feed.get("subtitle", "") or summary,
                published_at=str(latest.get("published", "")),
                raw_links=[site, final_url],
                raw_text=summary,
            ))
        return out
