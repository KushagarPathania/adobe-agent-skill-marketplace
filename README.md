# Brand AI-Readiness Audit

A read-only Agent Skill Marketplace that audits an arbitrary, previously
unseen website for two things: **can AI systems reliably discover,
extract, and answer questions from it**, and **does a human who arrives
via a direct AI citation actually stay and engage**. It produces one
evidence-backed JSON report, not a giant SEO checklist.

Built for Adobe University Hackathon 2026, Round 3 -- "Build the Agent
Skill Marketplace."

## 1. Problem

AI assistants increasingly answer questions about brands, products, and
services directly -- often without a click-through. A site can be
invisible or misrepresented to those assistants for reasons that have
nothing to do with classic SEO: content only exists after JavaScript
runs, key facts are locked inside an image, structured data contradicts
the visible page, or a visitor who *does* click through from an AI
citation lands on a page with no orientation and no next step. There was
no general, evidence-based way to diagnose this across arbitrary sites.

## 2. Solution

An orchestrated pipeline of reusable Agent Skills that: safely discovers
a small representative set of pages on a site, classifies what each page
and the site itself actually *are*, and then runs targeted, page-type-
aware checks for machine-readability and on-site engagement -- emitting
findings with evidence, confidence, severity, and a specific suggested
action, deduplicated and sorted so the worst problems surface first.

## 3. Why Agent Skills

The task decomposes naturally into reusable units of reasoning: fetching
and discovery is one concern, classification is another, and the actual
"is this a problem" judgment splits cleanly along technical / semantic /
engagement lines. Each skill has a single, real responsibility and a
narrow input/output contract, which is what makes this a genuine
composition rather than one large script wearing skill folders as a
costume: `page-classifier`'s output is what makes `technical-parser` and
`engagement-evaluator` page-type-aware instead of hardcoding rules.

## 4. Architecture

```
target URL
    |
    v
SECURITY GATE (site-discovery: is_safe_url) -- SSRF-safe, or refuse;
    |                                          a DNS/network failure here
    |                                          is a diagnostic, not a
    |                                          "this site is unsafe" claim
    v
DISCOVERY (site-discovery) -- robots.txt, sitemap (declared or probed at
    |                         common paths), homepage + depth-2 links.
    |                         A robots.txt exclusion is recorded as a
    |                         coverage-limitation diagnostic, never a
    |                         website finding.
    v
BOUNDED PAGE INVENTORY (default: 8 pages, ranked by relevance)
    |
    v
for each page: FETCH (raw + best-effort rendered; browser-level network
    |                requests of every resource type -- not only the
    |                main document -- are SSRF-checked the same way)
    |                -> CLASSIFY (page-classifier)
    |                -> APPLICABILITY (page-classifier: which
    |                   type-sensitive checks even apply to this page)
    v
TECHNICAL / MACHINE READABILITY   ENGAGEMENT (citation landing experience:
(technical-parser)                orientation, answer visibility,
    |                              meaningful-link continuation, dead-end)
    |                              (engagement-evaluator)
    +----------------+------------------+
                     |
                     v
        SEMANTIC / AI DISCOVERABILITY
        (semantic-analyzer -- page-level
         answerability/quotability, plus
         site-scope: entity consistency,
         reachability, entity clarity,
         proactive recommendations)
                     |
                     v
   OVERLAP MERGE + DEDUPLICATION + PRIORITIZATION
        (audit-orchestrator: aggregate.py)
                     |
                     v
     FINAL JSON REPORT (findings + audit_diagnostics)
```

## 5. Skills

| Skill | Role |
|---|---|
| `audit-orchestrator` | **Entrypoint.** Composes every skill below into one run and emits the final report. |
| `site-discovery` | SSRF-safe URL validation, bounded fetching, robots.txt, sitemap-driven page inventory. |
| `page-classifier` | Explainable page-type and site-type classification from multi-signal heuristics, plus an applicability engine deciding which type-sensitive checks apply to a given page. |
| `technical-parser` | Raw-vs-rendered content parity, structured-data validity and page-type-relevant completeness. |
| `semantic-analyzer` | Non-text-content accessibility, freshness, entity-name consistency, AI-discoverability (reachability, multi-signal entity clarity), page-level answerability/quotability for content pages, and proactive (non-defect) improvement opportunities. |
| `engagement-evaluator` | Landing-page orientation, answer scannability, meaningful-link continuation, dead-end detection, and an aggregate "citation landing experience" judgment across all three. |

### Agent Skills vs. Python implementation

Each marketplace skill directory is named with a hyphen
(`audit-orchestrator`, `site-discovery`, ...) per Agent Skills /
agentskills.io convention, and contains a `SKILL.md` (name, description,
license, When to use / Inputs / Procedure / Output). Python cannot import
a package whose name contains a hyphen, so the actual executable logic
lives in a separate internal Python package, `skills_impl/`
(underscore-named subpackages, exactly mirroring the skill names:
`skills_impl/audit_orchestrator/`, `skills_impl/site_discovery/`, etc.,
plus `skills_impl/common/` for helpers shared across all of them). This
is a deliberate, documented split -- not two copies of the same logic --
between the marketplace-facing "skin" (`skills/`) and the Python
implementation (`skills_impl/`). `run_audit.py` (the CLI, at the
marketplace root) invokes `skills_impl.audit_orchestrator` directly; the
entrypoint skill folder (`skills/audit-orchestrator/scripts/orchestrator.py`)
additionally carries a thin, documented shim re-exporting that same
implementation, so it has a literal, importable entry script of its own
too. Every other skill folder is `SKILL.md`-only (each SKILL.md
documents exactly where its real implementation lives) -- both patterns
are shown in the handout's own illustrative marketplace layout, where
only the entrypoint skill bundles a `scripts/` folder.

