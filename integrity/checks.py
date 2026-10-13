"""Structural + heuristic checks, and the embedded-claim sweep.

Severity contract (the load-bearing design decision):
  * a failed opt-in @check  -> CRITICAL   (you asserted it; reality broke it)
  * an auto-detected signal -> WARNING    (likely drift, but prose can be illustrative)
  * staleness / crosslinks  -> INFO        (advisory only)
This keeps the auditor loud where you committed and quiet where it is guessing, so it
stays trustworthy enough that you never learn to ignore it.
"""
import os
import re
from datetime import date, datetime
from pathlib import Path

from integrity.model import Finding, Severity, Category
from integrity import claims

HOME = Path(os.path.expanduser("~"))


def _rel(p):
    try:
        return "~/" + str(Path(p).resolve().relative_to(HOME))
    except ValueError:
        return str(p)


def safe_exists(p):
    """Path.exists() can raise OSError on network mounts (rclone gdrive throws
    Errno 5). Treat an unreadable path as 'present' so we never flag a path we
    simply couldn't stat — false silence beats false alarms here."""
    try:
        return p.exists()
    except OSError:
        return True


# ---- doc discovery --------------------------------------------------------

def discover_docs(cfg):
    ignore = set(cfg["ignore_dir_names"])
    exts = tuple(cfg["doc_extensions"])
    excluded = {Path(os.path.expanduser(d)).resolve() for d in cfg.get("exclude_docs", [])}
    docs = []
    for root_str in cfg["scan_roots"]:
        root = Path(os.path.expanduser(root_str))
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ignore]
            for fn in filenames:
                if fn.endswith(exts):
                    p = Path(dirpath) / fn
                    if p.resolve() not in excluded:
                        docs.append(p)
    return sorted(docs)


# ---- 1. embedded @check claims (CRITICAL on failure) ----------------------

def check_embedded_claims(docs, cfg, fast):
    findings, n = [], 0
    for doc in docs:
        try:
            text = doc.read_text(errors="replace")
        except Exception:
            continue
        for body, note, line in claims.parse_claims(text):
            n += 1
            res = claims.run_claim(body, str(doc), fast=fast)
            if res.skipped:
                continue
            if res.error:
                findings.append(Finding(
                    Category.CLAIM, Severity.WARNING,
                    f"Malformed @check: {body}", res.detail,
                    suggestion="Fix the claim syntax (see CONVENTIONS.md).",
                    doc=_rel(doc), line=line))
            elif not res.ok:
                extra = f" — note: {note}" if note else ""
                findings.append(Finding(
                    Category.CLAIM, Severity.CRITICAL,
                    f"Claim FAILED: {body}", res.detail + extra,
                    suggestion="The doc asserts something untrue. Fix the doc or fix reality.",
                    doc=_rel(doc), line=line))
    return findings, n


# ---- 2. dead paths (WARNING) ----------------------------------------------

PATH_RE = re.compile(r"(?<![\w/])(?:~|/home/[a-z_][a-z0-9_-]*)/[A-Za-z0-9._\-/]+")


def check_dead_paths(docs, cfg):
    allow = [re.compile(rx) for rx in cfg.get("path_allowlist_regex", [])]
    # Append-only history (changelogs, point-in-time audit reports) legitimately
    # references paths that were since removed — the dead-path heuristic is wrong there.
    skip_docs = {os.path.expanduser(d) for d in cfg.get("dead_path_exclude_docs", [])}
    # Append-only logs (every project's LOG.md, the Fable.md planning journals) record
    # paths as they were — including ones since deleted. Skip the dead-path heuristic on
    # them by basename so this generalizes to all current and future logs.
    skip_names = set(cfg.get("dead_path_exclude_basenames", []))
    # Whole TREES that are historical or aspirational by nature.
    #
    # 2026-09-15: this check was producing 277 dead-path warnings and therefore
    # producing none, because nobody reads a 277-line list. Measured, the bulk came
    # from three kinds of document that are CORRECT to reference things that no
    # longer exist:
    #   - point-in-time audits (`an old audit report` alone
    #     accounted for 56) — an audit records what it found on the day
    #   - archives and superseded copies, which are kept precisely so the old
    #     wording survives
    #   - continuity letters and goal files, which are chronology
    # Flagging those forever is how a guardrail becomes furniture. The exclusion is
    # by PREFIX so it generalises to next month's audit without another edit.
    skip_prefixes = tuple(os.path.expanduser(p) for p in cfg.get("dead_path_exclude_prefixes", []))
    findings = []
    for doc in docs:
        if doc.name in skip_names or str(doc) in skip_docs or str(doc.resolve()) in skip_docs:
            continue
        if skip_prefixes and str(doc.resolve()).startswith(skip_prefixes):
            continue
        try:
            text = doc.read_text(errors="replace")
        except Exception:
            continue
        # Paths that are the ARGUMENT of an @check claim are already verified by the
        # claim engine (and an `absent`/`nogrep` claim's path is meant to not exist) —
        # don't let the heuristic double-flag them.
        claim_spans = [(m.start(), m.end()) for m in claims.CLAIM_RE.finditer(text)]
        seen = set()
        for m in PATH_RE.finditer(text):
            if any(s <= m.start() < e for s, e in claim_spans):
                continue
            raw = m.group(0).rstrip(".,;:)`'\"")
            if raw in seen:
                continue
            seen.add(raw)
            if any(rx.search(raw) for rx in allow):
                continue
            resolved = Path(os.path.expanduser(raw))
            if safe_exists(resolved):
                continue
            # Paths with spaces ("~/My Log.md") truncate at the space; before
            # flagging, try extending the match with following words and see if
            # any extension exists on disk.
            ext = re.match(r"(?: [A-Za-z0-9._\-]+)+", text[m.end():])
            if ext:
                words = ext.group(0).split(" ")[1:]
                cand = raw
                if any(safe_exists(Path(os.path.expanduser(cand := f"{cand} {w}")))
                       for w in words):
                    continue
            # suppress if the line carries an explicit @example marker
            line_no = text.count("\n", 0, m.start()) + 1
            line_txt = text.splitlines()[line_no - 1] if line_no - 1 < len(text.splitlines()) else ""
            if "@example" in line_txt:
                continue
            findings.append(Finding(
                Category.DEAD_PATH, Severity.WARNING,
                f"Path referenced but missing: {raw}",
                f"{_rel(doc)} mentions {raw}, which does not exist on disk.",
                suggestion="If it was deleted/renamed, update the doc. If illustrative, add a "
                           "trailing `<!-- @example -->` on that line or allowlist it in registry.json.",
                doc=_rel(doc), line=line_no))
    return findings


