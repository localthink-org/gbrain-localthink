# gbrain-localthink

**Bridge agent session logs and a personal knowledge brain into one git-owned memory backup.**

`gbrain-localthink` is a small bridge kit that connects two things every local-first AI user has but rarely backs up well:

1. **Agent conversation sessions** (raw JSONL logs from tools like [Hermes Agent](https://github.com/NousResearch/hermes-agent), OpenCode, Codex, or any agent that keeps message logs), converted to [LocalThink Format (LTF)](https://github.com/localthink-org/localthink-format) markdown files.
2. **A personal knowledge brain** ([GBrain](https://github.com/garrytan/gbrain) — Postgres-native personal knowledge with hybrid RAG search), exported to plain markdown.

Both land in one git repository you own — so your knowledge and your conversations become portable text with history, diffable and diffable forever.

## Why

Agent platforms give you weak or no conversation export. Knowledge tools live in local databases you rarely back up. If a machine dies, both are gone.

The insight: **the most valuable state in personal AI — your knowledge and your conversation history — is also the cheapest state to back up, because it's all text.** One git repo is all you need.

`gbrain-localthink` is the missing wiring: a converter, a backup script, a restore script, and a cron template. No SaaS, no vendor lock, no daemon.

## What it does

- **Converts** agent session JSONL to clean LTF v1.0 markdown (auto redacts secrets, elides inline base64 images, summarizes tool output per LTF spec §5.2)
- **Exports** your GBrain pages to markdown (`gbrain export --dir`)
- **Scans** everything for plaintext secret patterns before pushing — blocks the backup if anything looks like a credential
- **Commits and pushes** idempotently (skips if nothing changed)
- **Restores** on a new machine with `restore.sh` (clone → `gbrain import`)

## What it does NOT do

- No encryption at rest (use a private repo; add `git-crypt` yourself if needed)
- No automatic GBrain setup (you install gbrain separately)
- No fancy parsing of arbitrary session formats — one JSONL structure is supported out of the box; see "Adapters" below

## Requirements

- Python 3.10+
- [gbrain](https://github.com/garrytan/gbrain) CLI installed (`gbrain` on PATH)
- git with push access to your backup repo
- A private GitHub (or any git host) repository to receive the backup

## Install

```sh
git clone https://github.com/localthink-org/gbrain-localthink.git
cd gbrain-localthink
```

Point `backup.sh` at your backup repo and your local directories (all paths are at the top of the script):

```sh
# edit these three lines in scripts/backup.sh
BACKUP_REPO_DIR="$HOME/Desktop/memory-backup"   # local clone of the backup repo
GBRAIN_DIR="$HOME/my-gbrain"                    # where your gbrain data lives
SESSIONS_DIR="$HOME/.hermes/sessions"           # agent session JSONLs
```

First run:

```sh
./scripts/backup.sh
```

Then set up a daily cron (see [cron/](cron/)) or run it yourself whenever.

## Restore on a new machine

```sh
# clone the backup, then:
./scripts/restore.sh ~/Desktop/memory-backup
# → runs `gbrain import ./export/` (no embeddings) and prints where the LTF files landed
```

## Adapters

The built-in converter reads a simple JSONL structure: one JSON object per line with `role` (`user` / `assistant` / `tool` / optional meta lines), `content` (string or list), and optional `timestamp`. Hook in your agent's log format by writing a small adapter that produces this shape, or by passing a different `--format` with your own Python adapter module.

## What's in an LTF file

Minimal example:

```markdown
---
localthink: "1.0"
title: "Researching a repo"
created: 2026-10-18
updated: 2026-10-18
platform: hermes-agent
language: zh-TW
project: "Danko Ai"
project_id: "dankoai"
kind: conversation
status: archived
source: export
visibility: private
tags: ["GitHub"]
x_session_id: "20260911_104208_ba74abae"
---

## Conversation

**Human:** What does this repo do?

**AI:** It's a Postgres-native knowledge brain with hybrid RAG search…
```

The `x_`-prefixed fields are custom extensions allowed by the LTF spec (parsers must ignore unknown fields). Tool messages are summarized, not dumped, per LTF spec §5.2.

## Security posture

- Push is **blocked** when a plaintext secret pattern is detected in the export/conversation output (the script logs and exits with code 2).
- Outputs are sanitized twice: once per-file at conversion, once repo-wide before commit.
- Known transforms: `sk-…`, `ghp_…`, `AKIA…`, `xox…-…`, `re_…`, `gsk_…`, `AIza…`, and `data:image/…;base64,…` are redacted or elided.
-Still: **review the diff before pushing anything public.** The private→public upgrade is a human decision, not a script decision.

## License

MIT — see [LICENSE](LICENSE).

## Credits

- [LocalThink Format](https://github.com/localthink-org/localthink-format) — the LTF markdown standard for human-AI conversations (CC0 spec)
- [GBrain](https://github.com/garrytan/gbrain) — the knowledge brain doing the searching and remembering
- Built as the bridge layer between them, filling the gap neither tool covers on its own.
