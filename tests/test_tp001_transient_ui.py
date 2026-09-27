"""Regression tests for a real false-positive pattern found live against
https://www.nytimes.com/: a cookie/privacy-consent panel (and, more
generally, auth/session modals) that only renders after JavaScript runs
was itself driving TP-001's "substantive content requires JavaScript
rendering" finding -- its own boilerplate ("Manage Privacy Preferences",
"Purposes", "Features", sign-in prompts, ...) inflated the rendered word
count and could register as missing structural content, even though none
of it is evidence that the page's actual article/product content needs
JavaScript.

`_strip_transient_ui` (skills_impl/technical_parser/scripts/js_render_parity.py)
is the fix: structural-first detection (ARIA role, aria-modal, the
native <dialog> element, id/class naming conventions real consent-
management platforms and auth widgets emit, plus a narrow exact-phrase
secondary signal on a leaf element's own text) removes these containers
from the rendered DOM before either the whole-page overlap ratio or the
missing-block detection runs -- never a blanket scan for words like
"privacy"/"cookie"/"account"/"login"/"session" in ordinary prose.
"""
from skills_impl.technical_parser.scripts.js_render_parity import check_js_render_parity, _is_transient_ui_container
from bs4 import BeautifulSoup
from tests import fixtures as f

ARTICLE_BODY = """
<article>
<h1>Scientists Learn Something Surprising From Sleepy Dogs</h1>
<p>Researchers studying canine sleep patterns have found new evidence linking rest cycles to memory
consolidation, a discovery that could reshape how veterinarians think about animal cognition.</p>
<p>The study, conducted over eighteen months, tracked more than two hundred dogs across several breeds
and found consistent patterns regardless of size or age.</p>
</article>
"""


def _raw(body=ARTICLE_BODY):
    return f"<html><head><title>Daily News</title></head><body>{body}</body></html>"


def _rendered(extra, body=ARTICLE_BODY):
    return f"<html><head><title>Daily News</title></head><body>{body}{extra}</body></html>"


# --- TEST 1: privacy/cookie consent UI -----------------------------------

COOKIE_CONSENT_PANEL = """
<div role="dialog" aria-modal="true" id="onetrust-banner-sdk">
  <h2>Manage Privacy Preferences</h2>
  <p>We and our vendors use cookies and similar methods to recognize visitors and remember their
  preferences, measure the effectiveness of advertising, and analyze site traffic.</p>
  <h3>Purposes</h3>
  <ul><li>Store and/or access information on a device</li><li>Personalized advertising</li></ul>
  <h3>Features</h3>
  <ul><li>Match and combine offline data sources</li><li>Link different devices</li></ul>
  <button>Accept All</button>
  <button>Reject All</button>
</div>
"""


def test_cookie_consent_panel_does_not_trigger_tp001():
    findings = check_js_render_parity(_raw(), _rendered(COOKIE_CONSENT_PANEL), "https://news.example/article")
    assert findings == []


# --- TEST 2: authentication/session UI ------------------------------------

AUTH_SESSION_MODAL = """
<div role="dialog" aria-modal="true" class="sign-in-modal">
  <h2>Your session has expired</h2>
  <p>Please sign in again to continue reading and to save your preferences across devices.</p>
  <button>Sign In</button>
  <button>Continue as Guest</button>
</div>
"""


def test_auth_session_modal_does_not_trigger_tp001():
    findings = check_js_render_parity(_raw(), _rendered(AUTH_SESSION_MODAL), "https://news.example/article")
    assert findings == []


# --- TEST 3: genuine JS-dependent substantive content ----------------------

def test_genuine_js_dependent_content_still_triggers_tp001():
    """Non-regression: raw HTML with little content, rendered DOM adding
    substantial article/pricing content that is NOT transient UI, must
    still be detected."""
    findings = check_js_render_parity(f.RAW_HTML_JS_HEAVY, f.RENDERED_HTML_JS_HEAVY, "https://acme-saas.example/pricing")
    assert len(findings) == 1
    assert findings[0]["id"] == "TP-001"


# --- TEST 4: mixed transient UI + genuine substantive content (critical) --

def test_mixed_transient_ui_and_genuine_content_still_triggers_tp001():
    """The most important case: rendered DOM adds BOTH a cookie-consent
    panel AND genuine JS-only pricing content. The transient UI must not
    drive (or meaningfully inflate) the finding, but the finding must
    still fire because the substantive content alone is strong enough."""
    raw = f.RAW_HTML_JS_HEAVY
    rendered = f.RENDERED_HTML_JS_HEAVY.replace("</body>", COOKIE_CONSENT_PANEL + "</body>")
    findings = check_js_render_parity(raw, rendered, "https://acme-saas.example/pricing")
    assert len(findings) == 1
    assert findings[0]["id"] == "TP-001"
    # The cookie panel's own boilerplate must not appear among the
    # reported examples -- the finding is driven by the real content gap.
    examples_text = " ".join(findings[0]["evidence"]["examples"])
    assert "Manage Privacy Preferences" not in examples_text
    assert "Purposes" not in examples_text


