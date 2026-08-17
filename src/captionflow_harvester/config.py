from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable


def _csv(name: str, default: str = "") -> tuple[str, ...]:
    value = os.getenv(name, default)
    return tuple(x.strip() for x in value.split(",") if x.strip())


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    youtube_api_key: str = ""
    google_spreadsheet_id: str = ""
    worker_count: int = 20
    target_languages: tuple[str, ...] = ("fr",)
    target_countries: tuple[str, ...] = ("BE", "FR", "CA", "CH")
    target_niches: tuple[str, ...] = ("business", "fitness", "marketing", "coaching", "real_estate", "finance")
    creator_types: tuple[str, ...] = ("coach", "consultant", "formateur", "entrepreneur", "creator", "podcast")
    min_subscribers: int = 500
    max_subscribers: int = 500_000
    recent_days: int = 45
    min_score: int = 55
    hot_score: int = 80
    good_score: int = 65
    possible_score: int = 50
    target_prospects_per_run: int = 500
    max_youtube_requests_per_run: int = 20
    max_youtube_search_requests_per_run: int = 3
    max_websites_per_run: int = 120
    max_pages_per_domain: int = 5
    max_enrichments_per_run: int = 120
    max_runtime_minutes: int = 40
    max_page_bytes: int = 1_500_000
    http_timeout_seconds: float = 12.0
    per_host_delay_seconds: float = 0.6
    public_seed_urls: tuple[str, ...] = field(default_factory=tuple)
    public_feed_urls: tuple[str, ...] = field(default_factory=tuple)
    public_sitemap_urls: tuple[str, ...] = field(default_factory=tuple)
    llm_enabled: bool = False
    user_agent: str = "CaptionflowLeadHarvester/1.0 (+public-contact-discovery)"

    @classmethod
    def from_env(cls) -> "Config":
        cfg = cls(
            youtube_api_key=os.getenv("YOUTUBE_API_KEY", "").strip(),
            google_spreadsheet_id=os.getenv("GOOGLE_SPREADSHEET_ID", "").strip(),
            worker_count=_int("WORKER_COUNT", 20),
            target_languages=_csv("TARGET_LANGUAGES", "fr"),
            target_countries=_csv("TARGET_COUNTRIES", "BE,FR,CA,CH"),
            target_niches=_csv("TARGET_NICHES", "business,fitness,marketing,coaching,real_estate,finance"),
            creator_types=_csv("CREATOR_TYPES", "coach,consultant,formateur,entrepreneur,creator,podcast"),
            min_subscribers=_int("MIN_SUBSCRIBERS", 500),
            max_subscribers=_int("MAX_SUBSCRIBERS", 500_000),
            recent_days=_int("RECENT_DAYS", 45),
            min_score=_int("MIN_SCORE", 55),
            hot_score=_int("HOT_SCORE", 80),
            good_score=_int("GOOD_SCORE", 65),
            possible_score=_int("POSSIBLE_SCORE", 50),
            target_prospects_per_run=_int("TARGET_PROSPECTS_PER_RUN", 500),
            max_youtube_requests_per_run=_int("MAX_YOUTUBE_REQUESTS_PER_RUN", 20),
            max_youtube_search_requests_per_run=_int("MAX_YOUTUBE_SEARCH_REQUESTS_PER_RUN", 3),
            max_websites_per_run=_int("MAX_WEBSITES_PER_RUN", 120),
            max_pages_per_domain=_int("MAX_PAGES_PER_DOMAIN", 5),
            max_enrichments_per_run=_int("MAX_ENRICHMENTS_PER_RUN", 120),
            max_runtime_minutes=_int("MAX_RUNTIME_MINUTES", 40),
            max_page_bytes=_int("MAX_PAGE_BYTES", 1_500_000),
            http_timeout_seconds=_float("HTTP_TIMEOUT_SECONDS", 12.0),
            per_host_delay_seconds=_float("PER_HOST_DELAY_SECONDS", 0.6),
            public_seed_urls=_csv("PUBLIC_SEED_URLS"),
            public_feed_urls=_csv("PUBLIC_FEED_URLS"),
            public_sitemap_urls=_csv("PUBLIC_SITEMAP_URLS"),
            llm_enabled=_bool("LLM_ENABLED", False),
            user_agent=os.getenv("HARVESTER_USER_AGENT", "CaptionflowLeadHarvester/1.0 (+public-contact-discovery)"),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.worker_count < 1 or self.worker_count > 100:
            raise ValueError("WORKER_COUNT must be between 1 and 100")
        if not (0 <= self.min_score <= 100 and 0 <= self.hot_score <= 100):
            raise ValueError("score thresholds must be between 0 and 100")
        if self.min_subscribers < 0 or self.max_subscribers < self.min_subscribers:
            raise ValueError("invalid subscriber range")
        for name in (
            "max_youtube_requests_per_run",
            "max_youtube_search_requests_per_run",
            "max_websites_per_run",
            "max_pages_per_domain",
            "max_enrichments_per_run",
            "max_runtime_minutes",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")

    @property
    def has_public_sources(self) -> bool:
        return bool(self.youtube_api_key or self.public_seed_urls or self.public_feed_urls or self.public_sitemap_urls)
