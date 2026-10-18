#!/usr/bin/env python3
"""ltf_converter.py — Agent session JSONL → LocalThink Format (LTF) v1.0.

Reads agent session JSONL files (one JSON object per line) and writes one
`.ltf.md` file per session into an output directory.

Expected JSONL shape:
  {"role":"session_meta", ...optional tools/timestamps...}   (first line, skipped)
  {"role":"user"|"assistant", "content": str|list, "timestamp": ISO, ...}
  {"role":"tool", "content": str, "timestamp": ISO, ...}

Design principles (mirroring LTF SPEC v1.0):
- Frontmatter: required fields + recommended fields + x_ custom extensions
- Body: **Human:** / **AI:** turns; tool output summarized per SPEC §5.2
- Sanitization: plaintext secret patterns → [REDACTED]; inline base64 image
  data URIs → "[image data elided]" (keeps markdown small and safe)
- Idempotent: reruns skip sessions whose output already exists unchanged
"""
import argparse
import glob
import json
import os
import re
import hashlib
import sys

DEFAULT_OUT_DIR = "./out/ltf/"

SECRET_PATTERNS = re.compile(
    r"sk-[a-zA-Z0-9_]{20,}"        # OpenAI-style
    r"|ghp_[a-zA-Z0-9]{30,}"       # GitHub PAT
    r"|AKIA[A-Z0-9]{16}"           # AWS access key
    r"|xox[baprs]-[0-9a-zA-Z-]{20,}" # Slack token
    r"|re_[a-zA-Z0-9]{30,}"        # Resend key
    r"|gsk_[a-zA-Z0-9]{30,}"       # Groq key
    r"|AIzaSy[a-zA-Z0-9_-]{33}"    # Google API key
)

DATA_URI = re.compile(r"data:image/[a-z+]+;base64,[A-Za-z0-9+/=\s]+")

TOOL_SUMMARY_LIMIT = 300  # chars per tool output, per LTF §5.2 spirit


