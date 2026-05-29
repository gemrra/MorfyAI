# -*- coding: utf-8 -*-
"""Houdini MCP package.

Architecture:
    hou_core.py  -> Low-level Houdini operations (shared by server / client)
    client.py    -> HoudiniMCP class, for internal AI Agent (direct Python calls)
    server.py    -> FastMCP HTTP server, for external MCP clients
    settings.py  -> MCPSettings configuration dataclass
    logger.py    -> Logging utilities

Public APIs:
- HoudiniMCP: UI-side helper client
- ensure_mcp_running / stop_mcp_server / get_mcp_status: server lifecycle
- MCPSettings / read_settings / get_logger: config and logging
- hou_core: shared Houdini operation primitives
"""
from __future__ import annotations

from .settings import MCPSettings, read_settings
from .logger import get_logger
from .client import HoudiniMCP
from .server import ensure_mcp_running, stop_mcp_server, get_mcp_status
from . import hou_core

__all__ = [
    "MCPSettings",
    "read_settings",
    "get_logger",
    "HoudiniMCP",
    "ensure_mcp_running",
    "stop_mcp_server",
    "get_mcp_status",
    "hou_core",
]
