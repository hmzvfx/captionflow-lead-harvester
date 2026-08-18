from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class RunMetrics:
    run_id: str
    started_at: str
    finished_at: str = ""
    duration: float = 0.0
    providers: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    candidates_found: int = 0
    unique_candidates: int = 0
    qualified: int = 0
    new_leads: int = 0
    updated_leads: int = 0
    emails_found: int = 0
    verified_emails: int = 0
    instagram_lookups: int = 0
    instagram_found: int = 0
    duplicates_prevented: int = 0
    youtube_requests: int = 0
    youtube_search_requests: int = 0
    web_requests: int = 0
    websites_crawled: int = 0
    http_429_count: int = 0
    retry_count: int = 0
    errors: int = 0

    def finish(self) -> None:
        end = datetime.now(UTC)
        self.finished_at = end.replace(microsecond=0).isoformat()
        start = datetime.fromisoformat(self.started_at)
        self.duration = round((end - start).total_seconds(), 3)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["429_count"] = data.pop("http_429_count")
        return data
