#!/usr/bin/env python3
"""doc-integrity — workspace documentation truth auditor.

Walks every live doc under ~/, runs the embedded @check claims against reality, and
flags drift (dead paths, missing doc suites, placeholders, staleness). stdlib-only:
runs under the system python3 with no venv.

Usage:
    python3 audit.py            # full audit, terminal report
    python3 audit.py --fast     # skip network/systemd checks (filesystem only)
    python3 audit.py --hook      # compact output for the SessionStart hook; always exits 0
    python3 audit.py --json      # machine-readable findings on stdout
    python3 audit.py --quiet     # only print if there are findings

Exit code: 2 if any CRITICAL finding (a doc is actively lying), else 0.
A CRITICAL only comes from an opt-in @check assertion that failed.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from integrity import runner, report as report_mod
from _logging import StructuredLogger, new_id, timed

log = StructuredLogger("doc-integrity")


def main():
    log.info("APP_STARTED")
    argv = set(sys.argv[1:])
    fast = "--fast" in argv or "--hook" in argv
    hook = "--hook" in argv
    as_json = "--json" in argv
    quiet = "--quiet" in argv

    workflow_id = new_id()
    try:
        with timed(log, "WORKFLOW_COMPLETED", workflow_id=workflow_id, stage="audit"):
            cfg = runner.load_config()
            rep = runner.run_audit(cfg, fast=fast)

            runner.save_history(rep)
            report_mod.write_snapshot(rep)

            log.info("AUDIT_COMPLETED", workflow_id=workflow_id, docs=rep.docs_scanned,
                     criticals=rep.critical_count, warnings=rep.warning_count)

        if hook:
            out = report_mod.format_hook(rep)
            if out:
                print(out)
            sys.exit(0)  # never block a session; just surface

        if as_json:
            print(json.dumps({
                "critical": rep.critical_count, "warning": rep.warning_count,
                "info": rep.info_count, "docs_scanned": rep.docs_scanned,
                "findings": [{"category": f.category.value, "severity": f.severity.value,
                              "title": f.title, "location": f.location,
                              "detail": f.detail} for f in rep.findings],
            }, indent=2))
        elif not (quiet and not rep.findings):
            print(report_mod.format_terminal(rep))

        sys.exit(2 if rep.has_criticals else 0)
    except Exception as e:
        log.exception("AUDIT_FAILED", workflow_id=workflow_id)
        raise


if __name__ == "__main__":
    main()
