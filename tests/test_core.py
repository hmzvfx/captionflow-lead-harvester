from datetime import UTC, datetime

import pytest

from captionflow_harvester.config import Config
from captionflow_harvester.discovery.deduplication import deduplicate_candidates, stable_lead_id
from captionflow_harvester.discovery.normalization import canonicalize_domain, canonicalize_url, normalize_email, normalize_username
from captionflow_harvester.discovery.query_expansion import QueryExpansionEngine
from captionflow_harvester.enrichment.email import extract_public_emails, is_bad_email
from captionflow_harvester.enrichment.evidence import public_email_evidence
from captionflow_harvester.models import Candidate, LeadRecord
from captionflow_harvester.persistence.sheets import lead_to_row
from captionflow_harvester.persistence.state import LocalJsonStateStore
from captionflow_harvester.providers.base import ProviderContext
from captionflow_harvester.providers.seed import SeedProvider
from captionflow_harvester.qualification.scoring import score_candidate
from captionflow_harvester.runtime.budget import RequestBudget


def test_url_normalization():
    value = canonicalize_url("http://www.Example.com/path/?utm_source=x&b=2&a=1#section")
    assert value == "https://example.com/path?a=1&b=2"
    assert canonicalize_domain(value) == "example.com"


def test_email_normalization():
    assert normalize_email("  Hello@Example.COM. ") == "hello@example.com"
    assert normalize_email("not-an-email") == ""
    assert normalize_username(" @Creator ") == "creator"


def test_email_extraction():
    text = "Business: hello@creator.com and duplicate HELLO@CREATOR.COM"
    assert extract_public_emails(text) == ["hello@creator.com"]


def test_bad_email_filter():
    assert is_bad_email("noreply@example.org")
    assert is_bad_email("test@real-domain.com")
    assert is_bad_email("privacy@real-domain.com")
    assert not is_bad_email("business@creator.com")


def test_deduplication():
    a = Candidate(source="YOUTUBE", platform="YouTube", provider_id="UC123", profile_url="https://youtube.com/channel/UC123")
    b = Candidate(source="YOUTUBE", platform="YouTube", provider_id="UC123", profile_url="https://youtube.com/channel/UC123?utm_source=x")
    unique, duplicates = deduplicate_candidates([a, b])
    assert len(unique) == 1
    assert duplicates == 1
    assert stable_lead_id(a) == stable_lead_id(b)


def test_scoring():
    candidate = Candidate(
        source="YOUTUBE",
        platform="YouTube",
        provider_id="UC1",
        name="Business Coach",
        website="https://creator.com",
        niche="business",
        country="FR",
        language="fr",
        followers=12000,
        published_at=datetime.now(UTC).isoformat(),
        description="Business coach face cam tips and educational shorts",
        raw_text="coach conseils captions shorts",
    )
    result = score_candidate(candidate, Config())
    assert 0 <= result.score <= 100
    assert result.score >= 65
    assert result.classification in {"GOOD", "HOT"}


def test_query_expansion():
    engine = QueryExpansionEngine(("fitness",), ("fr",), ("coach",))
    queries = engine.all_queries()
    assert len(queries) == len(set(q.lower() for q in queries))
    assert any("personal trainer" in q for q in queries)
    batch = engine.next_batch(0, 3)
    assert len(batch.queries) == 3
    assert batch.next_offset == 3


def test_checkpoint(tmp_path):
    path = tmp_path / "state.json"
    state = LocalJsonStateStore(path)
    state.set("processed_queries", ["coach fitness"])
    state.flush()
    restored = LocalJsonStateStore(path)
    assert restored.get("processed_queries") == ["coach fitness"]


def test_request_budget():
    budget = RequestBudget({"youtube_search_requests": 2})
    assert budget.try_consume("youtube_search_requests")
    assert budget.try_consume("youtube_search_requests")
    assert not budget.try_consume("youtube_search_requests")
    assert budget.remaining("youtube_search_requests") == 0


def test_google_sheet_row_mapping():
    lead = LeadRecord(
        lead_id="abc", discovered_at="2026-08-17T00:00:00+00:00", last_checked="2026-08-17T00:00:00+00:00",
        source="YOUTUBE", name="Creator", username="creator", platform="YouTube",
        profile_url="https://youtube.com/channel/abc", website="https://creator.com",
        email="hello@creator.com", email_status="VERIFIED_PUBLIC_SOURCE",
        email_source_url="https://creator.com/contact", niche="business", country="FR", language="fr",
        followers=1000, recent_activity="recent", content_type="talking_head", caption_opportunity="GOOD",
        captionflow_score=82, classification="HOT", why_qualified="content fit", status="NEW",
        instagram_url="https://www.instagram.com/creator/", instagram_status="FOUND_SEARCH_RESULT",
        instagram_search_query="hello creator instagram", outreach_status="SENT",
        email_subject="Je vous sous-titre une vidéo gratuitement", sent_at="2026-08-18T15:00:00+02:00",
        gmail_message_id="gmail-123", outreach_attempts=1,
    )
    row = lead_to_row(lead)
    assert len(row) == 32
    assert row[0] == "abc"
    assert row[9] == "hello@creator.com"
    assert row[19] == 82
    assert row[23] == "https://www.instagram.com/creator/"
    assert row[26] == "SENT"
    assert row[29] == "gmail-123"
    assert row[31] == 1


def test_public_source_evidence():
    evidence = public_email_evidence("business@creator.com", "https://creator.com/contact", "website")
    assert evidence.email == "business@creator.com"
    assert evidence.source_url == "https://creator.com/contact"
    assert evidence.verification_status == "VERIFIED_PUBLIC_SOURCE"
    assert 0.0 <= evidence.confidence <= 1.0


@pytest.mark.asyncio
async def test_provider_normalization():
    config = Config(public_seed_urls=("http://www.Example.com/path/?utm_source=x#frag",))
    context = ProviderContext(config=config, budget=None, http=None, state=None, metrics=None)
    candidates = await SeedProvider(context).discover()
    assert len(candidates) == 1
    assert candidates[0].provider_id == "example.com"
    assert candidates[0].profile_url == "https://example.com/path"
