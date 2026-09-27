"""Entrypoint: orchestrates site discovery, page classification, an
applicability decision per page, per-page checks, and site-scope checks
into one JSON-serializable audit report.

This is the only skill meant to be invoked directly; every other skill
(site_discovery, page_classifier, technical_parser, semantic_analyzer,
engagement_evaluator) is a reusable worker this module composes.

Pipeline: security gate -> bounded page discovery -> per-page fetch
(raw + best-effort rendered) -> page classification -> applicability
decision -> per-page checks (generic checks always run; type-sensitive
checks only when applicable) -> site-scope checks -> dedup -> prioritize
-> report. Internal tool failures (a check crashing, Playwright being
unavailable) are recorded as `audit_diagnostics`, separate from
`findings`, which are reserved for things observed about the website.
"""
import sys
import os
import re
import json
import time
import datetime
from urllib.parse import urlparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

from skills_impl.site_discovery.scripts.security import is_safe_url
from skills_impl.site_discovery.scripts.fetcher import safe_fetch, USER_AGENT
from skills_impl.site_discovery.scripts.discovery import discover_pages
from skills_impl.page_classifier.scripts.classifier import classify_page, classify_site
from skills_impl.page_classifier.scripts.applicability import (
    get_applicability, CHECK_CONTENT_FRESHNESS, CHECK_ANSWER_SCANNABILITY, CHECK_CITATION_LANDING,
    CHECK_ANSWERABILITY,
)
from skills_impl.technical_parser.scripts.js_render_parity import check_js_render_parity
from skills_impl.technical_parser.scripts.structured_data_validation import check_structured_data
from skills_impl.semantic_analyzer.scripts.non_text_accessibility import check_non_text_accessibility
from skills_impl.semantic_analyzer.scripts.content_freshness import check_content_freshness
from skills_impl.semantic_analyzer.scripts.entity_consistency import check_entity_consistency
from skills_impl.semantic_analyzer.scripts.ai_discoverability import check_ai_discoverability, check_proactive_recommendations
from skills_impl.semantic_analyzer.scripts.answerability import check_answerability
from skills_impl.engagement_evaluator.scripts.landing_context import check_landing_context
from skills_impl.engagement_evaluator.scripts.answer_scannability import check_answer_scannability
from skills_impl.engagement_evaluator.scripts.navigation_signals import check_navigation
from skills_impl.engagement_evaluator.scripts.citation_landing_experience import check_citation_landing_experience
from skills_impl.audit_orchestrator.scripts.aggregate import (
    deduplicate, prioritize, merge_overlapping_findings, validate_unique_finding_ids,
)
from skills_impl.audit_orchestrator.scripts.config import AuditConfig
from skills_impl.common.schema import make_finding

# Fetch failures in these categories are network/availability problems,
# not evidence of a website defect -- they are always reached *after*
# is_safe_url already passed the URL as safe, so a genuine SSRF/security
# rejection is never in this set.
_AVAILABILITY_ERROR_CATEGORIES = {
    "dns_resolution_failed", "timeout", "connection_failed",
    "network_failure", "redirect_limit_exceeded",
}

# A normal, modern desktop-browser User-Agent for the headless-Chromium
# render step specifically -- distinct from `fetcher.USER_AGENT`, which
# stays an honest, transparent bot-identifying string for the raw HTTP
# path (robots.txt matching is UA-independent here; see robots.py's
# DEFAULT_USER_AGENT="*"). A browser that actually renders JavaScript but
# announces itself as a bot is an unusual, easily-fingerprinted
# combination that some sites block outright -- this makes rendering
# closer to what a real visitor's browser would trigger, which is the
# point of rendering at all. Pinned to one representative modern Chrome
# release string rather than dynamically matching Playwright's bundled
# Chromium version, since Playwright's own bundled Chromium is still
# what actually executes (see `p.chromium.launch()` below) -- only the
# *announced* identity changes.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


# The only language this project's English-vocabulary-dependent
# heuristics (generic-heading detection, utility/FAQ keyword matching,
# answerability phrasing) are actually calibrated for. Deliberately
# small and explicit -- this is not a translation system, and nothing
# here should imply support for a language the implementation cannot
# actually analyze.
SUPPORTED_LANGUAGES = {"en"}

