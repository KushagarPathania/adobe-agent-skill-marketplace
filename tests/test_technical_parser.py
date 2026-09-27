from skills_impl.technical_parser.scripts.js_render_parity import check_js_render_parity
from skills_impl.technical_parser.scripts.structured_data_validation import check_structured_data
from tests import fixtures as f


def test_js_render_parity_detects_real_content_gap():
    findings = check_js_render_parity(f.RAW_HTML_JS_HEAVY, f.RENDERED_HTML_JS_HEAVY, "https://acme-saas.example/pricing")
    assert len(findings) == 1
    assert findings[0]["id"] == "TP-001"
    assert findings[0]["severity"] == "high"  # headings/paragraphs missing -> structural
    assert findings[0]["evidence"]["url"] == "https://acme-saas.example/pricing"


def test_js_render_parity_ignores_identical_html():
    findings = check_js_render_parity(f.HOMEPAGE_GOOD, f.HOMEPAGE_GOOD)
    assert findings == []


def test_js_render_parity_ignores_timestamps_and_boilerplate():
    raw = "<html><body><p>Welcome</p></body></html>"
    rendered = "<html><body><p>Welcome</p><span>12:45:03</span><div>Accept Cookies</div></body></html>"
    findings = check_js_render_parity(raw, rendered)
    assert findings == []


def test_js_render_parity_ignores_isolated_language_selector_label():
    """Real false positive found in live testing against Wikipedia: a
    lone <label>: 'en' from a language selector was reported as
    'Substantive content requires JavaScript rendering' despite the raw
    and rendered pages being effectively identical. A <label> is a
    UI/form-control element, not factual content, regardless of site."""
    raw = f.RENDERED_HTML_JS_HEAVY  # same substantial content on both sides
    rendered = raw.replace("</body>", "<label>en</label></body>")
    findings = check_js_render_parity(raw, rendered)
    assert findings == []


def test_js_render_parity_ignores_other_isolated_ui_controls():
    """Generalizes beyond <label>: buttons, select/option widgets, and
    form inputs are UI controls, not content, on any website."""
    raw = f.RENDERED_HTML_JS_HEAVY
    rendered = raw.replace(
        "</body>",
        "<button>OK</button><select><option>English</option><option>French</option></select>"
        "<input placeholder='Search'></body>",
    )
    findings = check_js_render_parity(raw, rendered)
    assert findings == []


def test_js_render_parity_ignores_decorative_icon_svg():
    """Decorative/icon SVGs (even ones carrying a <title> sub-element for
    accessibility) are already stripped wholesale before the content
    diff -- locking that in as a regression."""
    raw = f.RENDERED_HTML_JS_HEAVY
    rendered = raw.replace("</body>", "<svg><title>Search Icon</title><path d='M0 0'/></svg></body>")
    findings = check_js_render_parity(raw, rendered)
    assert findings == []


def test_js_render_parity_still_flags_isolated_short_but_meaningful_ui_text_when_structural():
    """The stricter non-structural length gate must not suppress genuine
    short-but-substantive STRUCTURAL content (headings/list items can
    legitimately be short) -- only non-structural leaf noise is filtered."""
    raw = "<html><body><p>Some unrelated filler text that establishes a baseline raw page for comparison purposes here.</p></body></html>"
    rendered = "<html><body><p>Some unrelated filler text that establishes a baseline raw page for comparison purposes here.</p><h2>FAQ</h2></body></html>"
    findings = check_js_render_parity(raw, rendered)
    # The finding must still fire (a short-but-structural heading is not
    # suppressed by the non-structural length gate); severity stays at
    # "medium" here because the rest of the page still overlaps heavily
    # (existing overlap-ratio calibration), not "low"/suppressed.
    assert len(findings) == 1
    assert findings[0]["severity"] == "medium"


