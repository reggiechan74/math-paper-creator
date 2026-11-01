"""Structural tests for the Claude Code plugin packaging.

These guard the conventions the plugin relies on: skills (not legacy
commands), the scripts/mpc launcher instead of `cd` into the plugin root,
and hook filters that only fire on .model.md files.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILLS = sorted((ROOT / "skills").glob("*/SKILL.md"))
EXPECTED_SKILLS = {
    "author", "onboard", "review", "check", "status",
    "report", "paper", "compile", "plain-english", "prove",
}
INTERACTIVE_SKILLS = {"author", "onboard", "review", "compile", "plain-english", "prove"}


def frontmatter(path: Path) -> dict:
    text = path.read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path} has no frontmatter"
    fields = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip('"')
    return fields


def test_no_legacy_commands_directory():
    assert not (ROOT / "commands").exists()


def test_expected_skills_present():
    assert {p.parent.name for p in SKILLS} == EXPECTED_SKILLS


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
def test_skill_frontmatter(skill):
    fm = frontmatter(skill)
    assert fm.get("name") == skill.parent.name
    assert fm.get("description")
    assert len(fm["description"]) <= 1536
    assert "arguments" not in fm, "use $ARGUMENTS in the body instead"
    if skill.parent.name in INTERACTIVE_SKILLS:
        assert fm.get("disable-model-invocation") == "true"
    else:
        assert "disable-model-invocation" not in fm


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
def test_skill_body_conventions(skill):
    body = skill.read_text()
    assert "$ARGUMENTS" in body
    assert 'cd "${CLAUDE_PLUGIN_ROOT}"' not in body
    assert "PYTHONPATH=src" not in body
    assert len(body.splitlines()) < 500


def test_referenced_plugin_files_exist():
    for skill in SKILLS:
        for rel in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", skill.read_text()):
            assert (ROOT / rel.rstrip("/.")).exists(), f"{skill}: missing {rel}"


def test_plugin_manifest():
    manifest = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
    assert manifest["name"] == "math-paper-creator"
    assert "commands" not in manifest
    assert (ROOT / manifest["icon"]).is_file()
    market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
    assert all("version" not in p for p in market["plugins"]), \
        "version lives only in plugin.json"


def test_versions_in_sync():
    manifest = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert f'version = "{manifest["version"]}"' in pyproject
    assert f"version-{manifest['version']}-" in (ROOT / "README.md").read_text()


def test_hooks_filter_to_model_md():
    hooks = json.loads((ROOT / "hooks/hooks.json").read_text())["hooks"]
    post = hooks["PostToolUse"][0]["hooks"]
    assert {h["if"] for h in post} == {"Write(//**/*.model.md)", "Edit(//**/*.model.md)"}
    for h in post + hooks["SessionStart"][0]["hooks"]:
        assert "args" in h, "use exec form"


class TestLauncher:
    def test_runs_from_any_cwd_with_absolute_path(self, tmp_path):
        doc = tmp_path / "m.model.md"
        doc.write_text('```python:validate\nSet("W", description="w")\nregistry.run_tests()\n```\n')
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_DATA"}
        result = subprocess.run(
            [str(ROOT / "scripts/mpc"), "check", str(doc)],
            cwd=tmp_path, capture_output=True, text=True, env=env, timeout=60,
        )
        assert result.returncode == 0, result.stderr

    def test_ignores_venv_until_ready(self, tmp_path):
        """Without the .ready marker the launcher must fall back to python3."""
        (tmp_path / "venv/bin").mkdir(parents=True)
        bogus = tmp_path / "venv/bin/python"
        bogus.write_text("#!/bin/sh\nexit 42\n")
        bogus.chmod(0o755)
        env = dict(os.environ, CLAUDE_PLUGIN_DATA=str(tmp_path))
        result = subprocess.run(
            [str(ROOT / "scripts/mpc"), "--help"],
            capture_output=True, text=True, env=env, timeout=60,
        )
        assert result.returncode == 0
        (tmp_path / "venv/.ready").write_text("x\n")
        result = subprocess.run(
            [str(ROOT / "scripts/mpc"), "--help"],
            capture_output=True, text=True, env=env, timeout=60,
        )
        assert result.returncode == 42


class TestSetupEnv:
    SCRIPT = ROOT / "scripts/setup_env.py"

    def test_noop_without_plugin_data(self):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_DATA"}
        result = subprocess.run([sys.executable, str(self.SCRIPT)], input="{}",
                                capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0
        assert result.stdout == ""

    def test_fast_path_when_current(self, tmp_path):
        import hashlib
        venv = tmp_path / "venv"
        (venv / "bin").mkdir(parents=True)
        (venv / "bin/python").write_text("")
        want = hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest()
        (venv / ".ready").write_text(want + "\n")
        env = dict(os.environ, CLAUDE_PLUGIN_DATA=str(tmp_path))
        result = subprocess.run([sys.executable, str(self.SCRIPT)], input="{}",
                                capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0
        assert not (tmp_path / "setup.log").exists(), "should not spawn an install"
