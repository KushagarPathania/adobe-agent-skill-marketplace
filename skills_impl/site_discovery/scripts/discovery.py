"""Bounded page-inventory discovery.

Builds a small, representative set of URLs to audit through a genuinely
bounded two-hop strategy rather than "homepage -> pick top links":

  depth 0: the target page itself
  depth 1: sitemap.xml (via robots.txt, or probed at common locations)
           + links found on the homepage
  depth 2: a handful of the highest-scoring depth-1 pages are fetched
           and their own internal links are folded back into the
           candidate pool (so a page only reachable through one
           intermediate page can still be found)

Every fetch -- at any depth -- goes through `safe_fetch` (SSRF-safe) and
is skipped when robots.txt disallows it. Depth-2 fetching is itself
bounded (a handful of pages, not every depth-1 page) to keep runtime
predictable.
"""
from urllib.parse import urljoin, urlparse, parse_qs, urlencode
from xml.etree import ElementTree
from bs4 import BeautifulSoup

from .fetcher import safe_fetch
from .robots import load_robots, can_fetch

DEFAULT_MAX_PAGES = 8
MAX_SITEMAP_URLS = 200
MAX_DEPTH2_FETCHES = 4          # how many depth-1 pages we'll open to look for more links
COMMON_SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml")

# Tracking/session query params that shouldn't make two URLs count as
# different pages worth separate budget slots.
_NOISE_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                  "ref", "fbclid", "gclid", "sessionid", "session_id"}

# (keyword, weight) -- used to rank which discovered pages/anchors are
# worth spending the page budget on. Matched against both the URL path
# and, separately, the anchor text a link was found under.
PRIORITY_KEYWORDS = [
    ("pricing", 5), ("price", 5), ("plans", 4),
    ("product", 4), ("products", 4), ("shop", 3), ("catalog", 3),
    ("service", 4), ("services", 4), ("solutions", 3), ("solution", 3),
    ("about", 4), ("company", 3),
    ("contact", 3), ("support", 2),
    ("faq", 4), ("help", 2),
    ("docs", 4), ("documentation", 4), ("api", 2), ("guide", 2),
    ("blog", 2), ("news", 2), ("article", 2),
    ("event", 2), ("events", 2),
    ("feature", 2), ("features", 2), ("compare", 2), ("comparison", 2),
    ("category", 2),
]


def _same_site(url, base_netloc):
    try:
        return urlparse(url).netloc.lower() == base_netloc.lower()
    except ValueError:
        return False


def _normalize_url(url):
    """Strip the fragment and known tracking params so the same page
    reached two different ways doesn't consume two budget slots.

    Deliberately does NOT touch a trailing slash: the caller's own
    `base_url` string (with whatever trailing slash it has) is used
    verbatim elsewhere (e.g. the orchestrator's exact-match homepage
    detection), so silently rewriting it here would desync discovery's
    idea of "the target URL" from the orchestrator's.
    """
    url = url.split('#')[0]
    parsed = urlparse(url)
    if parsed.query:
        kept = {k: v for k, v in parse_qs(parsed.query).items() if k.lower() not in _NOISE_PARAMS}
        query = urlencode(kept, doseq=True)
        url = parsed._replace(query=query).geturl()
    return url


def _keyword_score(text):
    text = (text or "").lower()
    score = 0
    for keyword, weight in PRIORITY_KEYWORDS:
        if keyword in text:
            score = max(score, weight)
    return score


def _score_url(url, depth, anchor_text="", has_query=False):
    path = urlparse(url).path
    score = _keyword_score(path) + _keyword_score(anchor_text) * 0.5
    depth_penalty = min(depth, 3) * 1.5
    query_penalty = 0.5 if has_query else 0
    return score - depth_penalty - query_penalty


