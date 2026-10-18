#!/bin/bash
# backup.sh — GBrain export + LTF conversion + sanitize + git push.
# Configurable at the top; safe to run repeatedly (idempotent).
set -euo pipefail

# ── CONFIG ────────────────────────────────────────────────────────────
BACKUP_REPO_DIR="${BACKUP_REPO_DIR:-$HOME/Desktop/memory-backup}"
GBRAIN_DIR="${GBRAIN_DIR:-$HOME/.gbrain}"        # your gbrain data location (informational)
SESSIONS_DIR="${SESSIONS_DIR:-$HOME/.hermes/sessions}"  # your agent's session logs
REPO_REMOTE="${REPO_REMOTE:-origin}"             # git remote to push to
BRANCH="${BRANCH:-main}"
# ──────────────────────────────────────────────────────────────────────

CONVERTER="$(dirname "$0")/../ltf/ltf_converter.py"

source_if() { [ -f "$1" ] && source "$1" || true; }
source_if "$HOME/.profile"   # for PATH: bun, gbrain, gh
export PATH="$HOME/.bun/bin:$HOME/.local/bin:$PATH"

cd "$BACKUP_REPO_DIR"

# Ensure the backup repo exists and is a git repo with the expected remote.
if [ ! -d .git ]; then
  echo "ERROR: $BACKUP_REPO_DIR is not a git repository" >&2
  exit 1
fi

# 1) GBrain → markdown export
mkdir -p export
if command -v gbrain > /dev/null 2>&1; then
  gbrain export --dir ./export/ > /tmp/gbrain_export.log 2>&1 || {
    echo "ERROR: gbrain export failed — see /tmp/gbrain_export.log" >&2
    exit 1
  }
fi

# 2) Sessions → LTF markdown
python3 "$CONVERTER" "$SESSIONS_DIR" --out ./conversations/

# 3) Secret / inline-image scan. Block push if anything matches.
if grep -rliE "sk-[a-zA-Z0-9_]{20,}|ghp_[a-zA-Z0-9]{30,}|AKIA[A-Z0-9]{16}|xox[baprs]-[0-9a-zA-Z-]{20,}|re_[a-zA-Z0-9]{30,}|gsk_[a-zA-Z0-9]{30,}|AIzaSy[a-zA-Z0-9_-]{33}|data:image/[a-z+]+;base64" export/ conversations/ ; then
  echo "BLOCKED: plaintext secret pattern found — resolve locally before pushing" >&2
  git reset > /dev/null 2>&1 || true
  exit 2
fi

# 4) Commit + push (idempotent — skip if nothing changed)
git add -A
if git diff --cached --quiet; then
  echo "$(date '+%F %T') no changes, skip push"
  exit 0
fi

git commit -q -m "backup: gbrain+ltf $(date '+%F') $(date '+%H:%M')"
git push "$REPO_REMOTE" "$BRANCH" > /dev/null 2>&1

echo "$(date '+%F %T') backup pushed: $(git log --oneline -1)"
