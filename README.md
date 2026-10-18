# gbrain-localthink

**Bridge agent session logs and a personal knowledge brain into one git-owned memory backup.**

`gbrain-localthink` is a small bridge kit that connects two things every local-first AI user has but rarely backs up well:

1. **Agent conversation sessions** (raw JSONL logs from tools like [Hermes Agent](https://github.com/NousResearch/hermes-agent), OpenCode, Codex, or any agent that keeps message logs), converted to [LocalThink Format (LTF)](https://github.com/localthink-org/localthink-format) markdown files.
2. **A personal knowledge brain** ([GBrain](https://github.com/garrytan/gbrain) — Postgres-native personal knowledge with hybrid RAG search), exported to plain markdown.

Both land in one git repository you own — so your knowledge and your conversations become portable text with history, diffable and durable forever.

## Links

- https://localthink.org
- https://localthink.org/ltf-builder
- Chrome Web Store LTF Builder: https://chromewebstore.google.com/detail/ltf-builder/icpjoemgdpkmllkngcpndocnalodhfaj
- Mac download: https://localthink.ai/download
- Format repo: https://github.com/localthink-org/localthink-format

## Why

Agent platforms give you weak or no conversation export. Knowledge tools live in local databases you rarely back up. If a machine dies, both are gone.

The insight: **the most valuable state in personal AI — your knowledge and your conversation history — is also the cheapest state to back up, because it's all text.** One git repo is all you need.

`gbrain-localthink` is the missing wiring: a converter, a backup script, a restore script, and a cron template. No SaaS, no vendor lock, no daemon.

## What it does

- **Converts** agent session JSONL to clean LTF v1.0 markdown (redacts secrets and incidental private IPs, MACs, and emails; elides inline base64 images; summarizes tool output per LTF spec §5.2)
- **Exports** your GBrain pages to markdown (`gbrain export --dir`)
- **Scans** `export/` and `conversations/` for plaintext secret patterns before pushing — blocks the backup if anything looks like a credential
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

Point `backup.sh` at your backup repo and your local directories with environment variables. You do not need to edit the script. Defaults match `scripts/backup.sh`:

```sh
export BACKUP_REPO_DIR="$HOME/Desktop/memory-backup"  # local clone of the backup repo
export SESSIONS_DIR="$HOME/.hermes/sessions"          # agent session JSONLs
export REPO_REMOTE="origin"                           # git remote to push
export BRANCH="main"
# Informational only. `gbrain export` uses the gbrain CLI's own data directory;
# this kit does not pass the path through. Default if you set it: $HOME/.gbrain
export GBRAIN_DIR="$HOME/.gbrain"
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

The built-in converter reads a simple JSONL structure: one JSON object per line with `role` (`user` / `assistant` / `tool` / optional meta lines), `content` (string or list), and optional `timestamp`. Hook in your agent's log format by writing a small adapter that produces this shape, then point `SESSIONS_DIR` at that directory.

## What's in an LTF file

Minimal example:

```markdown
---
localthink: "1.0"
title: "Researching a repo"
created: "2026-10-18"
updated: "2026-10-18"
platform: "hermes-agent"
language: "zh-TW"
project: "Danko Ai"
project_id: "dankoai"
kind: "conversation"
status: "archived"
source: "export"
visibility: "private"
tags: ["GitHub"]
x_session_id: "demo-session-0001"
---

## Conversation

**Human:** What does this repo do?

**AI:** It's a Postgres-native knowledge brain with hybrid RAG search…
```

The `x_`-prefixed fields are custom extensions allowed by the LTF spec (parsers must ignore unknown fields). Tool messages are summarized, not dumped, per LTF spec §5.2.

The converter writes every string field as a JSON-encoded double-quoted scalar (valid YAML). A title with quotes, backslashes, or newlines stays on one line and cannot invent extra frontmatter keys. Dates and other strings are quoted the same way.

## Security posture

Push is **blocked** when a plaintext secret pattern is detected in `export/` or `conversations/` (the script logs and exits with code 2). The patterns live in `ltf/ltf_converter.py`. `backup.sh` runs `ltf_converter.py --scan` so the shell script cannot drift from the converter.

Session text is redacted before it is written. The scan is a second gate for anything the redaction missed, and for GBrain markdown that never passed through the converter.

### Secrets (redacted, and they fail `--scan`)

- OpenAI-style `sk-…`, `sk-proj-…`, Anthropic `sk-ant-…`
- GitHub `ghp_` / `gho_` / `ghu_` / `ghs_` / `ghr_` and `github_pat_…`
- AWS `AKIA…` / `ASIA…`, Slack `xox…`, Resend `re_…`, Groq `gsk_…`, Google `AIzaSy…`
- Stripe `sk_live_` / `rk_live_` / `sk_test_` / `rk_test_`
- PEM blocks (`-----BEGIN … PRIVATE KEY-----` through the matching `END` line)
- JWTs (`eyJ….….…`), `Bearer <token>` with a long token, Telegram bot tokens (`<id>:<35 chars>`)
- Cloudflare-style assignments: `cloudflare=…`, `cf_api=…`, `CLOUDFLARE_API_TOKEN=…`, `CF_API_KEY=…`
- Generic `*API_KEY=`, `*TOKEN=`, and `*PASSWORD=` assignments whose value is at least 16 characters
- Inline `data:image/…;base64,…` (elided, and still a scan hit if one remains)

### PII (redacted in session conversion only)

Tool output often contains a LAN address or a mailbox. Those are rewritten in `.ltf.md` files:

| Marker | What it replaces |
| --- | --- |
| `[REDACTED-IP]` | RFC1918, link-local `169.254.0.0/16`, CGNAT `100.64.0.0/10`; IPv6 unique-local, link-local, deprecated site-local `fec0::/10`, and IPv4-mapped forms of those |
| `[REDACTED-MAC]` | Six-octet `:` or `-` MACs, and Linux `wlx` / `enx` names that embed 12 hex digits |
| `[REDACTED-EMAIL]` | ASCII `name@domain.tld` whose domain starts with a letter |

Left alone on purpose, so ordinary notes are not rewritten: public IPs, `127.0.0.1`, `0.0.0.0`, `8.8.8.8`, documentation ranges (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`, `2001:db8::/32`), `::1`, three-part versions (`10.20.30`), times (`10:30`), `user@localhost`, `image@2x.png`, and Cisco dotted MACs (`aabb.ccdd.eeff`). Bare 40-character Cloudflare tokens with no label are not guessed; they look like hashes. Assignment values shorter than 16 characters are not treated as secrets.

PII redaction does **not** rewrite `export/` and does **not** fail the push. A knowledge page may mention a LAN address on purpose. Conversations are different: tool output usually captured the address by accident.

Still: **review the diff before pushing anything public.** The private→public upgrade is a human decision, not a script decision.

## Exit codes

### `scripts/backup.sh`

| Code | Meaning |
| --- | --- |
| 0 | Pushed, or there was nothing new to commit |
| 1 | Not a git repo, `gbrain export` failed, the converter failed, or `git push` failed. Push is tried once more after `git pull --rebase`. The error is printed to stderr; it is not discarded. |
| 2 | Secret scan refused the push. Nothing was committed. |

### `scripts/restore.sh`

| Code | Meaning |
| --- | --- |
| 0 | `gbrain import` succeeded, or `gbrain` is not on `PATH` (conversations-only restore; a warning goes to stderr) |
| 1 | Bad usage, `export/` missing, or `gbrain` is installed and `gbrain import` failed. The script does not print `restore done` after a failed import. |

### `ltf/ltf_converter.py`

| Code | Meaning |
| --- | --- |
| 0 | Conversion finished. Blocked sessions are counted (`blocked=`, `stale_removed=`) and do not fail the process. |
| 1 | No `.jsonl` files, missing arguments, or `--scan` found a secret (or a scan path does not exist). |

When a session is blocked, any previous `.ltf.md` and its `.hash` marker are deleted so a stale copy is not committed. The filename is omitted from the log if the filename itself matches a secret rule.

## Tests

Runtime dependencies are the Python 3.10+ standard library. Tests need pytest:

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m pytest
shellcheck scripts/backup.sh scripts/restore.sh
```

## License

MIT — see [LICENSE](LICENSE).

## Credits

- [LocalThink Format](https://github.com/localthink-org/localthink-format) — the LTF markdown standard for human-AI conversations (CC0 spec)
- [GBrain](https://github.com/garrytan/gbrain) — the knowledge brain doing the searching and remembering
- Built as the bridge layer between them, filling the gap neither tool covers on its own.
