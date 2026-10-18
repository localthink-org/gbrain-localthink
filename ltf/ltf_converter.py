#!/usr/bin/env python3
"""ltf_converter.py — Agent session JSONL → LocalThink Format (LTF) v1.0.

Reads agent session JSONL files (one JSON object per line) and writes one
`.ltf.md` file per session into an output directory.

Expected JSONL shape:
  {"role":"session_meta", ...optional tools/timestamps...}   (first line, skipped)
  {"role":"user"|"assistant", "content": str|list, "timestamp": ISO, ...}
  {"role":"tool", "content": str, "timestamp": ISO, ...}

Also exposes ``--scan DIR`` so backup.sh can run the same secret rules the
converter uses, instead of keeping a second regex in the shell script.

Redaction policy (intentionally conservative):
- Secrets become ``[REDACTED]``. Inline ``data:image/...;base64`` payloads
  become ``[image data elided]``. The same rules gate ``--scan`` and the
  pre-push check.
- PII in converted sessions becomes ``[REDACTED-IP]``, ``[REDACTED-MAC]``, or
  ``[REDACTED-EMAIL]``. PII is not a push-blocking secret: a knowledge export
  may legitimately mention a LAN address, while tool output in a chat usually
  captured it by accident.
- IPv4 redaction covers RFC1918 (10/8, 172.16/12, 192.168/16), link-local
  169.254/16, and shared CGNAT 100.64/10. Loopback, 0.0.0.0, multicast,
  public addresses, and documentation ranges (192.0.2.0/24, 198.51.100.0/24,
  203.0.113.0/24) are left alone so tutorials and ``8.8.8.8`` / ``127.0.0.1``
  survive. Three-part versions (``10.20.30``) are not addresses.
- IPv6 redaction covers unique-local fc00::/7, link-local fe80::/10, the
  deprecated site-local fec0::/10, and IPv4-mapped forms of a sensitive IPv4.
  Loopback ``::1``, unspecified ``::``, documentation ``2001:db8::/32``, and
  global unicast are left alone.
- MAC addresses are six hex octets with ``:`` or ``-``, plus Linux predictable
  names ``wlx`` / ``enx`` plus 12 hex digits (those names are a MAC). Times
  (``10:30``) are not MACs. Cisco dotted form (``aabb.ccdd.eeff``) is not
  rewritten; it collides with other dotted hex.
- Emails are ASCII ``name@domain.tld`` whose domain starts with a letter.
  ``image@2x.png`` and ``user@localhost`` are not emails.
- Assignment values (``*API_KEY``, ``*TOKEN``, ``*PASSWORD``, any case) are
  redacted only when the value is at least 16 characters, so ``password=hunter2``
  and short placeholders stay readable. Bare Cloudflare API tokens (no prefix)
  are not guessed; ``CLOUDFLARE_API_TOKEN=``, ``CF_API_TOKEN=``, and
  ``cloudflare=`` / ``cf_api=`` are.
"""
import argparse
import glob
import hashlib
import ipaddress
import json
import os
import re
import sys

DEFAULT_OUT_DIR = "./out/ltf/"
ASSIGNMENT_VALUE_MIN = 16
TOOL_SUMMARY_LIMIT = 300  # chars per tool output, per LTF §5.2 spirit

_REDACTED = "[REDACTED]"


def _assignment_repl(match: re.Match) -> str:
    """Keep the key name; replace only the long value."""
    return (
        f"{match.group('q1')}{match.group('key')}{match.group('q2')}"
        f"{match.group('sep')}{match.group('q3')}{_REDACTED}"
    )


def _labeled_repl(match: re.Match) -> str:
    return f"{match.group('key')}{match.group('sep')}{match.group('q')}{_REDACTED}"


def _bearer_repl(match: re.Match) -> str:
    return f"{match.group('label')}{match.group('sp')}{_REDACTED}"


