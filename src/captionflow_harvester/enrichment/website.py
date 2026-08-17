from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ..config import Config
from ..discovery.normalization import canonicalize_domain, canonicalize_url
from ..models import EmailEvidence
from ..runtime.budget import RequestBudget
from ..runtime.metrics import RunMetrics
from ..runtime.network import AsyncHttpClient, NetworkError
from .email import email_preference_score, extract_public_emails
from .evidence import public_email_evidence

log = logging.getLogger(__name__)

PRIORITY_PATHS = ("/", "/contact", "/contact-us", "/about", "/about-us", "/team", "/legal", "/mentions-legales")
SOCIAL_HOSTS = ("instagram.com", "tiktok.com", "youtube.com", "youtu.be", "linkedin.com")


@dataclass
class WebsiteEnrichment:
    canonical_website: str
    emails: list[EmailEvidence] = field(default_factory=list)
    social_links: list[str] = field(default_factory=list)
    pages_checked: list[str] = field(default_factory=list)

    @property
    def best_email(self) -> EmailEvidence | None:
        return max(self.emails, key=lambda e: (email_preference_score(e.email), e.confidence), default=None)


class WebsiteEnricher:
    def __init__(self, config: Config, http: AsyncHttpClient, budget: RequestBudget, metrics: RunMetrics) -> None:
        self.config = config
        self.http = http
        self.budget = budget
        self.metrics = metrics

    async def enrich(self, website: str) -> WebsiteEnrichment:
        website = canonicalize_url(website)
        if not website or not canonicalize_domain(website):
            return WebsiteEnrichment("")
        if not self.budget.try_consume("websites"):
            return WebsiteEnrichment(website)
        self.metrics.websites_crawled += 1
        origin = f"https://{canonicalize_domain(website)}"
        enrichment = WebsiteEnrichment(origin)
        queue = list(PRIORITY_PATHS)
        seen: set[str] = set()

        while queue and len(enrichment.pages_checked) < self.config.max_pages_per_domain:
            path = queue.pop(0)
            url = canonicalize_url(urljoin(origin + "/", path))
            if url in seen:
                continue
            seen.add(url)
            try:
                text, final_url, content_type = await self.http.get_text(url, respect_robots=True)
            except NetworkError:
                continue
            if "html" not in content_type.lower() and not text.lstrip().startswith(("<html", "<!DOCTYPE", "<!doctype")):
                continue
            enrichment.pages_checked.append(final_url)
            for email in extract_public_emails(text):
                if not any(x.email == email for x in enrichment.emails):
                    enrichment.emails.append(public_email_evidence(email, final_url, "website"))

            soup = BeautifulSoup(text, "html.parser")
            for link in soup.find_all("a", href=True):
                href = str(link.get("href", "")).strip()
                if not href or href.startswith(("javascript:", "#")):
                    continue
                absolute = canonicalize_url(urljoin(final_url, href))
                host = canonicalize_domain(absolute)
                if any(social in host for social in SOCIAL_HOSTS):
                    if absolute not in enrichment.social_links:
                        enrichment.social_links.append(absolute)
                if host == canonicalize_domain(origin):
                    lower = urlsplit(absolute).path.lower()
                    if any(token in lower for token in ("contact", "about", "team", "legal", "mention")) and absolute not in seen:
                        queue.append(absolute)
        return enrichment
