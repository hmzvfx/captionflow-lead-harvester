from __future__ import annotations

from urllib.parse import urlsplit

from ..discovery.normalization import canonicalize_domain, canonicalize_url
from ..models import Candidate, UNKNOWN
from .base import DiscoveryProvider


class SeedProvider(DiscoveryProvider):
    name = "SEED"

    async def discover(self) -> list[Candidate]:
        out: list[Candidate] = []
        for raw in self.context.config.public_seed_urls:
            url = canonicalize_url(raw)
            domain = canonicalize_domain(url)
            if not domain:
                continue
            out.append(Candidate(
                source=self.name,
                platform="Web",
                provider_id=domain,
                name=domain.split(".")[0].replace("-", " ").title(),
                profile_url=url,
                website=url,
                raw_links=[url],
                raw_text=domain,
            ))
        return out
