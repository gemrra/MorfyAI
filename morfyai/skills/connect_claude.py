# -*- coding: utf-8 -*-
"""Connect MorfyAI's Houdini MCP server to an external Claude client.

Starts (or stops/queries) the in-Houdini FastMCP server and returns ready-to-paste
connection configs for Claude Desktop / Claude Code. Once connected, Claude can
read and build in this live Houdini session through MorfyAI's tools — using the
Claude subscription as the brain, MorfyAI as the Houdini engine.
"""

SKILL_INFO = {
    "name": "connect_claude",
    "description": (
        "Start MorfyAI's Houdini MCP server and return connection configs so Claude Desktop / Claude Code "
        "can connect and drive this Houdini session. Use when the user wants to connect Claude (or any "
        "external MCP client) to Houdini, or asks to 'connect to Claude' / 'expose Houdini to Claude'."
    ),
    "parameters": {
        "action": {
            "type": "string",
            "description": "start the server (default), stop it, or just report status/config",
            "enum": ["start", "stop", "status"],
            "default": "start",
        },
        "name": {
            "type": "string",
            "description": "Name to register the MCP server under in the Claude client",
            "default": "morfyai-houdini",
        },
    },
}


def run(action="start", name="morfyai-houdini"):
    try:
        from morfyai.utils import claude_connect as cc
    except Exception as e:
        return {"success": False, "error": f"claude_connect module unavailable: {e}"}

    action = (action or "start").lower()

    if action == "stop":
        ok, msg = cc.stop()
        return {"success": bool(ok), "action": "stop", "message": msg}

    if action == "status":
        report = cc.connection_report(name)
        report["success"] = True
        report["action"] = "status"
        return report

    # default: start
    ok, msg, url = cc.start()
    report = cc.connection_report(name)
    report["success"] = bool(ok)
    report["action"] = "start"
    report["start_message"] = msg
    report["message"] = (
        f"MCP server {'running' if ok else 'NOT started'} at {url}. "
        + ("Use the config below to connect Claude Desktop / Claude Code, then restart that client."
           if ok else "See error and ensure you are running inside Houdini.")
    )
    return report