def test_mixed_case_severity_matches_content_only_case():
    """The transient UI must not itself escalate (or deflate) severity --
    the mixed case should score the same as the content-only case."""
    content_only = check_js_render_parity(f.RAW_HTML_JS_HEAVY, f.RENDERED_HTML_JS_HEAVY, "https://acme-saas.example/pricing")
    mixed_rendered = f.RENDERED_HTML_JS_HEAVY.replace("</body>", COOKIE_CONSENT_PANEL + AUTH_SESSION_MODAL + "</body>")
    mixed = check_js_render_parity(f.RAW_HTML_JS_HEAVY, mixed_rendered, "https://acme-saas.example/pricing")
    assert mixed[0]["severity"] == content_only[0]["severity"]


# --- TEST 5: lexical safety -- ordinary prose must survive -----------------

PRIVACY_TOPIC_ARTICLE = """
<article>
<h1>How Tech Companies Handle Your Privacy</h1>
<p>A new report examines how major platforms manage user privacy, including how cookie data is
collected and how account login sessions are tracked across devices.</p>
<p>Critics argue that current privacy safeguards do not go far enough to protect users who remain
signed in for long session periods without re-authenticating their account.</p>
</article>
"""


def test_ordinary_article_discussing_privacy_cookies_login_is_not_discarded():
    """An article whose actual substantive text discusses privacy,
    cookies, accounts, login, and sessions -- ordinary prose, not a UI
    container -- must be treated as real content, not filtered."""
    raw = _raw(body="")  # raw has none of this content
    rendered = _rendered(extra="", body=PRIVACY_TOPIC_ARTICLE)  # only in rendered
    findings = check_js_render_parity(raw, rendered, "https://news.example/tech-privacy-report")
    assert len(findings) == 1
    assert findings[0]["id"] == "TP-001"  # the real content gap must still be detected
    examples_text = " ".join(findings[0]["evidence"]["examples"])
    assert "privacy" in examples_text.lower() or "cookie" in examples_text.lower() or "login" in examples_text.lower() or "session" in examples_text.lower()


def test_article_paragraph_with_sensitive_words_never_classified_as_transient_container():
    """Direct unit check on the detector itself: a plain <p> containing
    these words in ordinary prose is never treated as a transient UI
    container."""
    soup = BeautifulSoup(PRIVACY_TOPIC_ARTICLE, "html.parser")
    for p in soup.find_all("p"):
        assert _is_transient_ui_container(p) is False


def test_heading_naming_the_real_topic_is_not_treated_as_transient():
    """The article's own <h1> (a real, specific topic heading) must
    never be misidentified as transient UI, even though it names
    'privacy'."""
    soup = BeautifulSoup(PRIVACY_TOPIC_ARTICLE, "html.parser")
    h1 = soup.find("h1")
    assert _is_transient_ui_container(h1) is False


# --- Structural detector unit tests ----------------------------------------

def test_role_dialog_detected_as_transient():
    soup = BeautifulSoup('<div role="dialog"><p>x</p></div>', "html.parser")
    assert _is_transient_ui_container(soup.find("div")) is True


def test_aria_modal_true_detected_as_transient():
    soup = BeautifulSoup('<div aria-modal="true"><p>x</p></div>', "html.parser")
    assert _is_transient_ui_container(soup.find("div")) is True


def test_native_dialog_element_detected_as_transient():
    soup = BeautifulSoup('<dialog><p>x</p></dialog>', "html.parser")
    assert _is_transient_ui_container(soup.find("dialog")) is True


def test_known_cmp_id_pattern_detected_as_transient():
    soup = BeautifulSoup('<div id="onetrust-consent-sdk"><p>x</p></div>', "html.parser")
    assert _is_transient_ui_container(soup.find("div")) is True


def test_ordinary_div_with_no_signals_not_transient():
    soup = BeautifulSoup('<div class="article-body"><p>Some real content about our new product launch.</p></div>', "html.parser")
    assert _is_transient_ui_container(soup.find("div")) is False


# ==========================================================================
# Follow-up fix: the "flash"/notification-banner shape of session UI.
#
# Real-world finding: live testing against https://github.com/pricing
# showed the previous fix's structural detection (ARIA role="dialog"/
# aria-modal/<dialog>) does not cover this DOM pattern at all -- a
# same-tab-session-sync notice implemented as a non-modal "flash"
# message (no dialog role, no aria-modal), e.g.
# class="js-stale-session-flash stale-session-flash flash flash-warn
# flash-full" containing "You signed in with another tab or window.
# Reload to refresh your session." This is a distinct, common,
# generalizable UI shape (the Rails-originated "flash message"
# convention, also used by GitHub's own Primer design system and many
# other frameworks) -- not a GitHub-specific string.
# ==========================================================================

