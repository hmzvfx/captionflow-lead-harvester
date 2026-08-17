from __future__ import annotations

from datetime import UTC, datetime

from ..models import Candidate, UNKNOWN

CONTENT_HINTS = {
    "talking_head": ("face cam", "talking head", "conseil", "tips", "explique", "how to", "tuto", "tutorial", "coach"),
    "podcast": ("podcast", "interview", "episode"),
    "educational": ("formation", "learn", "education", "conseil", "tips", "guide", "cours"),
}
SHORT_HINTS = ("shorts", "short", "reel", "tiktok", "vertical", "clip")
CAPTION_HINTS = ("subtitle", "subtitles", "caption", "captions", "sous-titre", "sous titres")


def infer_content_type(candidate: Candidate) -> str:
    text = f"{candidate.name} {candidate.description} {candidate.raw_text}".lower()
    matches = [kind for kind, hints in CONTENT_HINTS.items() if any(h in text for h in hints)]
    return matches[0] if matches else candidate.content_type


def infer_caption_opportunity(candidate: Candidate) -> str:
    text = f"{candidate.description} {candidate.raw_text}".lower()
    if any(h in text for h in CAPTION_HINTS):
        return "GOOD"
    if infer_content_type(candidate) in {"talking_head", "educational", "podcast"}:
        return "GOOD"
    if any(h in text for h in SHORT_HINTS):
        return "DECENT"
    return candidate.caption_opportunity


def recent_activity_score(published_at: str, recent_days: int) -> int:
    if not published_at:
        return 0
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        age_days = (datetime.now(UTC) - dt.astimezone(UTC)).days
    except ValueError:
        return 0
    if age_days <= max(7, recent_days // 3):
        return 15
    if age_days <= recent_days:
        return 10
    if age_days <= recent_days * 2:
        return 4
    return 0
