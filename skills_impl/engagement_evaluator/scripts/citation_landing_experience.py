"""Citation Landing Experience: models what happens when a visitor lands
directly on this page from an AI answer/citation --

    orientation -> answer visibility -> continuation

This module does not re-implement detection logic that already exists
and is separately tested (`landing_context` for orientation,
`answer_scannability` for answer visibility, and the meaningful-link
count from `navigation_signals` for continuation) -- it reuses those
functions and adds the one thing none of them do alone: an *aggregate*
judgment across all three dimensions. A single weak dimension is already
reported by its own dedicated finding (EE-001/EE-002/EE-003); this module
only raises its own finding when at least two dimensions are weak *at the
same time*, which is a stronger, much less false-positive-prone signal
than any one dimension in isolation -- in keeping with "prefer a smaller
number of strong findings over many speculative ones."

Each dimension is scored "strong", "weak", or "insufficient_evidence"
(not applicable to this page type / not enough signal to judge) -- never
a fake numeric precision score.
"""
from skills_impl.common.schema import make_finding
from skills_impl.engagement_evaluator.scripts.landing_context import check_landing_context
from skills_impl.engagement_evaluator.scripts.answer_scannability import check_answer_scannability, UTILITY_PAGE_TYPES
from skills_impl.engagement_evaluator.scripts.navigation_signals import DEAD_END_SENSITIVE_TYPES, count_internal_links

STRONG = "strong"
ADEQUATE = "adequate"
WEAK = "weak"
NOT_APPLICABLE = "insufficient_evidence"


def assess_landing_experience(rendered_html, url_path="", url="", page_type="other"):
    """Return the internal (not part of the public report schema)
    assessment: {"orientation", "answer_visibility", "continuation",
    "overall", "reasons"}. Used by the orchestrator's applicability
    layer and by `check_citation_landing_experience` below.
    """
    reasons = []
    is_root = not url_path or url_path in ("/", "/index.html")

    if is_root:
        orientation = STRONG
        reasons.append("Homepage does not require breadcrumb/deep-page orientation cues.")
    else:
        weak = bool(check_landing_context(rendered_html, url_path, url))
        orientation = WEAK if weak else STRONG
        reasons.append(f"Deep-page orientation (H1/title/breadcrumb cues): {orientation}.")

    if page_type in UTILITY_PAGE_TYPES:
        weak = bool(check_answer_scannability(rendered_html, url_path, url, page_type))
        answer_visibility = WEAK if weak else STRONG
        reasons.append(f"Answer scannability for a '{page_type}' page: {answer_visibility}.")
    else:
        answer_visibility = NOT_APPLICABLE
        reasons.append(f"Answer-visibility structure is not held to a utility-page bar for page type '{page_type}'.")

    if page_type in DEAD_END_SENSITIVE_TYPES:
        counts = count_internal_links(rendered_html, url)
        continuation = WEAK if counts["meaningful"] == 0 else STRONG
        reasons.append(
            f"{counts['meaningful']} meaningful internal link(s) found (of {counts['total']} total, excluding "
            f"generic boilerplate like privacy/terms/login); a next step is expected for a '{page_type}' page: {continuation}."
        )
    else:
        continuation = NOT_APPLICABLE
        reasons.append(f"Page type '{page_type}' is not expected to provide a specific next action.")

    dimensions = (orientation, answer_visibility, continuation)
    weak_count = sum(1 for d in dimensions if d == WEAK)
    applicable_count = sum(1 for d in dimensions if d != NOT_APPLICABLE)

    if applicable_count == 0:
        overall = NOT_APPLICABLE
    elif weak_count >= 2:
        overall = WEAK
    elif weak_count == 1:
        overall = ADEQUATE
    else:
        overall = STRONG

    return {
        "orientation": orientation,
        "answer_visibility": answer_visibility,
        "continuation": continuation,
        "overall": overall,
        "weak_count": weak_count,
        "reasons": reasons,
    }


def check_citation_landing_experience(rendered_html: str, url_path: str = "", url: str = "", page_type: str = "other") -> list:
    assessment = assess_landing_experience(rendered_html, url_path, url, page_type)
    if assessment["overall"] != WEAK:
        return []

    # More corroborating weak dimensions (all 3 vs. exactly 2) is
    # stronger evidence the landing experience is genuinely bad, not
    # just a borderline case on one axis that happened to tip a second.
    confidence = 0.72 if assessment["weak_count"] >= 3 else 0.6

    return [make_finding(
        check_id="EE-004",
        title="Weak citation landing experience",
        severity="medium",
        evidence={
            "summary": (
                f"{assessment['weak_count']} of the applicable landing-experience dimensions are weak for a "
                "visitor arriving directly on this page from an AI citation: " + " ".join(assessment["reasons"])
            ),
            "url": url,
        },
        action_summary=(
            "Improve page orientation (a clear H1 and/or breadcrumbs), make the core answer scannable near the "
            "top, and add a contextually relevant next step -- addressing more than one of these compounds into "
            "a meaningfully better landing experience."
        ),
        confidence=confidence,
    )]
