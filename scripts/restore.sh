#!/bin/bash
# restore.sh — One-shot restore on a fresh machine.
# Usage: restore.sh <path-to-backup-repo-clone>
# Restores GBrain pages from ./export/ (no embeddings), and prints
# where the LTF conversation files live.
set -euo pipefail

SOURCE="${1:?usage: restore.sh <backup-repo-clone-dir>}"
ENVFILE="$HOME/.profile"
[ -f "$ENVFILE" ] && source "$ENVFILE"
export PATH="$HOME/.bun/bin:$HOME/.local/bin:$PATH"

if [ ! -d "$SOURCE/export" ]; then
  echo "ERROR: $SOURCE/export not found — is this the backup clone?" >&2
  exit 1
fi

# 1) GBrain import (markdown → new brain)
if command -v gbrain > /dev/null 2>&1; then
  echo "→ gbrain import (no embeddings; run 'gbrain embed' later for semantic recall)"
  gbrain import "$SOURCE/export/" --no-embed || echo "gbrain import failed — check gbrain init state"
else
  echo "WARN: gbrain not on PATH — skip import; conversations only"
fi

# 2) LTF conversations
echo "→ LTF conversations available at: $SOURCE/conversations/"
echo "   open any .ltf.md in a markdown reader; tools can search this tree directly."

echo "restore done."
