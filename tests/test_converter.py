"""Redaction, YAML, empty titles, stale cleanup, scan, and idempotent skip."""
import json
import subprocess
import sys

import ltf.ltf_converter as conv

from conftest import CONVERTER, ROOT, write_session

FAKE = "FAKE" * 8  # 32 chars, obviously not a credential


def parse_frontmatter(text: str) -> dict:
    lines = text.splitlines()
    assert lines[0] == "---"
    fields = {}
    for line in lines[1:]:
        if line == "---":
            return fields
        key, value = line.split(": ", 1)
        if value[:1] in "\"[":
            fields[key] = json.loads(value)
        else:
            fields[key] = value
    raise AssertionError("frontmatter did not close")


def test_slug_title_empty_user_messages_do_not_crash():
    messages = [
        {"role": "user", "content": ""},
        {"role": "user", "content": " \n\n "},
        {"role": "user", "content": None},
        {"role": "user", "content": []},
        {"role": "user", "content": "\n"},
        {"role": "assistant", "content": "pong"},
    ]
    assert conv.slug_title(messages) == "Untitled session"


def test_slug_title_redacts_before_the_length_cut():
    prefix = "Hello there friend. Please look at this key "
    content = prefix + "sk-" + FAKE
    assert len(prefix) < 60 < len(content)
    title = conv.slug_title([{"role": "user", "content": content}])
    assert "FAKE" not in title
    assert "[REDACTED]" in title


def test_slug_title_skips_blank_and_short_lines():
    messages = [
        {"role": "user", "content": "\n"},
        {"role": "user", "content": "hi"},
        {"role": "user", "content": "Hello there friend"},
    ]
    assert conv.slug_title(messages) == "Hello there friend"


def test_to_ltf_empty_first_user_message(tmp_path):
    path = tmp_path / "blank.jsonl"
    write_session(
        path,
        [
            {"role": "user", "content": "", "timestamp": "2026-04-01T09:00:00"},
            {"role": "assistant", "content": "pong", "timestamp": "2026-04-01T09:01:00"},
        ],
    )
    text = conv.to_ltf(str(path))
    assert parse_frontmatter(text)["title"] == "Untitled session"


def test_yaml_quoting_round_trips_quotes_backslashes_and_newlines(tmp_path):
    path = tmp_path / "demo.jsonl"
    title = 'He said "hello" and C:\\temp'
    write_session(
        path,
        [{"role": "user", "content": title, "timestamp": "2026-04-01T09:00:00"}],
    )
    project = "Say \"hi\" \\ path\nstatus: public"
    text = conv.to_ltf(path=str(path), project=project, project_id='a"b')
    front, _body = text.split("\n---\n", 1)
    assert not any(line.startswith("status: ") and not line.startswith("status: \"") for line in front.splitlines())
    fields = parse_frontmatter(text)
    assert fields["title"] == title
    assert fields["project"] == project
    assert fields["project_id"] == 'a"b'
    assert fields["created"] == "2026-04-01"
    project_line = next(line for line in front.splitlines() if line.startswith("project: "))
    assert "\n" not in project_line
    assert "\\n" in project_line


def test_safe_prose_is_not_rewritten():
    prose = (
        "Meet at 10:30:00. Version 10.20.30 is ready. "
        "Resolvers 8.8.8.8 and 1.1.1.1 and 127.0.0.1 stay. "
        "Documentation 192.0.2.10 and 2001:db8::1 and ::1 stay. "
        "See image@2x.png and user@localhost. "
        "Boundary 172.32.0.1 and 100.128.1.1 stay. "
        "Multicast ff02::1 stays."
    )
    assert conv.sanitize(prose) == prose
    assert conv.secret_hits(prose) == []