def _is_sitemap_resource(url):
    """True when `url` is itself a sitemap/discovery resource -- never a
    normal content page -- so it can be excluded from the audit queue at
    the earliest possible point, no matter how it was discovered (a
    sitemap-index entry, a homepage link, a depth-2 link). Always parses
    the URL first and reasons about its PATH (never the raw string or
    the query string), so a query string never defeats or spuriously
    triggers this check either way.

    Two independent shapes both count:
      1. A recognized sitemap file suffix on the path -- ".xml" or
         ".xml.gz" (a standard gzip-compressed-sitemap pattern, e.g.
         WordPress/Yoast). A paginated sub-sitemap such as
         "sitemap_products_1.xml?from=1&to=500" still matches, since the
         query string is never part of what's checked here (a real bug,
         fixed previously: checking the raw string's suffix instead of
         the parsed path misclassified such a sub-sitemap as a final
         page URL instead of recursing into it).
      2. A path with "sitemap" or "sitemaps" as one of its OWN path
         SEGMENTS (e.g. "/sitemaps/google_news", a real pattern for
         Google News sitemaps, which are valid XML sitemap documents
         conventionally served without a ".xml" extension). Matched
         against whole path segments only, never a substring of a
         longer segment -- an ordinary content page whose slug merely
         *contains* "sitemap" (e.g. "/blog/how-to-build-a-sitemap") is
         a different segment ("how-to-build-a-sitemap" != "sitemap")
         and is deliberately NOT matched, so this never becomes a blanket
         "any URL mentioning sitemap" blacklist.
    """
    path = urlparse(url).path.lower()
    if path.endswith('.xml') or path.endswith('.xml.gz'):
        return True
    segments = [s for s in path.split('/') if s]
    return 'sitemap' in segments or 'sitemaps' in segments


def _extract_sitemap_locs(xml_text, limit):
    urls = []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return urls
    for child in root:
        for sub in child:
            if sub.tag.lower().endswith('loc') and sub.text:
                urls.append(sub.text.strip())
                break
        if len(urls) >= limit:
            break
    return urls


def _collect_sitemap_urls(sitemap_urls, timeout, seen_sitemaps):
    """Fetch each sitemap (following one level of sitemap-index nesting)
    and return the page URLs found. `seen_sitemaps` dedupes across calls."""
    found = []
    for sitemap_url in sitemap_urls:
        if sitemap_url in seen_sitemaps or len(seen_sitemaps) >= 5:
            continue
        seen_sitemaps.add(sitemap_url)
        result = safe_fetch(sitemap_url, timeout=timeout, max_bytes=2_000_000)
        if not result["ok"]:
            continue
        entries = _extract_sitemap_locs(result["html"], MAX_SITEMAP_URLS)
        if entries and all(_is_sitemap_resource(e) for e in entries[:5]):
            # This was a sitemap index, not a page list -- descend one level.
            found.extend(_collect_sitemap_urls(entries[:5], timeout, seen_sitemaps))
        else:
            found.extend(entries)
    return found


def _extract_links(html, base_url):
    """Return [(absolute_url, anchor_text), ...] for same-page-relevant
    internal-looking links (mailto/tel/js/fragment-only excluded)."""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        links.append((urljoin(base_url, href), a.get_text(separator=' ', strip=True)))
    return links


