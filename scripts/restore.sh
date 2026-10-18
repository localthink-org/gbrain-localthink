#!/bin/bash
# restore.sh — One-shot restore on a fresh machine.
# Usage: restore.sh <path-to-backup-repo-clone>
# Restores GBrain pages from ./export/ (no embeddings), and prints
# where the LTF conversation files live.
#
# Exit codes:
#   0  gbrain import succeeded, or gbrain is not installed (conversations only)
#   1  bad usage, missing export/, or gbrain is installed and import failed
set -euo pipefail

SOURCE="${1:?usage: restore.sh <backup-repo-clone-dir>}"
ENVFILE="$HOME/.profile"
if [ -f "$ENVFILE" ]; then
  # shellcheck disable=SC1090
  source "$ENVFILE"
fi
export PATH="$HOME/.bun/bin:$HOME/.local/bin:$PATH"

if [ ! -d "$SOURCE/export" ]; then
  echo "ERROR: $SOURCE/export not found — is this the backup clone?" >&2
  exit 1
fi

# Conversations are plain files; they are available even when import fails.
echo "→ LTF conversations available at: $SOURCE/conversations/"
echo "   open any .ltf.md in a markdown reader; tools can search this tree directly."

# 1) GBrain import (markdown → new brain). A missing CLI is conversations-only
#    and still succeeds. An installed CLI that fails the import does not.
if command -v gbrain > /dev/null 2>&1; then
  echo "→ gbrain import (no embeddings; run 'gbrain embed' later for semantic recall)"
  if ! gbrain import "$SOURCE/export/" --no-embed; then
    echo "ERROR: gbrain import failed — check gbrain init state" >&2
    exit 1
  fi
else
  echo "WARN: gbrain not on PATH — skip import; conversations only" >&2
fi

echo "restore done."