def test_js_render_parity_still_flags_genuine_js_injected_paragraph_content():
    """Priority check: the new UI-control exclusion, length gate, and
    near-total-overlap guard must not swallow a real case where
    JavaScript injects substantive factual content that materially
    changes the page -- confirming detection stays intact."""
    findings = check_js_render_parity(f.RAW_HTML_JS_HEAVY, f.RENDERED_HTML_JS_HEAVY, "https://acme-saas.example/pricing")
    assert len(findings) == 1
    assert findings[0]["id"] == "TP-001"
    assert findings[0]["severity"] == "high"


def test_malformed_json_ld_flagged():
    findings = check_structured_data(f.MALFORMED_JSON_LD_PAGE, "https://acme.example/broken", "other")
    ids = [x["id"] for x in findings]
    assert "TP-002" in ids


def test_product_page_missing_schema_flagged_low_severity():
    findings = check_structured_data(f.PRODUCT_PAGE_MISSING_SCHEMA, "https://acme.example/widget", "product")
    schema_findings = [x for x in findings if x["id"] == "TP-003"]
    assert len(schema_findings) == 1
    assert schema_findings[0]["severity"] == "low"


def test_product_schema_present_no_missing_schema_finding():
    findings = check_structured_data(f.PRODUCT_PAGE_GOOD_SCHEMA, "https://acme.example/roboarm", "product")
    assert all(x["id"] != "TP-003" for x in findings)


def test_university_about_page_never_flagged_for_missing_product_schema():
    """False-positive prevention required by the brief: a university page
    must not be judged by ecommerce rules."""
    findings = check_structured_data(f.UNIVERSITY_ABOUT_PAGE, "https://springfield.edu/about", "about")
    assert findings == []


# --- CRITICAL FIX: stable, unique finding ids per missing-schema semantic -
#
# Every "missing expected schema" gap used to share the single id
# "TP-003" regardless of which schema family (Product/Organization/
# FAQPage/Article/Event/Service) was actually missing -- two genuinely
# different problems could reach a report under the same id. Each now
# has its own stable id, fixed by schema family, never derived from
# page order or a per-run counter.

def test_missing_organization_schema_on_homepage_uses_its_own_stable_id():
    html = "<html><head><title>Acme</title></head><body><h1>Acme</h1><p>Welcome.</p></body></html>"
    findings = check_structured_data(html, "https://acme.example/", "homepage")
    ids = [x["id"] for x in findings]
    assert "TP-006" in ids
    assert "TP-003" not in ids


def test_missing_faqpage_schema_uses_its_own_stable_id():
    findings = check_structured_data(f.FAQ_PAGE, "https://acme.example/faq", "faq")
    ids = [x["id"] for x in findings]
    assert "TP-007" in ids
    assert "TP-003" not in ids


def test_missing_article_schema_uses_its_own_stable_id():
    html = "<html><head><title>Big News</title></head><body><h1>Big News Today</h1><p>Story text.</p></body></html>"
    findings = check_structured_data(html, "https://acme.example/news/big-news", "article")
    ids = [x["id"] for x in findings]
    assert "TP-008" in ids
    assert "TP-003" not in ids


def test_missing_event_schema_uses_its_own_stable_id():
    html = "<html><head><title>Conference</title></head><body><h1>Annual Conference</h1><p>Join us.</p></body></html>"
    findings = check_structured_data(html, "https://acme.example/events/annual", "event")
    ids = [x["id"] for x in findings]
    assert "TP-009" in ids
    assert "TP-003" not in ids


def test_missing_service_schema_uses_its_own_stable_id():
    html = "<html><head><title>Consulting</title></head><body><h1>Our Consulting Service</h1><p>We help.</p></body></html>"
    findings = check_structured_data(html, "https://acme.example/services/consulting", "service")
    ids = [x["id"] for x in findings]
    assert "TP-010" in ids
    assert "TP-003" not in ids


