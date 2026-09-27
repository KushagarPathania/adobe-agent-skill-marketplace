"""SSRF-protection tests: the target list from the hackathon brief
(loopback, private ranges, link-local/cloud metadata, IPv6, bad schemes,
embedded credentials) plus DNS-rebinding and resolution-failure cases.
"""
import socket

from skills_impl.site_discovery.scripts.security import is_safe_url


def test_blocks_loopback_ipv4():
    assert is_safe_url("http://127.0.0.1/")[0] is False


def test_blocks_unspecified_ipv4():
    assert is_safe_url("http://0.0.0.0/")[0] is False


def test_blocks_private_ipv4_ranges():
    for host in ("10.0.0.5", "172.16.0.5", "192.168.1.1"):
        assert is_safe_url(f"http://{host}/")[0] is False, host


def test_blocks_link_local_and_cloud_metadata():
    assert is_safe_url("http://169.254.169.254/latest/meta-data/")[0] is False


def test_blocks_ipv6_loopback_and_link_local():
    assert is_safe_url("http://[::1]/")[0] is False
    assert is_safe_url("http://[fe80::1]/")[0] is False


def test_blocks_localhost_hostnames():
    assert is_safe_url("http://localhost/")[0] is False
    assert is_safe_url("http://foo.localhost/")[0] is False
    assert is_safe_url("http://box.internal/")[0] is False


def test_blocks_disallowed_schemes():
    assert is_safe_url("file:///etc/passwd")[0] is False
    assert is_safe_url("ftp://example.com/")[0] is False
    assert is_safe_url("javascript:alert(1)")[0] is False


def test_blocks_embedded_credentials():
    assert is_safe_url("http://user:pass@8.8.8.8/")[0] is False


def test_allows_public_ip_literal():
    ok, reason, category = is_safe_url("http://8.8.8.8/")
    assert ok is True, reason
    assert category == "safe"


def test_blocks_when_any_resolved_address_is_unsafe(monkeypatch):
    """DNS rebinding style defense: if a hostname resolves to a mix of a
    public and a private address, treat the whole host as unsafe rather
    than only checking the first answer."""
    def fake_getaddrinfo(host, port):
        return [
            (socket.AF_INET, None, None, '', ('8.8.8.8', 0)),
            (socket.AF_INET, None, None, '', ('127.0.0.1', 0)),
        ]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    ok, reason, category = is_safe_url("http://rebinding.example/")
    assert ok is False
    assert category == "unsafe"


def test_dns_failure_is_treated_as_unsafe_to_fetch(monkeypatch):
    """A DNS failure must still refuse to fetch (we can't verify safety
    for a host we can't resolve) -- but see the next test: it must be
    categorized differently from a genuine security rejection."""
    def fail(*args, **kwargs):
        raise socket.gaierror("no such host")
    monkeypatch.setattr(socket, "getaddrinfo", fail)
    assert is_safe_url("http://nonexistent.invalid/")[0] is False


def test_dns_failure_is_not_reported_as_a_security_rejection(monkeypatch):
    """This is the core distinction the reliability patch introduces: a
    DNS/network failure is NOT proof the target is unsafe, and callers
    must be able to tell the two apart so a temporary DNS hiccup on a
    legitimate public site is never reported as 'this website is
    unsafe'."""
    def fail(*args, **kwargs):
        raise socket.gaierror("no such host")
    monkeypatch.setattr(socket, "getaddrinfo", fail)
    ok, reason, category = is_safe_url("http://nonexistent.invalid/")
    assert ok is False
    assert category == "dns_resolution_failed"
    assert category != "unsafe"


def test_other_dns_lookup_errors_also_categorized_as_resolution_failure(monkeypatch):
    """Not every DNS/network hiccup raises socket.gaierror specifically
    (e.g. no local network access can raise a plain OSError) -- these
    must be categorized the same way, not fall through as 'unsafe'."""
    def fail(*args, **kwargs):
        raise OSError("network is unreachable")
    monkeypatch.setattr(socket, "getaddrinfo", fail)
    ok, reason, category = is_safe_url("http://example.com/")
    assert ok is False
    assert category == "dns_resolution_failed"


def test_credentials_bypass_trick_still_blocked():
    """A classic SSRF bypass: 'http://trusted.example@evil.internal/'
    parses trusted.example as userinfo and evil.internal as the real
    host -- must still be blocked outright (embedded credentials are
    never allowed), not treated as a mere availability question."""
    ok, reason, category = is_safe_url("http://trusted.example@127.0.0.1/")
    assert ok is False
    assert category == "unsafe"


def test_rejects_missing_or_overlong_url():
    assert is_safe_url("")[0] is False
    assert is_safe_url("http://" + "a" * 3000 + ".example/")[0] is False
