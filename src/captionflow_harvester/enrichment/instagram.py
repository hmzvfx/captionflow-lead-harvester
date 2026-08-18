from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import parse_qs, quote_plus, unquote, urlsplit

from bs4 import BeautifulSoup

from ..discovery.normalization import normalize_email, normalize_username
from ..runtime.network import AsyncHttpClient, NetworkError

SEARCH_ENDPOINT = "https://html.duckduckgo.com/html/"
INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com"}
RESERVED_INSTAGRAM_PATHS = {
    "p", "reel", "reels", "stories", "explore", "accounts", "direct", "about",
    "developer", "developers", "privacy", "legal", "terms", "challenge", "tv",
}
GENERIC_EMAIL_LOCALS = {
    "contact", "hello", "hi", "info", "support", "admin", "team", "sales", "business",
    "collab", "collabs", "collaboration", "booking", "bookings", "marketing", "media",
    "press", "partnership", "partnerships", "partner", "enquiry", "enquiries", "help",
    "orders", "office", "service", "customer", "customerservice",
}
INSTAGRAM_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


@dataclass(frozen=True)
class InstagramLookupResult:
    url: str = ""
    status: str = "NOT_FOUND"
    query: str = ""
    confidence: float = 0.0


def _compact(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", value.lower())


def email_localpart(email: str) -> str:
    value = normalize_email(email)
    return value.split("@", 1)[0] if value else ""


def _unwrap_search_href(href: str) -> str:
    value = (href or "").strip()
    if not value:
        return ""
    if value.startswith("//"):
        value = "https:" + value
    parts = urlsplit(value)
    if parts.netloc.lower().endswith("duckduckgo.com"):
        params = parse_qs(parts.query)
        target = params.get("uddg", [""])[0]
        if target:
            return unquote(target)
    return value


def normalize_instagram_profile_url(url: str) -> str:
    value = _unwrap_search_href(url)
    if not value:
        return ""
    if value.startswith("//"):
        value = "https:" + value
    if "://" not in value:
        value = "https://" + value.lstrip("/")
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if host not in INSTAGRAM_HOSTS:
        return ""
    segments = [segment for segment in parts.path.split("/") if segment]
    if not segments:
        return ""
    handle = segments[0].lstrip("@").strip()
    if handle.lower() in RESERVED_INSTAGRAM_PATHS or not INSTAGRAM_HANDLE_RE.fullmatch(handle):
        return ""
    return f"https://www.instagram.com/{handle}/"


def extract_instagram_profiles_from_search_html(html: str) -> list[tuple[str, str]]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        profile = normalize_instagram_profile_url(str(anchor.get("href", "")))
        if not profile or profile in seen:
            continue
        seen.add(profile)
        found.append((profile, anchor.get_text(" ", strip=True)))
    return found


def instagram_candidate_confidence(
    profile_url: str,
    *,
    email_local: str,
    lead_name: str = "",
    lead_username: str = "",
    result_title: str = "",
    rank: int = 0,
) -> float:
    profile = normalize_instagram_profile_url(profile_url)
    if not profile:
        return 0.0
    handle = profile.rstrip("/").rsplit("/", 1)[-1]
    handle_key = _compact(handle)
    local_key = _compact(email_local)
    username_key = _compact(normalize_username(lead_username))
    name_key = _compact(lead_name)
    title_key = _compact(result_title)

    score = max(0.0, 0.18 - (rank * 0.02))
    generic = email_local.lower() in GENERIC_EMAIL_LOCALS or len(local_key) < 4

    if username_key and handle_key == username_key:
        score = max(score, 0.99)
    elif username_key and len(username_key) >= 5:
        ratio = SequenceMatcher(None, handle_key, username_key).ratio()
        if ratio >= 0.86:
            score = max(score, 0.93)

    if local_key and not generic:
        if handle_key == local_key:
            score = max(score, 1.0)
        elif min(len(handle_key), len(local_key)) >= 5:
            ratio = SequenceMatcher(None, handle_key, local_key).ratio()
            if ratio >= 0.90:
                score = max(score, 0.95)
            elif ratio >= 0.80 or local_key in handle_key or handle_key in local_key:
                score = max(score, 0.86)

    if name_key and len(name_key) >= 5:
        if name_key in title_key or name_key in handle_key or handle_key in name_key:
            score = max(score, 0.88)
        else:
            name_tokens = {_compact(token) for token in re.split(r"\s+", lead_name) if len(_compact(token)) >= 4}
            if name_tokens and any(token in handle_key or token in title_key for token in name_tokens):
                score = max(score, 0.82)

    # Generic mailboxes such as contact@ or support@ are not identity evidence by themselves.
    # They only pass if the Instagram result independently matches the lead name/username.
    if generic and score < 0.82:
        return min(score, 0.45)
    return min(score, 1.0)


async def find_instagram_from_email(
    http: AsyncHttpClient,
    *,
    email: str,
    lead_name: str = "",
    lead_username: str = "",
    min_confidence: float = 0.78,
) -> InstagramLookupResult:
    local = email_localpart(email)
    if not local:
        return InstagramLookupResult(status="SKIPPED_INVALID_EMAIL")

    # The first query follows the requested rule exactly: <part-before-@> instagram.
    queries = [f"{local} instagram"]
    if local.lower() in GENERIC_EMAIL_LOCALS:
        identity = normalize_username(lead_username) or (lead_name or "").strip()
        if identity:
            queries.append(f"{local} {identity} instagram")

    best_url = ""
    best_query = queries[0]
    best_confidence = 0.0
    had_search_error = False

    for query in queries:
        search_url = f"{SEARCH_ENDPOINT}?q={quote_plus(query)}"
        try:
            html, _, _ = await http.get_text(search_url, respect_robots=False)
        except NetworkError:
            had_search_error = True
            continue

        for rank, (profile_url, title) in enumerate(extract_instagram_profiles_from_search_html(html)):
            confidence = instagram_candidate_confidence(
                profile_url,
                email_local=local,
                lead_name=lead_name,
                lead_username=lead_username,
                result_title=title,
                rank=rank,
            )
            if confidence > best_confidence:
                best_url = profile_url
                best_query = query
                best_confidence = confidence

        if best_url and best_confidence >= min_confidence:
            return InstagramLookupResult(
                url=best_url,
                status="FOUND_SEARCH_RESULT",
                query=best_query,
                confidence=round(best_confidence, 3),
            )

    if had_search_error and not best_url:
        return InstagramLookupResult(status="SEARCH_ERROR", query=queries[0])
    return InstagramLookupResult(
        url=best_url if best_confidence >= min_confidence else "",
        status="FOUND_SEARCH_RESULT" if best_confidence >= min_confidence else "NOT_FOUND",
        query=best_query,
        confidence=round(best_confidence, 3),
    )
