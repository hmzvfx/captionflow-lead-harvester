from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

UNKNOWN = "UNKNOWN"


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass
class EmailEvidence:
    email: str
    source_url: str
    source_type: str
    first_seen: str
    last_checked: str
    verification_status: str
    confidence: float
    evidence_reason: str


@dataclass
class Candidate:
    source: str
    platform: str
    provider_id: str = ""
    name: str = UNKNOWN
    username: str = UNKNOWN
    profile_url: str = ""
    website: str = ""
    niche: str = UNKNOWN
    country: str = UNKNOWN
    language: str = UNKNOWN
    followers: int | None = None
    recent_activity: str = UNKNOWN
    content_type: str = UNKNOWN
    caption_opportunity: str = UNKNOWN
    description: str = ""
    published_at: str = ""
    raw_links: list[str] = field(default_factory=list)
    raw_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class QualificationResult:
    score: int
    classification: str
    why_qualified: str
    signals: dict[str, int] = field(default_factory=dict)


@dataclass
class LeadRecord:
    lead_id: str
    discovered_at: str
    last_checked: str
    source: str
    name: str
    username: str
    platform: str
    profile_url: str
    website: str
    email: str
    email_status: str
    email_source_url: str
    niche: str
    country: str
    language: str
    followers: int | None
    recent_activity: str
    content_type: str
    caption_opportunity: str
    captionflow_score: int
    classification: str
    why_qualified: str
    status: str = "NEW"


LEAD_HEADERS = [
    "Lead ID", "Discovered At", "Last Checked", "Source", "Name", "Username",
    "Platform", "Profile URL", "Website", "Email", "Email Status", "Email Source URL",
    "Niche", "Country", "Language", "Followers/Subscribers", "Recent Activity", "Content Type",
    "Caption Opportunity", "Captionflow Score", "Classification", "Why Qualified", "Status",
]
