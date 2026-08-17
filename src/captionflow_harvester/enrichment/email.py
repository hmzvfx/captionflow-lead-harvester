from __future__ import annotations

import html
import re

from ..discovery.normalization import normalize_email

EMAIL_FIND_RE = re.compile(r"(?<![\w.+-])([A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,63})(?![\w.-])", re.I)
BAD_LOCAL_PREFIXES = (
    "noreply", "no-reply", "donotreply", "do-not-reply", "example", "test", "testing",
    "privacy", "abuse", "webmaster", "postmaster", "mailer-daemon", "root",
)
BAD_DOMAINS = {"example.com", "example.org", "example.net", "email.com", "domain.com", "sentry.io"}
BAD_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
PREFERRED_LOCALS = ("contact", "hello", "business", "collab", "partnership", "partnerships", "booking", "info")


def is_bad_email(email: str) -> bool:
    value = normalize_email(email)
    if not value:
        return True
    local, domain = value.rsplit("@", 1)
    if domain in BAD_DOMAINS or any(local.startswith(prefix) for prefix in BAD_LOCAL_PREFIXES):
        return True
    if any(value.endswith(ext) for ext in BAD_EXTENSIONS):
        return True
    if len(local) > 64 or ".." in value:
        return True
    return False


def extract_public_emails(text: str) -> list[str]:
    if not text:
        return []
    decoded = html.unescape(text).replace("[at]", "@").replace("(at)", "@")
    emails: list[str] = []
    seen: set[str] = set()
    for match in EMAIL_FIND_RE.findall(decoded):
        email = normalize_email(match)
        if email and email not in seen and not is_bad_email(email):
            seen.add(email)
            emails.append(email)
    return emails


def email_preference_score(email: str) -> int:
    value = normalize_email(email)
    if not value or is_bad_email(value):
        return -100
    local = value.split("@", 1)[0]
    score = 20
    if local in PREFERRED_LOCALS or any(local.startswith(p + ".") for p in PREFERRED_LOCALS):
        score += 15
    if any(token in local for token in ("business", "collab", "partner", "booking")):
        score += 10
    return score
