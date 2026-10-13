"""The claim grammar — the heart of doc-integrity.

A *claim* is an HTML comment embedded next to a factual statement in a doc:

    Applications are logged in `applied.md`.  <!-- @check: exists applied.md -->
    The dashboard is LIVE.                    <!-- @check: http https://example.com 200 | live since 2026-06-15 -->

Because it is an HTML comment it renders invisibly, so the doc reads normally to a
human while carrying its own proof obligation for the machine.

Verbs (fast = filesystem only; slow = network/subprocess, skipped under --fast):

  FAST
    exists <path>                  path exists (file or dir)
    absent <path>                  path does NOT exist
    grep <pattern> <path>          regex/substring present in file
    nogrep <pattern> <path>        pattern absent in file (placeholder / stale-string guard)
    count-lines <path> <op> <n>    non-empty line count, op in < <= == >= > !=

  SLOW
    service <name> active|inactive systemctl is-active --quiet <name>
    http <url> <code>              HTTP GET, assert status code (urllib, 10s timeout)
    port <n>                       something is LISTENing on tcp <n>
    git-clean <repo>               `git status --porcelain` is empty
    git-tracked <repo> <path>      <path> is tracked by git (not untracked/ignored)

Path resolution: a path starting with ~ or / is absolute; anything else is resolved
relative to the directory of the doc the claim lives in. So a project's HANDOFF.md can
simply assert `exists applied.md` about its own sibling file.
"""
import os
import re
import shlex
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

CLAIM_RE = re.compile(r"<!--\s*@check:\s*(.*?)\s*-->", re.IGNORECASE | re.DOTALL)

SLOW_VERBS = {"service", "http", "port", "git-clean", "git-tracked"}

HOME = Path(os.path.expanduser("~"))


class ClaimResult:
    __slots__ = ("ok", "detail", "skipped", "error")

    def __init__(self, ok, detail="", skipped=False, error=False):
        self.ok = ok
        self.detail = detail
        self.skipped = skipped
        self.error = error          # malformed claim / unknown verb


def parse_claims(text):
    """Yield (raw_body, note, line_number) for every @check in the text."""
    for m in CLAIM_RE.finditer(text):
        body = m.group(1).strip()
        note = ""
        if "|" in body:
            body, note = body.split("|", 1)
            body, note = body.strip(), note.strip()
        line = text.count("\n", 0, m.start()) + 1
        yield body, note, line


def _resolve(path_str, doc_path):
    p = os.path.expanduser(path_str)
    if os.path.isabs(p):
        return Path(p)
    return (Path(doc_path).resolve().parent / p).resolve()


def run_claim(body, doc_path, fast=False):
    """Execute one claim body, return a ClaimResult."""
    try:
        parts = shlex.split(body)
    except ValueError as e:
        return ClaimResult(False, f"unparseable claim: {e}", error=True)
    if not parts:
        return ClaimResult(False, "empty @check claim", error=True)

    verb, args = parts[0].lower(), parts[1:]

    if fast and verb in SLOW_VERBS:
        return ClaimResult(True, f"{verb} skipped (--fast)", skipped=True)

    try:
        return _DISPATCH.get(verb, _unknown)(verb, args, doc_path)
    except Exception as e:  # a check must never crash the whole audit
        return ClaimResult(False, f"{verb} check errored: {e}", error=True)


# ---- verb implementations -------------------------------------------------

def _unknown(verb, args, doc_path):
    return ClaimResult(False, f"unknown verb '{verb}'", error=True)


def _exists(verb, args, doc_path):
    if len(args) != 1:
        return ClaimResult(False, "exists needs exactly one <path>", error=True)
    p = _resolve(args[0], doc_path)
    return ClaimResult(p.exists(), f"{args[0]} -> {p} {'present' if p.exists() else 'MISSING'}")


def _absent(verb, args, doc_path):
    if len(args) != 1:
        return ClaimResult(False, "absent needs exactly one <path>", error=True)
    p = _resolve(args[0], doc_path)
    return ClaimResult(not p.exists(), f"{args[0]} -> {p} {'still present' if p.exists() else 'absent'}")


def _read(p):
    try:
        return p.read_text(errors="replace")
    except Exception:
        return None