Each `SKILL.md` also declares a `compatibility` field (in addition to
the required `name`/`description`/`license`) stating its actual runtime
requirements -- Python version, which of `beautifulsoup4`/`playwright`
it needs, whether it requires outbound network access, and (for
`audit-orchestrator` specifically) that Playwright's bundled Chromium is
needed only for rendered-DOM analysis and is never assumed to succeed.
All six skills validate cleanly against `skills-ref` (the
agentskills.io reference validator, run via `npx skills-ref validate
<skill_path>`), including this `compatibility` field.

**Package layout** (mirrors `marketplace.json`):

```
marketplace.json          # manifest: 6 skills, 1 entrypoint
README.md
run_audit.py               # CLI wrapper around skills_impl.audit_orchestrator's run_audit()
requirements.txt
conftest.py
skills/                    # Agent Skills / agentskills.io marketplace skin (what you zip)
  audit-orchestrator/       # entrypoint
    SKILL.md
    scripts/orchestrator.py   # thin shim -> skills_impl.audit_orchestrator
  site-discovery/
    SKILL.md
  page-classifier/
    SKILL.md
  technical-parser/
    SKILL.md
  semantic-analyzer/
    SKILL.md
  engagement-evaluator/
    SKILL.md
skills_impl/                # internal Python implementation (underscore-named)
  audit_orchestrator/
    scripts/{orchestrator,aggregate,config}.py
  site_discovery/
    scripts/{discovery,fetcher,robots,security}.py
  page_classifier/
    scripts/{classifier,applicability}.py
  technical_parser/
    scripts/{js_render_parity,structured_data_validation}.py
  semantic_analyzer/
    scripts/{non_text_accessibility,content_freshness,entity_consistency,
              ai_discoverability,answerability}.py
  engagement_evaluator/
    scripts/{landing_context,answer_scannability,navigation_signals,
              citation_landing_experience}.py
  common/                   # shared helpers, not itself a marketplace skill
    schema.py
tests/                     # offline, deterministic pytest suite (366 tests)
```

## 6. How the skills compose

`audit-orchestrator` is the only skill meant to be invoked directly.
Everything else is a plain Python function it calls with explicit
arguments -- there's no hidden shared state. `site-discovery` produces
the page inventory (a page robots.txt disallows is recorded there as a
`skipped_disallowed` URL, surfaced later as an `audit_diagnostics`
coverage-limitation entry -- never fetched, never a website finding);
the orchestrator fetches each page and hands the resulting HTML to
`page-classifier`. The classification (`page_type`) feeds two things:
`technical-parser`'s schema-relevance table, and `page-classifier`'s own
applicability engine, which decides whether page-type-sensitive checks
(freshness, answer scannability, dead-end detection, citation landing
experience, answerability) even run for that page -- a low-confidence
classification degrades to the conservative "other" row rather than
forcing type-specific checks onto a guess. Once every page is processed,
`semantic-analyzer`'s site-scope checks (entity consistency, AI
discoverability, proactive recommendations) and `engagement-evaluator`'s
navigation check run over the full page set.
The orchestrator then folds together findings that describe the same
underlying problem from two different checks (e.g. a same-page entity-
clarity finding and a schema-gap finding both citing missing
Organization/WebSite data), deduplicates repeats across pages, and
prioritizes before emitting the report. `semantic-analyzer`'s proactive
recommendations (currently just AI-005) are collected into their own
`opportunities` list instead, deliberately bypassing that same merge/
dedup/prioritize pipeline -- an opportunity is never folded against, or
ranked alongside, a detected-defect finding.

Two more gates run per page before the type-sensitive checks: whether
this page's headless render actually succeeded (`rendered_dom` vs.
`raw_html_fallback` -- see Output) and whether its `<html lang>`
indicates a supported language. Four checks that reason from structural
*absence* (landing-context orientation, answer scannability, citation
landing experience, answerability) are conservatively skipped, not run
on a best-effort guess, whenever either gate fails for that page; every
other check (structured data, non-text accessibility, freshness, JS
render parity) is unaffected by both gates. The language gate also
reaches two of `semantic-analyzer`'s site-scope checks: AI-003 (entity
clarity) is skipped for the homepage's own `<html lang>`, and AI-005
(the proactive FAQ suggestion) is skipped for the run when an audited
product page is in an unsupported language -- in both cases because
that specific check's evidence comes from an English-vocabulary
heuristic (generic-placeholder-title detection; the English FAQ-phrase/
heading match), not because the whole semantic-analyzer skill is
disabled. AI-001 (reachability) and every other site-scope check are
purely structural and unaffected either way.

## 7. Setup & input

