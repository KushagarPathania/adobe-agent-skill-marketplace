"""Static HTML fixtures used across the test suite.

Every fixture is a plain string so tests stay fully offline and
deterministic -- no network access or live site is ever required to run
the tests below.
"""

HOMEPAGE_GOOD = """
<html><head>
<title>Acme Robotics | Home</title>
<meta name="description" content="Acme Robotics designs and manufactures industrial robotic arms for automotive manufacturing plants worldwide.">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Acme Robotics","url":"https://acme-robotics.example"}</script>
</head><body>
<h1>Acme Robotics</h1>
<p>Acme Robotics designs and manufactures industrial robotic arms for automotive manufacturing plants worldwide.</p>
<nav><a href="/about">About</a><a href="/products">Products</a><a href="/contact">Contact</a></nav>
</body></html>
"""

HOMEPAGE_THIN = """
<html><head><title>Home</title></head><body>
<h1>Welcome</h1>
</body></html>
"""

PRODUCT_PAGE_GOOD_SCHEMA = """
<html><head><title>RoboArm X200 | Acme Robotics</title></head><body>
<h1>RoboArm X200</h1>
<p>The RoboArm X200 costs $12,499.00. Add to cart now. In stock.</p>
<script type="application/ld+json">{"@type":"Product","name":"RoboArm X200","offers":{"@type":"Offer","price":"12499.00","priceCurrency":"USD"}}</script>
<a href="/products">Back to Products</a>
</body></html>
"""

PRODUCT_PAGE_MISSING_SCHEMA = """
<html><head><title>Widget Pro | Acme Shop</title></head><body>
<h1>Widget Pro</h1>
<p>Buy now for $49.99. Add to cart today. In stock and ready to ship.</p>
<a href="/shop">Shop more</a>
</body></html>
"""

PRODUCT_PAGE_MISSING_SCHEMA_NO_LINKS = """
<html><head><title>Gadget Max</title></head><body>
<h1>Gadget Max</h1>
<p>Buy now for $19.99. Add to cart today. In stock.</p>
</body></html>
"""

PRODUCT_PAGE_PRICE_MISMATCH = """
<html><head><title>Widget Pro</title></head><body>
<h1>Widget Pro</h1>
<p>Buy now for $149.99. Add to cart. In stock.</p>
<script type="application/ld+json">{"@type":"Product","name":"Widget Pro","offers":{"@type":"Offer","price":"199.99","priceCurrency":"USD"}}</script>
</body></html>
"""

PRODUCT_PAGE_NO_VISIBLE_PRICE_CONTEXT = """
<html><head><title>Widget Pro</title></head><body>
<h1>Widget Pro</h1>
<p>Buy now. Add to cart. In stock. Model 4090, released 2019, weighs 12 units.</p>
<script type="application/ld+json">{"@type":"Product","name":"Widget Pro","offers":{"@type":"Offer","price":"199.99","priceCurrency":"USD"}}</script>
</body></html>
"""

PRODUCT_PAGE_MULTIPLE_LEGITIMATE_PRICES = """
<html><head><title>Widget Pro Plans</title></head><body>
<h1>Widget Pro Plans</h1>
<p>Starter plan: $19.99 per month. Pro plan: starting at $49.99 per month. Enterprise: from $199.99 per month.</p>
<script type="application/ld+json">{"@type":"Product","name":"Widget Pro","offers":{"@type":"Offer","price":"49.99","priceCurrency":"USD"}}</script>
</body></html>
"""

UNIVERSITY_PAGE_WITH_NUMBERS = """
<html><head><title>Admissions | Springfield State University</title></head><body>
<h1>Admissions</h1>
<p>Springfield State University was founded in 1861. The average GPA of admitted students is 3.8,
and the median SAT score is 1400. Room 204 in the admissions building handles enrollment year-round.</p>
<a href="/academics">Academics</a>
</body></html>
"""

FAQ_PAGE = """
<html><head><title>Support FAQ</title></head><body>
<h1>Frequently Asked Questions</h1>
<p>Here are answers to frequently asked questions about our service.</p>
</body></html>
"""

UNIVERSITY_ABOUT_PAGE = """
<html><head><title>Springfield State University | About</title></head><body>
<h1>About Springfield State University</h1>
<p>Springfield State University offers undergraduate and graduate admissions across 40 majors.
Our faculty lead research on campus and support student enrollment year-round.</p>
<a href="/admissions">Admissions</a><a href="/academics">Academics</a>
</body></html>
"""

DOCUMENTATION_PAGE = """
<html><head><title>Getting Started | API Reference</title></head><body>
<h1>Getting Started</h1>
<p>This documentation covers installation, configuration, and the API reference for the SDK.</p>
</body></html>
"""

ARTICLE_HISTORICAL_NO_METADATA = """
<html><head><title>Our Company History</title></head><body>
<h1>Founded in 1998: A Look Back</h1>
<p>The company was founded in 1998 and has grown steadily since. This article was originally published in 2005.</p>
<footer>&copy; 2005 Acme Historical Society</footer>
</body></html>
"""

