"""The public repo stays clean: no working plans and no local paths in tracked files (CLAUDE.md, Public repo rules)."""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOCAL = re.compile(r"/Users/|/private/tmp/|scratchpad|[(`]plans/")
ALLOWED = {"CLAUDE.md", "tests/test_repo.py"}  # they state the rules


def tracked() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return out.stdout.splitlines()


def test_no_plans_tracked():
    assert [f for f in tracked() if f.startswith("plans/")] == []


def test_no_local_paths_or_plan_links():
    hits = []
    for name in tracked():
        path = ROOT / name
        if name in ALLOWED or not path.is_file():
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue  # binary: the WAV fixtures
        hits += [f"{name}: {m.group()}" for m in LOCAL.finditer(text)]
    assert hits == []
