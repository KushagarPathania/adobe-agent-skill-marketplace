---
name: audit-orchestrator
description: Entrypoint skill. Given a website URL, safely discovers a bounded set of representative pages, classifies them, runs the technical/semantic/engagement worker skills over each, and aggregates the results into one schema-compliant JSON report.
license: MIT
compatibility: Python 3.9+; requires beautifulsoup4 and playwright (requirements.txt). Outbound network access required to audit a live site. Playwright's bundled Chromium (`playwright install chromium`) is needed only for rendered-DOM checks -- if unavailable or a render fails, that page falls back to raw-HTML-only analysis, recorded as an audit_diagnostics entry, never a fabricated defect.
---
# Audit Orchestrator

## When to use
Use as the sole entrypoint when diagnosing why a brand may be missing or
misrepresented in AI assistants, or why visitors arriving via a direct AI
citation don't engage. Works on an arbitrary, previously-unseen website --
ecommerce, SaaS, corporate, publisher, education, government,
documentation, nonprofit, hospitality, marketplace, local business, or
portfolio -- without any site-specific configuration.

## Inputs
A target website URL or bare domain, and optional runtime limits
(`AuditConfig`: max pages, timeouts, response size cap).

## Procedure
1. **Security gate.** Validate the target URL with `site-discovery`'s
   `is_safe_url` (scheme, DNS resolution, private/loopback/link-local/
   cloud-metadata ranges). A genuine security rejection (`category ==
   "unsafe"`) refuses the audit with a critical finding; a DNS/network
   resolution failure (`category == "dns_resolution_failed"`) is *not*
   treated as unsafe -- it produces an empty `findings` list and a
   `dns_resolution_failed` entry in `audit_diagnostics` instead, since
   being unreachable right now is not evidence a site is unsafe.
2. **Discovery.** Call `site-discovery` for a bounded, two-hop page
   inventory (sitemap + homepage links + depth-2 exploration), default 8
   pages. A page disallowed by robots.txt is skipped (never fetched) and
   recorded as an `audit_diagnostics` coverage-limitation entry, never as
   a website finding -- respecting robots.txt is correct crawler
   behavior, not a defect. A page that fails to fetch for a network/
   availability reason (timeout, connection failure, further DNS
   failure) is likewise a diagnostic, not a finding; a confirmed bad
   HTTP response on a page that IS allowed to be crawled can still be.
3. **Fetch.** For each candidate page, fetch raw HTML (SSRF-safe,
   redirect-revalidated, size-bounded) and attempt a best-effort headless
   render (browser-level network requests -- of every resource type, not
   only the main document -- are re-validated against the same
   `is_safe_url` safety gate). A render failure is recorded as a tool
   limitation for that one page -- it never halts the audit or the pages
   after it, and never becomes a fabricated "website is broken" finding.
4. **Classify + applicability.** Run `page-classifier` on each page's
   content to get a `page_type` (and, once every page is in, a
   `site_type`), then consult its applicability engine to decide which
   page-type-sensitive checks even apply to this page.
5. **Per-page checks.** Generic checks (JS-render parity, structured-data
   syntax/price-consistency, non-text accessibility, landing-context
   orientation) always run; type-sensitive checks (freshness, answer
   scannability, citation landing experience) only run when applicability
   says so for this page's type.
6. **Site-scope checks.** Once all pages are fetched, run entity
   consistency, AI-discoverability, and navigation/dead-end checks that
   need the full page set.
7. **Aggregate.** First fold together findings from two *different*
   checks describing the same underlying problem on the same page (e.g.
   an entity-clarity finding and a same-page Organization-schema gap),
   preserving the richer finding's evidence. Then deduplicate findings
   that repeat across pages into one site-scope finding with an
   `affected_pages` list, and sort everything by severity x confidence so
   the highest-impact issues surface first.
8. Emit the final JSON report.

## Output
A JSON audit report: `site`, `audited_at`, `summary`
(`total_findings` + severity counts), `findings[]` (`id`, `title`,
`severity`, `confidence`, `scope`, `evidence`, `suggested_action`), a
`metadata` block (site/page classifications, discovery stats, a
human-readable `limitations` list), and `audit_diagnostics[]` -- always
present (empty on a clean run) -- carrying tool-side limitations *and*
coverage limitations (a check that crashed, Playwright unavailable, a
page skipped by the timeout, a DNS/network failure, a robots.txt
exclusion) that must never be confused with an actual finding about the
audited website.

## Implementation
This is the marketplace-facing skill directory (Agent Skills / agentskills.io
format, hyphenated per convention). Its executable logic lives in the
internal `skills_impl` Python package (`skills_impl/audit_orchestrator/`,
underscore-named because Python identifiers cannot contain hyphens) and is
re-exported here at `scripts/orchestrator.py` as a thin, documented shim.
The CLI entrypoint (`run_audit.py` at the marketplace root) invokes this
skill's logic directly. See the root `README.md` ("Agent Skills vs. Python
implementation") for the full rationale.
