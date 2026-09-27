import re
from bs4 import BeautifulSoup

from skills_impl.common.schema import make_finding

STRUCTURAL_TAGS = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'td', 'th', 'li', 'dt', 'dd'}
BLOCK_TAGS = {'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'td', 'th', 'tr',
              'article', 'section', 'main', 'ul', 'ol', 'table', 'dl', 'dt', 'dd', 'blockquote'}
# Isolated UI/form-control elements are never "content" in the sense
# this check cares about -- a <label> or <option> naming a language, a
# <button> caption, an <input> placeholder -- regardless of what website
# they appear on. Excluded outright rather than left to the generic
# length/ignore-list heuristics below.
UI_CONTROL_TAGS = {'label', 'button', 'select', 'option', 'optgroup', 'input', 'legend', 'fieldset'}
IGNORE_UI = {
    'loading', 'please wait', 'welcome', 'menu', 'submit', 'search', 'login', 'sign in',
    'close', 'open', 'error', 'success', 'ok', 'cancel', 'accept cookies', 'accept all cookies',
    'we use cookies', 'cookie policy', 'back to top', 'skip to content',
}
# Below this length, an isolated *non-structural* leaf's text reads more
# like a code, abbreviation, or control label ("en", "US", "OK") than a
# factual claim -- headings/list-items/table-cells (STRUCTURAL_TAGS) are
# exempt since those can legitimately be short ("FAQ", "News").
MIN_NONSTRUCTURAL_CONTENT_LENGTH = 4
# A page that is *this* close to a full word-for-word match, with no
# structural content among the residual differences, is not meaningful
# evidence of a real render-dependency problem -- more likely a single
# short control/label whose exact placement doesn't line up byte-for-byte
# with the raw HTML despite the underlying content being unchanged.
NEAR_TOTAL_OVERLAP_THRESHOLD = 0.98

# --- Transient application/browser UI (cookie/privacy consent dialogs,
# auth/session modals, and similar chrome) --------------------------
#
# Real-world finding: a cookie-consent panel (or an auth/session modal)
# that only renders after JavaScript runs can dominate the raw-vs-
# rendered comparison -- its own boilerplate text ("Manage Privacy
# Preferences", "Purposes", "Features", ...) inflates the rendered word
# count and can itself register as "missing structural content", driving
# a false-positive TP-001 escalation that has nothing to do with whether
# the page's actual article/product content needs JavaScript. Detection
# is deliberately STRUCTURAL-first -- ARIA role, aria-modal, the native
# <dialog> element, and id/class NAMING conventions that real consent-
# management platforms (OneTrust, TrustArc, Cookiebot, Quantcast,
# Didomi, Sourcepoint, ...) and auth widgets actually emit -- never a
# blanket scan for words like "privacy"/"cookie"/"account"/"login"/
# "session" in ordinary body text. An article paragraph that happens to
# discuss privacy or cookies is substantive content and must never be
# discarded by this.
# role="alert"/"status" are the standard WAI-ARIA *live-region* roles
# for a transient, one-time status/notification message -- the same
# concept as a "flash" message below, just declared through ARIA instead
# of a naming convention.
_TRANSIENT_UI_ROLES = {"dialog", "alertdialog", "alert", "status"}

_TRANSIENT_UI_ID_CLASS_RE = re.compile(
    # `ident` (built below) joins an element's id with each of its
    # (possibly several) class tokens using spaces -- so a segment
    # boundary is the string start/end, a hyphen/underscore WITHIN one
    # id/class name, OR whitespace BETWEEN separate class names. All
    # three must count as a valid boundary, or a keyword that happens to
    # be its own whole class name (e.g. a standalone class="cookie...")
    # would never match since it isn't hyphen-adjacent to anything.
    r'(?:^|[-_\s])(cookie|consent|gdpr|ccpa|privacy[-_]?(?:preference|manager|choice)|'
    r'onetrust|trustarc|quantcast|cookiebot|didomi|sourcepoint|sp[-_]?message|cmp[-_]|'
    r'sign[-_]?in[-_]?modal|log[-_]?in[-_]?modal|auth[-_]?modal|'
    r'session[-_]?(?:expired|timeout)|stale[-_]?session|'
    # "flash" (a one-time server/client notice banner -- the Rails-
    # originated naming convention, also used by GitHub's Primer design
    # system and many other frameworks) only counts alongside a
    # qualifier that marks it as a transient notice type, never the
    # bare word alone -- so an unrelated "flashcard"/"flash-sale"-style
    # class never matches.
    r'flash[-_](?:warn(?:ing)?|notice|banner|full|error|success|alert|message)|'
    r'modal|overlay|lightbox)(?:[-_\s]|$)',
    re.I,
)