def test_missing_product_schema_still_uses_tp003_unchanged():
    """Product keeps its original id -- backward-compat anchor for the
    most common case, unaffected by the new taxonomy."""
    findings = check_structured_data(f.PRODUCT_PAGE_MISSING_SCHEMA, "https://acme.example/widget", "product")
    ids = [x["id"] for x in findings]
    assert "TP-003" in ids


def test_price_mismatch_between_schema_and_visible_text():
    findings = check_structured_data(f.PRODUCT_PAGE_PRICE_MISMATCH, "https://acme.example/widget", "product")
    ids = [x["id"] for x in findings]
    assert "TP-005" in ids


def test_single_ambiguous_price_candidate_gets_medium_not_high():
    """Priority 2 calibration: one disagreeing price-context candidate is
    weaker evidence (could be a different SKU/regional price) than
    multiple candidates all disagreeing -- severity/confidence must
    reflect that, not jump straight to high on a single ambiguous number."""
    findings = check_structured_data(f.PRODUCT_PAGE_PRICE_MISMATCH, "https://acme.example/widget", "product")
    tp005 = [x for x in findings if x["id"] == "TP-005"][0]
    assert tp005["severity"] == "medium"
    assert tp005["confidence"] < 0.7


def test_multiple_disagreeing_price_candidates_gets_high_severity():
    """Strong-evidence case: several visible price-context numbers, none
    matching the schema price, is stronger evidence of a real
    contradiction and should reach high severity."""
    html = """<html><head><title>Widget Pro</title></head><body>
    <h1>Widget Pro</h1>
    <p>Regular price $149.99. Sale price $129.99. Starting at $139.99 for a limited time.</p>
    <script type="application/ld+json">{"@type":"Product","name":"Widget Pro","offers":{"@type":"Offer","price":"199.99","priceCurrency":"USD"}}</script>
    </body></html>"""
    findings = check_structured_data(html, "https://acme.example/widget", "product")
    tp005 = [x for x in findings if x["id"] == "TP-005"][0]
    assert tp005["severity"] == "high"
    assert tp005["confidence"] >= 0.7


def test_no_price_finding_when_page_shows_only_model_numbers_and_years():
    """False-positive prevention (red-team scenario): a page with a
    declared schema price but no visible price-context number at all
    (only a model number and a year) must not be flagged as a
    contradiction -- that would be insufficient evidence, not a mismatch."""
    findings = check_structured_data(f.PRODUCT_PAGE_NO_VISIBLE_PRICE_CONTEXT, "https://acme.example/widget", "product")
    ids = [x["id"] for x in findings]
    assert "TP-005" not in ids


def test_multiple_legitimate_prices_do_not_trigger_false_mismatch():
    """A page listing several real prices (pricing tiers) should not be
    flagged just because most of them differ from the one schema price --
    as long as the schema price appears among them, it's not a
    contradiction."""
    findings = check_structured_data(f.PRODUCT_PAGE_MULTIPLE_LEGITIMATE_PRICES, "https://acme.example/plans", "pricing")
    ids = [x["id"] for x in findings]
    assert "TP-005" not in ids


# --- P0 hardening: currency-code-before-number normalization (real-world
# finding via CNN investigation: "USD 69"-style formatting, code BEFORE
# the number, was not recognized -- only "69 USD" was) -----------------

def test_currency_code_before_number_is_recognized_as_matching_price():
    html = """<html><body><h1>Widget</h1>
    <p>This item costs USD 69 including shipping.</p>
    <script type="application/ld+json">{"@type":"Product","name":"Widget","offers":{"@type":"Offer","price":"69","priceCurrency":"USD"}}</script>
    </body></html>"""
    findings = check_structured_data(html, "https://acme.example/widget", "product")
    assert all(f["id"] != "TP-005" for f in findings)


def test_us_dollar_sign_prefix_form_is_recognized_as_matching_price():
    html = """<html><body><h1>Widget</h1>
    <p>This item costs US$69 including shipping.</p>
    <script type="application/ld+json">{"@type":"Product","name":"Widget","offers":{"@type":"Offer","price":"69","priceCurrency":"USD"}}</script>
    </body></html>"""
    findings = check_structured_data(html, "https://acme.example/widget", "product")
    assert all(f["id"] != "TP-005" for f in findings)


