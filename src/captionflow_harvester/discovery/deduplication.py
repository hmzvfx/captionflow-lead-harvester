from __future__ import annotations

import hashlib
from collections.abc import Iterable

from .normalization import canonicalize_domain, canonicalize_url, normalize_email
from ..models import Candidate


def stable_lead_id(candidate: Candidate, email: str = "") -> str:
    if candidate.provider_id:
        key = f"{candidate.source}:{candidate.provider_id.strip().lower()}"
    elif normalize_email(email):
        key = f"email:{normalize_email(email)}"
    elif canonicalize_domain(candidate.website):
        key = f"domain:{canonicalize_domain(candidate.website)}"
    elif canonicalize_url(candidate.profile_url):
        key = f"profile:{canonicalize_url(candidate.profile_url)}"
    else:
        payload = f"{candidate.source}|{candidate.name}|{candidate.username}|{candidate.description[:120]}"
        key = f"fallback:{payload.lower()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def candidate_keys(candidate: Candidate) -> set[str]:
    keys: set[str] = set()
    if candidate.provider_id:
        keys.add(f"provider:{candidate.source.lower()}:{candidate.provider_id.lower()}")
    domain = canonicalize_domain(candidate.website)
    if domain:
        keys.add(f"domain:{domain}")
    profile = canonicalize_url(candidate.profile_url)
    if profile:
        keys.add(f"profile:{profile}")
    return keys


def deduplicate_candidates(candidates: Iterable[Candidate]) -> tuple[list[Candidate], int]:
    kept: list[Candidate] = []
    seen: set[str] = set()
    duplicates = 0
    for candidate in candidates:
        keys = candidate_keys(candidate)
        if keys and seen.intersection(keys):
            duplicates += 1
            continue
        seen.update(keys)
        kept.append(candidate)
    return kept, duplicates