# A small set of idiomatic UI phrases/idioms -- the kind of copy a
# consent/auth/session widget actually ships, never ordinary sentence
# prose -- used only as a SECONDARY signal on an element's own (whole,
# trimmed) text, mirroring the same multi-word-idiom philosophy
# IGNORE_UI already follows for short leaf text elsewhere in this file.
# Exact-phrase entries require the whole text to match; the last
# alternative is a looser PATTERN (not anchored to the full string via
# the outer ^...$) for the common "signed in/out in another tab/window,
# reload to refresh your session" multi-tab-session-sync idiom, which
# varies in exact wording across sites/frameworks but is a well-
# established, generalizable pattern -- not any one site's literal copy.
_TRANSIENT_UI_HEADING_RE = re.compile(
    r'^(manage (privacy|cookie) preferences|cookie (settings|preferences|consent|notice)s?|'
    r'privacy preferences|we (use|value) (your privacy|cookies)|purposes|features|'
    r'your privacy choices|(sign|log) in to continue|session (expired|timeout)|'
    r'your session has expired|please sign in again)$',
    re.I,
)
_TRANSIENT_SESSION_SYNC_RE = re.compile(
    r'signed (in|out).{0,40}(another|different) (tab|window).{0,80}reload.{0,40}(session|refresh)',
    re.I | re.S,
)


def _is_transient_ui_container(tag):
    """True when `tag` is itself the root of a transient UI container
    (a cookie/consent dialog, an auth/session modal, or similar chrome).
    Structural signals are checked first and are sufficient on their
    own; the heading-text signal is a secondary, narrowly-scoped
    fallback for containers that lack proper ARIA semantics or a
    recognizable id/class (a common real-world gap, not a hypothetical
    one) -- it only ever matches a short, exact, idiomatic UI phrase on
    that element's OWN text, never a keyword found anywhere in a larger
    block of prose.
    """
    role = (tag.get('role') or '').strip().lower()
    if role in _TRANSIENT_UI_ROLES:
        return True
    if (tag.get('aria-modal') or '').strip().lower() == 'true':
        return True
    if tag.name == 'dialog':
        return True

    classes = tag.get('class') or []
    if isinstance(classes, str):
        classes = [classes]
    ident = ' '.join([tag.get('id') or '', *classes])
    if ident.strip() and _TRANSIENT_UI_ID_CLASS_RE.search(ident):
        return True

    if tag.name in STRUCTURAL_TAGS or tag.name in ('div', 'p', 'span'):
        own_text = tag.get_text(separator=' ', strip=True)
        if own_text and _TRANSIENT_UI_HEADING_RE.match(own_text.strip()):
            return True
        # The session-sync idiom is a substring search (not a whole-
        # string match like the phrases above), so it's deliberately
        # only tried on SMALL, leaf-like elements -- a genuine notice
        # span/paragraph is short; a large container that merely
        # CONTAINS this phrase somewhere among substantial unrelated
        # content must never be wholesale-removed by it.
        if own_text and len(own_text) < 300 and _TRANSIENT_SESSION_SYNC_RE.search(own_text):
            return True

    return False


