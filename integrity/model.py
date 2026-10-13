"""Finding / Severity / report model.

Mirrors an earlier auditor's finding type on purpose so the two speak the same
language. If you already trust the life_os audit output, this reads identically.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Severity(Enum):
    CRITICAL = "CRITICAL"   # an opt-in @check assertion failed: a doc is actively lying
    WARNING = "WARNING"     # auto-detected heuristic: probably drift, but could be illustrative
    INFO = "INFO"           # advisory: staleness, unresolved links, skipped slow checks


class Category(Enum):
    CLAIM = "Embedded Claim"      # an @check: ... assertion
    DEAD_PATH = "Dead Path"       # a ~/... path mentioned in a doc that no longer exists
    DOC_SUITE = "Doc Suite"       # missing CHARTER/HANDOFF/LOG etc.
    PLACEHOLDER = "Placeholder"   # yourdomain.com, FIXME, CHANGEME, ...
    STALENESS = "Staleness"       # "Last updated" older than threshold
    CROSSLINK = "Crosslink"       # [[memory-name]] that resolves to nothing
    ENGINE = "Engine"             # the auditor itself had a problem


@dataclass
class Finding:
    category: Category
    severity: Severity
    title: str
    detail: str
    suggestion: str = ""
    doc: str = ""          # path of the doc the finding came from (relative to ~ where possible)
    line: int = 0          # 1-based line number, 0 if not line-specific

    @property
    def is_critical(self) -> bool:
        return self.severity == Severity.CRITICAL

    @property
    def is_warning(self) -> bool:
        return self.severity == Severity.WARNING

    @property
    def location(self) -> str:
        if self.doc and self.line:
            return f"{self.doc}:{self.line}"
        return self.doc or ""


@dataclass
class AuditReport:
    timestamp: datetime
    duration_seconds: float
    findings: list = field(default_factory=list)
    hostname: str = ""
    docs_scanned: int = 0
    checks_run: int = 0
    fast_mode: bool = False

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.is_critical)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.is_warning)

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.INFO)

    @property
    def has_criticals(self) -> bool:
        return self.critical_count > 0
