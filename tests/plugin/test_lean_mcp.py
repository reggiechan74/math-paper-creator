"""Lean MCP server wiring (Phase 2)."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _rpc(proc, msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    if "id" in msg:
        return json.loads(proc.stdout.readline())
    return None


def test_mcp_json_launches_wrapper_through_mpc():
    config = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]["lean"]
    assert config["command"] == "bash"
    assert config["args"][0] == "${CLAUDE_PLUGIN_ROOT}/scripts/mpc"
    assert config["args"][1:] == ["--python", "${CLAUDE_PLUGIN_ROOT}/scripts/lean_mcp.py"]


def test_wrapper_pins_lean_lsp_mcp():
    text = (ROOT / "scripts" / "lean_mcp.py").read_text()
    assert 'LEAN_LSP_MCP = "lean-lsp-mcp==' in text
    assert "lean_build" in text  # disabled: would rebuild the Mathlib project


def test_stub_server_without_lean(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ("MPC_LEAN_PROJECT", "ELAN_HOME")}
    env["CLAUDE_PLUGIN_DATA"] = str(tmp_path)  # no lean/.ready here
    proc = subprocess.Popen(
        ["bash", str(ROOT / "scripts" / "mpc"), "--python", str(ROOT / "scripts" / "lean_mcp.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, env=env,
    )
    try:
        init = _rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "t", "version": "0"}}})
        assert init["result"]["protocolVersion"] == "2025-06-18"
        assert "inactive" in init["result"]["serverInfo"]["name"]
        _rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = _rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert tools["result"]["tools"] == []
        unknown = _rpc(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {}})
        assert unknown["error"]["code"] == -32601
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


def test_workspace_file_is_inside_project(tmp_path):
    from meta_compiler.lean import LeanEnv, workspace_file

    env = LeanEnv(project=tmp_path, lake="lake", env={}, toolchain="t")
    a = workspace_file(env, Path("/papers/my-paper.model.md"))
    b = workspace_file(env, Path("/other/my-paper.model.md"))
    assert a.parent == tmp_path / "MPCWorkspace"
    assert a.name.startswith("my_paper_") and a.suffix == ".lean"
    assert a != b  # same file name in different folders doesn't collide


def test_lean_workspace_without_lean_exits_3(tmp_path, monkeypatch):
    import pytest

    pytest.importorskip("z3")
    from meta_compiler.cli import main

    for var in ("MPC_LEAN_PROJECT", "CLAUDE_PLUGIN_DATA", "ELAN_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "p.model.md"
    path.write_text('```python:validate\nTheorem("T1", claim="c", lean="theorem T1 : True := trivial", description="d")\n```\n')
    assert main(["lean", str(path), "--workspace"]) == 3