# --- Substantive-content vs. UI/control classification (P0 hardening) --
#
# Real-world finding: rendered-only DOM blocks aren't automatically
# evidence that real article/product content requires JavaScript --
# navigation widgets, account/login controls, carousels/pagination, and
# generic reload/action-link chrome commonly render only client-side
# too, without implying anything about the page's actual substantive
# content. This is a SECOND, narrower classification layer applied only
# to items that already survived every earlier filter (ignore list, UI
# control tags, transient-UI stripping, the base length floor) -- it
# never changes what counts as "missing" (the existing whole-page
# overlap-ratio backstop is untouched), only which of those missing
# items are trusted as SUBSTANTIVE evidence for severity/confidence
# escalation. Structural signals (id/class naming) are checked first;
# the action-text idiom list mirrors IGNORE_UI's own "curated multi-word
# phrase, never a bare keyword" philosophy; the length floor for
# non-structural leaves is the same "real paragraph" threshold used
# elsewhere in this project (answerability, landing-context).
_UI_CHROME_ID_CLASS_RE = re.compile(
    r'(?:^|[-_\s])(nav(?:bar|igation)?|menu|breadcrumb|'
    r'(?:user|account|profile)[-_]?(?:menu|nav|dropdown|panel)|'
    r'sign[-_]?(?:in|up)|log[-_]?(?:in|out)|'
    r'carousel|slider|pagination|pager|'
    r'personaliz(?:e|ation)|recommend(?:ed|ation)s?)(?:[-_\s]|$)',
    re.I,
)

_UI_ACTION_TEXT = {
    'reload', 'try again', 'refresh', 'learn more', 'read more', 'view all',
    'see all', 'shop now', 'get started', 'sign up', 'log out', 'sign out',
    'my account', 'add to bag', 'view more', 'show more', 'next', 'previous',
    'skip', 'dismiss', 'got it', 'view profile', 'edit profile',
}

# Real-world false positive found live on github.com/pricing: a
# client-side data-fetch failure renders a short "Uh oh! There was an
# error while loading. Please reload this page." widget -- a transient
# CLIENT ERROR STATE, not page content, regardless of what page it
# appears on. Matched as a substring pattern (not an exact whole-text
# match like `_UI_ACTION_TEXT`) since real sites phrase this slightly
# differently, but it's the same recognizable idiom class.
_UI_LOADING_ERROR_RE = re.compile(
    r'uh oh|oops|something went wrong|error while loading|failed to load|'
    r'please (try again|reload)|reload (this|the) page',
    re.I,
)

_MIN_SUBSTANTIVE_PROSE_LENGTH = 40  # matches the "real paragraph" threshold used elsewhere in this project

# Real-world false positive found live on stripe.com/in/pricing (whole-
# page word overlap 100%) and github.com/pricing (100%): a missing
# item's own EXACT combined text can fail the literal-substring check
# above even when virtually every individual word it's made of already
# exists somewhere in the raw HTML -- a common client-side hydration/
# pricing-variant-swap pattern where the same underlying copy is
# reflowed, reordered, or duplicated across different DOM elements
# server-side vs. client-side, not genuinely new information. Requiring
# a clear majority (not just "some") of an item's own significant words
# to already be present is what keeps this from swallowing genuinely
# new content: verified live against Shopify's and Nike's own genuine
# JS-only pricing/FAQ content, where well under half of any given
# missing item's words already exist in raw.
_ALREADY_REPRESENTED_WORD_RATIO = 0.6


def _id_class_ident(tag):
    """Join a tag's own id with each of its (possibly several) class
    tokens into one space-separated string for regex matching -- the
    same helper shape used for transient-UI id/class detection above.
    """
    classes = tag.get('class') or []
    if isinstance(classes, str):
        classes = [classes]
    return ' '.join([tag.get('id') or '', *classes])


