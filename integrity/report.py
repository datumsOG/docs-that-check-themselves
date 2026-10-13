"""Output formatting: rich terminal report, a compact hook line, and a markdown
snapshot written to data/last_report.md."""
from pathlib import Path

from integrity.model import Severity, Category

HERE = Path(__file__).resolve().parent.parent
DATA_DIR = HERE / "data"

_ICON = {Severity.CRITICAL: "✗", Severity.WARNING: "!", Severity.INFO: "i"}
_ORDER = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}


def _sorted(findings):
    return sorted(findings, key=lambda f: (_ORDER[f.severity], f.category.value, f.doc))


def format_terminal(report):
    lines = []
    lines.append("=" * 64)
    mode = "FAST (filesystem only)" if report.fast_mode else "FULL"
    lines.append(f"  doc-integrity audit — {report.timestamp:%Y-%m-%d %H:%M}  [{mode}]")
    lines.append(f"  {report.docs_scanned} docs scanned, {report.checks_run} embedded "
                 f"claims checked, {report.duration_seconds}s")
    lines.append("=" * 64)
    lines.append(f"  CRITICAL {report.critical_count}   "
                 f"WARNING {report.warning_count}   INFO {report.info_count}")
    lines.append("")
    if not report.findings:
        lines.append("  No findings. Every checkable claim matches reality.")
        return "\n".join(lines)
    for f in _sorted(report.findings):
        loc = f.location or "(workspace)"
        lines.append(f"  [{_ICON[f.severity]}] {f.severity.value:8} {f.category.value}")
        lines.append(f"      {f.title}")
        lines.append(f"      {loc}")
        if f.detail:
            lines.append(f"      {f.detail}")
        if f.suggestion:
            lines.append(f"      -> {f.suggestion}")
        lines.append("")
    return "\n".join(lines)


def format_hook(report):
    """One block for SessionStart hook stdout: silent when clean, loud on drift."""
    if report.critical_count == 0 and report.warning_count == 0:
        return ""  # stay quiet so the signal means something when it appears
    out = [f"[doc-integrity] {report.critical_count} CRITICAL, "
           f"{report.warning_count} WARNING across {report.docs_scanned} docs."]
    shown = [f for f in _sorted(report.findings)
             if f.severity in (Severity.CRITICAL, Severity.WARNING)][:8]
    for f in shown:
        out.append(f"  [{f.severity.value}] {f.title} ({f.location or 'workspace'})")
    extra = report.critical_count + report.warning_count - len(shown)
    if extra > 0:
        out.append(f"  ...and {extra} more. Run: python3 audit.py")
    return "\n".join(out)


def write_snapshot(report):
    DATA_DIR.mkdir(exist_ok=True)
    md = [f"# doc-integrity — last report",
          f"_{report.timestamp:%Y-%m-%d %H:%M}_ · mode: "
          f"{'fast' if report.fast_mode else 'full'} · "
          f"{report.critical_count} critical / {report.warning_count} warning / "
          f"{report.info_count} info", ""]
    if not report.findings:
        md.append("No findings. Every checkable claim matches reality.")
    for f in _sorted(report.findings):
        md.append(f"### [{f.severity.value}] {f.title}")
        md.append(f"- **where:** {f.location or '(workspace)'}")
        md.append(f"- **what:** {f.detail}")
        if f.suggestion:
            md.append(f"- **fix:** {f.suggestion}")
        md.append("")
    (DATA_DIR / "last_report.md").write_text("\n".join(md))
