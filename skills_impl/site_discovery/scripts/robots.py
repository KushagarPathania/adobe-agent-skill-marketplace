"""robots.txt handling.

If robots.txt disallows a path, this project does not crawl it -- full
stop. If robots.txt is missing or unreachable, that is treated as
permissive (the conventional interpretation), not as an error.
"""
import urllib.robotparser
from urllib.parse import urljoin

from .fetcher import safe_fetch

DEFAULT_USER_AGENT = "*"


def load_robots(base_url, timeout=10):
    """Fetch and parse robots.txt for `base_url`'s origin.

    Returns: {found, sitemaps, parser, error}
    `parser` is a stdlib RobotFileParser for use with `can_fetch`.
    """
    robots_url = urljoin(base_url, "/robots.txt")
    result = safe_fetch(robots_url, timeout=timeout, max_bytes=200_000)

    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)

    if not result["ok"] or result["status"] != 200:
        parser.parse([])  # no rules -> everything allowed
        return {"found": False, "sitemaps": [], "parser": parser, "error": result.get("error")}

    parser.parse(result["html"].splitlines())
    return {"found": True, "sitemaps": list(parser.site_maps() or []), "parser": parser, "error": None}


def can_fetch(robots_info, url, user_agent=DEFAULT_USER_AGENT):
    parser = robots_info.get("parser")
    if not parser:
        return True
    try:
        return parser.can_fetch(user_agent, url)
    except Exception:
        return True  # a broken robots.txt should not block a legitimate audit