def _compile_rules():
    """Single table of secret / payload rules. Scan and redact both use it."""
    raw = [
        (
            "pem",
            re.compile(
                r"(?is)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"
                r".*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
                r"|-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"
            ),
            _REDACTED,
        ),
        (
            "jwt",
            re.compile(
                r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{10,}"
                r"\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
            ),
            _REDACTED,
        ),
        (
            "bearer",
            re.compile(
                r"(?<![A-Za-z0-9])(?P<label>[Bb]earer)(?P<sp>\s+)"
                r"(?P<tok>[A-Za-z0-9\-._~+/]{20,}={0,2})"
            ),
            _bearer_repl,
        ),
        (
            "anthropic",
            re.compile(r"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_\-]{20,}"),
            _REDACTED,
        ),
        (
            "openai-project",
            re.compile(r"(?<![A-Za-z0-9])sk-proj-[A-Za-z0-9_\-]{20,}"),
            _REDACTED,
        ),
        (
            "openai",
            re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_]{20,}"),
            _REDACTED,
        ),
        (
            "github-fine-grained",
            re.compile(r"(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{22,}"),
            _REDACTED,
        ),
        (
            "github",
            re.compile(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{30,}"),
            _REDACTED,
        ),
        (
            "aws",
            re.compile(r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}"),
            _REDACTED,
        ),
        (
            "slack",
            re.compile(r"(?<![A-Za-z0-9])xox[baprs]-[0-9A-Za-z-]{20,}"),
            _REDACTED,
        ),
        (
            "resend",
            re.compile(r"(?<![A-Za-z0-9])re_[A-Za-z0-9]{30,}"),
            _REDACTED,
        ),
        (
            "groq",
            re.compile(r"(?<![A-Za-z0-9])gsk_[A-Za-z0-9]{30,}"),
            _REDACTED,
        ),
        (
            "google",
            re.compile(r"(?<![A-Za-z0-9])AIzaSy[A-Za-z0-9_\-]{33}"),
            _REDACTED,
        ),
        (
            "stripe",
            re.compile(
                r"(?<![A-Za-z0-9])(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"
            ),
            _REDACTED,
        ),
        (
            "telegram",
            re.compile(
                r"(?<![0-9])[0-9]{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"
            ),
            _REDACTED,
        ),
        (
            "cloudflare",
            re.compile(
                r"""(?ix)
                (?<![A-Za-z0-9])
                (?P<key>cloudflare(?:_[A-Za-z0-9]+)*|cf_api(?:_token|_key)?)
                \s*(?P<sep>[=:])\s*
                (?P<q>["']?)
                (?P<val>[A-Za-z0-9_\-]{20,})
                """
            ),
            _labeled_repl,
        ),
        (
            "assignment",
            re.compile(
                rf"""(?ix)
                (?<![A-Za-z0-9])
                (?P<q1>["']?)
                (?P<key>[A-Za-z0-9_]*(?:API_KEY|TOKEN|PASSWORD))
                (?P<q2>["']?)
                \s*(?P<sep>[=:])\s*
                (?P<q3>["']?)
                (?P<val>[^\s"'`,;]{{{ASSIGNMENT_VALUE_MIN},}})
                """
            ),
            _assignment_repl,
        ),
        (
            "data-uri",
            re.compile(r"data:image/[a-z+]+;base64,[A-Za-z0-9+/=\s]+"),
            "[image data elided]",
        ),
    ]
    return raw


SECRET_RULES = _compile_rules()


class _SecretScanner:
    """Drop-in ``.search`` / ``.sub`` view over ``SECRET_RULES``.

    Patterns are not joined into one expression: several rules carry their own
    flags, and a combined regex would either fail to compile or change them.
    """

    def search(self, text):
        return secret_hits(text) or None

    def sub(self, repl, text):
        return redact_secrets(text)


SECRET_PATTERNS = _SecretScanner()

_SENSITIVE_V4 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
)
_SENSITIVE_V6 = (
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fec0::/10"),
)

_IPV4_CANDIDATE = re.compile(
    r"(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])"
)
_IPV6_CANDIDATE = re.compile(
    r"(?<![A-Za-z0-9:])"
    r"(?:[0-9A-Fa-f]{0,4}:){2,7}"
    # Prefer an embedded IPv4 tail so ::ffff:192.168.0.1 is one address,
    # not a truncated hex prefix plus a dotted quad.
    r"(?:(?:\d{1,3}\.){3}\d{1,3}|[0-9A-Fa-f]{0,4})"
    r"(?![A-Za-z0-9:])"
)
_MAC = re.compile(
    r"(?<![A-Za-z0-9:])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![A-Za-z0-9:])"
)
_LINUX_MAC_IFACE = re.compile(
    r"(?<![A-Za-z0-9])(?:wlx|enx)[0-9A-Fa-f]{12}(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"[A-Za-z0-9._%+-]+@"
    r"[A-Za-z][A-Za-z0-9.-]*\.[A-Za-z]{2,}"
    r"(?![A-Za-z0-9.-])"
)


def secret_hits(text: str) -> list:
    """Rule names that match ``text``. Empty when nothing sensitive remains."""
    if not text:
        return []
    return [name for name, cre, _repl in SECRET_RULES if cre.search(text)]


def redact_secrets(text: str) -> str:
    for _name, cre, repl in SECRET_RULES:
        text = cre.sub(repl, text)
    return text


def _parse_ipv4(token: str):
    parts = token.split(".")
    if len(parts) != 4:
        return None
    nums = []
    for part in parts:
        if not part.isdigit():
            return None
        number = int(part)
        if number > 255:
            return None
        nums.append(str(number))
    try:
        return ipaddress.IPv4Address(".".join(nums))
    except ipaddress.AddressValueError:
        return None


