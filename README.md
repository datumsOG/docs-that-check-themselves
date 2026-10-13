# Documents that carry their own proof

By [Blair Zasitko](https://blairz.ca) · [Why it exists](https://blairz.ca/work/verification/)

Documentation drifts. A README says a service is running months after it was switched off,
and nobody notices because nothing checks. This is a small auditor, Python standard library
only, that reads every document under a folder and verifies what it can against the machine.

## The one idea

Next to a factual claim, write an HTML comment that says how to check it:

```markdown
Applications are logged in `applied.md`.  <!-- @check: exists applied.md -->
```

The comment is invisible when the document is rendered. When `applied.md` stops existing,
the next audit reports that line, with the file and line number, as a critical finding.
`CONVENTIONS.md` is the full grammar: files, services, ports, git state, counts.

It also checks things nobody annotated: paths mentioned in a document that are no longer on
disk, links between documents that point nowhere, and documents nobody has touched in a
long time.

## Run it

```
cp registry.example.json registry.json     # then set scan_roots to your own folders
python3 audit.py
```

It prints findings by severity and exits non-zero if any are critical, so it can run from
cron or a session-start hook.

## What using it taught me

The first version reported 1,801 warnings, so nobody read it, which is worse than having
no auditor. It was treating raw source material (exports, transcripts) as documentation.
Raw material cannot be out of date; only a curated document can. The exclusions in the
registry exist for that reason. On my own server it now checks 859 documents on every
session start.

## How it was made

I designed this and directed its construction with AI coding agents (Claude Code).

The code is MIT-licensed (see `LICENSE`).
