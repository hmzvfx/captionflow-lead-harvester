from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_KEYS = {"fbclid", "gclid", "dclid", "mc_cid", "mc_eid"}
EMAIL_RE = re.compile(r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,63}$", re.I)


def canonicalize_url(url: str) -> str:
    if not url:
        return ""
    value = url.strip()
    if value.startswith("//"):
        value = "https:" + value
    if "://" not in value:
        value = "https://" + value
    parts = urlsplit(value)
    scheme = "https" if parts.scheme in {"http", "https"} else parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    netloc = host
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query_items = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_KEYS
    ]
    query = urlencode(sorted(query_items))
    return urlunsplit((scheme, netloc, path, query, ""))


def canonicalize_domain(value: str) -> str:
    if not value:
        return ""
    url = canonicalize_url(value)
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def normalize_email(email: str) -> str:
    if not email:
        return ""
    value = email.strip().strip("<>[](){}.,;:'\"").lower()
    if not EMAIL_RE.match(value):
        return ""
    local, domain = value.rsplit("@", 1)
    return f"{local}@{domain.lower()}"


def normalize_username(username: str) -> str:
    return username.strip().lstrip("@").strip().lower() if username else ""