def _grep(verb, args, doc_path):
    if len(args) != 2:
        return ClaimResult(False, "grep needs <pattern> <path>", error=True)
    pattern, p = args[0], _resolve(args[1], doc_path)
    if not p.exists():
        return ClaimResult(False, f"file missing: {p}")
    text = _read(p)
    hit = re.search(pattern, text) is not None if text is not None else False
    return ClaimResult(hit, f"/{pattern}/ {'found' if hit else 'NOT found'} in {args[1]}")


def _nogrep(verb, args, doc_path):
    if len(args) != 2:
        return ClaimResult(False, "nogrep needs <pattern> <path>", error=True)
    pattern, p = args[0], _resolve(args[1], doc_path)
    if not p.exists():
        return ClaimResult(False, f"file missing: {p}")
    text = _read(p)
    hit = re.search(pattern, text) is not None if text is not None else False
    return ClaimResult(not hit, f"/{pattern}/ {'STILL present' if hit else 'absent'} in {args[1]}")


_OPS = {
    "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b, ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b, "!=": lambda a, b: a != b,
}


def _count_lines(verb, args, doc_path):
    if len(args) != 3:
        return ClaimResult(False, "count-lines needs <path> <op> <n>", error=True)
    p, op, n = _resolve(args[0], doc_path), args[1], args[2]
    if op not in _OPS or not n.lstrip("-").isdigit():
        return ClaimResult(False, f"bad op/number: {op} {n}", error=True)
    if not p.exists():
        return ClaimResult(False, f"file missing: {p}")
    text = _read(p) or ""
    count = sum(1 for ln in text.splitlines() if ln.strip())
    ok = _OPS[op](count, int(n))
    return ClaimResult(ok, f"{args[0]} has {count} non-empty lines (need {op} {n})")


def _service(verb, args, doc_path):
    if len(args) not in (1, 2):
        return ClaimResult(False, "service needs <name> [active|inactive]", error=True)
    name = args[0]
    want = args[1].lower() if len(args) == 2 else "active"
    r = subprocess.run(["systemctl", "is-active", name],
                       capture_output=True, text=True, timeout=10)
    state = r.stdout.strip()
    is_active = state == "active"
    ok = is_active if want == "active" else not is_active
    return ClaimResult(ok, f"service {name} is '{state}' (want {want})")


def _http(verb, args, doc_path):
    if len(args) != 2 or not args[1].isdigit():
        return ClaimResult(False, "http needs <url> <code>", error=True)
    url, want = args[0], int(args[1])
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "doc-integrity"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            code = resp.status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:
        return ClaimResult(False, f"{url} unreachable: {e}")
    return ClaimResult(code == want, f"{url} -> {code} (want {want})")


def _port(verb, args, doc_path):
    if len(args) != 1 or not args[0].isdigit():
        return ClaimResult(False, "port needs <n>", error=True)
    n = args[0]
    r = subprocess.run(["ss", "-ltn"], capture_output=True, text=True, timeout=10)
    listening = re.search(rf":{n}\b", r.stdout) is not None
    return ClaimResult(listening, f"tcp/{n} {'LISTENing' if listening else 'not listening'}")


def _git(repo):
    return ["git", "-C", str(repo)]


def _git_clean(verb, args, doc_path):
    if len(args) != 1:
        return ClaimResult(False, "git-clean needs <repo>", error=True)
    repo = _resolve(args[0], doc_path)
    r = subprocess.run(_git(repo) + ["status", "--porcelain"],
                       capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        return ClaimResult(False, f"not a git repo: {repo}")
    dirty = r.stdout.strip()
    return ClaimResult(not dirty, "clean" if not dirty else f"{len(dirty.splitlines())} uncommitted change(s)")


def _git_tracked(verb, args, doc_path):
    if len(args) != 2:
        return ClaimResult(False, "git-tracked needs <repo> <path>", error=True)
    repo = _resolve(args[0], doc_path)
    r = subprocess.run(_git(repo) + ["ls-files", "--error-unmatch", args[1]],
                       capture_output=True, text=True, timeout=15)
    return ClaimResult(r.returncode == 0,
                       f"{args[1]} {'tracked' if r.returncode == 0 else 'NOT tracked'} in {args[0]}")


_DISPATCH = {
    "exists": _exists, "absent": _absent, "grep": _grep, "nogrep": _nogrep,
    "count-lines": _count_lines, "service": _service, "http": _http,
    "port": _port, "git-clean": _git_clean, "git-tracked": _git_tracked,
}
