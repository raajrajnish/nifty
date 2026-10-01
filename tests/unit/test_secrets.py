"""Lesson L1: secrets must never sit in files git would pick up. Reports file:line only, never the value."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".venv", ".git", "runtime", "journal", "data", "__pycache__", ".pytest_cache", ".mypy_cache",
             ".ruff_cache", "node_modules", "agent_workdir"}
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".toml", ".json", ".txt", ".cfg", ".ini", ".js", ".html",
                 ".css", ".ps1", ".cmd", ".sh", ".example", ".csv"}
PATTERNS = {
    "jwt": re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\."),
    "anthropic_key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    # ENV-style assignment (GROWW_API_SECRET=abc...) or a quoted literal (token = "abc..."); not code calls
    "env_secret": re.compile(
        r"\b[A-Z][A-Z0-9_]*(TOKEN|SECRET|API_KEY|PASSWORD)[A-Z0-9_]*\s*[=:]\s*['\"]?[A-Za-z0-9+/_-]{24,}"),
    "quoted_secret": re.compile(r"(?i)(token|secret|api_key|password)\w*\s*[=:]\s*['\"][A-Za-z0-9+/_-]{24,}['\"]"),
}


def _candidate_files():
    for p in REPO.rglob("*"):
        rel = p.relative_to(REPO)
        if any(part in SKIP_DIRS for part in rel.parts) or not p.is_file():
            continue
        if p.name == ".env" or p.name.endswith(".env") or (p.name.startswith(".env.") and p.name != ".env.example"):
            continue  # gitignored secret files are allowed to hold secrets; test below proves they are ignored
        if p.suffix.lower() in TEXT_SUFFIXES or p.name in {".gitignore", ".env.example"}:
            yield p


def test_no_secret_values_in_repo_files():
    hits = []
    for p in _candidate_files():
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(lines, 1):
            for name, pat in PATTERNS.items():
                if pat.search(line):
                    hits.append(f"{p.relative_to(REPO)}:{i} ({name})")
    assert hits == [], "possible secrets committed: " + ", ".join(hits)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
@pytest.mark.parametrize("name", [".env", "runtime.env", "prod.env", ".env.local", "runtime/ui_auth.json"])
def test_secret_files_are_gitignored(name):
    r = subprocess.run(["git", "check-ignore", "-q", name], cwd=REPO, capture_output=True)  # noqa: S603, S607
    if r.returncode == 128:
        pytest.skip("not inside a git work tree")
    assert r.returncode == 0, f"{name} is NOT gitignored"


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_env_example_is_not_ignored():
    r = subprocess.run(["git", "check-ignore", "-q", ".env.example"], cwd=REPO, capture_output=True)  # noqa: S603, S607
    if r.returncode == 128:
        pytest.skip("not inside a git work tree")
    assert r.returncode == 1