_HTML_LANG_RE = re.compile(r'<html[^>]*\blang\s*=\s*["\']([^"\']*)["\']', re.I)


def _page_language_support(html):
    """Return (lang_value, supported). `lang_value` is the raw `<html
    lang="...">` attribute value if present, else None. `supported` is
    True unless the tag is present with a valid, unambiguous primary
    subtag (e.g. "fr" from "fr-CA") that is NOT in SUPPORTED_LANGUAGES --
    missing, empty, or malformed lang values are treated as supported
    (preserve current behavior rather than penalize a page for omitting
    or malforming a signal most real sites do provide correctly; English
    behavior must not become more restrictive because this check exists).
    """
    if not html:
        return None, True
    match = _HTML_LANG_RE.search(html)
    if not match:
        return None, True
    lang_value = match.group(1).strip()
    if not lang_value:
        return lang_value, True
    primary_subtag = re.split(r'[-_]', lang_value)[0].lower()
    if not primary_subtag.isalpha():
        return lang_value, True  # malformed -- don't penalize, preserve current behavior
    return lang_value, primary_subtag in SUPPORTED_LANGUAGES


# --- Access-denied / block / interstitial response detection -----------
#
# Real-world finding: a page's RAW HTTP fetch can succeed with genuine,
# substantial content while the SEPARATE headless-render step gets an
# access-denied/bot-block interstitial instead (a bot-management system
# fingerprinting the automated browser differently from a plain HTTP
# client) -- e.g. rendered title/body literally "Access to this page has
# been denied" while the raw HTML underneath is a real, complete article.
# Treating that interstitial as "the rendered page" corrupts every
# downstream check that assumes rendered_html represents the requested
# content -- most visibly TP-001 (comparing raw vs. a block page looks
# like "substantive content requires JavaScript") and EE-001 (analyzing
# the block page's own missing H1/breadcrumb as if it were the real deep
# page's orientation).
#
# Detection requires BOTH a curated, well-known block-page phrase as the
# page's OWN title or H1 (an exact/near-exact match, never a keyword
# found anywhere in a larger paragraph) AND a short overall body length
# -- a genuine interstitial is minimal; a real article that happens to
# discuss "access denied" as a topic, or is even literally titled
# "Forbidden" as an unusual editorial choice, still has substantial body
# content, which the length guard rules out. This mirrors the same
# structural+corroborating-signal conservatism already used for
# transient UI (js_render_parity.py) and language detection above.
_ACCESS_DENIED_PHRASE_RE = re.compile(
    r'^(access (to this page has been )?denied|'
    r'you (have|\'ve) been blocked|sorry,? you have been blocked|'
    r'(this )?request (has been )?blocked|'
    r'you (do not|don\'t) have permission to access(?: this page)?|'
    r'pardon our interruption|attention required|403 forbidden)$',
    re.I,
)
_ACCESS_DENIED_MAX_BODY_LENGTH = 500


def _is_access_denied_page(html):
    """True when `html` is itself a block/access-denied/interstitial
    document rather than genuine requested-page content. See module
    note above for the detection rationale.
    """
    if not html:
        return False
    soup = BeautifulSoup(html, 'html.parser')
    title_tag = soup.find('title')
    title_text = (title_tag.get_text(strip=True) if title_tag else "").strip()
    h1_tag = soup.find('h1')
    h1_text = (h1_tag.get_text(strip=True) if h1_tag else "").strip()

    phrase_matched = bool(
        (title_text and _ACCESS_DENIED_PHRASE_RE.match(title_text)) or
        (h1_text and _ACCESS_DENIED_PHRASE_RE.match(h1_text))
    )
    if not phrase_matched:
        return False

    body_text = soup.get_text(separator=' ', strip=True)
    return len(body_text) < _ACCESS_DENIED_MAX_BODY_LENGTH


def _is_request_url_allowed(url):
    """Pure predicate wrapping `is_safe_url` for one intercepted browser
    network request -- factored out so it's unit-testable without a real
    browser (Playwright's `route`/`request` objects can be faked with
    anything exposing the same `.url` attribute). An unresolvable host is
    treated the same as unsafe here: this low-level guard only needs a
    yes/no answer, and refusing to fetch is correct either way.
    """
    safe, _, _ = is_safe_url(url)
    return safe


