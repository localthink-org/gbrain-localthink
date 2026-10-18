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

Similar to how professional pipelines treat network egress as a boundary, this kit treats **git push as a boundary**. Nothing plaintext-secret-shaped crosses it. Two layers:

1. Per-file: converter redacts (`sk-…`, `ghp_…`, AWS, Slack, resend, Groq, Google, and inline base64 image data)
2. Repo-wide: `backup.sh` greps the full export + conversations tree before committing; a hit blocks push with exit code 2

Rule of thumb: **if even one secret pattern slips past the per-file pass, you want the repo-wide gate to catch it — and you want to investigate why the first layer missed.**

## Idempotency detail

Each converted LTF file has a content-hash marker (`.session_id.hash`). On rerun, conversions with identical content skip the write — so a daily cron doesn't grow the repo with unchanged sessions.

## Adapting to other agent platforms

- The built-in converter expects a simple JSONL per-message shape. If your agent logs differently, write a thin adapter that emits the expected shape, then run the converter as usual.
- Future: a small `adapters/` directory with examples for common formats (Hermes variants, OpenCode, Codex). Contributions welcome.

## What this kit is NOT

- Not a proxy, SDK, or runtime tool — it's a bridge, not a platform
- Not a security product — patterns are heuristic; review diffs before publishing
- Not opinionated about GBrain config — install and run GBrain as its own repo instructs
