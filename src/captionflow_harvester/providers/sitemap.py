from __future__ import annotations

import xml.etree.ElementTree as ET

from ..discovery.normalization import canonicalize_domain, canonicalize_url
from ..models import Candidate
from ..runtime.network import NetworkError
from .base import DiscoveryProvider


class SitemapProvider(DiscoveryProvider):
    name = "SITEMAP"

    async def discover(self) -> list[Candidate]:
        out: list[Candidate] = []
        for sitemap_url in self.context.config.public_sitemap_urls:
            try:
                text, _, _ = await self.context.http.get_text(sitemap_url, respect_robots=True)
            except NetworkError:
                continue
            try:
                root = ET.fromstring(text)
            except ET.ParseError:
                continue
            locs = [el.text.strip() for el in root.iter() if el.tag.lower().endswith("loc") and el.text]
            domains: dict[str, str] = {}
            for loc in locs[:500]:
                url = canonicalize_url(loc)
                domain = canonicalize_domain(url)
                if domain and domain not in domains:
                    domains[domain] = url
            for domain, url in domains.items():
                out.append(Candidate(
                    source=self.name,
                    platform="Web",
                    provider_id=domain,
                    name=domain.split(".")[0].replace("-", " ").title(),
                    profile_url=url,
                    website=f"https://{domain}",
                    raw_links=[url],
                    raw_text="sitemap public source",
                ))
        return out