def _is_ui_chrome_missing_item(tag, norm_text, original_text):
    """True when a MISSING item (one that already passed every earlier
    filter) still looks like UI chrome/navigation/account control rather
    than substantive page content. The id/class check walks up the
    ANCESTOR chain too -- a real navigation/account widget typically
    applies its identifying class to a wrapping container
    (`<div class="navbar"><h3>Quick Links</h3>...`), not to every
    individual heading/list-item inside it, so checking only the tag's
    own attributes would miss the vast majority of real-world markup.
    """
    ident = _id_class_ident(tag)
    if ident.strip() and _UI_CHROME_ID_CLASS_RE.search(ident):
        return True
    for ancestor in tag.parents:
        if not hasattr(ancestor, 'get'):
            continue
        ancestor_ident = _id_class_ident(ancestor)
        if ancestor_ident.strip() and _UI_CHROME_ID_CLASS_RE.search(ancestor_ident):
            return True

    if norm_text in _UI_ACTION_TEXT:
        return True

    if _UI_LOADING_ERROR_RE.search(norm_text):
        return True

    # An isolated <a> tag's OWN text (not a link embedded inside a real
    # paragraph -- that would show up as the paragraph's own text, not
    # separately, since a <p> containing an inline <a> is filtered by
    # `has_block_child`/counted as the <p>'s own text) is presumptively
    # navigation/action-link chrome unless it's long enough to actually
    # read like a sentence.
    if tag.name == 'a' and len(original_text) < _MIN_SUBSTANTIVE_PROSE_LENGTH:
        return True

    # Headings/list-items/table-cells (STRUCTURAL_TAGS) are exempt from
    # this length floor -- they can legitimately be short ("FAQ", "News")
    # -- mirroring the same exemption the base missing-item filter above
    # already applies.
    if tag.name not in STRUCTURAL_TAGS and len(original_text) < _MIN_SUBSTANTIVE_PROSE_LENGTH:
        return True

    return False


def _strip_transient_ui(soup):
    """Remove transient UI containers from `soup` IN PLACE -- applied
    once, before any raw-vs-rendered comparison is made, so neither the
    whole-page overlap ratio nor the missing-block detection below can
    be driven by transient application/browser state rather than real
    page content.
    """
    matches = [tag for tag in soup.find_all(True) if _is_transient_ui_container(tag)]
    for tag in matches:
        # A descendant of an already-removed container has no parent by
        # the time we get to it here -- skip it rather than double-
        # decompose (this is the standard, safe bs4 idiom for removing
        # possibly-nested matches found via one upfront find_all pass).
        if tag.parent is not None:
            tag.decompose()