```bash
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium   # one-time browser download; see note below
python3 run_audit.py https://example.com
```

The Chromium install step is a genuine, separate download (the
`playwright` *package* alone does not include a browser binary) --
without it, rendering is unavailable and the audit automatically falls
back to raw-HTML-only checks, recording that as an `audit_diagnostics`
entry (`type: "render_unavailable"`) rather than failing or pretending
the page is broken. Running the audit does not require Chromium to be
installed; it only loses the JS-render-parity check without it.

Input is a URL or bare domain, plus optional runtime limits
(`AuditConfig`): `max_pages` (default 8), `request_timeout`,
`render_timeout_ms`, `total_audit_timeout`, `max_response_bytes`.

```bash
python3 run_audit.py https://example.com
python3 run_audit.py example.com --max-pages 5 --total-timeout 60
```

## 8. Output

```jsonc
{
  "site": "...",
  "audited_at": "...",
  "summary": { "total_findings": N, "critical": N, "high": N, "medium": N, "low": N },
  "findings": [
    {
      "id": "TP-001", "title": "...", "severity": "high", "confidence": 0.85,
      "scope": "page" | "site",
      "evidence": { "summary": "...", "url": "...", "examples": [...] },
      "suggested_action": { "summary": "...", "priority": "high" }
    }
  ],
  "opportunities": [
    {
      "id": "AI-005", "title": "...", "confidence": 0.4, "scope": "site",
      "evidence": { "summary": "...", "affected_pages": [...] },
      "suggested_action": { "summary": "...", "priority": "low" }
    }
  ],
  "metadata": {
    "site_type": "...", "pages_discovered": N, "pages_selected": N, "pages_audited": N,
    "robots_txt_found": true, "limitations": [...],
    "page_analysis": { "https://...": { "analysis_mode": "rendered_dom" | "raw_html_fallback" } },
    "coverage": {
      "candidate_pages_discovered": N, "pages_selected": N, "pages_successfully_audited": N,
      "robots_skipped_pages": N, "timeout_or_network_skipped_pages": N,
      "runtime_limit_unaudited_pages": N, "represented_page_types": [...], "coverage_limitations": [...]
    }
  },
  "audit_diagnostics": [
    { "type": "render_failed", "check": "check_js_render_parity", "page_url": "...", "error_type": null, "message": "..." }
  ]
}
```

`metadata` and `audit_diagnostics` are additive context beyond the
schema the challenge requires (`site`, `audited_at`, `summary`,
`findings`, and each finding's `id`/`title`/`severity`/`evidence`/
`suggested_action`, which are always present). `audit_diagnostics` is
always present (as `[]` when nothing went wrong) and is where tool-side
limitations live -- a check that crashed, Playwright being unavailable,
a page skipped by the audit timeout, a DNS/network failure, a robots.txt
exclusion, reduced coverage from a raw-HTML fallback, or an unsupported-
language limitation -- so a limitation of the *audit tool or its
coverage* can never be confused with a *website finding*. See Security
and Findings vs. opportunities vs. diagnostics below for why this
distinction exists.

**`opportunities`** (new, additive; always present, `[]` when there are
none) holds proactive, evidence-backed suggestions that go beyond a
detected defect -- exactly what the handout calls out as optional but
rewarded ("Suggestions may go beyond the detected problems"). `summary`
is computed from `findings` only; nothing in `opportunities` ever
affects `total_findings` or any severity count, and opportunities are
never merged/deduplicated against findings (see How the skills compose).

**`metadata.page_analysis`** records, per audited URL, whether this
audit actually rendered the page (`"rendered_dom"`) or fell back to raw
server HTML (`"raw_html_fallback"`) -- raw HTML is never presented as
equivalent to a rendered DOM. **`metadata.coverage`** is purely
informational bookkeeping (discovered vs. selected vs. successfully
audited page counts, robots/timeout/runtime skip counts, the page types
actually represented in this run) -- a small, bounded sample is never
itself treated as a defect.

## 9. Generalization

No skill hardcodes a domain, CMS, framework, language, or currency --
including for the specific false positives found and fixed during
development (see Testing below): the fix for Wikipedia's language-gateway
homepage is a structural detector (many links to sibling subdomains, or
a large `<select>`) usable on *any* multi-language site, not a
Wikipedia-specific carve-out. `page-classifier` derives `page_type`/
`site_type` from weighted, transparent signals (URL path, title,
headings, JSON-LD `@type`, structural patterns) -- never a single
keyword. Schema expectations in `technical-parser` come from a
`page_type -> expected schema` lookup table, so a university "about"
page is never told it's missing Product schema, and a documentation page
is never judged by ecommerce rules. All thresholds referenced in this
document (page counts, link counts, keyword-repetition minimums,
confidence cutoffs) are this project's own calibrated heuristics, not
values the Adobe Round 3 handout mandates -- the handout deliberately
leaves those choices to the submission.

Verified live against real, unrelated sites during development: MIT's
site classified as `education`; python.org and GitHub's documentation
classified as `documentation`/`corporate` with zero ecommerce-rule
findings; Wikipedia's language-gateway homepage no longer misreported as
a discovery failure or dead end. See the known `site_type` limitation
below, though -- it isn't perfectly stable on every large, topically
broad page.