def _sensitive_v4(ip: ipaddress.IPv4Address) -> bool:
    return any(ip in network for network in _SENSITIVE_V4)


def _redact_ipv4(text: str) -> str:
    def repl(match: re.Match) -> str:
        ip = _parse_ipv4(match.group(0))
        if ip is not None and _sensitive_v4(ip):
            return "[REDACTED-IP]"
        return match.group(0)

    return _IPV4_CANDIDATE.sub(repl, text)


def _sensitive_v6(ip: ipaddress.IPv6Address) -> bool:
    mapped = ip.ipv4_mapped
    if mapped is not None:
        return _sensitive_v4(mapped)
    return any(ip in network for network in _SENSITIVE_V6)


def _redact_ipv6(text: str) -> str:
    def repl(match: re.Match) -> str:
        token = match.group(0)
        try:
            ip = ipaddress.ip_address(token)
        except ValueError:
            return token
        if isinstance(ip, ipaddress.IPv6Address) and _sensitive_v6(ip):
            return "[REDACTED-IP]"
        return token

    return _IPV6_CANDIDATE.sub(repl, text)


def redact_pii(text: str) -> str:
    """Redact private-network PII. See the module docstring for exclusions."""
    text = _MAC.sub("[REDACTED-MAC]", text)
    text = _LINUX_MAC_IFACE.sub("[REDACTED-MAC]", text)
    text = _EMAIL.sub("[REDACTED-EMAIL]", text)
    text = _redact_ipv6(text)
    text = _redact_ipv4(text)
    return text


def sanitize(text: str) -> str:
    if not text:
        return ""
    return redact_pii(redact_secrets(text))


def _safe_path(path: str) -> str:
    """Hide a path whose name is itself a secret, so logs do not repeat it."""
    if not secret_hits(path):
        return path
    parent = os.path.dirname(path)
    return os.path.join(parent, "[REDACTED-NAME]") if parent else "[REDACTED-NAME]"


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


def yaml_quoted(value: str) -> str:
    """JSON string literal, which is a valid YAML double-quoted scalar.

    Quotes, backslashes, and newlines are escaped, so a title cannot break out
    of the frontmatter and invent another field.
    """
    return json.dumps("" if value is None else str(value), ensure_ascii=False)


def slug_title(msgs) -> str:
    """Derive a human-readable title: first meaningful user line."""
    for message in msgs:
        if message.get("role") != "user":
            continue
        lines = flatten(message.get("content")).strip().splitlines()
        if not lines:
            continue
        # Redact before truncating so a token that crosses the 60-character
        # cut is not sliced into a fragment the secret rules no longer match.
        first = sanitize(lines[0].strip())
        if len(first) >= 4:
            return first[:60]
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
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue  # ignore malformed line
            if data.get("role") == "session_meta":
                meta = data
                continue
            msgs.append(data)

    if not any(message.get("role") in ("user", "assistant") for message in msgs):
        return None

    created = (meta.get("timestamp") or (msgs[0].get("timestamp") or ""))[:10] or sid[:8]
    updated = (msgs[-1].get("timestamp") or created)[:10]
    title = slug_title(msgs)
    all_text = "\n".join(flatten(message.get("content")) for message in msgs)
    tags = topic_tags(all_text)
    n_tool = sum(1 for message in msgs if message.get("role") == "tool")
    n_tool_types = len(meta.get("tools") or [])

    fields = {
        "title": title,
        "created": created,
        "updated": updated,
        "platform": platform,
        "language": language,
        "project": project,
        "project_id": project_id,
        "kind": kind,
        "status": status,
        "source": source,
        "visibility": "private",
        "x_session_id": sid,
    }
    fm_lines = ["---", 'localthink: "1.0"']
    for key, value in fields.items():
        fm_lines.append(f"{key}: {yaml_quoted(sanitize(value))}")
    fm_lines.append(f"tags: {json.dumps(tags, ensure_ascii=False)}")
    fm_lines.append(f"x_tool_calls: {n_tool}")
    fm_lines.append(f"x_tool_definitions: {n_tool_types}")
    fm_lines.append("---")
    fm = "\n".join(fm_lines) + "\n"

    lines = ["## Conversation\n"]
    for data in msgs:
        role = data.get("role")
        text = sanitize(flatten(data.get("content")).strip())
        if not text:
            continue
        ts = (data.get("timestamp") or "")[:16].replace("T", " ")
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


def sha1_of(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:10]


def _discard_stale(paths) -> list:
    removed = []
    for path in paths:
        if os.path.lexists(path):
            os.remove(path)
            removed.append(path)
    return removed


