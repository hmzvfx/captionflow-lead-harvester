from __future__ import annotations

from ..config import Config
from ..models import Candidate, QualificationResult, UNKNOWN
from .rules import infer_caption_opportunity, infer_content_type, recent_activity_score


def classify(score: int, config: Config) -> str:
    if score >= config.hot_score:
        return "HOT"
    if score >= config.good_score:
        return "GOOD"
    if score >= config.possible_score:
        return "POSSIBLE"
    return "LOW"


def score_candidate(candidate: Candidate, config: Config) -> QualificationResult:
    text = f"{candidate.name} {candidate.description} {candidate.raw_text}".lower()
    signals: dict[str, int] = {}

    niche = candidate.niche.lower() if candidate.niche != UNKNOWN else ""
    if niche in config.target_niches or any(n.replace("_", " ") in niche for n in config.target_niches) or any(n.replace("_", " ") in text for n in config.target_niches):
        signals["target_niche"] = 18

    if candidate.language != UNKNOWN and candidate.language.lower() in {x.lower() for x in config.target_languages}:
        signals["target_language"] = 10
    elif candidate.language == UNKNOWN:
        signals["target_language"] = 2

    if candidate.country != UNKNOWN and candidate.country.upper() in {x.upper() for x in config.target_countries}:
        signals["target_country"] = 8
    elif candidate.country == UNKNOWN:
        signals["target_country"] = 1

    followers = candidate.followers
    if followers is not None:
        if config.min_subscribers <= followers <= config.max_subscribers:
            signals["audience_fit"] = 15
        elif followers > 0:
            signals["audience_fit"] = 4

    activity = recent_activity_score(candidate.published_at, config.recent_days)
    if activity:
        signals["recent_activity"] = activity

    content_type = infer_content_type(candidate)
    if content_type in {"talking_head", "educational", "podcast"}:
        signals["content_fit"] = 16
    elif content_type != UNKNOWN:
        signals["content_fit"] = 5

    caption = infer_caption_opportunity(candidate)
    if caption == "GOOD":
        signals["caption_opportunity"] = 13
    elif caption == "DECENT":
        signals["caption_opportunity"] = 7

    if candidate.website:
        signals["public_website"] = 5
    if any(token in text for token in ("coach", "consultant", "formateur", "entrepreneur", "business", "podcast")):
        signals["commercial_creator"] = 8

    score = min(100, sum(signals.values()))
    classification = classify(score, config)
    reasons = [name.replace("_", " ") for name, value in sorted(signals.items(), key=lambda x: x[1], reverse=True) if value >= 8]
    why = ", ".join(reasons[:5]) if reasons else "limited public qualification signals"
    return QualificationResult(score=score, classification=classification, why_qualified=why, signals=signals)
