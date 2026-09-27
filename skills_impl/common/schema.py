"""Shared finding schema used by every check skill.

Every check in this project (technical, semantic, engagement) builds its
findings through `make_finding` so the report always has one consistent
shape, and so severity/confidence bookkeeping isn't reinvented six times.
"""

SEVERITY_WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def clamp_confidence(value: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = 0.5
    return round(max(0.05, min(1.0, value)), 2)


def make_finding(check_id, title, severity, evidence, action_summary,
                  action_priority=None, confidence=0.75, scope="page"):
    """Build one finding dict in the report's standard shape.

    `evidence` may be a plain string (wrapped as {"summary": ...}) or a
    dict that already carries structured details (url, selector, examples,
    affected_pages, ...) -- either way the result always has a "summary".
    """
    if isinstance(evidence, str):
        evidence = {"summary": evidence}
    else:
        evidence = dict(evidence)
    evidence.setdefault("summary", "")

    return {
        "id": check_id,
        "title": title,
        "severity": severity,
        "confidence": clamp_confidence(confidence),
        "scope": scope,
        "evidence": evidence,
        "suggested_action": {
            "summary": action_summary,
            "priority": action_priority or severity,
        },
    }
