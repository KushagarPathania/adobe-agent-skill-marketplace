"""SSRF protection.

The audit accepts an arbitrary, untrusted URL from the caller and then
makes outbound requests to it. `is_safe_url` is the single gate every
fetch in this project goes through -- on the initial target URL, and
again on every redirect hop, since a redirect is never assumed safe just
because the original URL was.
"""
import ipaddress
import socket
from urllib.parse import urlparse

MAX_URL_LENGTH = 2048
ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOSTNAMES = {"localhost"}
BLOCKED_HOST_SUFFIXES = (".local", ".localhost", ".internal")


def _is_unsafe_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparsable -> treat as unsafe rather than risk it

    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped  # unwrap ::ffff:127.0.0.1-style addresses

    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local  # covers 169.254.169.254 cloud metadata endpoints
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def is_safe_url(url: str):
    """Return (ok, reason, category).

    `category` distinguishes WHY `ok` is False, which matters a great
    deal to callers:

      "safe"                  -- ok is True; fine to fetch.
      "unsafe"                -- a confirmed security rejection (private/
                                  loopback/link-local/reserved address,
                                  disallowed scheme, embedded credentials,
                                  a blocked hostname). Never fetch this,
                                  regardless of network conditions.
      "dns_resolution_failed" -- the hostname could not be resolved at
                                  all. This is NOT evidence the target is
                                  unsafe -- only that it could not be
                                  reached or verified right now (a
                                  transient DNS/network issue). Callers
                                  must not report this as "the website is
                                  unsafe"; it is an audit limitation.

    Either way `ok=False` still means "do not fetch this" -- an
    unresolvable host can't be verified safe either, so refusing to fetch
    is correct in both cases. The category only changes how a caller
    should *report* the refusal.
    """
    if not url or len(url) > MAX_URL_LENGTH:
        return False, "URL is missing or exceeds the maximum allowed length", "unsafe"

    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, f"scheme '{parsed.scheme}' is not allowed (only http/https)", "unsafe"
    if parsed.username or parsed.password:
        return False, "URLs with embedded credentials are not allowed", "unsafe"

    hostname = parsed.hostname
    if not hostname:
        return False, "URL has no hostname", "unsafe"

    host_lower = hostname.lower()
    if host_lower in BLOCKED_HOSTNAMES or any(host_lower.endswith(s) for s in BLOCKED_HOST_SUFFIXES):
        return False, f"host '{hostname}' is blocked", "unsafe"

    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        return False, f"DNS resolution failed: {e}", "dns_resolution_failed"
    except OSError as e:
        # Other getaddrinfo failures (e.g. no local network access) are
        # just as unresolvable as a gaierror -- same category.
        return False, f"DNS resolution failed: {e}", "dns_resolution_failed"

    if not resolved:
        return False, "DNS resolution returned no addresses", "dns_resolution_failed"

    # Reject if ANY resolved address is unsafe (defends against a host
    # that returns one public and one private/internal A/AAAA record).
    for info in resolved:
        ip_str = info[4][0]
        if _is_unsafe_ip(ip_str):
            return False, f"host resolves to a non-public address ({ip_str})", "unsafe"

    return True, None, "safe"
