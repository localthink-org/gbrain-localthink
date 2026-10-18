"""backup.sh and restore.sh exit codes, using a local git repo and a fake gbrain."""
import os
import subprocess
from pathlib import Path

from conftest import BACKUP, RESTORE, write_session

FAKE = "FAKE" * 8


def _git(repo: Path, *args, env=None):
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _script_env(home: Path) -> dict:
    home.mkdir(parents=True, exist_ok=True)
    gitconfig = home / "gitconfig"
    gitconfig.write_text(
        "\n".join(
            [
                "[init]",
                "    defaultBranch = main",
                "[commit]",
                "    gpgsign = false",
                "[tag]",
                "    gpgsign = false",
                "[user]",
                "    name = Backup Test",
                "    email = backup-test@example.com",
                "[safe]",
                "    directory = *",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = "/usr/bin:/bin"
    env["GIT_CONFIG_GLOBAL"] = str(gitconfig)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_AUTHOR_NAME"] = "Backup Test"
    env["GIT_AUTHOR_EMAIL"] = "backup-test@example.com"
    env["GIT_COMMITTER_NAME"] = "Backup Test"
    env["GIT_COMMITTER_EMAIL"] = "backup-test@example.com"
    return env


def _init_repo(path: Path, env):
    subprocess.run(
        ["git", "init", "-b", "main", str(path)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    _git(path, "config", "user.email", "backup-test@example.com", env=env)
    _git(path, "config", "user.name", "Backup Test", env=env)
    _git(path, "config", "commit.gpgsign", "false", env=env)


def _seed_session(sessions: Path):
    sessions.mkdir(parents=True, exist_ok=True)
    write_session(
        sessions / "demo.jsonl",
        [
            {
                "role": "user",
                "content": "Hello there friend. LAN 192.168.1.50 key sk-" + FAKE,
                "timestamp": "2026-04-01T09:00:00",
            }
        ],
    )


def _run_backup(env, **extra):
    env = dict(env)
    env.update(extra)
    return subprocess.run(
        ["bash", str(BACKUP)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_restore_missing_export_and_usage(tmp_path):
    env = _script_env(tmp_path / "home")
    (tmp_path / "empty").mkdir()
    missing = subprocess.run(
        ["bash", str(RESTORE), str(tmp_path / "empty")],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert missing.returncode == 1
    assert "ERROR" in missing.stderr
    assert "restore done" not in missing.stdout

    usage = subprocess.run(
        ["bash", str(RESTORE)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert usage.returncode != 0


def test_restore_without_gbrain_is_conversations_only(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    source = tmp_path / "backup"
    (source / "export").mkdir(parents=True)
    (source / "conversations").mkdir()
    env = _script_env(home)
    result = subprocess.run(
        ["bash", str(RESTORE), str(source)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "conversations only" in result.stderr
    assert "restore done" in result.stdout
    assert str(source / "conversations") in result.stdout


def test_restore_gbrain_failure_is_nonzero(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gbrain = bindir / "gbrain"
    gbrain.write_text("#!/bin/sh\necho 'import blew up' >&2\nexit 3\n", encoding="utf-8")
    gbrain.chmod(0o755)
    source = tmp_path / "backup"
    (source / "export").mkdir(parents=True)
    env = _script_env(home)
    env["PATH"] = f"{bindir}:/usr/bin:/bin"
    result = subprocess.run(
        ["bash", str(RESTORE), str(source)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 1
    assert "ERROR: gbrain import failed" in result.stderr
    assert "import blew up" in result.stderr
    assert "restore done" not in result.stdout
    assert "conversations" in result.stdout


def test_restore_gbrain_success(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    marker = tmp_path / "imported"
    gbrain = bindir / "gbrain"
    gbrain.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" > {marker}\nexit 0\n",
        encoding="utf-8",
    )
    gbrain.chmod(0o755)
    source = tmp_path / "backup"
    (source / "export").mkdir(parents=True)
    env = _script_env(home)
    env["PATH"] = f"{bindir}:/usr/bin:/bin"
    result = subprocess.run(
        ["bash", str(RESTORE), str(source)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "restore done" in result.stdout
    assert "import" in marker.read_text(encoding="utf-8")


def test_backup_redacts_and_pushes(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = _script_env(home)
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    work = tmp_path / "work"
    _init_repo(work, env)
    (work / "README.md").write_text("seed\n", encoding="utf-8")
    _git(work, "add", "README.md", env=env)
    _git(work, "commit", "-m", "seed", env=env)
    _git(work, "remote", "add", "origin", str(remote), env=env)
    _git(work, "push", "-u", "origin", "main", env=env)

    sessions = tmp_path / "sessions"
    _seed_session(sessions)
    result = _run_backup(
        env,
        BACKUP_REPO_DIR=str(work),
        SESSIONS_DIR=str(sessions),
        REPO_REMOTE="origin",
        BRANCH="main",
    )
    assert result.returncode == 0, result.stderr
    assert "backup pushed" in result.stdout
    assert "WARN:" not in result.stderr
    stored = subprocess.run(
        ["git", "-C", str(work), "show", "HEAD:conversations/demo.ltf.md"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout
    assert "FAKE" not in stored
    assert "192.168.1.50" not in stored
    assert "[REDACTED]" in stored
    assert "[REDACTED-IP]" in stored


def test_backup_secret_in_export_exits_2(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = _script_env(home)
    work = tmp_path / "work"
    _init_repo(work, env)
    (work / "README.md").write_text("seed\n", encoding="utf-8")
    _git(work, "add", "README.md", env=env)
    _git(work, "commit", "-m", "seed", env=env)
    export = work / "export"
    export.mkdir()
    (export / "leak.md").write_text("ghp_" + FAKE + "\n", encoding="utf-8")
    sessions = tmp_path / "sessions"
    _seed_session(sessions)
    result = _run_backup(
        env,
        BACKUP_REPO_DIR=str(work),
        SESSIONS_DIR=str(sessions),
    )
    assert result.returncode == 2
    assert "BLOCKED" in result.stderr
    assert "FAKE" not in result.stderr
    log = subprocess.run(
        ["git", "-C", str(work), "log", "--oneline"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout
    assert "backup:" not in log


def test_backup_push_failure_is_visible(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = _script_env(home)
    work = tmp_path / "work"
    _init_repo(work, env)
    (work / "README.md").write_text("seed\n", encoding="utf-8")
    _git(work, "add", "README.md", env=env)
    _git(work, "commit", "-m", "seed", env=env)
    _git(work, "remote", "add", "origin", str(tmp_path / "not-a-remote"), env=env)
    sessions = tmp_path / "sessions"
    _seed_session(sessions)
    result = _run_backup(
        env,
        BACKUP_REPO_DIR=str(work),
        SESSIONS_DIR=str(sessions),
    )
    assert result.returncode == 1
    assert "ERROR:" in result.stderr
    assert "backup pushed" not in result.stdout


def test_backup_retries_push_after_rebase(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = _script_env(home)
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    work = tmp_path / "work"
    _init_repo(work, env)
    (work / "README.md").write_text("seed\n", encoding="utf-8")
    _git(work, "add", "README.md", env=env)
    _git(work, "commit", "-m", "seed", env=env)
    _git(work, "remote", "add", "origin", str(remote), env=env)
    _git(work, "push", "-u", "origin", "main", env=env)

    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(remote), str(other)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    _git(other, "config", "user.email", "backup-test@example.com", env=env)
    _git(other, "config", "user.name", "Backup Test", env=env)
    (other / "from-other.md").write_text("other machine\n", encoding="utf-8")
    _git(other, "add", "from-other.md", env=env)
    _git(other, "commit", "-m", "from another machine", env=env)
    _git(other, "push", "origin", "main", env=env)

    sessions = tmp_path / "sessions"
    _seed_session(sessions)
    result = _run_backup(
        env,
        BACKUP_REPO_DIR=str(work),
        SESSIONS_DIR=str(sessions),
    )
    assert result.returncode == 0, result.stderr
    assert "WARN:" in result.stderr
    assert "ERROR:" not in result.stderr
    assert "backup pushed" in result.stdout
    log = subprocess.run(
        ["git", "--git-dir", str(remote), "log", "--oneline"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout
    assert "from another machine" in log
    assert "backup:" in log