def test_private_addresses_macs_and_emails_are_redacted():
    text = (
        "LAN 192.168.1.50 10.1.2.3 172.16.5.5 172.31.255.255 "
        "169.254.1.10 100.64.1.1 "
        "fd00::10 fe80::abcd fec0::1 ::ffff:192.168.0.8 "
        "MAC 02:00:00:00:00:01 and 02-00-00-00-00-02 "
        "iface wlx020000000001 "
        "mail ada@example.com"
    )
    out = conv.sanitize(text)
    for raw in (
        "192.168.1.50",
        "10.1.2.3",
        "172.16.5.5",
        "169.254.1.10",
        "100.64.1.1",
        "fd00::10",
        "fe80::abcd",
        "192.168.0.8",
        "02:00:00:00:00:01",
        "02-00-00-00-00-02",
        "wlx020000000001",
        "ada@example.com",
    ):
        assert raw not in out
    assert "[REDACTED-IP]" in out
    assert "[REDACTED-MAC]" in out
    assert "[REDACTED-EMAIL]" in out
    assert conv.secret_hits(text) == []


def test_leading_zero_private_ipv4_is_redacted():
    assert conv.sanitize("addr 192.168.001.010") == "addr [REDACTED-IP]"


def test_secret_rules_redact_and_name_the_hit():
    samples = {
        "openai": "sk-" + FAKE,
        "openai-project": "sk-proj-" + FAKE,
        "anthropic": "sk-ant-" + FAKE,
        "github": "ghp_" + FAKE,
        "github-fine-grained": "github_pat_" + FAKE,
        "aws": "AKIAFAKEFAKEFAKEFAKE",
        "slack": "xoxb-" + FAKE,
        "stripe": "sk_live_" + FAKE,
        "jwt": "eyJFAKEHEADER.eyJFAKEPAYLOAD.FAKESIGNATUREPART",
        "bearer": "Bearer FAKEBEARERTOKENVALUE123",
        "telegram": "123456789:" + ("FAKE" * 9)[:35],
        "cloudflare": "cloudflare=FAKECLOUDFLARETOKEN1234567890",
        "assignment": "MY_TOKEN=fakevaluebutlongenough",
        "pem": (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "FAKEKEYMATERIAL\n"
            "-----END RSA PRIVATE KEY-----"
        ),
        "data-uri": "data:image/png;base64,AAAA",
    }
    for rule, raw in samples.items():
        assert rule in conv.secret_hits(raw), rule
        assert raw not in conv.sanitize(raw)
    for prefix in ("gho_", "ghu_", "ghs_", "ghr_"):
        token = prefix + FAKE
        assert "github" in conv.secret_hits(token)
        assert conv.sanitize(token) == "[REDACTED]"
    assert conv.sanitize("rk_live_" + FAKE) == "[REDACTED]"
    assert conv.sanitize("sk_test_" + FAKE) == "[REDACTED]"
    assert "aws" in conv.secret_hits("ASIAFAKEFAKEFAKEFAKE")
    assert conv.sanitize("password=hunter2") == "password=hunter2"
    assert conv.sanitize("sk-short") == "sk-short"
    assert "FAKE" not in conv.sanitize("password=correcthorsebatterystaple")
    assert conv.sanitize("OPENAI_API_KEY=sk-" + FAKE).startswith("OPENAI_API_KEY=")
    public = "-----BEGIN PUBLIC KEY-----\nABC\n-----END PUBLIC KEY-----"
    assert conv.sanitize(public) == public


def test_tool_line_and_project_are_redacted(tmp_path):
    path = tmp_path / "demo.jsonl"
    write_session(
        path,
        [
            {
                "role": "user",
                "content": "Check the demo network please",
                "timestamp": "2026-04-01T09:00:00",
            },
            {
                "role": "tool",
                "content": "inet 192.168.1.50 ether 02:00:00:00:00:01 mail ada@example.com",
                "timestamp": "2026-04-01T09:01:00",
            },
        ],
    )
    text = conv.to_ltf(str(path), project="sk-" + FAKE)
    assert "192.168.1.50" not in text
    assert "02:00:00:00:00:01" not in text
    assert "ada@example.com" not in text
    assert "FAKE" not in text
    assert "[REDACTED-IP]" in text
    assert "[REDACTED]" in text
    assert "*Tool" in text