## 10. Evidence model

Every finding's `evidence` is a structured object, not a vague string:
a `summary` sentence plus, where applicable, `url`, `element`/`selector`,
concrete `examples`, or (for a deduplicated site-scope finding)
`affected_pages` and a few `representative_evidence` samples. A finding
always states what was found, where, and why it matters; `suggested_action`
always states a concrete fix.

## 11. Confidence model

`severity` (how bad the problem is) and `confidence` (how sure the check
is that it's real) are tracked separately and never conflated -- a
finding can be `severity: high, confidence: 0.55` (a real problem *if*
it's real, but the signal is indirect) as legitimately as `severity: low,
confidence: 0.95`. `skills_impl/audit_orchestrator/scripts/aggregate.py` sorts findings by
`severity_weight x confidence` (with a small site-scope boost) so the
report reads top-down as "fix these first," not a flat list of equally
weighted warnings.

## 12. Security

Every outbound HTTP request goes through `is_safe_url`
(`skills_impl/site_discovery/scripts/security.py`): disallowed schemes,
embedded credentials, `localhost`/`.internal` hostnames, and any hostname
whose DNS resolution includes even one private, loopback, link-local
(covers cloud metadata endpoints like `169.254.169.254`), reserved,
multicast, or unspecified address are refused. This gate runs on the
initial target **and again on every redirect hop** (redirects are
followed manually, never automatically) so a redirect can't smuggle the
fetch to an internal host. Response bodies are size-capped on the
*decompressed* output, guarding against a decompression-bomb-style
response.

**Browser-level (Playwright) requests reuse the same `is_safe_url`
check, for every resource type it issues** -- not only the main document.
A route handler (`context.route("**/*", handler)`) intercepts every
HTTP(S) request a rendered page makes (document, script, image,
stylesheet, iframe, font, XHR/fetch, media, and any other resource type
Playwright's routing mechanism sees) and aborts it if `is_safe_url`
rejects the URL; because Playwright dispatches a new routable request
for each redirect hop, a redirect to a private address is caught the
same way. The browser identifies as a normal modern desktop browser
(`context.new_context(user_agent=...)`), not a bot string -- distinct
from the raw-HTTP fetcher's own, separately-preserved, transparent
bot-identifying User-Agent (robots.txt matching is itself
UA-independent: `can_fetch` always checks against `"*"`). Chromium is
launched via Playwright's own bundled browser (`p.chromium.launch()`,
installed by `playwright install chromium`) -- never a user's separately
installed system browser.

**Documented boundary, not a claim of perfect protection:** Playwright's
request-routing mechanism does not intercept WebSocket connections (a
documented Playwright limitation), so a page that opens a WebSocket to
an internal address during the bounded, read-only `domcontentloaded`
render is not covered by this specific guard. No skill in this
marketplace executes user-driven page interactions or authenticates
against a site, which limits what a rendered page can actually do over
such a connection in that window -- but this is a known, accepted gap,
stated here rather than glossed over.

**A DNS/network failure is never reported as a security or website
finding.** `is_safe_url` returns `(ok, reason, category)`, where
`category` is `"unsafe"` (a genuine security rejection -- blocked, full
stop, reported as a critical `ORCH-000` finding) or
`"dns_resolution_failed"` (the host simply couldn't be resolved/reached
right now -- not evidence it's unsafe). The same distinction runs
through the actual fetch: a request-time DNS failure, timeout, or
connection error is categorized (`dns_resolution_failed`, `timeout`,
`connection_failed`, `network_failure`) and recorded as an
`audit_diagnostic`, with `findings` staying empty and
`metadata.network_unreachable: true` -- never a fabricated critical
"this website is broken" claim. Verified live: a nonexistent domain
produces `audit_diagnostics: [{"type": "dns_resolution_failed", ...}]`
and zero findings, while a loopback/link-local target still produces the
critical `ORCH-000` exactly as before.

**Respecting robots.txt is correct crawler behavior, not a website
defect.** A page robots.txt disallows is never fetched, and is recorded
as a `{"type": "robots_exclusion", "page_url": ..., "message": ...}`
`audit_diagnostics` entry -- it never appears in `findings` and never
inflates `summary.total_findings` or any severity count (verified live:
see Testing).

**HTTP 401/403 is treated as ambiguous, not automatically escalated.** A
confirmed access-denied response on the requested target used to be
reported at `severity: "high", confidence: 0.9` just like any other
fetch failure. It's now its own finding (`ORCH-003`, `severity:
"medium"`, `confidence: 0.4`) with evidence that states the ambiguity
plainly: a blocked crawler is itself a real Round-2 discoverability
failure mode, but it can also be an artifact of *this specific audit
run's* own request signature rather than something a real AI assistant's
crawler would hit the same way. Every other HTTP error status keeps the
original, unmodified `ORCH-001` behavior.

## 13. Runtime limits

All bounded by `AuditConfig`: page inventory capped (default 8, never an
unbounded crawl), per-request timeout, per-page render timeout, a total
wall-clock audit budget after which remaining pages are skipped (and the
skip is recorded, not silently dropped), redirect count, and response
size.

## 14. Testing

**366 tests**, `python3 -m pytest -q` (offline, deterministic -- no test
depends on network access or a live site). Covers both true positives
and explicit false-positive prevention, across 27 test files:

- **Security** (`test_security.py`, `test_fetcher.py`): loopback/private/
  link-local/cloud-metadata IPs, IPv6, bad schemes, embedded credentials
  (including the classic `user@internal-host` userinfo bypass trick),
  DNS-rebinding-style multi-answer resolution, DNS failure explicitly
  distinguished from a security rejection, request-time timeout/
  connection-failure classification, and a redirect-to-private-address
  attempt confirmed still blocked.
- **Discovery** (`test_discovery.py`, `test_sitemap_resource_filtering.py`):
  sitemap-index following, common sitemap-path probing when robots.txt
  declares none (never bypassing a disallow rule to do it), depth-2 link
  exploration, robots.txt disallow enforcement, page-count bound,
  duplicate-homepage-entry regression, offline via monkeypatched fetch.
  Real bug fix found live against real sites: a sitemap-index child
  resource with no recognized extension (e.g. a Google News sitemap
  path with no ".xml" at all) or served gzip-compressed (".xml.gz") was
  not recognized as "itself a sitemap resource, not a content page,"
  and could enter the audit-page candidate pool -- where its lack of an
  H1/breadcrumb/title then triggered a false orientation-context
  finding. `_is_sitemap_resource` now recognizes both forms plus a bare
  "sitemap(s)" path segment, applied both during sitemap-index recursion
  and as a defense-in-depth filter in the candidate-page queue itself.
- **Classification & applicability** (`test_classifier.py`,
  `test_applicability.py`, `test_generalization.py`): product/FAQ/
  documentation/homepage detection across ten site categories
  (ecommerce, SaaS, news, university, documentation, government,
  corporate, JS-heavy, static, image-heavy); a university about-page is
  confirmed *not* classified as a product page; a low-confidence
  classification is confirmed to skip type-specific checks rather than
  force them.
- **Technical parser** (`test_technical_parser.py`): real JS-render gaps
  detected; identical raw/rendered HTML produces zero findings;
  boilerplate/timestamps/UI-control elements (labels, buttons, selects,
  decorative SVG) ignored; malformed JSON-LD flagged; price-mismatch
  detection requires price-shaped context (currency symbol/word) so
  spec numbers like "256GB" or "2019" never trigger a false price
  finding; currency-format equivalents (`$69`, `US$69`, `USD 69`, `69
  USD`, `69.00`) all normalize to the same value. On a page declaring a
  single (or not distinctly-named) product, price matching stays the
  original page-wide comparison. On a genuine **multi-product** page
  (several distinctly-named JSON-LD `Product` entries -- e.g. a roundup
  article), each product is instead checked only against price-context
  text inside its own smallest enclosing DOM container (list item,
  table row/cell, card, paragraph), never against a different product's
  visible price elsewhere on the page; when a product's name can't be
  located in any such container, or no price-shaped number is inside
  it, that product is conservatively skipped rather than flagged on
  ambiguous evidence. Real bug fix found via live testing against a
  real product-roundup page: `Product.offers` can itself be a nested
  `AggregateOffer` wrapping a list of per-seller `Offer` entries several
  levels deep -- a single-level offer lookup found no price for any
  product this way, which silently fell back to page-wide pooling and
  produced a misleading "schema price vs. 20 unrelated visible numbers"
  finding; price extraction now walks the offers structure to arbitrary
  depth, regardless of how deeply `AggregateOffer`/`Offer` nesting goes.
- **TP-001 content classification** (`test_tp001_content_classification.py`,
  `test_tp001_transient_ui.py`): rendered-only DOM blocks are classified
  as substantive content (headings/paragraphs/article/product text,
  tables, lists) vs. UI/navigation/control chrome (nav menus, login/
  account widgets, carousels/pagination, isolated short action links)
  before severity is decided -- a UI-only rendered difference caps at
  low severity/confidence even when the pre-existing overlap-ratio
  backstop alone would have scored higher, while genuine JS-dependent
  article/product/table/list content still reaches high; evidence
  reports `substantive_missing_count`/`ui_chrome_missing_count`/
  `overlap_ratio` and shows the real substantive content first, not the
  chrome, when both are present. Transient session/consent UI (modal
  dialogs, cookie-consent panels, stale-session-flash notices) is
  stripped before the comparison entirely, separately from this
  classification.
- **Semantic analyzer** (`test_semantic_analyzer.py`): decorative
  empty-alt images never flagged; info-bearing isolated images flagged
  high, decorative-looking ones flagged low; **"Founded in 1998" is
  confirmed to never be read as a staleness signal**; entity clarity
  distinguishes a signal being *present* from being *meaningful* (a
  clear brand with no Organization schema is not flagged; schema alone
  does not excuse a page whose visible title/H1 are "Home"/"Welcome");
  entity-name consistency confidence scales with how lopsided the
  disagreement is.
- **Engagement & citation landing experience**
  (`test_engagement_evaluator.py`, `test_citation_landing_experience.py`):
  breadcrumb/orientation detection; a short well-written paragraph is
  never flagged as "unscannable" (only genuinely dense unstructured
  prose is); meaningful links (related products, pricing, support) are
  distinguished from generic boilerplate (privacy/terms/cookies/login),
  which does not count as useful continuation; a language-gateway
  homepage (many links to sibling subdomains, or a large `<select>`) is
  confirmed *not* to be flagged as a discovery failure or dead end, while
  an ordinary homepage with genuinely no navigation still is.
- **Deduplication** (`test_aggregate.py`, `test_calibration_fixes.py`):
  same-check findings across multiple pages merge into one site-scope
  finding; two *different* checks describing the same underlying
  problem on the same page (an entity-clarity finding and a same-page
  Organization-schema gap; a citation-landing-experience finding and
  the individual dimension findings it already restates) fold into one,
  with evidence preserved, not discarded -- and unrelated findings are
  confirmed to never merge. A merged finding's severity, `confidence`,
  and `suggested_action.priority` all track the same worst-severity
  instance (not an arbitrary first-iterated page), and that instance's
  own check-specific evidence fields (e.g. TP-001's
  `substantive_missing_count`, TP-005's `schema_price`) are carried
  forward onto the merged finding's top-level `evidence`, not left
  visible only inside a nested `representative_evidence` sample.
  `test_calibration_fixes.py` also locks in the SaaS/ecommerce
  "checkout"-word hospitality-classifier fix found via live testing
  against a real payments/ecommerce site.
- **Orchestrator integration** (`test_orchestrator_integration.py`,
  `test_red_team.py`): full pipeline offline via monkeypatched network
  calls -- report schema (including `audit_diagnostics` always present),
  a check crashing becomes a diagnostic rather than a fake website
  finding, rendering-unavailable and DNS/network failures are diagnostics
  rather than critical findings, cross-page dedup, priority ordering,
  SSRF-blocked targets, and a consolidated ten-scenario false-positive
  red-team suite (excellent page gets few findings, weak evidence never
  reaches high/critical, spec numbers never fake a price mismatch, etc.).
- **Answerability / quotability** (`test_answerability.py`, AI-004):
  a specific heading is enough evidence on its own even if the fuller
  answer sits further down the page; a generic heading is excused by a
  genuinely substantive opening paragraph/list/table; ecommerce, gateway,
  and utility page types are excluded entirely (never even evaluated),
  by construction rather than by a runtime suppression rule.
- **Proactive recommendations** (in `test_semantic_analyzer.py`, AI-005):
  a product site with no audited FAQ page gets one low-confidence,
  clearly-labeled improvement suggestion referencing real discovered
  product URLs; suppressed when a FAQ page exists, when there are no
  product pages, or (Day 4) when a product page already contains an
  embedded FAQ heading/schema.
- **Day 4 adversarial red-team** (`test_day4_adversarial.py`, plus new
  cases in `test_discovery.py`): a systematic pass re-testing every
  finding against unseen-site patterns known to fool deterministic
  auditors, including live runs against real, unrelated sites. Found and
  fixed three real false positives: a documentation/FAQ *hub* page (H1
  matching its own shallow URL segment, e.g. "/docs" titled
  "Documentation") was wrongly flagged for poor orientation; an
  icon-only control labelled via `aria-label` on its *wrapping*
  `<button>`/`<a>` (the standard accessible-icon pattern, not on the
  icon itself) was wrongly flagged as inaccessible; and a SaaS/fintech
  pricing page naming a "Checkout" product (plus an unrelated incidental
  price mention) was misclassified as an ecommerce product page, purely
  because the classifier's cart-intent regex trusted the bare word
  "checkout" as strongly as unambiguous phrases like "add to cart" --
  found live on a real (unnamed, non-hardcoded) site. Also confirms
  existing, unmodified behavior on: malformed/truncated sitemap XML,
  cross-domain sitemap pollution, tracking-parameter URL duplicates,
  table/list-based answers, mixed-type and ambiguous JSON-LD `@type`
  values, and code-block-based documentation answers.
- **Access-denied render safety** (`test_access_denied_safety.py`): a
  real false-positive class found live against a real news site -- the
  RAW HTTP fetch succeeds with genuine article content, but the
  separate Playwright render step gets a bot-management access-denied
  interstitial instead. `_is_access_denied_page` recognizes this only
  when a page's own title/H1 exactly matches a curated, well-known
  block-page phrase AND its body text is short (a genuine interstitial
  is minimal; a real article merely mentioning "access" is not
  penalized); the interstitial is never compared against the real raw
  content as if it were "the rendered page" (which had backwards
  produced a false TP-001 "requires JavaScript" finding), and never
  analyzed for orientation context as if it were the actual deep page
  (which had produced a false EE-001 finding) -- recorded instead as an
  `access_denied` coverage-limitation diagnostic.
- **Playwright / browser render config & browser-level SSRF**
  (`test_playwright_and_browser_ssrf.py`): the browser context's
  User-Agent is confirmed modern-browser-like and distinct from the raw
  HTTP fetcher's own bot-identifying string; a Playwright launch/
  navigation exception is caught and returned as a clean error, never
  raised; a navigation timeout still returns the partially-loaded DOM;
  and -- the actual fix -- an unsafe request is now aborted for every
  resource type (document, script, image, stylesheet, iframe, font,
  XHR/fetch, media, other), not only `resource_type == "document"` as
  before, while a safe public request of any resource type still
  continues normally. Playwright interaction is mocked (fake
  `route`/`request` objects); these are not live-browser tests.
- **Diagnostics vs. findings separation** (`test_diagnostics_vs_findings.py`):
  a robots.txt exclusion produces an `audit_diagnostics` entry, never a
  `findings` entry, with `summary` counts staying correct and the audit
  continuing on the pages that remain allowed; an HTTP 401/403 produces
  the recalibrated `ORCH-003` (medium severity, low confidence) instead
  of the generic high-severity `ORCH-001`, while every other HTTP error
  status keeps the original `ORCH-001` behavior unchanged; and no
  diagnostic `type` value ever collides with a finding `id`.
- **Opportunities separation** (`test_opportunities.py`): AI-005 appears
  only in `opportunities`, never `findings`; `opportunities` never
  affects any `summary` count; the required opportunity fields
  (`id`/`title`/`evidence`/`suggested_action`/`confidence`) are present;
  and an opportunity's `id` is confirmed disjoint from every finding
  `id` (never deduplicated against one).
- **Raw HTML vs. rendered DOM safety** (`test_raw_vs_rendered_safety.py`):
  `metadata.page_analysis` correctly reports `rendered_dom` or
  `raw_html_fallback` per page; the four structural-absence checks
  (landing context, answer scannability, citation landing experience,
  answerability) run normally when rendering succeeds and are
  conservatively skipped -- with a `render_reduced_coverage` diagnostic
  naming exactly which ones -- when it didn't, while structured-data and
  non-text-accessibility checks keep running either way; a render
  failure never becomes a website finding.
- **Language safety** (`test_language_safety.py`): `<html lang="en">`/
  `"en-US"`/missing/empty/malformed all preserve current (English)
  behavior exactly; an explicit unsupported language (e.g. `"fr"`,
  `"de"`, `"ja"`) conservatively skips the same four English-vocabulary-
  dependent checks (with a `language_unsupported` diagnostic, never a
  finding, naming which ones), while language-independent checks keep
  running. The two site-scope semantic-analyzer checks with their own
  English-vocabulary heuristics are gated the same way: AI-003 (entity
  clarity -- generic-placeholder-title/H1 detection) is skipped for an
  unsupported-language homepage while AI-001 (reachability, purely
  structural) on that same homepage is confirmed unaffected; AI-005
  (the proactive FAQ suggestion, whose only suppression signal is the
  English phrase/heading "frequently asked questions"/"FAQ(s)") is
  skipped for a run where an audited product page is in an unsupported
  language, rather than risking a false "no FAQ found" suggestion.
- **Coverage metadata** (`test_coverage_metadata.py`): every
  `metadata.coverage` field is present and reuses existing inventory/
  diagnostic/classification data (no redundant crawling); a small,
  bounded, sitemap-less sample is confirmed to never itself become a
  finding.
- **Regression-lock adversarial suite** (`test_p1_adversarial_stability.py`):
  a dedicated pass confirming already-hardened behavior holds on
  scenarios a calibration review specifically probed for, without
  changing the underlying logic (site-type classification and AI-004
  answerability were reviewed and found not to need a change this
  pass): SaaS/ecommerce/documentation/publisher classification from
  combined structural signals rather than an isolated keyword;
  government/hospitality classification not triggered by an isolated
  incidental word (e.g. ordinary "checkout" language on a SaaS site);
  an answerable article with a specific heading not flagged; a
  sparse-but-specifically-titled page not penalized for being short;
  FAQ and generic documentation-hub pages never even evaluated by
  answerability, by construction.

Beyond the offline suite, the pipeline was exercised **live** against
real, unrelated public sites (python.org, MIT, GitHub Docs, Wikipedia)
during development -- this is how several real bugs were actually found
and fixed, not merely asserted safe: a gzip/deflate decoding bug (a
plain `dict()` of response headers lost case-insensitive lookup,
corrupting every compressed response into binary noise), a
homepage-detection bug on deep-URL targets, an FAQ-classifier and a
government-classifier false positive from a single incidental keyword
match, an isolated `<label>` UI control read as "missing content," and
Wikipedia's language-gateway homepage misread as a discovery failure.

## 15. Example execution

```bash
$ python3 run_audit.py https://docs.python.org/3/
```

## 16. Example report

Real output from a fresh run (`page_classifications` and
`representative_evidence` trimmed for brevity -- everything else is
verbatim; note `audit_diagnostics` is present and empty on a clean run).
This also shows `pages_discovered` (every candidate URL found before
ranking/selection) now correctly differing from `pages_selected` (the
bounded top-N actually chosen) -- a metadata-naming fix from the latest
hardening pass:

```json
{
  "site": "docs.python.org",
  "audited_at": "2026-09-13T07:44:13.711413+00:00",
  "summary": { "total_findings": 1, "critical": 0, "high": 0, "medium": 0, "low": 1 },
  "findings": [
    {
      "id": "TP-001",
      "title": "Substantive content requires JavaScript rendering",
      "severity": "low",
      "confidence": 0.6,
      "scope": "site",
      "evidence": {
        "summary": "Detected on 8 page(s): 1 distinct content block(s) appear in the rendered DOM but are absent from the raw server HTML (1 classified as substantive content, 0 as UI/navigation/control chrome and excluded from severity scoring). Whole-page word overlap between raw and rendered text is 88% (raw: 186 unique words, rendered: 212).",
        "affected_pages": ["https://docs.python.org/3/", "https://docs.python.org/3.10/", "..."]
      },
      "suggested_action": {
        "summary": "Ensure critical factual content is present in the initial server-rendered HTML, not only added via client-side JavaScript.",
        "priority": "low"
      }
    }
  ],
  "metadata": {
    "site_type": "documentation",
    "site_type_confidence": 0.55,
    "pages_audited": 8,
    "pages_discovered": 133,
    "pages_selected": 8,
    "robots_txt_found": true,
    "sitemap_found": true,
    "pages_blocked_by_robots": 0,
    "playwright_available": true,
    "page_classifications": { "...": { "page_type": "documentation", "confidence": 0.58, "applicable_checks": ["answer_scannability", "citation_landing_experience", "navigation_dead_end"] } },
    "limitations": []
  },
  "audit_diagnostics": []
}
```

Real `audit_diagnostics` excerpt from a separate live run against an
unrelated ecommerce site, demonstrating the `robots_exclusion` coverage
diagnostic in practice (Priority 5, Section 12): two pages the site's
own robots.txt disallowed were discovered but correctly never fetched,
and never appear in `findings`:

```json
"audit_diagnostics": [
  { "type": "robots_exclusion", "check": null, "page_url": "https://www.allbirds.com/search",
    "error_type": null, "message": "Page was discovered but not audited because robots.txt disallowed crawling." },
  { "type": "robots_exclusion", "check": null, "page_url": "https://www.allbirds.com/policies/privacy-policy",
    "error_type": null, "message": "Page was discovered but not audited because robots.txt disallowed crawling." }
]
```

## 17. Limitations

- Classification is heuristic, not ML -- a page with unusual or sparse
  content can land in `other`/`low confidence` rather than a specific
  type. That's treated as a feature (checks gated on a type don't fire
  on a low-confidence guess) rather than patched over.
- Discovery is intentionally bounded (representative coverage, not a
  full crawl); a very large site's long tail of pages is not audited.
- Corroboration is internal-only (cross-page and structured-data-vs-text
  consistency). No external fact-checking API is used, in keeping with
  the requirement to stay provider-neutral and not fabricate
  corroboration from a single source.
- If Playwright cannot launch in the runtime environment, rendering is
  skipped and recorded as a `limitations` entry; raw-HTML-only checks
  still run. This is reported as a tool limitation, never as a false
  "website is broken" finding.
- Heuristic text checks (freshness claims, FAQ detection, entity-name
  extraction) can still occasionally mis-classify unusual page
  structures; severity/confidence are kept conservative specifically to
  bound the damage such misses can do to report quality.
- `site_type` classification (`classify_site`) is keyword-based and not
  perfectly stable on very long, topically broad pages: live testing
  against Wikipedia's own AI article currently produces `saas` (a long
  article discussing AI-as-a-service business models can legitimately
  mention "subscription"/"API" more than the two-occurrence
  co-occurrence threshold requires). This is a known, unfixed limitation
  of that one signal -- `site_type` is report metadata, not a finding,
  and doesn't affect any finding's severity or confidence, but it should
  not be read as authoritative on long, general-topic content. (A
  similarly-caused `government` misclassification found earlier in
  development was fixed by requiring more specific phrases, e.g.
  "department of public works" rather than a bare "department of".)
- This audit does not claim to work correctly on every website. It has
  been exercised against a modest set of real, unrelated public sites
  (see Testing) plus 366 offline regression tests; a genuinely novel
  page structure can still produce a false positive or negative that
  hasn't been found yet.
- Browser-level SSRF protection covers every resource type Playwright's
  request routing intercepts, but not WebSocket connections (a
  documented Playwright limitation) -- see Security. This is not claimed
  to be perfect SSRF protection, only a documented, defensible boundary.
- Language support is intentionally narrow: `SUPPORTED_LANGUAGES = {"en"}`.
  A page whose `<html lang>` names a different language conservatively
  skips only the checks that depend on English vocabulary -- the four
  per-page checks (landing-context orientation, answer scannability,
  citation landing experience, answerability), plus two site-scope
  semantic-analyzer checks with their own English-vocabulary heuristics
  (AI-003 entity clarity, gated on the homepage's own language; AI-005's
  proactive FAQ suggestion, gated when an audited product page is in an
  unsupported language). Missing/malformed `lang`, AI-001 (reachability,
  purely structural), and every other check are unaffected. This is not
  a multilingual semantic-analysis capability -- it's a narrow, honest
  opt-out for content the implementation cannot actually read, not
  support for those languages.
- Live testing surfaced one cosmetic (non-functional) side effect of
  broadening browser-level SSRF interception to every resource type:
  Playwright can print harmless `asyncio.CancelledError` traceback noise
  to stderr during browser teardown on some real sites (observed live
  against a real ecommerce site). This does not affect the exit code,
  the JSON output's validity, or any finding/diagnostic -- confirmed on
  the same run that produced it -- but it is stderr noise this project
  does not currently suppress.
