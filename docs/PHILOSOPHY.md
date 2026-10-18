# Philosophy and Setup Notes

## The three layers and why they belong together

| Layer | What it captures | Where it lives before this kit |
|---|---|---|
| Knowledge | Facts, rules, SOPs, decisions you'd want to recall later | GBrain (local PGlite) |
| Conversation | The *how* behind the knowledge — decisions, digestion, corrections | Hermes/OpenCode/Codex session JSONL |
| Timeline | Timestamped history of both | git commit history |

Backed up together, the three layers answer: *what I knew, how I figured it out, and when*. No single tool gives you all three.

## Why LocalThink Format for conversations

LTF is deliberately simple markdown: readable without a tool, diffable in git, extensible via `x_` fields, parseable by any YAML-aware script. The spec (CC0) is a small standard — see [localthink-format](https://github.com/localthink-org/localthink-format) — and this kit is one of its first full implementations.

## Why GBrain for knowledge

GBrain is local-first (PGlite, no server), keyword-plus-hybrid RAG, and has a real import/export path (`gbrain export` / `gbrain import`) that produces plain markdown — exactly the shape git wants.

## Why git as the backup target

- Text-native storage with history, diffs, and blame
- Public or private is a repo-level switch
- Any git host works; no lock-in to a vendor's "export API"
- Restore is `git clone`

## The sanitize-first principle

Similar to how professional pipelines treat network egress as a boundary, this kit treats **git push as a boundary**. Nothing plaintext-secret-shaped crosses it. Two layers, one list of rules:

1. Per-file: the converter redacts secrets and incidental PII (private IPs, MACs, emails) while it writes `.ltf.md`. String frontmatter is JSON-quoted so a title cannot break the YAML.
2. Repo-wide: `backup.sh` runs `ltf_converter.py --scan` on `export/` and `conversations/` before committing. A hit blocks the push with exit code 2. The shell script does not keep a second copy of the regex.

PII markers are not scan failures. GBrain pages are the user's notes; a LAN address there may be intentional. Session tool output is redacted because it usually captured the address by accident.

Rule of thumb: **if even one secret pattern slips past the per-file pass, you want the repo-wide gate to catch it — and you want to investigate why the first layer missed.**

A session that still matches after redaction is not written. Its previous `.ltf.md` and hash marker are removed so an older, unredacted copy is not what gets committed.

## Idempotency detail

Each converted LTF file has a content-hash marker (`.session_id.hash`). On rerun, conversions with identical content skip the write — so a daily cron doesn't grow the repo with unchanged sessions. The hash is checked only after the secret gate: a blocked session never keeps a hash that would skip a later clean run, and the stale file is deleted first.

## Adapting to other agent platforms

- The built-in converter expects a simple JSONL per-message shape. If your agent logs differently, write a thin adapter that emits the expected shape, then run the converter as usual.
- Future: a small `adapters/` directory with examples for common formats (Hermes variants, OpenCode, Codex). Contributions welcome.

## What this kit is NOT

- Not a proxy, SDK, or runtime tool — it's a bridge, not a platform
- Not a security product — patterns are heuristic; review diffs before publishing
- Not opinionated about GBrain config — install and run GBrain as its own repo instructs
