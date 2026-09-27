---
name: site-discovery
description: SSRF-safe URL validation, bounded HTTP fetching, robots.txt handling, and a representative page-inventory builder (sitemap + homepage links). Used by the orchestrator before any content check runs.
license: MIT
compatibility: Python 3.9+; requires beautifulsoup4 (see requirements.txt). Outbound network access (HTTP/HTTPS) is required to fetch pages, robots.txt, and sitemaps. No Playwright/Chromium dependency of its own -- rendered-DOM fetching is handled separately by `audit-orchestrator`.
---
# Site Discovery

## When to use
Use whenever a check needs to reach a website: validating that a target
URL is safe to fetch, fetching a page's raw HTML, or building a bounded
list of pages worth auditing on an unfamiliar site.

## Inputs
A target URL (and, for discovery, a max-page count and timeout).

## Procedure
1. **URL safety (`security.py`).** Reject disallowed schemes, embedded
   credentials, `localhost`/`.internal`/`.local` hosts, and any hostname
   that resolves (via real DNS) to a private, loopback, link-local
   (including cloud metadata endpoints), reserved, multicast, or
   unspecified address. Every resolved address is checked, not just the
   first, to resist a host that answers with a mix of public and private
   records. A DNS resolution failure is categorized separately from a
   genuine security rejection (`"dns_resolution_failed"` vs `"unsafe"`)
   -- both refuse to fetch, but only the latter is ever reported as a
   security finding. This same check is reused to validate browser-level
   (Playwright) network requests, not only the raw HTTP path -- see
   Implementation below for the documented boundary of that coverage.
2. **Bounded fetch (`fetcher.py`).** Re-validate safety on every redirect
   hop (redirects are never auto-followed), cap response size on the
   *decompressed* body (so a small gzip response can't expand past the
   limit in memory), transparently decode gzip/deflate, and classify any
   request-time failure (`timeout`, `connection_failed`,
   `dns_resolution_failed`, `network_failure`, `http_error`) so a caller
   can tell an availability problem apart from an actual HTTP response.
3. **robots.txt (`robots.py`).** Fetch and parse robots.txt through the
   same safe fetcher. Missing/unreachable robots.txt is treated as
   permissive, per convention; found rules are always honored -- a page
   robots.txt disallows is never fetched, and the orchestrator records
   that exclusion as a coverage-limitation diagnostic, never a website
   defect.
4. **Discovery (`discovery.py`).** A bounded two-hop strategy: prefer
   sitemap.xml (declared in robots.txt, following one level of sitemap
   index, or probed at common locations like `/sitemap.xml` when robots
   declares none -- never bypassing a disallow rule to do so); pull
   links from the homepage; then open a handful of the best-scoring
   depth-1 pages and fold their links back in, so a page only reachable
   through one intermediate page can still be found. Candidates are
   scored by URL-path and anchor-text keywords (pricing, product, about,
   faq, docs, contact, ...) and the top N are returned. This is
   representative sampling under a bounded runtime, not exhaustive
   crawling -- the page-count cap and total-audit timeout are this
   project's own calibrated defaults, not a threshold the handout
   mandates. Disallowed URLs are recorded and excluded, never fetched.

## Output
`is_safe_url(url) -> (ok, reason, category)` where `category` is
`"safe"`, `"unsafe"`, or `"dns_resolution_failed"`; `safe_fetch(url, ...) -> dict`
(`ok`, `html`, `status`, `headers`, `truncated`, `error`, `error_category`);
`discover_pages(url, ...) -> dict` (`candidate_urls`, `robots_found`,
`sitemap_found`, `skipped_disallowed`, `weak_internal_linking`,
`depth2_pages_explored`, ...).

## Implementation
This is the marketplace-facing skill directory (Agent Skills / agentskills.io
format, hyphenated per convention). Its executable logic lives in the
internal `skills_impl` Python package, at `skills_impl/site_discovery/scripts/`
(underscore-named because Python identifiers cannot contain hyphens),
imported by `audit-orchestrator`. See the root `README.md` ("Agent Skills
vs. Python implementation") for the full rationale.