GITHUB_STYLE_SESSION_FLASH = """
<div class="js-stale-session-flash stale-session-flash flash flash-warn flash-full">
  <span class="js-stale-session-flash-signed-in">You signed in with another tab or window.
  Reload to refresh your session. <a class="Link--inTextBlock">Reload</a></span>
  <span class="js-stale-session-flash-signed-out">You signed out in another tab or window.
  Reload to refresh your session. <a class="Link--inTextBlock">Reload</a></span>
</div>
"""


# --- 1. GitHub-style authentication/session UI (flash message shape) -----

def test_github_style_session_flash_does_not_trigger_tp001():
    findings = check_js_render_parity(_raw(), _rendered(GITHUB_STYLE_SESSION_FLASH), "https://code-host.example/pricing")
    assert findings == []


def test_flash_warn_class_detected_as_transient_without_dialog_role():
    """The container carries no role="dialog"/aria-modal at all -- this
    confirms the fix covers the non-modal 'flash notice' shape, not only
    dialogs."""
    soup = BeautifulSoup(GITHUB_STYLE_SESSION_FLASH, "html.parser")
    container = soup.find("div")
    assert container.get("role") is None
    assert container.get("aria-modal") is None
    assert _is_transient_ui_container(container) is True


def test_session_sync_sentence_detected_on_leaf_span_alone():
    """Even without the container-level class match, the leaf <span>'s
    own idiomatic 'signed in ... another tab ... reload ... session'
    text is independently recognized."""
    soup = BeautifulSoup(GITHUB_STYLE_SESSION_FLASH, "html.parser")
    span = soup.find("span")
    assert _is_transient_ui_container(span) is True


def test_bare_flash_class_alone_is_not_transient():
    """Conservatism guard: the bare word "flash" alone (e.g. a
    "flashcard" or "flash-sale" style class unrelated to a transient
    notice) must not match -- only "flash" combined with a qualifier
    that actually marks it as a notice type does."""
    soup = BeautifulSoup('<div class="flashcard-widget"><p>Study flashcards for your exam.</p></div>', "html.parser")
    assert _is_transient_ui_container(soup.find("div")) is False


def test_long_container_merely_containing_the_session_phrase_is_not_wholesale_removed():
    """The session-sync phrase is a substring search, so it's guarded to
    only fire on small, leaf-like elements -- a large section that
    happens to CONTAIN this phrase somewhere amid substantial unrelated
    content must not be treated as transient in its entirety."""
    long_text = "Extensive documentation about account security. " * 20
    html = f'<div class="docs-section"><p>{long_text}</p><p>You signed in with another tab or window. Reload to refresh your session.</p></div>'
    soup = BeautifulSoup(html, "html.parser")
    assert _is_transient_ui_container(soup.find("div")) is False


# --- 2. Cookie/privacy UI (regression, generalized wording) --------------

def test_generalized_cookie_privacy_banner_does_not_trigger_tp001():
    banner = """
    <div class="flash flash-notice cookie-notice-banner">
    <p>We use cookies to improve your experience on this site.</p>
    <button>Accept</button>
    </div>
    """
    findings = check_js_render_parity(_raw(), _rendered(banner), "https://code-host.example/pricing")
    assert findings == []


# --- 3. Genuine JS-dependent content (regression) --------------------------

def test_genuine_js_dependent_pricing_content_still_triggers_tp001_after_broadened_filter():
    findings = check_js_render_parity(f.RAW_HTML_JS_HEAVY, f.RENDERED_HTML_JS_HEAVY, "https://acme-saas.example/pricing")
    assert len(findings) == 1
    assert findings[0]["id"] == "TP-001"


# --- 4. Mixed: session flash + genuine substantive content ----------------

def test_mixed_session_flash_and_genuine_content_still_triggers_tp001():
    rendered = f.RENDERED_HTML_JS_HEAVY.replace("</body>", GITHUB_STYLE_SESSION_FLASH + "</body>")
    findings = check_js_render_parity(f.RAW_HTML_JS_HEAVY, rendered, "https://acme-saas.example/pricing")
    assert len(findings) == 1
    assert findings[0]["id"] == "TP-001"
    examples_text = " ".join(findings[0]["evidence"]["examples"])
    assert "signed in" not in examples_text.lower()
    assert "reload" not in examples_text.lower()


# --- 5. Lexical safety (regression, broadened patterns included) ----------

def test_substantive_text_with_login_account_session_privacy_cookie_words_survives():
    """Direct check against the NEW patterns specifically: ordinary
    prose using these words in unrelated sentence structure (not the
    'signed in ... another tab ... reload' idiom, not a flash/notice
    class) must not be classified as transient."""
    html = """<p class="docs-paragraph">Users can log in to their account and maintain a session
    across requests. Our privacy policy explains how session cookies are used to keep you signed
    in.</p>"""
    soup = BeautifulSoup(html, "html.parser")
    assert _is_transient_ui_container(soup.find("p")) is False
