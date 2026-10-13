"""Orchestrates the whole audit. Mirrors an earlier auditor's runner in spirit:
each check is isolated so one crashing check degrades to a single Finding instead of
taking down the run."""
import json
import os
import socket
import time
from datetime import datetime
from pathlib import Path

from integrity.model import AuditReport, Finding, Severity, Category
from integrity import checks

HERE = Path(__file__).resolve().parent.parent
DATA_DIR = HERE / "data"


def load_config(path=None):
    cfg_path = Path(path) if path else (HERE / "registry.json")
    cfg = json.loads(cfg_path.read_text())
    return {k: v for k, v in cfg.items() if not k.startswith("_")}


def _safe(findings, label, fn, *args):
    try:
        findings.extend(fn(*args))
    except Exception as e:
        findings.append(Finding(
            Category.ENGINE, Severity.WARNING,
            f"Check '{label}' crashed", str(e),
            suggestion="Bug in the auditor itself — fix integrity/ code."))


def run_audit(cfg=None, fast=False):
    if cfg is None:
        cfg = load_config()

    start = time.monotonic()
    findings = []

    docs = checks.discover_docs(cfg)

    claim_findings, n_claims = checks.check_embedded_claims(docs, cfg, fast)
    findings.extend(claim_findings)

    _safe(findings, "dead_paths", checks.check_dead_paths, docs, cfg)
    _safe(findings, "doc_suite", checks.check_doc_suite, cfg)
    _safe(findings, "placeholders", checks.check_placeholders, docs, cfg)
    _safe(findings, "staleness", checks.check_staleness, docs, cfg)
    _safe(findings, "crosslinks", checks.check_crosslinks, cfg)

    return AuditReport(
        timestamp=datetime.now(),
        duration_seconds=round(time.monotonic() - start, 2),
        findings=findings,
        hostname=socket.gethostname(),
        docs_scanned=len(docs),
        checks_run=n_claims,
        fast_mode=fast,
    )


def save_history(report):
    DATA_DIR.mkdir(exist_ok=True)
    rec = {
        "timestamp": report.timestamp.isoformat(),
        "duration_s": report.duration_seconds,
        "fast_mode": report.fast_mode,
        "docs_scanned": report.docs_scanned,
        "claims_run": report.checks_run,
        "critical": report.critical_count,
        "warning": report.warning_count,
        "info": report.info_count,
        "findings": [
            {"category": f.category.value, "severity": f.severity.value,
             "title": f.title, "location": f.location}
            for f in report.findings
        ],
    }
    with open(DATA_DIR / "history.jsonl", "a") as fh:
        fh.write(json.dumps(rec) + "\n")
