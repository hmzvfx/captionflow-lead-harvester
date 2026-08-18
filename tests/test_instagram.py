from captionflow_harvester.enrichment.instagram import (
    email_localpart,
    extract_instagram_profiles_from_search_html,
    instagram_candidate_confidence,
    normalize_instagram_profile_url,
)


def test_email_localpart():
    assert email_localpart("John.Smith@example.com") == "john.smith"
    assert email_localpart("not-an-email") == ""


def test_instagram_profile_normalization():
    assert normalize_instagram_profile_url("https://www.instagram.com/john.smith/?hl=en") == "https://www.instagram.com/john.smith/"
    assert normalize_instagram_profile_url("https://instagram.com/p/ABC123/") == ""
    assert normalize_instagram_profile_url("https://example.com/john.smith") == ""


def test_duckduckgo_result_unwrap():
    html = '''
    <html><body>
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.instagram.com%2Fjohn.smith%2F">John Smith (@john.smith) Instagram</a>
    </body></html>
    '''
    results = extract_instagram_profiles_from_search_html(html)
    assert results == [("https://www.instagram.com/john.smith/", "John Smith (@john.smith) Instagram")]


def test_exact_email_local_match_is_high_confidence():
    score = instagram_candidate_confidence(
        "https://www.instagram.com/john.smith/",
        email_local="john.smith",
        lead_name="John Smith",
        lead_username="johnsmith",
        result_title="John Smith Instagram",
    )
    assert score >= 0.95


def test_generic_contact_does_not_match_random_instagram():
    score = instagram_candidate_confidence(
        "https://www.instagram.com/randomperson/",
        email_local="contact",
        lead_name="Creator Brand",
        lead_username="creatorbrand",
        result_title="Random Person Instagram",
    )
    assert score < 0.78


def test_generic_contact_can_match_known_username():
    score = instagram_candidate_confidence(
        "https://www.instagram.com/creatorbrand/",
        email_local="contact",
        lead_name="Creator Brand",
        lead_username="creatorbrand",
        result_title="Creator Brand Instagram",
    )
    assert score >= 0.95