def flatten(content) -> str:
    """Flatten string-or-list message content to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(
                    item.get("text")
                    or item.get("content")
                    or json.dumps(item, ensure_ascii=False)
                )
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def sanitize(text: str) -> str:
    text = SECRET_PATTERNS.sub("[REDACTED]", text)
    text = DATA_URI.sub("[image data elided]", text)
    return text


def slug_title(msgs) -> str:
    """Derive a human-readable title: first meaningful user line."""
    for m in msgs:
        if m.get("role") == "user":
            first = flatten(m.get("content")).strip().splitlines()[0][:60]
            if first and len(first) >= 4:
                return first
    return "Untitled session"


def topic_tags(all_text: str) -> list:
    """Cheap keyword → topic tag mapping. Override/extend as needed."""
    table = [
        ("dankochat", "DankoChat"), ("dankomen", "DankoMen"), ("gbrain", "GBrain"),
        ("cron", "Cron/Automation"), ("whatsapp", "WhatsApp"),
        ("cloudflare", "Cloudflare"), ("github", "GitHub"),
        ("telegram", "Telegram"), ("email", "Email"),
        ("hermes", "Hermes Agent"), ("opencode", "OpenCode"),
        ("market brief", "Market Brief"),
    ]
    low = all_text.lower()
    tags = [tag for kw, tag in table if kw in low or kw in all_text]
    return tags[:5] or ["general"]


def to_ltf(path: str, platform: str = "hermes-agent",
           language: str = "zh-TW", project: str = "Personal",
           project_id: str = "personal", kind: str = "conversation",
           status: str = "archived", source: str = "export") -> str | None:
    """Convert one session JSONL file to an LTF markdown string."""
    sid = os.path.basename(path).rsplit(".", 1)[0]
    msgs, meta = [], {}
    with open(path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue  # ignore malformed line
            if d.get("role") == "session_meta":
                meta = d
                continue
            msgs.append(d)

    if not any(m.get("role") in ("user", "assistant") for m in msgs):
        return None

    created = (meta.get("timestamp") or (msgs[0].get("timestamp") or ""))[:10] or sid[:8]
    updated = (msgs[-1].get("timestamp") or created)[:10]
    title = slug_title(msgs)
    all_text = "\n".join(flatten(m.get("content")) for m in msgs)
    tags = topic_tags(all_text)
    n_tool = sum(1 for m in msgs if m.get("role") == "tool")
    n_tool_types = len(meta.get("tools") or [])

    fm = (
        "---\n"
        'localthink: "1.0"\n'
        f'title: "{title}"\n'
        f"created: {created}\n"
        f"updated: {updated}\n"
        f"platform: {platform}\n"
        f"language: {language}\n"
        f'project: "{project}"\n'
        f'project_id: "{project_id}"\n'
        f"kind: {kind}\n"
        f"status: {status}\n"
        f"source: {source}\n"
        "visibility: private\n"
        f"tags: {json.dumps(tags, ensure_ascii=False)}\n"
        f'x_session_id: "{sid}"\n'
        f"x_tool_calls: {n_tool}\n"
        f"x_tool_definitions: {n_tool_types}\n"
        "---\n"
    )

    lines = ["## Conversation\n"]
    for d in msgs:
        role = d.get("role")
        text = sanitize(flatten(d.get("content")).strip())
        if not text:
            continue
        ts = (d.get("timestamp") or "")[:16].replace("T", " ")
        if role == "user":
            label = "**Human:**"
        elif role == "assistant":
            label = "**AI:**"
        elif role == "tool":
            short = text if len(text) <= TOOL_SUMMARY_LIMIT else text[:TOOL_SUMMARY_LIMIT - 3] + "..."
            lines.append(f"   *Tool ({ts}):* {short}")
            continue
        else:
            label = f"**{role.capitalize()}:**"
        header = f"{label} `{ts}`\n" if ts else f"{label}\n"
        lines.append(header + text + "\n")

    return fm + "\n".join(lines) + "\n"


def sha1_of(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:10]


def main():
    p = argparse.ArgumentParser(description="Convert agent session JSONL to LTF markdown.")
    p.add_argument("sessions_dir", help="Directory of *.jsonl session files")
    p.add_argument("--out", default=DEFAULT_OUT_DIR, help="Output directory")
    p.add_argument("--platform", default="hermes-agent")
    p.add_argument("--language", default="zh-TW")
    p.add_argument("--project", default="Personal")
    p.add_argument("--project-id", default="personal")
    p.add_argument("--overwrite", action="store_true",
                   help="Re-write files even if unchanged (default: skip if content hash matches)")
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)
    files = sorted(glob.glob(os.path.join(args.sessions_dir, "*.jsonl")))
    if not files:
        print(f"no .jsonl files under {args.sessions_dir}", file=sys.stderr)
        return 1

    written = skipped = empty = blocked = 0
    for path in files:
        ltf = to_ltf(path, platform=args.platform, language=args.language,
                     project=args.project, project_id=args.project_id)
        if ltf is None:
            empty += 1
            continue
        sid = os.path.basename(path).rsplit(".", 1)[0]
        out_path = os.path.join(args.out, f"{sid}.ltf.md")
        h = sha1_of(ltf)
        marker = os.path.join(args.out, f".{sid}.hash")
        if not args.overwrite and os.path.exists(marker) and open(marker).read() == h:
            skipped += 1
            continue
        if SECRET_PATTERNS.search(ltf):
            blocked += 1
            print(f"BLOCKED (secret found in {sid}) — skipped", file=sys.stderr)
            continue
        with open(out_path, "w") as f:
            f.write(ltf)
        with open(marker, "w") as f:
            f.write(h)
        written += 1

    print(f"written={written} skipped_unchanged={skipped} skipped_empty={empty} blocked={blocked}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