def process_sessions(sessions_dir: str, out: str, overwrite: bool = False,
                     platform: str = "hermes-agent", language: str = "zh-TW",
                     project: str = "Personal", project_id: str = "personal") -> int:
    """Convert every ``*.jsonl`` under ``sessions_dir``. Return a process code."""
    os.makedirs(out, exist_ok=True)
    files = sorted(glob.glob(os.path.join(sessions_dir, "*.jsonl")))
    if not files:
        print(f"no .jsonl files under {sessions_dir}", file=sys.stderr)
        return 1

    written = skipped = empty = blocked = stale_removed = 0
    for path in files:
        ltf = to_ltf(
            path,
            platform=platform,
            language=language,
            project=project,
            project_id=project_id,
        )
        if ltf is None:
            empty += 1
            continue
        sid = os.path.basename(path).rsplit(".", 1)[0]
        out_path = os.path.join(out, f"{sid}.ltf.md")
        marker = os.path.join(out, f".{sid}.hash")
        hits = secret_hits(ltf)
        name_hits = secret_hits(sid)
        if hits or name_hits:
            blocked += 1
            removed = _discard_stale((out_path, marker))
            rules = ",".join(dict.fromkeys([*hits, *name_hits]))
            shown = "[REDACTED-NAME]" if name_hits else sid
            if removed:
                stale_removed += 1
                listed = ", ".join(_safe_path(item) for item in removed)
                print(
                    f"BLOCKED (secret found in {shown}; rules: {rules}) "
                    f"— removed stale output: {listed}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"BLOCKED (secret found in {shown}; rules: {rules}) "
                    "— skipped (no prior output)",
                    file=sys.stderr,
                )
            continue
        digest = sha1_of(ltf)
        previous = ""
        if os.path.exists(marker):
            with open(marker, encoding="utf-8") as handle:
                previous = handle.read().strip()
        if not overwrite and previous == digest:
            skipped += 1
            continue
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(ltf)
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write(digest)
        written += 1

    print(
        f"written={written} skipped_unchanged={skipped} "
        f"skipped_empty={empty} blocked={blocked} stale_removed={stale_removed}"
    )
    return 0


def _read_text(path: str):
    with open(path, "rb") as handle:
        blob = handle.read()
    if b"\0" in blob:
        return None
    return blob.decode("utf-8", errors="replace")


def _iter_scan_files(path: str):
    if os.path.isfile(path):
        yield path
        return
    for root, dirs, files in os.walk(path):
        dirs[:] = [name for name in dirs if name != ".git"]
        for name in files:
            yield os.path.join(root, name)


def scan_paths(paths) -> int:
    """Scan files for SECRET_RULES. Exit 1 when a path is missing or a rule hits.

    Matching text is not printed. Callers learn the rule name and the path.
    """
    missing = [path for path in paths if not os.path.exists(path)]
    if missing:
        for path in missing:
            print(f"ERROR: scan path not found: {path}", file=sys.stderr)
        return 1

    hits = 0
    files = 0
    for raw in paths:
        for path in _iter_scan_files(raw):
            files += 1
            text = _read_text(path)
            if text is None:
                continue
            for rule in secret_hits(text):
                hits += 1
                print(
                    f"SECRET rule={rule} path={_safe_path(path)}",
                    file=sys.stderr,
                )
    print(f"scan_hits={hits} files={files}")
    return 1 if hits else 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Convert agent session JSONL to LTF markdown.",
        epilog=(
            "exit codes: 0 conversion finished or scan clean; "
            "1 no session files, bad arguments, or --scan found secrets. "
            "A blocked session is reported and its stale output is removed; "
            "that does not by itself fail the process."
        ),
    )
    parser.add_argument(
        "sessions_dir",
        nargs="?",
        help="Directory of *.jsonl session files (not used with --scan)",
    )
    parser.add_argument("--out", default=DEFAULT_OUT_DIR, help="Output directory")
    parser.add_argument("--platform", default="hermes-agent")
    parser.add_argument("--language", default="zh-TW")
    parser.add_argument("--project", default="Personal")
    parser.add_argument("--project-id", default="personal")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-write files even if unchanged (default: skip if content hash matches)",
    )
    parser.add_argument(
        "--scan",
        nargs="+",
        metavar="PATH",
        help="Scan files or directories with the converter's secret rules and exit",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.scan:
        return scan_paths(args.scan)
    if not args.sessions_dir:
        print("ERROR: sessions_dir is required unless --scan is used", file=sys.stderr)
        return 1
    return process_sessions(
        args.sessions_dir,
        args.out,
        overwrite=args.overwrite,
        platform=args.platform,
        language=args.language,
        project=args.project,
        project_id=args.project_id,
    )


if __name__ == "__main__":
    sys.exit(main())
