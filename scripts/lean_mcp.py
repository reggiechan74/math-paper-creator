"""Launch the Lean MCP server (lean-lsp-mcp) for the plugin's Lean project.

Declared in .mcp.json and run through scripts/mpc. When Lean is ready (the
plugin's `enable_lean` option has finished installing, or MPC_LEAN_PROJECT is
set) and `uvx` is available, this execs a pinned lean-lsp-mcp against that
project: live goal states, diagnostics, multi-attempt tactics and Mathlib
search for the prove skill.

Otherwise it serves a minimal MCP server with no tools, so sessions without
Lean see neither a failed server nor extra tools.
"""

from __future__ import annotations

import json
import os
import shutil
import sys

LEAN_LSP_MCP = "lean-lsp-mcp==0.31.0"
# lean_build would run `lake build` on the Mathlib project; widgets need a UI.
DISABLED_TOOLS = "lean_build,lean_get_widgets,lean_get_widget_source"


def serve_stub(reason: str) -> None:
    """A do-nothing MCP server: answers the handshake, offers no tools."""
    print(f"math-paper-creator lean MCP: inactive ({reason})", file=sys.stderr)
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in msg:
            continue  # notification
        method = msg.get("method")
        if method == "initialize":
            requested = (msg.get("params") or {}).get("protocolVersion", "2025-06-18")
            result = {
                "protocolVersion": requested,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "math-paper-creator-lean (inactive)", "version": "0"},
                "instructions": f"Lean tools are unavailable: {reason}",
            }
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": result}
        elif method == "tools/list":
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": []}}
        elif method == "ping":
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": {}}
        else:
            reply = {"jsonrpc": "2.0", "id": msg["id"],
                     "error": {"code": -32601, "message": f"method not found: {method}"}}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


def main() -> None:
    from meta_compiler.lean import find_lean_env

    lean_env = find_lean_env()
    if lean_env is None:
        serve_stub("Lean is not enabled or not installed yet")
        return
    uvx = shutil.which("uvx", path=lean_env.env.get("PATH")) or shutil.which("uvx")
    if uvx is None:
        serve_stub("uvx (from uv) is not installed")
        return
    args = [uvx, LEAN_LSP_MCP, "--lean-project-path", str(lean_env.project),
            "--disable-tools", DISABLED_TOOLS]
    os.execve(uvx, args, lean_env.env)


if __name__ == "__main__":
    main()