def discover_pages(base_url, max_pages=DEFAULT_MAX_PAGES, timeout=10):
    """Return a page inventory:
    {
      base_url, robots_found, sitemap_found, sitemap_url_count,
      homepage_fetch_ok, total_candidates, skipped_disallowed,
      candidate_urls, depth2_pages_explored, depth2_new_urls,
      probed_common_sitemap, weak_internal_linking,
    }
    """
    base_netloc = urlparse(base_url).netloc
    robots_info = load_robots(base_url, timeout=timeout)

    candidates = {}   # normalized url -> {"score": float, "depth": int}
    seen_sitemaps = set()

    def add(raw_url, depth, base_score=0, anchor_text=""):
        url = _normalize_url(raw_url)
        if not url or not _same_site(url, base_netloc):
            return
        # A sitemap/discovery resource is never a normal content page --
        # this is the single, centralized enforcement point every
        # discovered candidate passes through, so it applies uniformly
        # no matter how the URL was found: a sitemap-index entry the
        # recursion heuristic above didn't catch, a literal "Sitemap"
        # link in the homepage's footer, or a link surfaced during
        # depth-2 exploration. It still gets *used* for discovery --
        # `_collect_sitemap_urls` fetches and parses it above -- it just
        # never becomes an auditable page candidate itself. The
        # explicitly-requested target URL (depth 0) is exempt: a caller
        # who deliberately points the audit at a sitemap URL is a
        # different, out-of-scope case this filter shouldn't silently
        # swallow into an empty candidate pool.
        if depth > 0 and _is_sitemap_resource(url):
            return
        has_query = bool(urlparse(url).query)
        score = base_score + _score_url(url, depth, anchor_text, has_query)
        existing = candidates.get(url)
        if existing is None or score > existing["score"]:
            candidates[url] = {"score": score, "depth": depth}

    add(base_url, depth=0, base_score=100)

    # --- depth 1: sitemap (declared in robots.txt, or probed at common
    # locations if robots.txt didn't declare one -- never bypassing a
    # robots.txt disallow rule to do so).
    sitemap_urls = list(robots_info["sitemaps"][:3])
    probed_common_sitemap = False
    if not sitemap_urls:
        for path in COMMON_SITEMAP_PATHS:
            candidate_sitemap = urljoin(base_url, path)
            if can_fetch(robots_info, candidate_sitemap):
                sitemap_urls.append(candidate_sitemap)
                probed_common_sitemap = True

    sitemap_entries = _collect_sitemap_urls(sitemap_urls, timeout, seen_sitemaps)
    sitemap_url_count = len(sitemap_entries)
    for entry in sitemap_entries:
        add(entry, depth=1, base_score=10)

    # --- depth 1: homepage links.
    home = safe_fetch(base_url, timeout=timeout, max_bytes=3_000_000)
    homepage_link_count = 0
    if home["ok"]:
        for link_url, anchor_text in _extract_links(home["html"], base_url):
            if _same_site(link_url, base_netloc):
                homepage_link_count += 1
            add(link_url, depth=1, anchor_text=anchor_text)

    # --- depth 2: open a few of the best depth-1 pages (that robots.txt
    # allows) and fold their links back in, so a page only reachable
    # through one intermediate page (e.g. /products -> /products/x200)
    # can still be discovered. Bounded to MAX_DEPTH2_FETCHES extra fetches.
    depth1_ranked = sorted(
        (u for u, info in candidates.items() if info["depth"] == 1 and can_fetch(robots_info, u)),
        key=lambda u: candidates[u]["score"], reverse=True,
    )
    depth2_pages_explored = 0
    candidates_before_depth2 = set(candidates)
    for url in depth1_ranked[:MAX_DEPTH2_FETCHES]:
        result = safe_fetch(url, timeout=timeout, max_bytes=2_000_000)
        if not result["ok"]:
            continue
        depth2_pages_explored += 1
        for link_url, anchor_text in _extract_links(result["html"], url):
            add(link_url, depth=2, anchor_text=anchor_text)
    depth2_new_urls = len(set(candidates) - candidates_before_depth2)

    skipped_disallowed = []
    allowed = []
    for url, info in candidates.items():
        if can_fetch(robots_info, url):
            allowed.append((url, info["score"]))
        else:
            skipped_disallowed.append(url)

    allowed.sort(key=lambda item: item[1], reverse=True)
    selected = [u for u, _ in allowed[:max_pages]]
    if base_url not in selected and allowed:
        selected = [base_url] + [u for u in selected if u != base_url][:max_pages - 1]

    # A broad, multi-signal "discovery is weak" condition -- never fired
    # from sitemap absence alone (a site can be perfectly discoverable
    # through strong internal linking with no sitemap at all).
    weak_internal_linking = (
        sitemap_url_count == 0
        and homepage_link_count < 5
        and depth2_new_urls < 2
    )

    return {
        "base_url": base_url,
        "robots_found": robots_info["found"],
        "sitemap_found": sitemap_url_count > 0,
        "sitemap_url_count": sitemap_url_count,
        "probed_common_sitemap": probed_common_sitemap,
        "homepage_fetch_ok": home["ok"],
        "homepage_link_count": homepage_link_count,
        "depth2_pages_explored": depth2_pages_explored,
        "depth2_new_urls": depth2_new_urls,
        "total_candidates": len(candidates),
        "skipped_disallowed": skipped_disallowed[:20],
        "candidate_urls": selected,
        "weak_internal_linking": weak_internal_linking,
    }
