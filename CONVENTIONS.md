# doc-integrity — CONVENTIONS (the claim grammar)

This is the spec you actually use day to day. It is excluded from the auditor's own
scan (see `registry.json` → `exclude_docs`) precisely because it contains example
claims and example paths that are meant to be illustrative, not real.

---

## The one idea

Next to any factual claim in a doc, embed an HTML comment that tells the machine how to
verify it:

```markdown
Applications are logged in `applied.md`.  <!-- @check: exists applied.md -->
```

It renders invisibly (it's an HTML comment), so the doc reads normally to a human while
carrying its own proof obligation. When `applied.md` stops existing, the next audit
turns that line into a CRITICAL finding pointed at the exact file and line.

**Rule of thumb:** if a sentence states a fact that *could* be checked against the
filesystem, a service, or git — give it an `@check`. If it can't be mechanically
checked (vision, philosophy, sales judgement), leave it as prose; that's not drift-prone
in the same way.

## Syntax

```
<!-- @check: <verb> <args...> -->
<!-- @check: <verb> <args...> | freeform human note -->
```

- Whitespace-tolerant, case-insensitive on the verb.
- The optional `| note` after a pipe is shown in the finding (good for "live since…",
  ticket links, why-this-matters).
- Paths starting with `~` or `/` are absolute; **anything else is resolved relative to
  the directory of the doc the claim lives in.** So a project's `HANDOFF.md` can say
  `exists applied.md` about its own sibling — copy a doc elsewhere and its claims still
  point at the right place.

## Verbs

### Fast (filesystem only — run in every session via the hook)

| Verb | Example | Passes when |
|---|---|---|
| `exists <path>` | `<!-- @check: exists docs/applied.md -->` | path exists |
| `absent <path>` | `<!-- @check: absent ~/sun-v2 -->` | path does **not** exist |
| `grep <pat> <path>` | `<!-- @check: grep "LIVE" HANDOFF.md -->` | regex found in file |
| `nogrep <pat> <path>` | `<!-- @check: nogrep "yourdomain" setup.md -->` | regex **absent** (placeholder guard) |
| `count-lines <path> <op> <n>` | `<!-- @check: count-lines sent.md > 1 -->` | non-empty line count satisfies op (`< <= == >= > !=`) |

### Slow (network / subprocess — full run only, skipped under `--fast`/hook)

| Verb | Example | Passes when |
|---|---|---|
| `service <name> [active\|inactive]` | `<!-- @check: service jobs-dashboard active -->` | `systemctl is-active` matches |
| `http <url> <code>` | `<!-- @check: http https://example.com 200 -->` | GET returns that status |
| `port <n>` | `<!-- @check: port 3000 -->` | something is LISTENing on tcp/n |
| `git-clean <repo>` | `<!-- @check: git-clean ~/outreach -->` | `git status --porcelain` empty |
| `git-tracked <repo> <path>` | `<!-- @check: git-tracked . scoring.py -->` | path is tracked by git |

## Severity contract (why you can trust it)

| Source | Severity | Meaning |
|---|---|---|
| A failed `@check` | **CRITICAL** | You asserted it; reality broke it. A doc is lying. |
| Auto-detected dead path / missing doc-suite / placeholder | **WARNING** | Probably drift, but prose can be illustrative. |
| Staleness, unresolved `[[memory-links]]` | **INFO** | Advisory only. |

CRITICAL is reserved for things *you opted into*. That is deliberate: it means a red
alert always corresponds to a promise you made and broke, so you never learn to ignore
it. Exit code is `2` iff there is at least one CRITICAL.

## Escape hatches (controlling false positives)

- **Illustrative path on a line:** add `<!-- @example -->` anywhere on that line and the
  dead-path scanner skips every path on it.
- **Permanent allowlist:** add a regex to `registry.json` → `path_allowlist_regex`.
- **A doc full of examples:** add it to `registry.json` → `exclude_docs` (like this file).

## Worked example (these are real and pass against this repo)

The auditor's own entrypoint exists  <!-- @check: exists audit.py -->
and its registry is present too.      <!-- @check: exists registry.json -->
This conventions file is the spec.    <!-- @check: grep "claim grammar" CONVENTIONS.md -->

(These three live in an excluded file, so they document the grammar without being scored.
Put real claims like them directly in the docs whose facts you want locked down.)

## Where to put claims first (highest leverage)

1. Any sentence asserting a file/dir exists, especially success-metric files
   (`jobs/applied.md`, `outreach/sent.md`).
2. Any "LIVE at <url>" or "service X running" claim.
3. Any "committed / tracked" claim about code that docs say is done.
4. Any setup doc with a domain/credential that must be real before use (`nogrep` the
   placeholder).
