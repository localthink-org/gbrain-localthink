"""Shared fixtures for the backup-kit tests. No network, no real secrets."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONVERTER = ROOT / "ltf" / "ltf_converter.py"
BACKUP = ROOT / "scripts" / "backup.sh"
RESTORE = ROOT / "scripts" / "restore.sh"


def write_session(path: Path, messages, tools=None, timestamp="2026-04-01T09:00:00"):
    meta = {"role": "session_meta", "timestamp": timestamp, "tools": tools or []}
    lines = [json.dumps(meta, ensure_ascii=False)]
    for message in messages:
        lines.append(json.dumps(message, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