ARTICLE_HISTORICAL_WITH_METADATA = """
<html><head><title>About Us</title>
<script type="application/ld+json">{"@type":"Article","dateModified":"2015-06-01"}</script>
</head><body>
<h1>Founded in 1998</h1>
<p>Our company, founded in 1998, continues to serve customers today.</p>
</body></html>
"""

STALE_CURRENT_CLAIM_PAGE = """
<html><head><title>2026 Pricing Guide</title>
<script type="application/ld+json">{"@type":"Article","dateModified":"2020-01-01"}</script>
</head><body>
<h1>Current as of 2026</h1>
<p>This pricing guide reflects our current as of 2026 rates.</p>
</body></html>
"""

FRESHNESS_CONFLICT_PAGE = """
<html><head><title>Docs</title>
<script type="application/ld+json">{"@type":"Article","dateModified":"2023-01-01"}</script>
</head><body>
<h1>Documentation</h1>
<p>Last updated on 2021.</p>
</body></html>
"""

DECORATIVE_IMAGE_PAGE = """
<html><body>
<h1>Welcome</h1>
<img src="deco.png" alt="">
<p>Welcome to our homepage where you can learn more about us.</p>
</body></html>
"""

IMPORTANT_INFO_IN_IMAGE_PAGE = """
<html><body>
<h2>Pricing</h2>
<div><img src="pricing-table.png" alt="chart"></div>
</body></html>
"""

NON_IMPORTANT_ISOLATED_IMAGE_PAGE = """
<html><body>
<div><img src="random.png" alt="graphic"></div>
</body></html>
"""

RAW_HTML_JS_HEAVY = """
<html><head><title>Acme SaaS | Pricing</title></head><body>
<div id="app"></div>
</body></html>
"""

RENDERED_HTML_JS_HEAVY = """
<html><head><title>Acme SaaS | Pricing</title></head><body>
<div id="app">
<h1>Pricing Plans</h1>
<h2>Starter Plan</h2>
<p>The Starter plan costs $29 per month and includes 5 seats and API access.</p>
<h2>Enterprise Plan</h2>
<p>The Enterprise plan costs $299 per month and includes unlimited seats.</p>
</div>
</body></html>
"""

ENTITY_HOMEPAGE_ACME = """
<html><head><title>Acme Robotics</title>
<script type="application/ld+json">{"@type":"Organization","name":"Acme Robotics"}</script>
</head><body><h1>Acme Robotics</h1></body></html>
"""

ENTITY_ABOUT_ACME_SUFFIX_ONLY = """
<html><head><title>About</title>
<script type="application/ld+json">{"@type":"Organization","name":"Acme Robotics, Inc."}</script>
</head><body><h1>About</h1></body></html>
"""

ENTITY_ABOUT_DIFFERENT_NAME = """
<html><head><title>About</title>
<script type="application/ld+json">{"@type":"Organization","name":"Zenith Corp"}</script>
</head><body><h1>About</h1></body></html>
"""

MALFORMED_JSON_LD_PAGE = """
<html><head><title>Broken Schema</title>
<script type="application/ld+json">{"@type": "Product", "name": "Bad" ,,, }</script>
</head><body><h1>Broken Schema</h1></body></html>
"""

# --- Generalization-suite fixtures: one representative page per site
# category (in addition to the more targeted fixtures above).

SAAS_HOMEPAGE = """
<html><head><title>CloudSync - Team Collaboration Software</title>
<meta name="description" content="CloudSync is a team collaboration platform with a free trial, API access, and integrations for every workflow.">
</head><body>
<h1>CloudSync</h1>
<p>CloudSync helps teams collaborate in real time. Start your free trial today -- no credit card required.
Includes API key access and integrations with your favorite tools.</p>
<nav><a href="/pricing">Pricing</a><a href="/features">Features</a><a href="/docs">Docs</a></nav>
</body></html>
"""

GOVERNMENT_PAGE = """
<html><head><title>Department of Public Works | City of Springfield</title></head><body>
<h1>Department of Public Works</h1>
<p>The Department of Public Works maintains city infrastructure including roads, water systems, and public
buildings. This is an official government of Springfield public notice page.</p>
<a href="/services">Services</a><a href="/contact">Contact</a>
</body></html>
"""

CORPORATE_ABOUT_PAGE = """
<html><head><title>About Acme Manufacturing Corp</title></head><body>
<h1>About Acme Manufacturing Corp</h1>
<p>Acme Manufacturing Corp is headquartered in Detroit and serves enterprise clients worldwide. Our clients
include Fortune 500 manufacturers across the automotive and aerospace industries.</p>
<a href="/careers">Careers</a><a href="/contact">Contact</a>
</body></html>
"""