def test_idempotent_skip_and_secret_is_written_redacted(tmp_path, capsys):
    sessions = tmp_path / "sessions"
    out = tmp_path / "out"
    sessions.mkdir()
    write_session(
        sessions / "demo.jsonl",
        [
            {
                "role": "user",
                "content": "Hello there friend. key sk-" + FAKE,
                "timestamp": "2026-04-01T09:00:00",
            }
        ],
    )
    assert conv.process_sessions(str(sessions), str(out)) == 0
    first = capsys.readouterr().out
    assert "written=1" in first
    body = (out / "demo.ltf.md").read_text(encoding="utf-8")
    assert "FAKE" not in body
    assert "[REDACTED]" in body
    marker = (out / ".demo.hash").read_text(encoding="utf-8")
    assert marker == conv.sha1_of(body)

    assert conv.process_sessions(str(sessions), str(out)) == 0
    second = capsys.readouterr().out
    assert "skipped_unchanged=1" in second
    assert "written=0" in second
    assert (out / "demo.ltf.md").read_text(encoding="utf-8") == body


def test_blocked_session_removes_stale_output(tmp_path, monkeypatch, capsys):
    sessions = tmp_path / "sessions"
    out = tmp_path / "out"
    sessions.mkdir()
    write_session(
        sessions / "demo.jsonl",
        [{"role": "user", "content": "Hello there friend", "timestamp": "2026-04-01T09:00:00"}],
    )
    assert conv.process_sessions(str(sessions), str(out)) == 0
    assert (out / "demo.ltf.md").is_file()
    assert (out / ".demo.hash").is_file()
    capsys.readouterr()

    monkeypatch.setattr(conv, "secret_hits", lambda _text: ["forced"])
    assert conv.process_sessions(str(sessions), str(out)) == 0
    captured = capsys.readouterr()
    assert "blocked=1" in captured.out
    assert "stale_removed=1" in captured.out
    assert "BLOCKED" in captured.err
    assert "removed stale output" in captured.err
    assert not (out / "demo.ltf.md").exists()
    assert not (out / ".demo.hash").exists()

    assert conv.process_sessions(str(sessions), str(out)) == 0
    again = capsys.readouterr()
    assert "stale_removed=0" in again.out
    assert "no prior output" in again.err


def test_blocked_then_clean_rewrites(tmp_path, monkeypatch, capsys):
    sessions = tmp_path / "sessions"
    out = tmp_path / "out"
    sessions.mkdir()
    write_session(
        sessions / "demo.jsonl",
        [{"role": "user", "content": "Hello there friend", "timestamp": "2026-04-01T09:00:00"}],
    )
    conv.process_sessions(str(sessions), str(out))
    capsys.readouterr()
    original = conv.secret_hits
    monkeypatch.setattr(conv, "secret_hits", lambda _text: ["forced"])
    conv.process_sessions(str(sessions), str(out))
    assert not (out / "demo.ltf.md").exists()
    monkeypatch.setattr(conv, "secret_hits", original)
    assert conv.process_sessions(str(sessions), str(out)) == 0
    assert (out / "demo.ltf.md").is_file()
    assert "Hello there friend" in (out / "demo.ltf.md").read_text(encoding="utf-8")


def test_secret_filename_is_blocked_and_not_logged(tmp_path, capsys):
    sessions = tmp_path / "sessions"
    out = tmp_path / "out"
    sessions.mkdir()
    secret_name = "sk-" + FAKE
    write_session(
        sessions / f"{secret_name}.jsonl",
        [{"role": "user", "content": "Hello there friend", "timestamp": "2026-04-01T09:00:00"}],
    )
    # Plant a stale file under that secret name, as a previous run might have.
    out.mkdir()
    stale = out / f"{secret_name}.ltf.md"
    stale.write_text("old secret copy\n", encoding="utf-8")
    (out / f".{secret_name}.hash").write_text("deadbeef00", encoding="utf-8")

    assert conv.process_sessions(str(sessions), str(out)) == 0
    captured = capsys.readouterr()
    assert "blocked=1" in captured.out
    assert "stale_removed=1" in captured.out
    assert "FAKE" not in captured.err
    assert "FAKE" not in captured.out
    assert "[REDACTED-NAME]" in captured.err
    assert not stale.exists()
    assert not (out / f".{secret_name}.hash").exists()


