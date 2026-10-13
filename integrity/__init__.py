"""doc-integrity: a workspace-wide documentation truth auditor.

stdlib-only by deliberate choice (a deliberate discipline): it must run
under the system python3 with no venv, so the thing that guards the docs can never
itself rot from a broken dependency.
"""
from integrity.model import Finding, Severity, Category, AuditReport
from integrity.runner import run_audit

__all__ = ["Finding", "Severity", "Category", "AuditReport", "run_audit"]
