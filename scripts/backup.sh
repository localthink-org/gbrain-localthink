#!/bin/bash
# backup.sh — GBrain export + LTF conversion + secret scan + git push.
# Configure with environment variables (defaults below). Safe to re-run.
set -euo pipefail

# ── CONFIG (env vars, with defaults) ──────────────────────────────────
BACKUP_REPO_DIR="${BACKUP_REPO_DIR:-$HOME/Desktop/memory-backup}"
# Informational compatibility knob. `gbrain export` uses the gbrain CLI's
# own data directory; this path is not passed to it. Kept so existing
# setups can still set GBRAIN_DIR without the script rejecting it.
# shellcheck disable=SC2034
GBRAIN_DIR="${GBRAIN_DIR:-$HOME/.gbrain}"
SESSIONS_DIR="${SESSIONS_DIR:-$HOME/.hermes/sessions}"  # agent session JSONL logs
REPO_REMOTE="${REPO_REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
# ──────────────────────────────────────────────────────────────────────

CONVERTER="$(dirname "$0")/../ltf/ltf_converter.py"

source_if() {
  if [ -f "$1" ]; then
    # User profile path is not a file ShellCheck can follow.
    # A profile that returns non-zero must not abort the backup.
    # shellcheck disable=SC1090
    source "$1" || true
  fi
}
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

# 3) Secret / inline-image scan. Same rules as the converter (--scan).
#    Block the push if anything still matches. Exit 2 is the scan gate.
if ! python3 "$CONVERTER" --scan ./export ./conversations; then
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

# Push failures must be visible. Retry once after rebase so two machines
# that committed in the same window can fast-forward instead of failing
# the cron run silently.
push_with_one_rebase_retry() {
  if git push "$REPO_REMOTE" "$BRANCH"; then
    return 0
  fi
  echo "WARN: git push to ${REPO_REMOTE} ${BRANCH} failed; retrying once after git pull --rebase" >&2
  if ! git pull --rebase "$REPO_REMOTE" "$BRANCH"; then
    echo "ERROR: git pull --rebase from ${REPO_REMOTE} ${BRANCH} failed; the local backup commit was not pushed" >&2
    return 1
  fi
  if ! git push "$REPO_REMOTE" "$BRANCH"; then
    echo "ERROR: git push to ${REPO_REMOTE} ${BRANCH} failed after one rebase retry" >&2
    return 1
  fi
}

push_with_one_rebase_retry || exit 1

echo "$(date '+%F %T') backup pushed: $(git log --oneline -1)"