def _install_ssrf_guard(context):
    """Abort any browser network request -- the main document, a
    redirect hop, or any subresource (script, image, stylesheet,
    iframe, font, XHR/fetch, media, ...) -- that resolves to a
    non-public address. `context.route("**/*", handler)` intercepts
    every HTTP(S) request the page issues regardless of resource type,
    including each redirect hop (Playwright dispatches a new routable
    request per hop), so checking every request here -- not just
    `resource_type == "document"` -- closes the gap where a page could
    otherwise load a private-network image/script/iframe/XHR that the
    top-level navigation check alone would never see.

    Documented boundary: Playwright's request routing does not intercept
    WebSocket connections (a documented Playwright limitation, not
    something this guard can add without a materially different
    mechanism), so a page that opens a WebSocket to an internal address
    is not covered by this specific guard. This is a read-only,
    non-interactive render (`domcontentloaded`, no user actions taken),
    which limits how much a page can actually do over a WebSocket during
    the bounded render window -- but this is not "perfect" SSRF
    protection, and is documented as such rather than overclaimed.
    """
    def handler(route):
        if not _is_request_url_allowed(route.request.url):
            route.abort()
            return
        route.continue_()

    context.route("**/*", handler)


def _render_page(url, timeout_ms):
    """Best-effort headless render. Returns (html, error). A render
    failure is a tool limitation for this one page, never treated as a
    website defect by the caller.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "", "Playwright is not installed in this environment"
    try:
        with sync_playwright() as p:
            # Playwright's own bundled Chromium (installed via `playwright
            # install chromium`), never a user's separately installed
            # system browser -- no `channel=` or `executable_path=`
            # override, so this stays fully portable.
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=BROWSER_USER_AGENT)
            _install_ssrf_guard(context)
            page = context.new_page()
            try:
                page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            except PlaywrightTimeoutError:
                pass  # a partially loaded DOM is still useful
            html = page.content()
            browser.close()
            return html, None
    except Exception as e:
        return "", str(e)


def safe_execute(diagnostics, func, *args, page_url=None, **kwargs):
    """Run a check function. An internal bug in *our* code becomes an
    audit diagnostic, never a fake website finding -- this is what keeps
    a check crash from being reported as if it were a defect on the
    audited site.
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        diagnostics.append({
            "type": "check_error",
            "check": func.__name__,
            "page_url": page_url,
            "error_type": type(e).__name__,
            "message": f"Unexpected internal error while running {func.__name__}: {e}",
        })
        return []


def _fetch_and_render(url, config):
    raw = safe_fetch(url, timeout=config.request_timeout,
                      max_redirects=config.max_redirects,
                      max_bytes=config.max_response_bytes)
    if not raw["ok"]:
        return raw, "", None
    rendered_html, render_error = _render_page(raw["final_url"], config.render_timeout_ms)
    return raw, rendered_html, render_error


def _final_report(url, findings, metadata=None, diagnostics=None, opportunities=None):
    """`summary` is computed from `findings` ONLY -- `opportunities` (Day 5
    hardening: proactive, non-defect suggestions like AI-005) can never
    affect `total_findings` or any severity count, no matter what's in it.
    `opportunities` is always present in the report (like `findings`),
    defaulting to an empty list, never omitted.
    """
    parsed = urlparse(url)
    summary = {
        "total_findings": len(findings),
        "critical": sum(1 for f in findings if f.get("severity") == "critical"),
        "high": sum(1 for f in findings if f.get("severity") == "high"),
        "medium": sum(1 for f in findings if f.get("severity") == "medium"),
        "low": sum(1 for f in findings if f.get("severity") == "low"),
    }
    report = {
        "site": parsed.netloc or url,
        "audited_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "summary": summary,
        "findings": findings,
        "opportunities": opportunities if opportunities is not None else [],
    }
    if metadata:
        report["metadata"] = metadata
    if diagnostics is not None:
        report["audit_diagnostics"] = diagnostics
    return report