def test_unrelated_nearby_number_still_does_not_satisfy_a_different_price():
    """Conservatism guard: a genuinely different, unrelated price-context
    number elsewhere on the page must not be treated as satisfying an
    unrelated schema price merely because both carry price-shaped
    context -- this is exactly the ambiguity a multi-product page can
    introduce, and the check must not paper over it with a coincidental
    nearby number."""
    html = """<html><body><h1>Roundup</h1>
    <p>Item A is priced at $70. Item B is a completely different product.</p>
    <script type="application/ld+json">{"@type":"Product","name":"Item B","offers":{"@type":"Offer","price":"69","priceCurrency":"USD"}}</script>
    </body></html>"""
    findings = check_structured_data(html, "https://acme.example/roundup", "article")
    tp005 = [f for f in findings if f["id"] == "TP-005"]
    assert len(tp005) == 1
    assert tp005[0]["evidence"]["schema_price"] == 69.0
    assert 70.0 in tp005[0]["evidence"]["visible_price_candidates"]


def test_university_page_with_gpa_and_sat_numbers_never_triggers_price_finding():
    """Red-team scenario: GPA/SAT/room numbers on a university page must
    never be misread as a price, and with no schema price declared at
    all there is nothing to compare against in the first place."""
    findings = check_structured_data(f.UNIVERSITY_PAGE_WITH_NUMBERS, "https://springfield.edu/admissions", "other")
    assert all(x["id"] != "TP-005" for x in findings)


# --- P1 hardening: TP-005 multi-product contextual price association ----
#
# Page-wide price pooling is insufficient on a genuine multi-product page
# (e.g. a roundup article with several distinct JSON-LD Product entries):
# a DIFFERENT product's visible price must never be used as evidence
# against this one. `_extract_product_price_pairs` associates each named
# Product with its own price, and `_contextual_prices_near_product` looks
# only at text near that product's own name (LEVEL 2); when the name
# can't be located at all, or no price is nearby, that product is
# skipped entirely rather than guessed at (LEVEL 3). A single (or
# not distinctly-named) product on the page keeps the exact prior
# page-wide behavior (LEVEL 1) -- already covered by the tests above,
# which are unaffected by this change.

def _multi_product_html(entries, extra_text=""):
    scripts = "".join(
        f'<script type="application/ld+json">{{"@type":"Product","name":"{name}",'
        f'"offers":{{"@type":"Offer","price":"{price}","priceCurrency":"USD"}}}}</script>'
        for name, price, _ in entries
    )
    body_text = "".join(f"<p>{name} costs {text}.</p>" for name, price, text in entries)
    return f"<html><head><title>Roundup</title></head><body><h1>Roundup</h1>{body_text}{extra_text}{scripts}</body></html>"


def test_multiple_products_with_matching_visible_prices_produce_no_finding():
    """3. Product A matches its own nearby visible price -> no finding."""
    html = _multi_product_html([
        ("Product A", "69", "$69"),
        ("Product B", "33", "$33"),
    ])
    findings = check_structured_data(html, "https://acme.example/roundup", "article")
    assert all(f["id"] != "TP-005" for f in findings)


def test_one_of_multiple_products_genuinely_mismatched_still_flagged():
    """4. Product A's own nearby visible price genuinely disagrees with
    its schema price -> a finding for Product A specifically, while
    Product B (correctly matching) is not flagged."""
    html = _multi_product_html([
        ("Product A", "69", "$99"),
        ("Product B", "33", "$33"),
    ])
    findings = check_structured_data(html, "https://acme.example/roundup", "article")
    tp005 = [f for f in findings if f["id"] == "TP-005"]
    assert len(tp005) == 1
    assert tp005[0]["evidence"]["product_name"] == "Product A"
    assert tp005[0]["evidence"]["schema_price"] == 69.0
    assert 99.0 in tp005[0]["evidence"]["visible_price_candidates"]


