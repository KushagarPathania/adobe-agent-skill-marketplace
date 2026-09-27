"""Applicability engine: decides which page-type-sensitive checks are
relevant to a given page, so a check never runs (and can never produce a
finding) on a page type it doesn't actually apply to.

Generic checks that are always relevant regardless of page type --
JS-render parity, JSON-LD syntax/price-consistency, non-text-content
accessibility -- are not gated here; they run on every page. This
matrix covers only the checks whose relevance genuinely depends on what
kind of page this is: freshness doesn't matter on a contact page, a
dead-end/CTA expectation doesn't belong on a reference article, and so
on. Low-confidence classifications degrade to the conservative "other"
row rather than forcing type-specific checks onto a guess.
"""

CHECK_CONTENT_FRESHNESS = "content_freshness"
CHECK_ANSWER_SCANNABILITY = "answer_scannability"
CHECK_NAVIGATION_DEAD_END = "navigation_dead_end"
CHECK_CITATION_LANDING = "citation_landing_experience"
CHECK_ANSWERABILITY = "answerability"

GATED_CHECKS = {
    CHECK_CONTENT_FRESHNESS,
    CHECK_ANSWER_SCANNABILITY,
    CHECK_NAVIGATION_DEAD_END,
    CHECK_CITATION_LANDING,
    CHECK_ANSWERABILITY,
}

# page_type -> subset of GATED_CHECKS that apply to that type. Anything
# not in a row's set is a deliberate skip, not an oversight -- e.g.
# "contact" and "search" pages get none of these because freshness,
# scannable-answer structure, dead-end/CTA expectations, and citation
# landing scoring are not meaningful judgments for those page types.
APPLICABILITY_MATRIX = {
    "homepage":      {CHECK_CITATION_LANDING},
    "product":       {CHECK_CONTENT_FRESHNESS, CHECK_ANSWER_SCANNABILITY, CHECK_NAVIGATION_DEAD_END, CHECK_CITATION_LANDING},
    "category":      {CHECK_NAVIGATION_DEAD_END, CHECK_CITATION_LANDING},
    "pricing":       {CHECK_ANSWER_SCANNABILITY, CHECK_NAVIGATION_DEAD_END, CHECK_CITATION_LANDING},
    "article":       {CHECK_CONTENT_FRESHNESS, CHECK_CITATION_LANDING, CHECK_ANSWERABILITY},
    "blog":          {CHECK_CONTENT_FRESHNESS, CHECK_CITATION_LANDING, CHECK_ANSWERABILITY},
    "faq":           {CHECK_ANSWER_SCANNABILITY, CHECK_CITATION_LANDING},
    "documentation": {CHECK_ANSWER_SCANNABILITY, CHECK_NAVIGATION_DEAD_END, CHECK_CITATION_LANDING},
    "about":         {CHECK_CONTENT_FRESHNESS, CHECK_CITATION_LANDING, CHECK_ANSWERABILITY},
    "contact":       set(),
    "service":       {CHECK_CONTENT_FRESHNESS, CHECK_ANSWER_SCANNABILITY, CHECK_NAVIGATION_DEAD_END, CHECK_CITATION_LANDING},
    "event":         {CHECK_CONTENT_FRESHNESS, CHECK_CITATION_LANDING},
    "profile":       set(),
    "search":        set(),
    "other":         set(),
}

LOW_CONFIDENCE_THRESHOLD = 0.45


def get_applicability(page_type, confidence):
    """Return {"page_type", "effective_page_type", "confidence",
    "applicable_checks", "skipped_checks", "reasoning_signals"}.

    When confidence is below the threshold, the *effective* type used
    for lookup degrades to "other" (skip every gated check) rather than
    running type-specific checks against an unreliable guess -- the
    original classified `page_type` is still reported for transparency.
    """
    reasoning = []

    if confidence < LOW_CONFIDENCE_THRESHOLD and page_type != "other":
        effective_type = "other"
        reasoning.append(
            f"Classification confidence ({confidence}) is below the applicability threshold "
            f"({LOW_CONFIDENCE_THRESHOLD}); treating this page as 'other' rather than applying "
            f"'{page_type}'-specific checks to an unreliable guess."
        )
    else:
        effective_type = page_type
        reasoning.append(f"Page classified as '{page_type}' with confidence {confidence}.")

    applicable = APPLICABILITY_MATRIX.get(effective_type, set())
    skipped = GATED_CHECKS - applicable

    if skipped:
        reasoning.append(f"Not applicable to '{effective_type}' pages: {', '.join(sorted(skipped))}.")

    return {
        "page_type": page_type,
        "effective_page_type": effective_type,
        "confidence": confidence,
        "applicable_checks": sorted(applicable),
        "skipped_checks": sorted(skipped),
        "reasoning_signals": reasoning,
    }
