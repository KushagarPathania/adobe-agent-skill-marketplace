"""Runtime limits for one audit run.

Keeping every timeout/limit in one dataclass makes the "bounded, not
unlimited" crawling guarantee easy to see and adjust in one place.
"""
from dataclasses import dataclass


@dataclass
class AuditConfig:
    max_pages: int = 8               # page inventory size cap
    max_redirects: int = 5           # per-request redirect cap
    request_timeout: int = 10        # seconds, per raw HTTP request
    render_timeout_ms: int = 15000   # per-page Playwright navigation timeout
    total_audit_timeout: int = 90    # seconds, wall clock for the whole audit
    max_response_bytes: int = 3_000_000