def test_multiple_products_with_unrelated_prices_elsewhere_no_false_mismatch():
    """5. Product A has no price-context number near its own name at
    all; Product B's and Product C's visible prices exist elsewhere on
    the page but must never be borrowed as 'evidence' against Product A."""
    html = _multi_product_html([
        ("Product A", "69", "is a great choice"),  # no nearby price
        ("Product B", "33", "$33"),
        ("Product C", "99", "$99"),
    ])
    findings = check_structured_data(html, "https://acme.example/roundup", "article")
    assert all(f["id"] != "TP-005" for f in findings)


def test_ambiguous_product_association_when_name_not_found_is_conservative():
    """10. The schema declares a product name that never actually
    appears in the visible text (e.g. a truncated/renamed mention) --
    ambiguous association must not be treated as a mismatch."""
    html = _multi_product_html([
        ("Widget Ultra 5000", "69", "$69"),
        ("Gadget Pro", "33", "$33"),
    ]).replace("Widget Ultra 5000 costs $69.", "This item is a great choice for $70.")
    findings = check_structured_data(html, "https://acme.example/roundup", "article")
    assert all(f["id"] != "TP-005" for f in findings)


def test_aggregate_offer_nested_price_is_correctly_associated_per_product():
    """11 / real-world regression: live investigation against CNN's own
    product-roundup pages found each Product's price declared via a
    nested `AggregateOffer` (`offers: {"@type": "AggregateOffer",
    "offers": [{"@type": "Offer", "price": ...}, ...]}`) -- a standard,
    general schema.org pattern, not specific to that site. The original
    single-level offer lookup found no price for ANY product this way,
    which forced every page like this onto the old page-wide-pooling
    path and produced a schema price vs. a large list of mostly
    unrelated visible numbers -- exactly the ambiguous evidence pattern
    CNN exposed. With nested-offer extraction fixed, each product is
    correctly associated with its OWN price and its OWN nearby visible
    text, and a genuinely matching price now correctly produces NO
    finding instead of a misleading page-wide "mismatch"."""
    html = """<html><head><title>Roundup</title></head><body><h1>Roundup</h1>
    <div class="product-card">
      <h2>Lego Space Explorer Set</h2>
      <p>This delightful set is priced at $70 and includes three astronauts.</p>
    </div>
    <div class="product-card">
      <h2>Lego Ocean Adventure Set</h2>
      <p>This set comes in at $120, a great value for the detail included.</p>
    </div>
    <script type="application/ld+json">{"@type":"Product","name":"Lego Space Explorer Set","offers":
      {"@type":"AggregateOffer","priceCurrency":"USD","lowPrice":70,"highPrice":70,"offerCount":2,
       "offers":[{"@type":"Offer","priceCurrency":"USD","price":70,"seller":"Amazon"},
                 {"@type":"Offer","priceCurrency":"USD","price":70,"seller":"Lego"}]}}</script>
    <script type="application/ld+json">{"@type":"Product","name":"Lego Ocean Adventure Set","offers":
      {"@type":"AggregateOffer","priceCurrency":"USD","lowPrice":120,"highPrice":120,"offerCount":2,
       "offers":[{"@type":"Offer","priceCurrency":"USD","price":120,"seller":"Amazon"},
                 {"@type":"Offer","priceCurrency":"USD","price":120,"seller":"Lego"}]}}</script>
    </body></html>"""
    findings = check_structured_data(html, "https://acme.example/roundup", "article")
    assert all(f["id"] != "TP-005" for f in findings)


