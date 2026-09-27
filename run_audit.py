#!/usr/bin/env python3
"""CLI entrypoint for the Brand AI-Readiness Audit marketplace.

Invokes the `audit-orchestrator` Agent Skill (skills/audit-orchestrator/) --
its actual implementation lives in the internal `skills_impl` Python package
(underscore-named, as Python's import system requires; the marketplace-facing
skill directories under skills/ are hyphenated per Agent Skills convention
and are documentation-only -- see README.md "Agent Skills vs. Python
implementation").

Usage:
    python3 run_audit.py https://example.com
    python3 run_audit.py example.com --max-pages 5
"""
import argparse
import json
import sys

from skills_impl.audit_orchestrator.scripts.orchestrator import run_audit
from skills_impl.audit_orchestrator.scripts.config import AuditConfig


def main():
    parser = argparse.ArgumentParser(description="Audit a website for AI discoverability and on-site engagement.")
    parser.add_argument("url", help="Target website URL or domain")
    parser.add_argument("--max-pages", type=int, default=AuditConfig.max_pages)
    parser.add_argument("--total-timeout", type=int, default=AuditConfig.total_audit_timeout)
    args = parser.parse_args()

    config = AuditConfig(max_pages=args.max_pages, total_audit_timeout=args.total_timeout)
    report = run_audit(args.url, config=config)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    sys.exit(main())