def test_scan_cli_reports_rule_without_echoing_the_secret(tmp_path):
    folder = tmp_path / "export"
    folder.mkdir()
    secret = "sk-" + FAKE
    (folder / "note.md").write_text(f"prefix {secret} suffix\n", encoding="utf-8")
    dirty = subprocess.run(
        [sys.executable, str(CONVERTER), "--scan", str(folder)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert dirty.returncode == 1
    assert "rule=openai" in dirty.stderr
    assert "note.md" in dirty.stderr
    assert secret not in dirty.stderr
    assert secret not in dirty.stdout

    (folder / "note.md").write_text("nothing to see\n", encoding="utf-8")
    clean = subprocess.run(
        [sys.executable, str(CONVERTER), "--scan", str(folder)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert clean.returncode == 0
    assert "scan_hits=0" in clean.stdout

    missing = subprocess.run(
        [sys.executable, str(CONVERTER), "--scan", str(tmp_path / "nope")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 1
    assert "not found" in missing.stderr


def test_cli_idempotent_skip(tmp_path):
    sessions = tmp_path / "sessions"
    out = tmp_path / "out"
    sessions.mkdir()
    write_session(
        sessions / "demo.jsonl",
        [{"role": "user", "content": "Hello there friend", "timestamp": "2026-04-01T09:00:00"}],
    )
    first = subprocess.run(
        [sys.executable, str(CONVERTER), str(sessions), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0
    assert "written=1" in first.stdout
    second = subprocess.run(
        [sys.executable, str(CONVERTER), str(sessions), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0
    assert "skipped_unchanged=1" in second.stdout


def test_cli_empty_user_message(tmp_path):
    sessions = tmp_path / "sessions"
    out = tmp_path / "out"
    sessions.mkdir()
    write_session(
        sessions / "demo.jsonl",
        [
            {"role": "user", "content": "", "timestamp": "2026-04-01T09:00:00"},
            {"role": "assistant", "content": "pong", "timestamp": "2026-04-01T09:01:00"},
        ],
    )
    result = subprocess.run(
        [sys.executable, str(CONVERTER), str(sessions), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    text = (out / "demo.ltf.md").read_text(encoding="utf-8")
    assert 'title: "Untitled session"' in text


def test_examples_are_fictional_samples():
    example_dir = ROOT / "examples"
    blob = "\n".join(
        path.read_text(encoding="utf-8") for path in example_dir.glob("*.md")
    )
    assert "192.168." not in blob
    assert "wlx" not in blob
    assert "enx" not in blob
    greeting = (example_dir / "example-1-session-greeting.ltf.md").read_text(encoding="utf-8")
    assert "192.0.2.10" in greeting
    assert "192.0.2.1" in greeting
    assert "02:00:00:00:00:01" in greeting
    assert "wlan-demo0" in greeting
    assert "*Tool" in greeting
    research = (example_dir / "example-2-session-research.ltf.md").read_text(encoding="utf-8")
    assert "https://example.com/acme/demo-widget" in research
    readme = (example_dir / "README.md").read_text(encoding="utf-8")
    assert "not exports of real sessions" in readme


def test_backup_script_delegates_scan_and_does_not_hide_push():
    text = (ROOT / "scripts" / "backup.sh").read_text(encoding="utf-8")
    assert "--scan" in text
    assert "git pull --rebase" in text
    assert "ghp_" not in text
    assert "AKIA" not in text
    for line in text.splitlines():
        if "git push" in line:
            assert "/dev/null" not in line