def get_bounded_raw_corpus(soup: BeautifulSoup) -> str:
    soup_copy = BeautifulSoup(str(soup), 'html.parser')

    for tag in soup_copy(['script', 'style', 'template', 'noscript', 'nav', 'footer', 'header', 'aside', 'svg']):
        tag.decompose()
    for tag in soup_copy.find_all(attrs={"hidden": True}):
        tag.decompose()
    for tag in soup_copy.find_all(style=re.compile(r'display\s*:\s*none', re.I)):
        tag.decompose()

    # A letters-only marker survives the same punctuation filter applied
    # below as real content does, so it can't be confused with (or
    # accidentally destroyed by) punctuation that's actually part of the
    # page's own text -- e.g. the "|" in a title like "Acme | Home".
    for tag in soup_copy.find_all(BLOCK_TAGS):
        tag.insert_before(" zzblockzz ")
        tag.insert_after(" zzblockzz ")

    text = soup_copy.get_text(separator=' ').lower()
    text = re.sub(r'[^a-z0-9\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return f" {text.strip()} "


def _is_ignorable(norm_text: str) -> bool:
    if not norm_text or norm_text in IGNORE_UI:
        return True
    # Pure numbers/timestamps (clocks, relative "2 min ago" counters,
    # copyright years) are dynamic UI chrome, not substantive content.
    if re.fullmatch(r'[\d\s:/\-]+', norm_text):
        return True
    return False


def _is_already_represented_elsewhere(norm_text: str, raw_word_set: set) -> bool:
    """True when a MISSING item's own exact combined text doesn't match
    the raw corpus verbatim, but a clear majority of its own individual
    (significant) words already exist somewhere in the raw HTML -- see
    `_ALREADY_REPRESENTED_WORD_RATIO` above for the real-world false
    positives this addresses. A short item with no significant words at
    all (e.g. only 1-2 letter tokens) can't be assessed this way and is
    conservatively treated as NOT already represented, deferring to the
    existing filters instead.
    """
    words = [w for w in norm_text.split() if len(w) > 2]
    if not words:
        return False
    present = sum(1 for w in words if w in raw_word_set)
    return (present / len(words)) >= _ALREADY_REPRESENTED_WORD_RATIO


def _content_overlap_ratio(raw_soup, rend_soup):
    """A coarse, whole-page overlap metric: what fraction of unique
    "words" seen in the rendered text also appear in the raw text. Used
    to tell "a couple of blocks differ but the page is basically the
    same" from "most of the substantive content is missing" -- so a
    handful of missing structural tags on an otherwise-overlapping page
    doesn't get the same severity as a page that's substantially empty
    without JavaScript.
    """
    def words(soup):
        text = soup.get_text(separator=' ').lower()
        text = re.sub(r'[^a-z0-9\s]', '', text)
        return set(text.split())

    raw_words = words(raw_soup)
    rend_words = words(rend_soup)
    if not rend_words:
        return 1.0, 0, 0
    overlap = len(raw_words & rend_words) / len(rend_words)
    return overlap, len(raw_words), len(rend_words)


def check_js_render_parity(raw_html: str, rendered_html: str, url: str = "") -> list:
    raw_soup = BeautifulSoup(raw_html, 'html.parser')
    rend_soup = BeautifulSoup(rendered_html, 'html.parser')

    # Strip transient UI (cookie/consent dialogs, auth/session modals)
    # from the rendered DOM FIRST, before any comparison is made -- so
    # neither the whole-page overlap ratio nor the missing-block
    # detection below can be driven by transient application state
    # rather than real page content. The existing whole-page overlap
    # signal itself is unchanged; only what counts as "rendered content"
    # going into it is refined.
    _strip_transient_ui(rend_soup)

    raw_corpus = get_bounded_raw_corpus(raw_soup)
    raw_word_set = set(raw_corpus.split())
    overlap_ratio, raw_word_count, rendered_word_count = _content_overlap_ratio(raw_soup, rend_soup)

    for tag in rend_soup(['script', 'style', 'noscript', 'nav', 'footer', 'header', 'aside', 'svg']):
        tag.decompose()

    missing_items = {}
    # `missing_structural` now means "a missing STRUCTURAL item that is
    # ALSO substantive content, not UI chrome" -- every downstream line
    # that reads it (the backstop below, severity, confidence) is
    # otherwise completely unchanged, so this one redefinition is what
    # actually implements "base TP-001 severity primarily on substantive
    # rendered-only content" without restructuring the decision logic
    # itself. `ui_chrome_missing_count` is kept only for evidence
    # transparency -- it never influences the decision on its own (the
    # existing overlap-ratio backstop below is untouched).
    missing_structural = False
    substantive_missing = {}
    ui_chrome_missing_count = 0

    for tag in rend_soup.find_all(True):
        if tag.name in UI_CONTROL_TAGS:
            continue

        original_text = tag.get_text(separator=' ', strip=True)
        if not original_text:
            continue

        has_block_child = any(child.name in BLOCK_TAGS for child in tag.find_all(True))
        if has_block_child:
            continue

        norm_text = re.sub(r'[^a-z0-9\s]', '', original_text.lower())
        norm_text = re.sub(r'\s+', ' ', norm_text).strip()
        if _is_ignorable(norm_text):
            continue

        is_structural = tag.name in STRUCTURAL_TAGS
        if not is_structural and len(norm_text) < MIN_NONSTRUCTURAL_CONTENT_LENGTH:
            continue

        search_str = f" {norm_text} "
        if search_str not in raw_corpus and norm_text not in missing_items:
            if _is_ui_chrome_missing_item(tag, norm_text, original_text):
                missing_items[norm_text] = (tag.name, original_text)
                ui_chrome_missing_count += 1
            elif _is_already_represented_elsewhere(norm_text, raw_word_set):
                # Not UI chrome, but this exact combined phrase failing
                # the literal-substring check above while most of its
                # own words already exist somewhere in raw is stronger
                # evidence of DOM restructuring/duplication (a real
                # false-positive class -- see `_ALREADY_REPRESENTED_
                # WORD_RATIO` above) than of genuinely new content.
                # Excluded entirely: neither UI chrome nor trusted
                # substantive evidence, so it affects neither count.
                continue
            else:
                missing_items[norm_text] = (tag.name, original_text)
                substantive_missing[norm_text] = (tag.name, original_text)
                if is_structural:
                    missing_structural = True

    if not missing_items:
        return []

    if not missing_structural and overlap_ratio >= NEAR_TOTAL_OVERLAP_THRESHOLD:
        # The only residual differences are non-structural (or UI
        # chrome) and the page is otherwise a near word-for-word match
        # -- not meaningful evidence of a real render-dependency problem.
        return []

    # Escalate to "high" only when SUBSTANTIVE structural content is
    # missing *and* the page's overall word overlap is meaningfully low
    # -- a couple of missing headings on a page that otherwise overlaps
    # 90%+ is a much weaker signal than most of the page's words being
    # absent from raw. UI-chrome-only differences (navigation, account/
    # login controls, carousels, generic action links) can never reach
    # "high" through this path, since `missing_structural` above is only
    # ever set by a substantive item.
    if missing_structural and overlap_ratio < 0.85:
        severity = "high"
    elif missing_structural:
        severity = "medium"
    else:
        severity = "medium" if overlap_ratio < 0.85 else "low"

    # Conservative cap: the whole-page overlap ratio counts every word on
    # the page, including UI chrome -- so a page whose missing items are
    # EXCLUSIVELY UI/navigation/control chrome (zero substantive items)
    # can still see overlap dip below 0.85 purely from that chrome's own
    # word count, reaching "medium" through the overlap-only branch above
    # with no substantive evidence behind it at all. "Base severity
    # primarily on substantive rendered-only content" applies here too:
    # when there is literally no substantive evidence, this is capped to
    # "low" rather than left to an overlap number that chrome alone can
    # move. The overlap-ratio backstop itself (the branches above) is
    # otherwise completely unchanged.
    if not substantive_missing:
        severity = "low"

    # Evidence prioritizes substantive missing items first (the same
    # "shown evidence must substantiate the claim" principle already
    # used elsewhere in this project) -- a reviewer should see the
    # actual article/product/pricing content driving the finding, not
    # incidental UI chrome that happened to be discovered first.
    ordered_items = list(substantive_missing.values()) + [
        v for k, v in missing_items.items() if k not in substantive_missing
    ]
    sample_items = ordered_items[:4]
    examples = [f"<{tag_name}>: '{text[:60]}{'...' if len(text) > 60 else ''}'" for tag_name, text in sample_items]

    return [make_finding(
        check_id="TP-001",
        title="Substantive content requires JavaScript rendering",
        severity=severity,
        evidence={
            "summary": (
                f"{len(missing_items)} distinct content block(s) appear in the rendered DOM but are absent from "
                f"the raw server HTML ({len(substantive_missing)} classified as substantive content, "
                f"{ui_chrome_missing_count} as UI/navigation/control chrome and excluded from severity scoring). "
                f"Whole-page word overlap between raw and rendered text is "
                f"{overlap_ratio:.0%} (raw: {raw_word_count} unique words, rendered: {rendered_word_count})."
            ),
            "url": url,
            "examples": examples,
            "overlap_ratio": round(overlap_ratio, 2),
            "substantive_missing_count": len(substantive_missing),
            "ui_chrome_missing_count": ui_chrome_missing_count,
        },
        action_summary="Ensure critical factual content is present in the initial server-rendered HTML, not only added via client-side JavaScript.",
        action_priority=severity,
        confidence=(
            0.85 if (missing_structural and overlap_ratio < 0.85)
            else 0.4 if not substantive_missing
            else 0.6
        ),
    )]
