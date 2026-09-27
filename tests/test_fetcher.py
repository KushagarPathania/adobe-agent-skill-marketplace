"""Regression tests for the raw-HTML fetcher, in particular gzip/deflate
Content-Encoding handling. A real bug caught during manual live testing:
a plain dict built from `resp.headers` loses the header's built-in
case-insensitivity, so looking it up as "Content-Encoding" silently
missed a lowercase "content-encoding" header and left compressed bytes
undecoded -- which would have misread nearly every gzip-serving site on
the web as "missing all of its content without JavaScript".
"""
import email.message
import gzip
import socket
import urllib.error
import zlib

import skills_impl.site_discovery.scripts.fetcher as fetcher_mod
from skills_impl.site_discovery.scripts.fetcher import _decode_body, _classify_fetch_exception, safe_fetch


def test_gzip_body_is_decompressed_case_insensitively():
    original = "<html><body><h1>Hello</h1></body></html>"
    compressed = gzip.compress(original.encode("utf-8"))

    # The header name case seen on real servers (python.org) is lowercase.
    text, ok, error = _decode_body(compressed, "gzip", max_bytes=1_000_000)
    assert ok is True, error
    assert text == original

    text, ok, error = _decode_body(compressed, "GZIP", max_bytes=1_000_000)
    assert ok is True, error
    assert text == original


def test_deflate_body_is_decompressed():
    original = "<html><body><p>Deflate test</p></body></html>"
    compressed = zlib.compress(original.encode("utf-8"))
    text, ok, error = _decode_body(compressed, "deflate", max_bytes=1_000_000)
    assert ok is True, error
    assert text == original


def test_plain_body_passes_through_unchanged():
    original = "<html><body>No compression</body></html>"
    text, ok, error = _decode_body(original.encode("utf-8"), "", max_bytes=1_000_000)
    assert ok is True
    assert text == original


def test_unsupported_encoding_is_refused_not_corrupted():
    text, ok, error = _decode_body(b"\x1b\x01\x02garbage", "br", max_bytes=1_000_000)
    assert ok is False
    assert text == ""
    assert "br" in error


def test_decompression_output_is_bounded():
    """A small compressed payload must not be allowed to expand past the
    byte cap in memory (decompression-bomb guard)."""
    original = "A" * 1_000_000
    compressed = gzip.compress(original.encode("utf-8"))
    text, ok, error = _decode_body(compressed, "gzip", max_bytes=1000)
    assert ok is True
    assert len(text) <= 1000


# --- Reliability patch: DNS/network failures during the actual request
# (i.e. reached *after* is_safe_url already passed the URL) must be
# categorized as availability problems, never as a security rejection.

class _FakeOpener:
    """A stand-in for urllib's opener whose .open() call raises or
    returns a scripted sequence of results -- one per call, in order."""
    def __init__(self, side_effects):
        self._side_effects = list(side_effects)

    def open(self, req, timeout=None):
        effect = self._side_effects.pop(0)
        if isinstance(effect, BaseException):
            raise effect
        return effect


def _redirect_error(location, code=302):
    hdrs = email.message.Message()
    hdrs["Location"] = location
    return urllib.error.HTTPError("http://acme.example/redirect", code, "Found", hdrs, None)


def test_classify_fetch_exception_distinguishes_categories():
    assert _classify_fetch_exception(socket.timeout("timed out")) == "timeout"
    assert _classify_fetch_exception(TimeoutError("timed out")) == "timeout"
    assert _classify_fetch_exception(ConnectionRefusedError("refused")) == "connection_failed"
    assert _classify_fetch_exception(urllib.error.URLError(socket.gaierror("no such host"))) == "dns_resolution_failed"
    assert _classify_fetch_exception(urllib.error.URLError(ConnectionRefusedError("refused"))) == "connection_failed"
    assert _classify_fetch_exception(OSError("something else")) == "network_failure"


def test_dns_failure_during_request_is_availability_not_unsafe(monkeypatch):
    """DNS can resolve fine at is_safe_url's pre-flight check and then
    still fail moments later during the real request -- that must be
    categorized the same as any other DNS failure, never as 'unsafe'."""
    err = urllib.error.URLError(socket.gaierror("no such host"))
    monkeypatch.setattr(fetcher_mod.urllib.request, "build_opener", lambda *a, **k: _FakeOpener([err]))

    result = safe_fetch("http://8.8.8.8/", timeout=1)
    assert result["ok"] is False
    assert result["error_category"] == "dns_resolution_failed"
    assert "unsafe" not in result["error"]


def test_timeout_during_request_is_availability_not_unsafe(monkeypatch):
    monkeypatch.setattr(fetcher_mod.urllib.request, "build_opener", lambda *a, **k: _FakeOpener([socket.timeout("timed out")]))

    result = safe_fetch("http://8.8.8.8/", timeout=1)
    assert result["ok"] is False
    assert result["error_category"] == "timeout"


def test_redirect_to_private_address_is_blocked_as_unsafe(monkeypatch):
    """The redirect-revalidation path itself: a safe initial URL that
    redirects to a private address must be refused with category
    'unsafe', proving the SSRF check re-runs on the redirect target and
    is not weakened by the availability-vs-unsafe distinction."""
    monkeypatch.setattr(
        fetcher_mod.urllib.request, "build_opener",
        lambda *a, **k: _FakeOpener([_redirect_error("http://127.0.0.1/admin")]),
    )

    result = safe_fetch("http://8.8.8.8/", timeout=1)
    assert result["ok"] is False
    assert result["error_category"] == "unsafe"
    assert "blocked unsafe URL" in result["error"]


def test_redirect_then_network_failure_is_availability_not_unsafe(monkeypatch):
    """A redirect to a perfectly safe address that then fails to connect
    is a network problem, not a security rejection."""
    monkeypatch.setattr(
        fetcher_mod.urllib.request, "build_opener",
        lambda *a, **k: _FakeOpener([_redirect_error("http://1.1.1.1/"), ConnectionResetError("reset")]),
    )

    result = safe_fetch("http://8.8.8.8/", timeout=1)
    assert result["ok"] is False
    assert result["error_category"] == "connection_failed"