# ---- 3. doc suite completeness (WARNING) ----------------------------------

def check_doc_suite(cfg):
    findings = []
    for proj in cfg.get("projects", []):
        base = Path(os.path.expanduser(proj["path"]))
        if not base.exists():
            findings.append(Finding(
                Category.DOC_SUITE, Severity.WARNING,
                f"Registered project missing: {proj['name']}",
                f"{proj['path']} is in registry.json but not on disk.",
                suggestion="Remove it from registry.json or restore the project.",
                doc=proj["path"]))
            continue
        for fname in proj.get("suite", []):
            if not (base / fname).exists():
                findings.append(Finding(
                    Category.DOC_SUITE, Severity.WARNING,
                    f"{proj['name']}: missing {fname}",
                    f"Expected standard doc {proj['path']}/{fname} not found.",
                    suggestion=f"Create {fname} or drop it from this project's suite in registry.json.",
                    doc=proj["path"]))
    return findings


# ---- 4. placeholders (WARNING) --------------------------------------------

def check_placeholders(docs, cfg):
    # longest tokens first so 'apt.yourdomain.com' wins over 'yourdomain.com'
    tokens = sorted(cfg.get("placeholders", []), key=len, reverse=True)
    findings = []
    for doc in docs:
        try:
            text = doc.read_text(errors="replace")
        except Exception:
            continue
        claimed = []  # (start, end) spans already reported on this doc
        for tok in tokens:
            start = 0
            while True:
                idx = text.find(tok, start)
                if idx == -1:
                    break
                end = idx + len(tok)
                if not any(s <= idx and end <= e for s, e in claimed):
                    claimed.append((idx, end))
                    findings.append(Finding(
                        Category.PLACEHOLDER, Severity.WARNING,
                        f"Placeholder left in doc: {tok!r}",
                        f"{_rel(doc)} still contains the placeholder {tok!r}.",
                        suggestion="Replace with the real value before this doc is trusted.",
                        doc=_rel(doc), line=text.count("\n", 0, idx) + 1))
                start = end
    return findings


# ---- 5. staleness (INFO / WARNING) ----------------------------------------

STAMP_RE = re.compile(r"(?:last updated|last-updated|updated)[:\s*]*\**\s*(\d{4}-\d{2}-\d{2})",
                      re.IGNORECASE)


def check_staleness(docs, cfg):
    info_days = cfg.get("stale_days_info", 120)
    warn_days = cfg.get("stale_days_warning", 240)
    today = date.today()
    findings = []
    for doc in docs:
        try:
            text = doc.read_text(errors="replace")
        except Exception:
            continue
        m = STAMP_RE.search(text)
        if not m:
            continue
        try:
            stamp = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        age = (today - stamp).days
        if age >= warn_days:
            findings.append(Finding(
                Category.STALENESS, Severity.WARNING,
                f"Doc not updated in {age} days", f"{_rel(doc)} last updated {m.group(1)}.",
                suggestion="Re-read it against reality and bump the date, or archive it.",
                doc=_rel(doc), line=text.count(chr(10), 0, m.start()) + 1))
        elif age >= info_days:
            findings.append(Finding(
                Category.STALENESS, Severity.INFO,
                f"Doc aging ({age} days)", f"{_rel(doc)} last updated {m.group(1)}.",
                suggestion="Worth a freshness pass soon.",
                doc=_rel(doc), line=text.count(chr(10), 0, m.start()) + 1))
    return findings


# ---- 6. memory crosslinks (INFO) ------------------------------------------

LINK_RE = re.compile(r"\[\[([a-z0-9\-]+)\]\]", re.IGNORECASE)


def check_crosslinks(cfg):
    findings = []
    for target_str in cfg.get("extra_crosslink_targets", []):
        target = Path(os.path.expanduser(target_str))
        if not target.exists():
            continue
        mem_dir = target.parent
        existing = {p.stem for p in mem_dir.glob("*.md")}
        text = target.read_text(errors="replace")
        for m in LINK_RE.finditer(text):
            name = m.group(1)
            if name not in existing:
                findings.append(Finding(
                    Category.CROSSLINK, Severity.INFO,
                    f"Unresolved memory link [[{name}]]",
                    f"{_rel(target)} links to a memory '{name}' that has no file yet.",
                    suggestion="Fine if intentional (marks a memory worth writing); "
                               "otherwise fix the slug.",
                    doc=_rel(target), line=text.count(chr(10), 0, m.start()) + 1))
    return findings
