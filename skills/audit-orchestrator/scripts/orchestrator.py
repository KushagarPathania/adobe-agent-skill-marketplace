"""Thin entrypoint shim.

The marketplace-facing skill directory name must be hyphenated per Agent
Skills / agentskills.io convention (`skills/audit-orchestrator/`), but
Python's import system cannot import a package whose name contains a
hyphen. The actual implementation therefore lives in the internal
`skills_impl` Python package (underscore-named, as Python requires:
`skills_impl/audit_orchestrator/scripts/orchestrator.py`) and is
re-exported here so this skill folder still carries a literal, importable
entry point matching the layout the handout illustrates for the
entrypoint skill. See the root README.md for the full rationale.
"""
from skills_impl.audit_orchestrator.scripts.orchestrator import run_audit  # noqa: F401
from skills_impl.audit_orchestrator.scripts.config import AuditConfig  # noqa: F401
