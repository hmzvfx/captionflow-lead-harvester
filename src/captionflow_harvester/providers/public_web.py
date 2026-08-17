from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..discovery.normalization import canonicalize_domain, canonicalize_url
from ..models import Candidate, UNKNOWN
from ..runtime.network import NetworkError
from .base import DiscoveryProvider

SOCIAL_HOSTS = ("youtube.com", "instagram.com", "tiktok.com", "linkedin.com")


class PublicWebProvider(DiscoveryProvider):
    name = "WEB"

    async def discover(self) -> list[Candidate]:
        out: list[Candidate] = []
        # Free/public discovery is intentionally anchored in explicit public seeds.
        # The provider enriches those seeds and discovers public social/feed/sitemap links.
        for seed in self.context.config.public_seed_urls[:50]:
            try:
                text, final_url, content_type = await self.context.http.get_text(seed, respect_robots=True)
            except NetworkError:
                continue
            if "html" not in content_type.lower() and "<html" not in text.lower()[:500]:
                continue
            soup = BeautifulSoup(text, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else canonicalize_domain(final_url)
            description_tag = soup.find("meta", attrs={"name": "description"})
            description = str(description_tag.get("content", "")) if description_tag else ""
            links: list[str] = []
            for a in soup.find_all("a", href=True):
                absolute = canonicalize_url(urljoin(final_url, str(a.get("href"))))
                host = canonicalize_domain(absolute)
                if any(s in host for s in SOCIAL_HOSTS) and absolute not in links:
                    links.append(absolute)
            domain = canonicalize_domain(final_url)
            if not domain:
                continue
            out.append(Candidate(
                source=self.name,
                platform="Web",
                provider_id=domain,
                name=title or domain,
                profile_url=final_url,
                website=f"https://{domain}",
                description=description,
                raw_links=links,
                raw_text=f"{title} {description}",
                metadata={"social_links": links},
            ))
        return out
