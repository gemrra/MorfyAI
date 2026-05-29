# -*- coding: utf-8 -*-
"""Claude Connect — expose the in-Houdini MCP server to external Claude clients.

MorfyAI already ships a FastMCP streamable-HTTP server (utils/mcp/server.py) that
exposes Houdini operations. This helper makes it trivial to (a) start that server
inside the live Houdini session and (b) get ready-to-paste connection configs so
Claude Desktop or Claude Code can connect and DRIVE Houdini — using the user's
Claude subscription as the brain, with MorfyAI as the Houdini engine.

Pure Python (no Qt). The config generators work anywhere; start/stop/status need
to run inside Houdini (where the server's hou tools function).
"""

from __future__ import annotations
import json

try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None

_DEFAULT_NAME = "morfyai-houdini"


def _settings():
    """Read live MCP settings (host/port/transport). Falls back to defaults."""
    try:
        from morfyai.utils.mcp.settings import read_settings
        return read_settings()
    except Exception as e:
        _dbg(f"[ClaudeConnect] settings read failed: {e}")

        class _S:  # minimal fallback matching MCPSettings fields used here
            host = "127.0.0.1"
            port = 9000
            transport = "streamable-http"
        return _S()


def get_url() -> str:
    """The MCP endpoint URL external clients connect to."""
    s = _settings()
    host = getattr(s, "host", "127.0.0.1")
    port = getattr(s, "port", 9000)
    return f"http://{host}:{port}/mcp"


# ── server lifecycle (run inside Houdini) ────────────────────────────

def start():
    """Start the MCP server in this Houdini session. Returns (ok, message, url)."""
    try:
        from morfyai.utils.mcp.server import ensure_mcp_running
        ok, msg = ensure_mcp_running(auto_start=True)
        return bool(ok), str(msg), get_url()
    except Exception as e:
        return False, f"failed to start MCP server: {e}", get_url()


def stop():
    try:
        from morfyai.utils.mcp.server import stop_mcp_server
        res = stop_mcp_server()
        return res if isinstance(res, tuple) else (True, str(res))
    except Exception as e:
        return False, f"failed to stop MCP server: {e}"


def status():
    try:
        from morfyai.utils.mcp.server import get_mcp_status
        return get_mcp_status()
    except Exception as e:
        return {"running": False, "error": str(e)}


# ── connection configs (work anywhere) ───────────────────────────────

def claude_code_command(name: str = _DEFAULT_NAME) -> str:
    """One-line command to register the server with Claude Code."""
    return f"claude mcp add --transport http {name} {get_url()}"


def claude_code_json(name: str = _DEFAULT_NAME) -> str:
    """`.mcp.json` snippet for Claude Code (project-level MCP config)."""
    return json.dumps({"mcpServers": {name: {"type": "http", "url": get_url()}}}, indent=2)


def claude_desktop_json(name: str = _DEFAULT_NAME) -> str:
    """`claude_desktop_config.json` snippet.

    Claude Desktop connects to a remote HTTP MCP server through the `mcp-remote`
    bridge (run via npx), since it natively launches stdio servers.
    """
    return json.dumps(
        {"mcpServers": {name: {"command": "npx", "args": ["-y", "mcp-remote", get_url()]}}},
        indent=2,
    )


def connection_report(name: str = _DEFAULT_NAME) -> dict:
    """Everything a caller/UI needs to connect a Claude client."""
    url = get_url()
    st = status()
    running = bool(st.get("running")) if isinstance(st, dict) else False
    return {
        "url": url,
        "server_running": running,
        "server_status": st,
        "claude_code_command": claude_code_command(name),
        "claude_code_json": claude_code_json(name),
        "claude_desktop_json": claude_desktop_json(name),
        "steps": [
            "1. Keep Houdini + MorfyAI open (the server runs inside this session).",
            f"2. Make sure the MCP server is running at {url} (call start() / the connect_claude skill).",
            "3a. Claude Code: run the claude_code_command, OR drop claude_code_json into a .mcp.json, then restart Claude Code.",
            "3b. Claude Desktop: paste claude_desktop_json into claude_desktop_config.json, then restart Claude Desktop.",
            "4. In Claude, you can now read/build in this Houdini session via MorfyAI's tools.",
        ],
        "note": ("Localhost only (127.0.0.1) — not exposed externally. The server lets the "
                 "connected Claude execute Houdini operations (incl. Python), so only connect "
                 "trusted clients."),
    }
