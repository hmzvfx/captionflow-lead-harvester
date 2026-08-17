from __future__ import annotations

from ..models import EmailEvidence, utc_now_iso
from .email import email_preference_score


def public_email_evidence(email: str, source_url: str, source_type: str, first_seen: str | None = None) -> EmailEvidence:
    now = utc_now_iso()
    confidence = min(1.0, 0.85 + max(0, email_preference_score(email) - 20) / 100)
    return EmailEvidence(
        email=email,
        source_url=source_url,
        source_type=source_type,
        first_seen=first_seen or now,
        last_checked=now,
        verification_status="VERIFIED_PUBLIC_SOURCE",
        confidence=round(confidence, 2),
        evidence_reason=f"exact address observed on public {source_type} source",
    )
