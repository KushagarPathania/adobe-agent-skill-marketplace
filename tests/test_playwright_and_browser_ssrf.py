"""Day 5 (Adobe submission QA) focused regression tests for:

1. Playwright/browser render configuration (Priority 3) -- the browser
   context's User-Agent, the Chromium launch configuration, render
   failure/timeout handling, and diagnostic generation.
2. Browser-level SSRF protection (Priority 4) -- `_install_ssrf_guard`'s
   request interceptor now covers every resource type, not only the
   main document.

All Playwright interaction here is mocked/simulated with fake `route`/
`request`/`context` objects exposing the same shape Playwright's real
API does (`.url`, `.resource_type`, `.abort()`, `.continue_()`,
`.route()`) -- these are NOT real browser/network tests; no Chromium is
launched. `test_orchestrator_integration.py` separately covers the
raw-HTML-fallback / diagnostic-vs-finding behavior end-to-end with
`PLAYWRIGHT_AVAILABLE=False`.
"""
import skills_impl.audit_orchestrator.scripts.orchestrator as orch
import skills_impl.site_discovery.scripts.fetcher as fetcher_mod


# --- Priority 3: browser render configuration ----------------------------

def test_browser_user_agent_is_modern_and_not_bot_styled():
    """The browser context announces a normal modern desktop-browser
    identity, not the honest-bot string used for raw HTTP."""
    ua = orch.BROWSER_USER_AGENT
    assert "Mozilla" in ua and "Chrome" in ua
    assert "bot" not in ua.lower()
    assert "BrandAIReadinessAudit" not in ua


def test_browser_user_agent_is_distinct_from_raw_http_user_agent():
    """Raw HTTP fetching (and robots.txt matching, which is
    UA-independent -- see robots.DEFAULT_USER_AGENT="*") keeps its own,
    separate, transparent bot-identifying string -- unaffected by the
    browser-context change."""
    assert orch.BROWSER_USER_AGENT != fetcher_mod.USER_AGENT
    assert "BrandAIReadinessAudit" in fetcher_mod.USER_AGENT


def test_render_page_returns_clean_diagnostic_when_playwright_unavailable(monkeypatch):
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", False)
    html, error = orch._render_page("https://example.com/", 5000)
    assert html == ""
    assert "Playwright is not installed" in error


def test_render_page_failure_is_a_tool_limitation_not_an_exception(monkeypatch):
    """A Playwright launch/navigation exception must be caught and
    returned as (empty html, error string) -- never raised up to the
    caller, and never fabricated into a website finding."""
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", True)

    class _FakeSyncPlaywrightCtx:
        def __enter__(self):
            raise RuntimeError("simulated browser launch failure")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(orch, "sync_playwright", lambda: _FakeSyncPlaywrightCtx())
    html, error = orch._render_page("https://example.com/", 5000)
    assert html == ""
    assert "simulated browser launch failure" in error


def test_render_page_timeout_still_returns_partial_dom(monkeypatch):
    """A navigation timeout is swallowed (a partially-loaded DOM is still
    useful) rather than treated as a hard failure -- retain existing
    timeout-tolerant behavior."""
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", True)

    class _FakePage:
        def goto(self, url, timeout, wait_until):
            raise orch.PlaywrightTimeoutError("simulated timeout")

        def content(self):
            return "<html><body>partial</body></html>"

    class _FakeContext:
        def new_page(self):
            return _FakePage()

        def route(self, pattern, handler):
            pass

    class _FakeBrowser:
        def new_context(self, user_agent):
            assert user_agent == orch.BROWSER_USER_AGENT
            return _FakeContext()

        def close(self):
            pass

    class _FakeChromium:
        def launch(self, headless):
            assert headless is True
            return _FakeBrowser()

    class _FakeSyncPlaywrightCtx:
        def __enter__(self):
            return type("P", (), {"chromium": _FakeChromium()})()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(orch, "sync_playwright", lambda: _FakeSyncPlaywrightCtx())
    html, error = orch._render_page("https://example.com/", 5000)
    assert html == "<html><body>partial</body></html>"
    assert error is None


# --- Priority 4: browser-level SSRF (subresource coverage) ---------------

class _FakeRequest:
    def __init__(self, url, resource_type):
        self.url = url
        self.resource_type = resource_type


class _FakeRoute:
    def __init__(self, url, resource_type):
        self.request = _FakeRequest(url, resource_type)
        self.aborted = False
        self.continued = False

    def abort(self):
        self.aborted = True

    def continue_(self):
        self.continued = True


class _FakeContext:
    def __init__(self):
        self.handler = None

    def route(self, pattern, handler):
        self.handler = handler


def test_is_request_url_allowed_blocks_localhost():
    assert orch._is_request_url_allowed("http://localhost/") is False


def test_is_request_url_allowed_blocks_private_ip():
    assert orch._is_request_url_allowed("http://192.168.1.1/") is False


def test_is_request_url_allowed_allows_safe_public_request():
    assert orch._is_request_url_allowed("http://8.8.8.8/") is True


def test_unsafe_document_request_is_aborted():
    ctx = _FakeContext()
    orch._install_ssrf_guard(ctx)
    route = _FakeRoute("http://127.0.0.1/", "document")
    ctx.handler(route)
    assert route.aborted is True
    assert route.continued is False


def test_unsafe_subresource_request_is_also_aborted():
    """The fix: before Priority 4, only resource_type=='document' was
    checked -- an <img>/<script>/<iframe>/XHR request to a private
    target would have been silently allowed through. Every resource
    type must now go through the same safety check."""
    ctx = _FakeContext()
    orch._install_ssrf_guard(ctx)
    for resource_type in ("script", "image", "stylesheet", "iframe", "font", "xhr", "fetch", "media", "other"):
        route = _FakeRoute("http://169.254.169.254/latest/meta-data/", resource_type)
        ctx.handler(route)
        assert route.aborted is True, f"resource_type={resource_type} was not blocked"
        assert route.continued is False


def test_redirect_hop_to_private_ip_is_blocked():
    """Playwright dispatches a new routable request for each redirect
    hop -- simulated here by invoking the handler directly with the
    post-redirect URL, exactly as Playwright would for that hop."""
    ctx = _FakeContext()
    orch._install_ssrf_guard(ctx)
    route = _FakeRoute("http://10.0.0.5/internal-admin", "document")
    ctx.handler(route)
    assert route.aborted is True


def test_safe_public_document_and_subresource_requests_continue():
    ctx = _FakeContext()
    orch._install_ssrf_guard(ctx)
    for resource_type in ("document", "script", "image", "xhr"):
        route = _FakeRoute("http://8.8.8.8/asset", resource_type)
        ctx.handler(route)
        assert route.continued is True
        assert route.aborted is False