STATIC_SIMPLE_PAGE = """
<!DOCTYPE html>
<html><head><title>Jane Doe</title></head><body>
<h1>Jane Doe</h1>
<p>Freelance illustrator based in Portland. Available for commissions.</p>
<a href="mailto:jane@example.com">Email me</a>
</body></html>
"""

NEWS_ARTICLE_PAGE = """
<html><head><title>City Council Approves New Park Funding</title>
<script type="application/ld+json">{"@type":"NewsArticle","headline":"City Council Approves New Park Funding","datePublished":"2026-08-01","dateModified":"2026-08-01"}</script>
</head><body>
<h1>City Council Approves New Park Funding</h1>
<p>The city council voted 6-1 on Tuesday to approve funding for a new park downtown. Construction is expected
to begin next spring and take approximately eight months to complete.</p>
<a href="/news">More News</a>
</body></html>
"""

# --- Realistic large-catalog ecommerce fixture -----------------------
# Regression coverage for two real bugs found via live testing against
# an unseen ecommerce site (not reproduced here): (1) a sitemap-index
# sub-sitemap URL carrying a pagination query string being misread as a
# final page URL instead of being recursed into, and (2) ordinary US
# choice-of-law legal boilerplate ("governed by the laws of the State of
# California") being misread as government-site identity. The structural
# pattern that broke is reproduced exactly; no real site's content is.

ECOMMERCE_ROBOTS_TXT = """User-agent: *
Disallow: /search
Sitemap: https://shopdemo.example/sitemap.xml
"""

# The sitemap INDEX. Its first child sitemap carries a pagination query
# string, exactly like the real-world pattern that broke discovery.
ECOMMERCE_SITEMAP_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://shopdemo.example/sitemap_products_1.xml?from=1&amp;to=500</loc></sitemap>
<sitemap><loc>https://shopdemo.example/sitemap_pages_1.xml</loc></sitemap>
</sitemapindex>
"""

ECOMMERCE_PRODUCTS_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://shopdemo.example/products/trail-runner</loc></url>
<url><loc>https://shopdemo.example/products/wool-loafer</loc></url>
</urlset>
"""

ECOMMERCE_PAGES_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://shopdemo.example/about</loc></url>
</urlset>
"""

# Realistic ecommerce homepage: real nav/product structure, PLUS an
# ordinary legal footer containing both false-positive patterns found
# live -- a properly-capitalized "State of California" inside a genuine
# choice-of-law clause, and the lowercase idiomatic "state of residence"
# -- alongside genuine ecommerce content the classifier should weigh
# instead.
ECOMMERCE_HOMEPAGE_WITH_LEGAL_FOOTER = """
<html><head><title>ShopDemo | Everyday Essentials</title></head><body>
<h1>ShopDemo</h1>
<p>ShopDemo makes everyday essentials from sustainable materials. Add to cart in seconds and enjoy free
shipping on every order.</p>
<nav>
<a href="/products/trail-runner">Trail Runner</a>
<a href="/products/wool-loafer">Wool Loafer</a>
<a href="/collections/new">New Arrivals</a>
</nav>
<footer>
<p>These Terms of Service shall be governed by and construed in accordance with the laws of the
State of California, without regard to conflict of law rules or principles (whether of the
State of California or any other jurisdiction). Depending on your state of residence, you may
have additional consumer rights.</p>
<p>&copy; 2026 ShopDemo, Inc.</p>
</footer>
</body></html>
"""

ECOMMERCE_PRODUCT_PAGE = """
<html><head><title>Trail Runner | ShopDemo</title></head><body>
<h1>Trail Runner</h1>
<p>The Trail Runner costs $98.00. Add to cart now. In stock.</p>
<a href="/collections/new">More new arrivals</a>
</body></html>
"""

# --- Day 3: answerability/quotability fixtures ------------------------
# A generic H1/title ("Overview" / "Home") sitting above a run of short
# navigational/boilerplate fragments -- none of the first several content
# elements carries a real answer. Reproduces the "excessive boilerplate
# before useful content" pattern the answerability check exists to catch.
BOILERPLATE_HEAVY_ARTICLE_PAGE = """
<html><head><title>Home</title></head><body>
<header><nav><a href="/">Home</a><a href="/about">About</a></nav></header>
<h1>Overview</h1>
<p>Menu</p>
<p>Skip to content</p>
<ul><li>Item</li></ul>
<p>Search</p>
<p>Share</p>
<p>Print</p>
</body></html>
"""

# A generic H1 that WOULD be flagged on the heading signal alone, but a
# genuinely substantive opening paragraph is right there -- the two-signal
# AND-gate means this must NOT be flagged (heading generic, but intro
# content is present and accessible).
GENERIC_HEADING_BUT_GOOD_INTRO_PAGE = """
<html><head><title>Overview</title></head><body>
<h1>Overview</h1>
<p>Our return policy allows returns within 30 days of delivery for a full refund, provided the item is
unworn and in its original packaging with tags attached.</p>
</body></html>
"""
