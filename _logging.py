# VENDORED from a shared logging module on 2026-06-24T23:43:50Z.
# Do not edit here; edit the canonical source and re-run vendor.sh.

"""Central redaction: strip sensitive data from log records before write.

Pure and defensive — never raises. Matches by key name (recursive) and by
value pattern (SIN, Ontario health card, email, bearer/authorization token).
"""
import re

REDACTED = "[REDACTED]"

SENSITIVE_KEYS = {
    "name", "email", "phone", "address", "dob", "sin", "health_card",
    "passport", "credit_card", "password", "api_key", "token", "secret",
    "authorization", "conversation_text", "therapy_notes", "medical_history",
    "resume_content",
}

# Value patterns. Order matters; bearer/authorization first so it wins over email.
_VALUE_PATTERNS = [
    re.compile(r"(?i)\b(?:bearer\s+)\S+"),
    re.compile(r"(?i)Authorization:\s*\S+"),
    re.compile(r"\b\d{3}[-\s]?\d{3}[-\s]?\d{3}\b"),          # SIN / 9-digit health card
    re.compile(r"\b\d{4}[-\s]?\d{3}[-\s]?\d{3}[-\s]?[A-Za-z]{0,2}\b"),  # ON health card 10-digit + optional version code
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),           # email
]


def _redact_str(s):
    for pat in _VALUE_PATTERNS:
        if pat is _VALUE_PATTERNS[1]:           # "Authorization: X" -> keep label
            s = pat.sub("Authorization: " + REDACTED, s)
        else:
            s = pat.sub(REDACTED, s)
    return s


def redact(value):
    try:
        if isinstance(value, dict):
            return {
                k: (REDACTED if str(k).lower() in SENSITIVE_KEYS else redact(v))
                for k, v in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [redact(v) for v in value]
        if isinstance(value, str):
            return _redact_str(value)
        return value
    except Exception:
        return REDACTED

"""Canonical structured JSONL logger. Vendored into each project.

Never raises into the host app: any failure warns to stderr and returns.
"""
import json
import os
import sys
import uuid
import traceback
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def new_id():
    return uuid.uuid4().hex


class StructuredLogger:
    def __init__(self, app, log_dir="~/logs"):
        self.app = app
        self.dir = Path(os.path.expanduser(log_dir)) / app

    # ── public level methods ────────────────────────────────────────────
    def debug(self, event, message="", **kw):    self._emit("DEBUG", event, message, kw)
    def info(self, event, message="", **kw):      self._emit("INFO", event, message, kw)
    def warning(self, event, message="", **kw):   self._emit("WARNING", event, message, kw)
    def error(self, event, message="", **kw):     self._emit("ERROR", event, message, kw)
    def critical(self, event, message="", **kw):  self._emit("CRITICAL", event, message, kw)

    def exception(self, event, message="", **kw):
        kw.setdefault("traceback", traceback.format_exc().strip())
        self._emit("ERROR", event, message, kw)

    # ── internals ───────────────────────────────────────────────────────
    def _record(self, level, event, message, kw):
        request_id = kw.pop("request_id", None)
        workflow_id = kw.pop("workflow_id", None)
        duration_ms = kw.pop("duration_ms", None)
        rec = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "schema_version": SCHEMA_VERSION,
            "app": self.app,
            "environment": os.environ.get("LOG_ENV", "production"),
            "level": level,
            "event": event,
            "message": message,
            "request_id": request_id,
            "workflow_id": workflow_id,
            "duration_ms": duration_ms,
            "extra": kw,
        }
        return redact(rec)

    def _emit(self, level, event, message, kw):
        try:
            rec = self._record(level, event, message, kw)
            self.dir.mkdir(parents=True, exist_ok=True)
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            line = json.dumps(rec, default=str, ensure_ascii=False)
            with open(self.dir / f"{day}.jsonl", "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception as e:  # never crash the host app
            print(f"[logging] write failed: {e}", file=sys.stderr)

"""AI-call logging + timing helpers built on StructuredLogger."""
import time
from contextlib import contextmanager


def _ai_event(self, event, *, provider, model, tokens_in=None, tokens_out=None,
              cost_usd=None, duration_ms=None, **extra):
    self._emit("INFO", event, "", {
        "provider": provider, "model": model,
        "tokens_in": tokens_in, "tokens_out": tokens_out,
        "cost_usd": cost_usd, "duration_ms": duration_ms, **extra,
    })

StructuredLogger.ai_event = _ai_event


@contextmanager
def timed(log, event, **fields):
    start = time.monotonic()
    try:
        yield
    finally:
        fields["duration_ms"] = int((time.monotonic() - start) * 1000)
        log.info(event, **fields)
