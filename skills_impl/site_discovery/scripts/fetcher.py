"""Bounded, SSRF-safe HTTP fetching.

Every request goes through `is_safe_url` before it is made, and again on
every redirect hop -- redirects are followed manually (never by urllib's
default handler) so a redirect to an internal host can never slip through.
Response size is capped (on the *decompressed* body, so a small gzipped
response can't decompression-bomb its way past the limit) so a hostile
or misbehaving server can't exhaust memory.
"""
import socket
import urllib.request
import urllib.error
import urllib.parse
import zlib

from .security import is_safe_url

USER_AGENT = "Mozilla/5.0 (compatible; BrandAIReadinessAudit/1.0; +https://example.invalid/bot)"
READ_CHUNK = 65536


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Disables automatic redirect-following so callers can validate
    each hop themselves before it is fetched."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

    http_error_308 = urllib.request.HTTPRedirectHandler.http_error_302


def _classify_fetch_exception(e):
    """Best-effort categorization of a low-level fetch failure. This
    code path is only reached AFTER `is_safe_url` already passed the
    URL as safe -- so a failure here is never a security rejection, only
    a network/availability problem (DNS flaked between the check and the
    request, the connection was refused, the request timed out, etc.).
    """
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(e, urllib.error.URLError):
        reason = e.reason
        if isinstance(reason, socket.gaierror):
            return "dns_resolution_failed"
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return "timeout"
        if isinstance(reason, ConnectionError):
            return "connection_failed"
        return "network_failure"
    if isinstance(e, ConnectionError):
        return "connection_failed"
    return "network_failure"


def _read_bounded(resp, max_bytes):
    """Read the response body up to `max_bytes` (of wire bytes, which may
    still be compressed). Returns (raw_bytes, truncated)."""
    chunks = []
    total = 0
    truncated = False
    while total < max_bytes:
        chunk = resp.read(READ_CHUNK)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    else:
        truncated = resp.read(1) != b""  # more data exists beyond our cap
    return b"".join(chunks), truncated


def _decode_body(raw_bytes, content_encoding, max_bytes):
    """Decode `raw_bytes` to text, transparently handling gzip/deflate
    Content-Encoding. Decompressed output is itself capped at max_bytes
    so a small compressed payload can't expand into a huge one in memory.
    Returns (text, ok, error).
    """
    encoding = (content_encoding or '').strip().lower()

    if encoding in ('', 'identity'):
        return raw_bytes[:max_bytes].decode('utf-8', errors='ignore'), True, None

    if encoding == 'gzip':
        decompressor = zlib.decompressobj(zlib.MAX_WBITS | 16)
    elif encoding == 'deflate':
        decompressor = zlib.decompressobj()
    else:
        # e.g. brotli -- not something we can safely decode; refuse
        # rather than silently returning corrupted text.
        return "", False, f"unsupported Content-Encoding '{encoding}'"

    try:
        out = decompressor.decompress(raw_bytes, max_bytes)
    except zlib.error as e:
        return "", False, f"failed to decompress response body: {e}"
    return out.decode('utf-8', errors='ignore'), True, None


def safe_fetch(url, timeout=10, max_redirects=5, max_bytes=3_000_000):
    """Fetch `url`, validating SSRF-safety on the initial URL and on every
    redirect hop.

    Returns: {ok, url, final_url, status, html, headers, truncated, error,
    error_category}. `error_category` is None on success; on failure it is
    one of "unsafe" (a genuine security rejection -- never retry/report as
    a mere availability issue), "dns_resolution_failed", "timeout",
    "connection_failed", "network_failure", "redirect_limit_exceeded",
    "http_error", or "decode_error" -- the first five are availability
    problems, not evidence the target is unsafe or defective.
    """
    current_url = url
    redirects = 0
    opener = urllib.request.build_opener(_NoRedirect)

    while True:
        safe, reason, category = is_safe_url(current_url)
        if not safe:
            if category == "unsafe":
                error_msg = f"blocked unsafe URL: {reason}"
            else:
                error_msg = f"could not verify URL safety: {reason}"
            return {"ok": False, "url": url, "final_url": current_url, "status": None,
                     "html": "", "headers": {}, "truncated": False,
                     "error": error_msg, "error_category": category}

        req = urllib.request.Request(current_url, headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        })
        try:
            resp = opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            location = e.headers.get("Location") if e.headers else None
            if e.code in (301, 302, 303, 307, 308) and location:
                redirects += 1
                if redirects > max_redirects:
                    return {"ok": False, "url": url, "final_url": current_url, "status": e.code,
                             "html": "", "headers": {}, "truncated": False,
                             "error": "too many redirects", "error_category": "redirect_limit_exceeded"}
                current_url = urllib.parse.urljoin(current_url, location)
                continue
            return {"ok": False, "url": url, "final_url": current_url, "status": e.code,
                     "html": "", "headers": dict(e.headers or {}), "truncated": False,
                     "error": str(e), "error_category": "http_error"}
        except Exception as e:
            # Reached only after is_safe_url already passed -- so this is
            # always an availability problem, never a security rejection.
            return {"ok": False, "url": url, "final_url": current_url, "status": None,
                     "html": "", "headers": {}, "truncated": False,
                     "error": str(e), "error_category": _classify_fetch_exception(e)}

        # resp.headers is case-insensitive (email.message.Message);
        # resolve Content-Encoding from it directly before flattening to
        # a plain dict, since a plain dict lookup would not be.
        content_encoding = resp.headers.get('Content-Encoding')
        headers = dict(resp.headers)
        raw, read_truncated = _read_bounded(resp, max_bytes)
        html, decoded_ok, decode_error = _decode_body(raw, content_encoding, max_bytes)
        if not decoded_ok:
            return {"ok": False, "url": url, "final_url": current_url, "status": resp.status,
                     "html": "", "headers": headers, "truncated": False,
                     "error": decode_error, "error_category": "decode_error"}

        return {"ok": True, "url": url, "final_url": current_url, "status": resp.status,
                 "html": html, "headers": headers,
                 "truncated": read_truncated or len(html) >= max_bytes,
                 "error": None, "error_category": None}
