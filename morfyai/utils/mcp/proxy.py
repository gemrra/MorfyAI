# -*- coding: utf-8 -*-
"""Order-independent stdio MCP proxy for the MorfyAI Houdini server.

Claude Code spawns THIS script over stdio at startup, so the connection always
succeeds regardless of whether Houdini is open. It serves the tool list from a
cached schema (tools stay visible even when Houdini is closed) and forwards each
tool call LIVE to the in-Houdini server at http://127.0.0.1:9000/mcp.

- Houdini open   -> the call runs for real.
- Houdini closed -> the call returns a clear "open Houdini" message (no crash,
  no need to restart Claude Code; the next call just works once Houdini is up).

Uses only the `mcp` SDK (stdio server) + urllib (HTTP forward) — NOT fastmcp's
client (which isn't bundled). stdout is kept clean (it IS the MCP channel);
diagnostics go to stderr.
"""

import os
import sys
import json
import asyncio
import urllib.request


def _log(*a):
    print("[morfyai-proxy]", *a, file=sys.stderr, flush=True)


def _bootstrap_lib():
    """Put vendored deps (mcp + pywin32) on the path. Silent on stdout."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        lib = os.path.abspath(os.path.join(here, "..", "..", "..", "lib"))
        if os.path.isdir(lib):
            if lib not in sys.path:
                sys.path.insert(0, lib)
            for sub in ("win32", os.path.join("win32", "lib"), "Pythonwin"):
                p = os.path.join(lib, sub)
                if os.path.isdir(p) and p not in sys.path:
                    sys.path.append(p)
            dll = os.path.join(lib, "pywin32_system32")
            if os.path.isdir(dll):
                try:
                    os.add_dll_directory(dll)
                except Exception:
                    pass
                os.environ["PATH"] = dll + os.pathsep + os.environ.get("PATH", "")
    except Exception as e:
        _log("lib bootstrap failed:", e)


_bootstrap_lib()

BACKEND_URL = os.environ.get("MORFYAI_MCP_URL", "http://127.0.0.1:9000/mcp")
_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxy_tools_cache.json")


def _load_cached_tools():
    try:
        with open(_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _log("could not load tool cache:", e)
        return []


def _sse(raw):
    for ln in raw.splitlines():
        if ln.startswith("data:"):
            try:
                return json.loads(ln[5:].strip())
            except Exception:
                pass
    try:
        return json.loads(raw)
    except Exception:
        return None


def _forward(name, arguments):
    """Forward one tool call to the Houdini HTTP MCP server. Raw HTTP MCP.

    Returns the tool's text output. Raises on connection failure (handled by caller).
    """
    def post(payload, sid=None):
        h = {"Content-Type": "application/json",
             "Accept": "application/json, text/event-stream"}
        if sid:
            h["mcp-session-id"] = sid
        req = urllib.request.Request(BACKEND_URL, data=json.dumps(payload).encode(),
                                     headers=h, method="POST")
        r = urllib.request.urlopen(req, timeout=180)
        return r.read().decode("utf-8", "replace"), (sid or r.headers.get("mcp-session-id"))

    _, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "morfyai-proxy", "version": "1"}}})
    post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    raw, _ = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                   "params": {"name": name, "arguments": arguments}}, sid)
    data = _sse(raw) or {}
    result = data.get("result", {}) if isinstance(data, dict) else {}
    text = ""
    for b in result.get("content", []) or []:
        if isinstance(b, dict) and b.get("type") == "text":
            text += b.get("text", "")
    if not text:
        sc = result.get("structuredContent")
        text = json.dumps(sc, default=str) if sc is not None else json.dumps(result, default=str)
    return text


async def _amain():
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server
    import mcp.types as types

    cached = _load_cached_tools()
    _log(f"serving {len(cached)} cached tools, backend={BACKEND_URL}")

    server = Server("morfyai-houdini")

    @server.list_tools()
    async def list_tools():
        return [types.Tool(name=t["name"], description=t.get("description", ""),
                           inputSchema=t.get("inputSchema", {"type": "object", "properties": {}}))
                for t in cached]

    @server.call_tool()
    async def call_tool(name, arguments):
        try:
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(None, _forward, name, arguments or {})
            return [types.TextContent(type="text", text=text)]
        except Exception as e:
            return [types.TextContent(type="text", text=json.dumps({
                "status": "error",
                "message": ("Houdini/MorfyAI is not running (or its MCP server is off). "
                            "Open Houdini + the MorfyAI panel, then run this tool again — "
                            "no need to restart Claude Code."),
                "detail": str(e),
            }))]

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main():
    try:
        asyncio.run(_amain())
    except Exception as e:
        _log("fatal:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