def run_audit(url: str, config: AuditConfig = None) -> dict:
    config = config or AuditConfig()
    if '://' not in url:
        url = 'https://' + url  # bare domain, e.g. "example.com" -- do not
        # touch a URL that already names a scheme (including a disallowed
        # one like file:// or ftp://) so is_safe_url's rejection reason
        # stays accurate instead of DNS-resolving a mangled string.

    safe, reason, category = is_safe_url(url)
    if not safe:
        if category == "dns_resolution_failed":
            # Not a security rejection: we could not resolve/reach the
            # host at all, which is no evidence the target is unsafe --
            # only that it couldn't be verified right now. This must
            # never be reported as a critical website defect.
            diagnostic = {
                "type": "dns_resolution_failed",
                "check": None,
                "page_url": url,
                "error_type": None,
                "message": (
                    f"Could not resolve or reach the target host, so the audit could not proceed: {reason}. "
                    "This is a network/DNS availability limitation, not evidence that the website is unsafe "
                    "or defective."
                ),
            }
            return _final_report(url, [], metadata={
                "pages_audited": 0,
                "network_unreachable": True,
                "limitations": [diagnostic["message"]],
            }, diagnostics=[diagnostic])

        return _final_report(url, [make_finding(
            check_id="ORCH-000",
            title="Target URL blocked for safety",
            severity="critical",
            evidence={"summary": f"The requested URL was not audited: {reason}"},
            action_summary="Supply a public website URL. Internal, loopback, and link-local addresses are never audited.",
            confidence=1.0,
        )], metadata={"blocked": True}, diagnostics=[])

    start_time = time.time()
    inventory = discover_pages(url, max_pages=config.max_pages, timeout=config.request_timeout)

    findings = []
    diagnostics = []      # audit-tool limitations/errors -- never website findings
    pages = []             # [{"url", "html"}] -- rendered html if available, else raw
    page_types = {}         # url -> page_type
    page_applicability = {}  # url -> applicability summary (for metadata)
    page_analysis_mode = {}  # url -> "rendered_dom" | "raw_html_fallback"
    page_language_supported = {}  # url -> bool, reused by site-scope checks below
    homepage_html = ""
    runtime_limit_unaudited_count = 0  # pages left unaudited because the total-runtime budget was reached

    # A robots.txt exclusion is a coverage limitation, not a website
    # defect -- the crawler correctly obeyed a rule the site itself
    # published, so this is recorded as a diagnostic (never a finding,
    # never counted in summary.total_findings/severity) per page that
    # was discovered but not audited for this reason.
    for excluded_url in inventory.get("skipped_disallowed", []):
        diagnostics.append({
            "type": "robots_exclusion", "check": None, "page_url": excluded_url, "error_type": None,
            "message": "Page was discovered but not audited because robots.txt disallowed crawling.",
        })

    if not PLAYWRIGHT_AVAILABLE:
        diagnostics.append({
            "type": "render_unavailable", "check": None, "page_url": None, "error_type": None,
            "message": (
                "Playwright is unavailable in this environment; the audit fell back to raw server HTML only, "
                "so JavaScript-rendering-gap findings were skipped rather than guessed at."
            ),
        })

    for candidate_url in inventory["candidate_urls"]:
        if time.time() - start_time > config.total_audit_timeout:
            runtime_limit_unaudited_count = len(inventory["candidate_urls"]) - len(pages)
            diagnostics.append({
                "type": "timeout_skip", "check": None, "page_url": None, "error_type": None,
                "message": f"Audit time budget ({config.total_audit_timeout}s) reached; {runtime_limit_unaudited_count} discovered page(s) were not audited.",
            })
            break

        raw, rendered_html, render_error = _fetch_and_render(candidate_url, config)

        if not raw["ok"]:
            error_category = raw.get("error_category")
            if error_category in _AVAILABILITY_ERROR_CATEGORIES:
                # DNS/timeout/connection problems reached *after*
                # is_safe_url already passed are availability issues,
                # not evidence of a website defect -- record as a
                # diagnostic and move on rather than fabricating a
                # website finding out of our own network conditions.
                diagnostics.append({
                    "type": error_category, "check": None, "page_url": candidate_url, "error_type": None,
                    "message": f"Could not fetch {candidate_url}: {raw['error']}. This is a network/availability limitation, not a confirmed website defect.",
                })
                continue
            status = raw.get("status")
            if error_category == "http_error" and status in (401, 403):
                # Ambiguous by nature: an access-denied response could be
                # a genuine "AI crawlers aren't let in" discoverability
                # problem (Round-2 failure mode #1 -- see the handout
                # appendix), OR an artifact of this specific audit run's
                # own request signature (a real AI assistant's crawler
                # may use a different UA/IP and not be blocked the same
                # way). Never confidently declared a confirmed defect,
                # never escalated to "high" purely because it's the
                # requested target URL, and never silently dropped
                # either -- kept as a low-confidence signal worth a
                # human's attention.
                findings.append(make_finding(
                    check_id="ORCH-003",
                    title="Page returned an access-denied response",
                    severity="medium",
                    evidence={
                        "summary": (
                            f"HTTP {status} was returned for this page. This may reflect a real crawler-access "
                            "problem, or it may be an artifact of this audit's own request signature -- treat "
                            "as a signal to investigate, not a confirmed defect."
                        ),
                        "url": candidate_url, "status": status,
                    },
                    action_summary="Verify this page is reachable by standard automated crawlers/AI agents, not only interactive browsers; if access is intentionally restricted, confirm that's deliberate.",
                    confidence=0.4,
                ))
                continue
            findings.append(make_finding(
                check_id="ORCH-001",
                title="Page could not be fetched",
                severity="high" if candidate_url == url else "low",
                evidence={"summary": f"Raw HTTP fetch failed: {raw['error']}", "url": candidate_url},
                action_summary="Confirm the page is publicly reachable and does not block standard HTTP clients.",
                confidence=0.9,
            ))
            continue

        # A bot-management/WAF block page can appear on the RENDERED
        # side alone (a headless browser fingerprinted and blocked
        # differently from the plain HTTP fetch that got the real raw
        # HTML) -- treating that interstitial as "the rendered page"
        # would corrupt every downstream check. Detected access-denial
        # content is never used as "rendered content": this page falls
        # back to raw HTML (still genuinely usable, and eligible for
        # checks that trust the raw response -- see below) exactly like
        # a render failure, plus a `response_state` used for a clearer,
        # distinct diagnostic than a generic render failure.
        rendered_access_denied = bool(rendered_html) and _is_access_denied_page(rendered_html)
        raw_access_denied = _is_access_denied_page(raw["html"])
        usable_rendered_html = None if rendered_access_denied else rendered_html
        response_state = "access_denied" if (rendered_access_denied or raw_access_denied) else "normal_content"

        effective_html = usable_rendered_html if usable_rendered_html else raw["html"]
        path = urlparse(raw["final_url"]).path or "/"

        # Per-page analysis mode: "rendered_dom" when the headless render
        # actually succeeded for this page, "raw_html_fallback" otherwise
        # (Playwright unavailable entirely, this page's render failed/
        # timed out, or its render was itself an access-denied
        # interstitial). Raw HTML is never treated as equivalent to a
        # rendered DOM -- see the rendered-dependent-check gating below.
        analysis_mode = "rendered_dom" if usable_rendered_html else "raw_html_fallback"
        page_analysis_mode[candidate_url] = analysis_mode

        if rendered_access_denied or raw_access_denied:
            diagnostics.append({
                "type": "access_denied", "check": None, "page_url": candidate_url, "error_type": None,
                "message": (
                    "The " + ("rendered" if rendered_access_denied else "raw") + " response for this page was "
                    "an access-denied/block interstitial rather than the requested content. This is an audit "
                    "coverage limitation, not a confirmed website defect -- rendered-DOM-dependent evidence from "
                    "this page is excluded from findings" +
                    (" (raw HTML was still usable as a fallback)." if not raw_access_denied else
                     ", and no usable content was available from either the raw or rendered response.")
                ),
            })

        # <html lang> is the primary language signal for this page. Only
        # an explicit, unsupported non-English value limits anything --
        # missing/unknown/English all behave exactly as before.
        lang_value, language_supported = _page_language_support(effective_html)
        page_language_supported[candidate_url] = language_supported

        classification = classify_page(candidate_url, effective_html)
        page_type = classification["page_type"]
        page_types[candidate_url] = page_type
        pages.append({"url": candidate_url, "html": effective_html})

        applicability = get_applicability(page_type, classification["confidence"])
        page_applicability[candidate_url] = applicability
        applicable = set(applicability["applicable_checks"])

        # "Primary page" for entity-clarity/site-classification purposes:
        # the exact page the caller asked to audit (which is very often a
        # specific article/product/doc URL, not the bare domain root), so
        # this must not be gated on path == "/" -- that would leave it
        # unset (and therefore always empty) for any deep-URL target.
        if candidate_url == url or (not homepage_html and path in ("", "/")):
            homepage_html = effective_html

        # --- Generic checks: always relevant regardless of page type.
        # `usable_rendered_html` (not the raw `rendered_html`) gates
        # this: an access-denied interstitial must never be compared
        # against raw HTML as if it were genuine rendered content --
        # that comparison is exactly backwards (it would look like
        # "substantive content requires JavaScript" when the truth is
        # the raw response already had the real content and the render
        # step got blocked).
        if usable_rendered_html and not raw_access_denied:
            findings.extend(safe_execute(diagnostics, check_js_render_parity, raw["html"], usable_rendered_html, candidate_url, page_url=candidate_url))
        elif render_error and PLAYWRIGHT_AVAILABLE:
            diagnostics.append({
                "type": "render_failed", "check": "check_js_render_parity", "page_url": candidate_url,
                "error_type": None,
                "message": f"Rendering failed for {candidate_url}: {render_error}. Raw-HTML-only checks still ran for this page.",
            })

        # These two are safe on raw HTML: JSON-LD is canonically
        # server-rendered (a text-only crawler reads exactly this raw
        # HTML too, so a genuine absence is real, load-bearing evidence,
        # not an artifact of not rendering), and non-text-accessibility
        # only ever judges graphics that are actually present in
        # whatever HTML was analyzed -- it can under-see JS-injected
        # images, but never manufactures a false "missing text
        # equivalent" claim about an image that isn't there.
        findings.extend(safe_execute(diagnostics, check_structured_data, effective_html, candidate_url, page_type, page_url=candidate_url))
        findings.extend(safe_execute(diagnostics, check_non_text_accessibility, effective_html, candidate_url, page_url=candidate_url))

        # These four all reason from STRUCTURAL ABSENCE (no breadcrumb,
        # no table/list, no opening paragraph, no meaningful link) via
        # ENGLISH-vocabulary heuristics (generic-heading words, utility/
        # FAQ keywords, answerability phrasing) -- two independent
        # reasons the same four checks can be unreliable: (1) an
        # incomplete raw-HTML page whose real structure is only added by
        # client-side JS ("absence cannot be established"), and (2) a
        # page in a language these English-calibrated heuristics were
        # never built to read. Either condition alone is enough to
        # conservatively skip the check rather than risk a false
        # finding; both are recorded as diagnostics, never a website
        # defect. This does not weaken coverage for the common case (a
        # rendered, English, or English-unmarked page) -- these checks
        # still run exactly as before whenever both conditions hold.
        run_absence_dependent = analysis_mode == "rendered_dom" and language_supported
        skipped_for_raw_fallback = []
        skipped_for_language = []

        def _run_or_skip(check_name):
            if run_absence_dependent:
                return True
            if analysis_mode != "rendered_dom":
                skipped_for_raw_fallback.append(check_name)
            if not language_supported:
                skipped_for_language.append(check_name)
            return False

        if _run_or_skip("landing_context"):
            findings.extend(safe_execute(diagnostics, check_landing_context, effective_html, path, candidate_url, page_url=candidate_url))

        # --- Type-sensitive checks: only run when the applicability
        # engine says this page type calls for them.
        if CHECK_CONTENT_FRESHNESS in applicable:
            findings.extend(safe_execute(diagnostics, check_content_freshness, effective_html, path, raw["headers"].get("Last-Modified"), page_url=candidate_url))
        if CHECK_ANSWER_SCANNABILITY in applicable:
            if _run_or_skip("answer_scannability"):
                findings.extend(safe_execute(diagnostics, check_answer_scannability, effective_html, path, candidate_url, page_type, page_url=candidate_url))
        if CHECK_CITATION_LANDING in applicable:
            if _run_or_skip("citation_landing_experience"):
                findings.extend(safe_execute(diagnostics, check_citation_landing_experience, effective_html, path, candidate_url, page_type, page_url=candidate_url))
        if CHECK_ANSWERABILITY in applicable:
            if _run_or_skip("answerability"):
                findings.extend(safe_execute(diagnostics, check_answerability, effective_html, candidate_url, page_type, page_url=candidate_url))

        if skipped_for_raw_fallback:
            diagnostics.append({
                "type": "render_reduced_coverage", "check": None, "page_url": candidate_url, "error_type": None,
                "message": (
                    f"Rendering was unavailable or failed for this page, so raw-HTML-only checks continued, but "
                    f"rendered-DOM-dependent check(s) that reason from structural absence were conservatively "
                    f"skipped rather than risking a false finding from incomplete raw HTML: "
                    f"{', '.join(skipped_for_raw_fallback)}."
                ),
            })
        if skipped_for_language:
            diagnostics.append({
                "type": "language_unsupported", "check": None, "page_url": candidate_url, "error_type": None,
                "message": (
                    f"This page's <html lang> ('{lang_value}') is outside the small set of languages this "
                    f"project's English-vocabulary-dependent heuristics are calibrated for ({', '.join(sorted(SUPPORTED_LANGUAGES))}), "
                    f"so the following check(s) were conservatively skipped rather than misapplied: "
                    f"{', '.join(skipped_for_language)}. Language-independent checks (structured data, "
                    f"non-text accessibility, freshness signals, security/robots) still ran normally."
                ),
            })

    if not pages:
        # `findings` at this point can only hold ORCH-001 entries (site
        # checks haven't run yet); if it's empty AND we actually recorded
        # an availability-category diagnostic (not just, say, the
        # unrelated "Playwright unavailable" note), every fetch failure
        # was a network/availability problem -- meaning we never got a
        # real HTTP response from anything, so this is our own
        # reachability limitation, not proven evidence the website
        # itself is broken.
        had_availability_failure = any(d["type"] in _AVAILABILITY_ERROR_CATEGORIES for d in diagnostics)
        if not findings and had_availability_failure:
            return _final_report(url, [], metadata={
                "pages_audited": 0,
                "network_unreachable": True,
                "limitations": [d["message"] for d in diagnostics],
            }, diagnostics=diagnostics)

        findings.append(make_finding(
            check_id="ORCH-002",
            title="No pages could be audited",
            severity="critical",
            evidence={"summary": "Every discovered candidate page failed to fetch; no content-based checks could run."},
            action_summary="Verify the site is publicly reachable and not blocking automated HTTP requests entirely.",
            confidence=0.9,
            # MINOR CLEANUP: this describes a site-wide audit failure (no
            # single page is being blamed -- every candidate failed),
            # not a defect on one specific page, so its scope is "site",
            # not the default "page".
            scope="site",
        ))
        return _final_report(url, findings, metadata={"pages_audited": 0}, diagnostics=diagnostics)

    if not homepage_html:
        homepage_html = pages[0]["html"]  # defensive fallback: target page itself failed to fetch

    page_classifications = [{"page_type": t} for t in page_types.values()]
    site_classification = classify_site(url, page_classifications, homepage_html)

    # --- Site-scope checks: need the full page set, run once at the end.
    findings.extend(safe_execute(diagnostics, check_entity_consistency, pages))

    # AI-003 (entity clarity) is the one signal inside check_ai_discoverability
    # that genuinely depends on English vocabulary (is_generic_text's
    # "Home"/"Welcome"/"Overview" placeholder list, and English-stopword-
    # based title/H1 consistency) -- AI-001 (reachability) is purely
    # structural and is unaffected. The homepage's own <html lang> is the
    # trusted signal here, same as every per-page gate above; passing it
    # through lets the check skip only that one language-dependent signal
    # rather than the whole check.
    homepage_lang_value, homepage_language_supported = _page_language_support(homepage_html)
    findings.extend(safe_execute(
        diagnostics, check_ai_discoverability, inventory, homepage_html, url, homepage_language_supported
    ))
    if not homepage_language_supported:
        diagnostics.append({
            "type": "language_unsupported", "check": None, "page_url": url, "error_type": None,
            "message": (
                f"The homepage's <html lang> ('{homepage_lang_value}') is outside the small set of languages "
                f"this project's English-vocabulary-dependent heuristics are calibrated for ({', '.join(sorted(SUPPORTED_LANGUAGES))}), "
                "so the following site-scope check(s) were conservatively skipped rather than misapplied: entity_clarity."
            ),
        })

    findings.extend(safe_execute(diagnostics, check_navigation, pages, page_types))

    # Proactive opportunities (AI-005 and any future proactive-only check)
    # are collected into their own list, never `findings` -- they are
    # evidence-backed, non-defect suggestions the handout explicitly
    # distinguishes from detected problems. Deliberately NOT run through
    # merge_overlapping_findings/deduplicate/prioritize: that pipeline
    # exists to fold together and rank *detected-defect* findings, and an
    # opportunity must never be merged against (or ranked alongside) one.
    # `check_proactive_recommendations` already returns at most one entry
    # per audit run, so no dedup is needed here in practice either.
    opportunities = safe_execute(
        diagnostics, check_proactive_recommendations, pages, page_types, page_language_supported
    )

    findings = merge_overlapping_findings(findings)
    findings = deduplicate(findings)
    findings = prioritize(findings)
    # CRITICAL FIX: guarantee no two findings in the final report share
    # an id -- deliberately NOT wrapped in safe_execute/try-except, so a
    # violation fails loudly (an aggregation bug) rather than silently
    # reaching a report or being swallowed into a diagnostic.
    validate_unique_finding_ids(findings)

    metadata = {
        "site_type": site_classification["site_type"],
        "site_type_confidence": site_classification["confidence"],
        "pages_audited": len(pages),
        # MINOR CLEANUP: `pages_discovered` previously used the bounded/
        # selected candidate count (identical to `pages_selected` below),
        # even though the actual discovery count was already computed
        # and exposed one level deeper as `coverage.candidate_pages_
        # discovered`. Now consistent: "discovered" (every candidate URL
        # the bounded discovery pass found, before ranking/selection),
        # "selected" (the top-N actually chosen for this run), "audited"
        # (of those selected, how many were actually fetched and
        # checked) each mean one distinct thing at every level of the
        # report, not just inside `coverage`.
        "pages_discovered": inventory.get("total_candidates", len(inventory["candidate_urls"])),
        "pages_selected": len(inventory["candidate_urls"]),
        "robots_txt_found": inventory["robots_found"],
        "sitemap_found": inventory["sitemap_found"],
        "pages_blocked_by_robots": len(inventory["skipped_disallowed"]),
        "playwright_available": PLAYWRIGHT_AVAILABLE,
        "page_classifications": {
            u: {"page_type": a["page_type"], "confidence": a["confidence"], "applicable_checks": a["applicable_checks"]}
            for u, a in page_applicability.items()
        },
        # Per-page analysis mode -- "rendered_dom" (a real headless render
        # succeeded for this page) or "raw_html_fallback" (Playwright
        # unavailable or this page's render failed; raw server HTML was
        # analyzed instead). Raw HTML is never presented as equivalent to
        # a rendered DOM -- see `render_reduced_coverage` in
        # audit_diagnostics for which checks were consequently skipped.
        "page_analysis": {
            u: {"analysis_mode": mode} for u, mode in page_analysis_mode.items()
        },
        # Backward-compatible human-readable view of the same diagnostics.
        "limitations": [d["message"] for d in diagnostics],
        # --- Coverage metadata (Day 5 hardening): informational only --
        # a small/bounded sample, no sitemap, or a low page count is
        # never, by itself, a website defect. Terminology is deliberately
        # precise: "discovered" (every candidate URL the bounded
        # discovery pass found, before ranking/selection) vs "selected"
        # (the top-N actually chosen for this bounded run) vs
        # "successfully audited" (of those selected, how many were
        # actually fetched and checked) -- these can legitimately differ,
        # and the difference is exactly what this section explains.
        "coverage": {
            "candidate_pages_discovered": inventory.get("total_candidates", len(inventory["candidate_urls"])),
            "pages_selected": len(inventory["candidate_urls"]),
            "pages_successfully_audited": len(pages),
            "robots_skipped_pages": len(inventory["skipped_disallowed"]),
            "timeout_or_network_skipped_pages": sum(
                1 for d in diagnostics if d["type"] in _AVAILABILITY_ERROR_CATEGORIES
            ),
            "runtime_limit_unaudited_pages": runtime_limit_unaudited_count,
            "represented_page_types": sorted(set(page_types.values())),
            # Same underlying diagnostic messages as `limitations` above,
            # exposed under a name that makes clear these are audit
            # COVERAGE limitations, not detected website problems.
            "coverage_limitations": [d["message"] for d in diagnostics],
        },
    }

    return _final_report(url, findings, metadata, diagnostics, opportunities=opportunities)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    print(f"Auditing {target} ...", file=sys.stderr)
    print(json.dumps(run_audit(target), indent=2))