def test_aggregate_offer_nested_price_still_flags_a_genuine_per_product_mismatch():
    """Same nested-AggregateOffer shape as above, but one product's own
    nearby visible price now genuinely disagrees with its declared
    price -- must still be flagged, scoped to that product only."""
    html = """<html><head><title>Roundup</title></head><body><h1>Roundup</h1>
    <div class="product-card">
      <h2>Lego Space Explorer Set</h2>
      <p>This delightful set is priced at $85 and includes three astronauts.</p>
    </div>
    <div class="product-card">
      <h2>Lego Ocean Adventure Set</h2>
      <p>This set comes in at $120, a great value for the detail included.</p>
    </div>
    <script type="application/ld+json">{"@type":"Product","name":"Lego Space Explorer Set","offers":
      {"@type":"AggregateOffer","priceCurrency":"USD","lowPrice":70,"highPrice":70,"offerCount":2,
       "offers":[{"@type":"Offer","priceCurrency":"USD","price":70,"seller":"Amazon"},
                 {"@type":"Offer","priceCurrency":"USD","price":70,"seller":"Lego"}]}}</script>
    <script type="application/ld+json">{"@type":"Product","name":"Lego Ocean Adventure Set","offers":
      {"@type":"AggregateOffer","priceCurrency":"USD","lowPrice":120,"highPrice":120,"offerCount":2,
       "offers":[{"@type":"Offer","priceCurrency":"USD","price":120,"seller":"Amazon"},
                 {"@type":"Offer","priceCurrency":"USD","price":120,"seller":"Lego"}]}}</script>
    </body></html>"""
    findings = check_structured_data(html, "https://acme.example/roundup", "article")
    tp005 = [f for f in findings if f["id"] == "TP-005"]
    assert len(tp005) == 1
    assert tp005[0]["evidence"]["product_name"] == "Lego Space Explorer Set"
    assert tp005[0]["evidence"]["schema_price"] == 70.0
    assert 85.0 in tp005[0]["evidence"]["visible_price_candidates"]


def test_single_named_product_page_unaffected_by_multi_product_logic():
    """1/2 (single-product-page baseline, explicit regression lock): a
    page with exactly one named Product keeps the original page-wide
    LEVEL 1 behavior -- both the matching and genuinely-mismatched
    cases, already covered above by
    test_price_mismatch_between_schema_and_visible_text and
    test_product_schema_present_no_missing_schema_finding, are
    unaffected by the new multi-product branch."""
    html = _multi_product_html([("Solo Product", "69", "$69")])
    findings = check_structured_data(html, "https://acme.example/solo", "product")
    assert all(f["id"] != "TP-005" for f in findings)


def test_69_usd_code_after_number_normalization_in_multi_product_context():
    """7. '69 USD' (code after the number) recognized as matching, in
    the multi-product proximity path."""
    html = _multi_product_html([
        ("Product A", "69", "69 USD"),
        ("Product B", "33", "$33"),
    ])
    findings = check_structured_data(html, "https://acme.example/roundup", "article")
    assert all(f["id"] != "TP-005" for f in findings)


def test_69_00_decimal_normalization_in_multi_product_context():
    """9. '69.00' (explicit trailing decimal) recognized as matching."""
    html = _multi_product_html([
        ("Product A", "69", "$69.00"),
        ("Product B", "33", "$33"),
    ])
    findings = check_structured_data(html, "https://acme.example/roundup", "article")
    assert all(f["id"] != "TP-005" for f in findings)


def test_documentation_page_with_code_block_counts_as_structure():
    """Real bug fix: a documentation answer built from a fenced code
    block (no table/list/bold) must not be flagged as unstructured."""
    from skills_impl.engagement_evaluator.scripts.answer_scannability import check_answer_scannability
    html = """<html><head><title>API Reference</title></head><body>
    <h1>API Reference</h1>
    <h2>Documentation: Usage</h2>
    <p>Call the function like this:</p>
    <pre><code>result = do_thing(x, y)</code></pre>
    </body></html>"""
    findings = check_answer_scannability(html, "/docs/usage", "https://acme.example/docs/usage", "documentation")
    assert findings == []
