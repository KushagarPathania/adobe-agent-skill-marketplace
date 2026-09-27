from skills_impl.page_classifier.scripts.applicability import (
    get_applicability, CHECK_CONTENT_FRESHNESS, CHECK_ANSWER_SCANNABILITY,
    CHECK_NAVIGATION_DEAD_END, CHECK_CITATION_LANDING,
)


def test_product_page_gets_full_type_specific_checks():
    result = get_applicability("product", 0.9)
    assert result["effective_page_type"] == "product"
    assert CHECK_CONTENT_FRESHNESS in result["applicable_checks"]
    assert CHECK_ANSWER_SCANNABILITY in result["applicable_checks"]
    assert CHECK_NAVIGATION_DEAD_END in result["applicable_checks"]
    assert CHECK_CITATION_LANDING in result["applicable_checks"]


def test_contact_page_gets_no_type_specific_checks():
    """A contact page shouldn't be judged for freshness, scannability, or
    dead-end/CTA expectations -- none of those are meaningful there."""
    result = get_applicability("contact", 0.9)
    assert result["applicable_checks"] == []
    assert CHECK_CONTENT_FRESHNESS in result["skipped_checks"]
    assert CHECK_NAVIGATION_DEAD_END in result["skipped_checks"]


def test_article_does_not_get_navigation_dead_end_check():
    """Articles are exempt from the dead-end/CTA bar entirely -- an
    isolated reference article is not a defect."""
    result = get_applicability("article", 0.9)
    assert CHECK_NAVIGATION_DEAD_END not in result["applicable_checks"]
    assert CHECK_CONTENT_FRESHNESS in result["applicable_checks"]


def test_low_confidence_classification_degrades_to_other():
    """A shaky classification must not be trusted enough to run
    type-specific checks against it."""
    result = get_applicability("product", 0.2)
    assert result["effective_page_type"] == "other"
    assert result["page_type"] == "product"  # original classification preserved for transparency
    assert result["applicable_checks"] == []
    assert any("threshold" in r for r in result["reasoning_signals"])


def test_high_confidence_other_stays_other():
    result = get_applicability("other", 0.9)
    assert result["effective_page_type"] == "other"
    assert result["applicable_checks"] == []


def test_reasoning_signals_are_non_empty_and_explain_skips():
    result = get_applicability("homepage", 0.8)
    assert result["reasoning_signals"]
    assert result["skipped_checks"]  # homepage doesn't get freshness/scannability/dead-end
