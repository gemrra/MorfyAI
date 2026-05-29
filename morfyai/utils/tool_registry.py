# -*- coding: utf-8 -*-
"""
ToolRegistry — unified tool registration center

Unifies three capability systems (Core Tools / Skills / Plugin Tools):
  - Get available tool list by mode (agent / ask / plan_planning / plan_executing)
  - Unified execution entry
  - Supports tool enable/disable (persisted to config/plugins.json)
  - Provides tool list metadata for the UI
"""

import json
import threading
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None


# ─────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────

@dataclass
class ToolMeta:
    """Tool metadata"""
    name: str                                    # unique identifier
    schema: dict                                 # OpenAI function calling schema
    handler: Optional[Callable] = None           # execution function (args: dict) -> dict; may be None (dispatched by MCP Client)
    source: str = "core"                         # "core" | "skill" | "plugin" | "user"
    plugin_name: str = ""                        # for plugin tools, the plugin name
    tags: Set[str] = field(default_factory=set)  # {"readonly", "geometry", "network", "system", ...}
    modes: Set[str] = field(default_factory=set) # {"agent", "ask", "plan_planning", "plan_executing"}
    enabled: bool = True                         # whether enabled


# ─────────────────────────────────────────────
# Mode-inference helpers (used only when auto-registering core tools)
# ─────────────────────────────────────────────

# Ask mode whitelist (read-only / query tools)
_ASK_TOOLS = frozenset({
    'get_network_structure', 'get_node_parameters', 'list_children',
    'read_selection', 'search_node_types', 'semantic_search_nodes',
    'find_nodes_by_param', 'get_node_inputs', 'check_errors',
    'verify_and_summarize', 'web_search', 'fetch_webpage',
    'search_local_doc', 'get_houdini_node_doc', 'list_skills',
    'add_todo', 'update_todo', 'get_node_positions',
    'list_network_boxes', 'perf_start_profile', 'perf_stop_and_report',
})

# Plan-planning phase whitelist
_PLAN_PLANNING_TOOLS = frozenset({
    'get_network_structure', 'get_node_parameters', 'list_children',
    'read_selection', 'search_node_types', 'semantic_search_nodes',
    'find_nodes_by_param', 'get_node_inputs', 'check_errors',
    'verify_and_summarize', 'web_search', 'fetch_webpage',
    'search_local_doc', 'get_houdini_node_doc', 'list_skills',
    'add_todo', 'update_todo', 'get_node_positions',
    'list_network_boxes', 'perf_start_profile', 'perf_stop_and_report',
    'create_plan', 'ask_question',
})

# Readonly tag inference
_READONLY_TOOLS = frozenset({
    'get_network_structure', 'get_node_parameters', 'list_children',
    'read_selection', 'search_node_types', 'semantic_search_nodes',
    'find_nodes_by_param', 'get_node_inputs', 'check_errors',
    'verify_and_summarize', 'web_search', 'fetch_webpage',
    'search_local_doc', 'get_houdini_node_doc', 'list_skills',
    'get_node_positions', 'list_network_boxes',
    'perf_start_profile', 'perf_stop_and_report',
    'capture_viewport',
})


def _infer_modes(name: str) -> Set[str]:
    """Infer applicable modes from the tool name"""
    modes = {"agent", "plan_executing"}  # all tools are available in Agent and Plan-executing by default
    if name in _ASK_TOOLS:
        modes.add("ask")
    if name in _PLAN_PLANNING_TOOLS:
        modes.add("plan_planning")
    return modes


def _infer_tags(name: str) -> Set[str]:
    """Infer tags from the tool name"""
    tags: Set[str] = set()
    if name in _READONLY_TOOLS:
        tags.add("readonly")
    # Geometry / network related
    geo_kw = ('node', 'network', 'connect', 'create', 'delete', 'display',
              'parameter', 'children', 'selection', 'wrangle', 'copy', 'batch',
              'inputs', 'flag', 'layout', 'box')
    for kw in geo_kw:
        if kw in name.lower():
            tags.add("network")
            break
    # System / Shell
    if name in ('execute_python', 'execute_shell', 'save_hip', 'undo_redo'):
        tags.add("system")
    # Search / docs
    if name in ('web_search', 'fetch_webpage', 'search_local_doc', 'get_houdini_node_doc'):
        tags.add("docs")
    # Skill
    if name.startswith("skill__") or name.startswith("skill:") or name in ('run_skill', 'list_skills'):
        tags.add("skill")
    # Task management
    if name in ('add_todo', 'update_todo'):
        tags.add("task")
    return tags


# ─────────────────────────────────────────────
# ToolRegistry singleton
# ─────────────────────────────────────────────

class ToolRegistry:
    """Unified tool registration center

    Each tool registration requires:
      - name: unique identifier
      - schema: OpenAI function calling schema
      - handler: execution function (args: dict) -> dict, may be None
      - source: "core" | "skill" | "plugin" | "user"
      - tags: set[str]  e.g. {"readonly", "geometry", "network"}
      - modes: set[str]  e.g. {"agent", "ask", "plan_planning", "plan_executing"}
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._tools: Dict[str, ToolMeta] = {}       # name -> ToolMeta
        self._disabled_tools: Set[str] = set()       # persisted disabled list
        self._initialized = False

    # ---------- Register / Unregister ----------

    def register(self, name: str, schema: dict,
                 handler: Optional[Callable] = None,
                 source: str = "core",
                 plugin_name: str = "",
                 tags: Optional[Set[str]] = None,
                 modes: Optional[Set[str]] = None,
                 enabled: bool = True):
        """Register a tool"""
        with self._lock:
            meta = ToolMeta(
                name=name,
                schema=schema,
                handler=handler,
                source=source,
                plugin_name=plugin_name,
                tags=tags or set(),
                modes=modes or set(),
                enabled=enabled and (name not in self._disabled_tools),
            )
            self._tools[name] = meta

    def unregister(self, name: str):
        """Unregister a tool"""
        with self._lock:
            self._tools.pop(name, None)

    def unregister_by_source(self, source: str, plugin_name: str = ""):
        """Unregister by source (optionally a specific plugin)"""
        with self._lock:
            to_remove = [
                n for n, m in self._tools.items()
                if m.source == source and (not plugin_name or m.plugin_name == plugin_name)
            ]
            for n in to_remove:
                del self._tools[n]

    # ---------- Queries ----------

    def get_tools_for_mode(self, mode: str) -> List[dict]:
        """Get the list of tool schemas for a mode (only enabled tools)"""
        with self._lock:
            result = []
            for meta in self._tools.values():
                if not meta.enabled:
                    continue
                if mode in meta.modes:
                    result.append(meta.schema)
            return result

    def get_tool_schemas(self, names: Optional[List[str]] = None) -> List[dict]:
        """Get schemas for the given tools (returns all enabled if names is None)"""
        with self._lock:
            result = []
            for meta in self._tools.values():
                if not meta.enabled:
                    continue
                if names is None or meta.name in names:
                    result.append(meta.schema)
            return result

    def has_tool(self, name: str) -> bool:
        """Check whether a tool is registered"""
        return name in self._tools

    def get_handler(self, name: str) -> Optional[Callable]:
        """Get the execution function for a tool"""
        meta = self._tools.get(name)
        return meta.handler if meta else None

    def list_all(self) -> List[Dict[str, Any]]:
        """List all tool metadata (for the UI)"""
        with self._lock:
            result = []
            for meta in self._tools.values():
                result.append({
                    "name": meta.name,
                    "source": meta.source,
                    "plugin_name": meta.plugin_name,
                    "tags": sorted(meta.tags),
                    "modes": sorted(meta.modes),
                    "enabled": meta.enabled,
                    "description": meta.schema.get("function", {}).get("description", "")[:120],
                })
            return sorted(result, key=lambda x: (x["source"], x["name"]))

    # ---------- Execution ----------

    def execute(self, name: str, args: dict) -> dict:
        """Unified execution entry

        If the tool has a handler, call it directly. Otherwise return an error.
        Note: core Houdini tools have None as handler — dispatched by MCP Client.
        """
        meta = self._tools.get(name)
        if not meta:
            return {"success": False, "error": f"Tool not registered: {name}"}
        if not meta.enabled:
            return {"success": False, "error": f"Tool disabled: {name}"}
        if not meta.handler:
            return {"success": False, "error": f"Tool {name} has no handler (dispatched by MCP Client)"}
        try:
            return meta.handler(args)
        except Exception as e:
            return {"success": False, "error": f"Tool {name} execution failed: {e}\n{traceback.format_exc()[:500]}"}

    # ---------- Enable / Disable ----------

    def set_enabled(self, name: str, enabled: bool):
        """Set the enabled/disabled state of a tool"""
        with self._lock:
            meta = self._tools.get(name)
            if meta:
                meta.enabled = enabled
            if enabled:
                self._disabled_tools.discard(name)
            else:
                self._disabled_tools.add(name)

    def is_enabled(self, name: str) -> bool:
        """Query whether a tool is enabled"""
        meta = self._tools.get(name)
        return meta.enabled if meta else False

    def load_disabled_from_config(self, disabled_list: List[str]):
        """Load the disabled list from configuration"""
        with self._lock:
            self._disabled_tools = set(disabled_list)
            for name, meta in self._tools.items():
                meta.enabled = name not in self._disabled_tools

    def get_disabled_tools(self) -> List[str]:
        """Get the current disabled list"""
        return sorted(self._disabled_tools)

    def save_disabled_to_config(self):
        """Save the disabled list to plugins.json"""
        try:
            from .hooks import _plugin_config, _save_plugin_config
            _plugin_config["disabled_tools"] = sorted(self._disabled_tools)
            _save_plugin_config()
        except Exception as e:
            _dbg(f"[ToolRegistry] Save disabled list failed: {e}")

    # ---------- Bulk-register core tools ----------

    def register_core_tools(self, houdini_tools: List[dict]):
        """Bulk-register the HOUDINI_TOOLS list as core tools

        handler is None — core tools are dispatched by MCP Client via _TOOL_DISPATCH.
        """
        for tool_def in houdini_tools:
            name = tool_def.get("function", {}).get("name", "")
            if not name:
                continue
            self.register(
                name=name,
                schema=tool_def,
                handler=None,
                source="core",
                tags=_infer_tags(name),
                modes=_infer_modes(name),
            )
        self._initialized = True

    # ---------- Intent-aware tool filtering ----------

    # Tools grouped by function
    _INTENT_TOOL_GROUPS: Dict[str, Set[str]] = {
        'query': {
            'get_network_structure', 'get_node_parameters', 'list_children',
            'check_errors', 'read_selection', 'get_node_inputs',
            'get_node_positions', 'list_network_boxes',
            'verify_and_summarize',
            'search_memory',
            'capture_viewport',
        },
        'create': {
            'create_node', 'create_nodes_batch', 'create_wrangle_node',
            'connect_nodes', 'copy_node',
        },
        'modify': {
            'set_node_parameter', 'batch_set_parameters', 'set_display_flag',
        },
        'code': {
            'execute_python', 'execute_shell',
        },
        'search': {
            'web_search', 'fetch_webpage', 'search_local_doc',
            'search_node_types', 'semantic_search_nodes',
            'find_nodes_by_param', 'get_houdini_node_doc',
            'search_memory',
        },
        'layout': {
            'layout_nodes', 'create_network_box',
        },
        'task': {
            'add_todo', 'update_todo',
        },
        'perf': {
            'perf_start_profile', 'perf_stop_and_report',
        },
        'file': {
            'save_hip', 'undo_redo',
        },
        'plan': {
            'create_plan', 'update_plan_step', 'ask_question',
        },
        'skill': set(),  # populated dynamically
    }

    # Intent keywords (English + Indonesian for the maintainer's native usage)
    _INTENT_KEYWORDS: Dict[str, List[str]] = {
        'query': ['what', 'show', 'list', 'check', 'look', 'display', 'view', 'see',
                  'apa', 'cek', 'lihat', 'tampilkan', 'analisa', 'status'],
        'create': ['create', 'build', 'make', 'add', 'generate', 'construct',
                   'buat', 'bikin', 'tambah', 'tambahin', 'gen', 'add'],
        'modify': ['change', 'set', 'modify', 'update', 'adjust', 'tweak',
                   'ubah', 'ganti', 'edit', 'set', 'atur'],
        'code': ['python', 'script', 'code', 'run', 'execute', 'vex', 'wrangle',
                 'jalankan', 'jalanin', 'eksekusi'],
        'search': ['search', 'find', 'where', 'document', 'doc', 'web', 'online',
                   'memory', 'remember', 'recall',
                   'cari', 'cariin', 'temukan', 'dokumen', 'ingat', 'memori'],
        'layout': ['layout', 'organize', 'arrange', 'position', 'move',
                   'rapikan', 'rapikin', 'susun', 'pindah'],
        'perf': ['performance', 'profile', 'benchmark', 'speed', 'slow',
                 'performa', 'kecepatan', 'lambat', 'optimasi'],
        'file': ['save', 'undo', 'redo', 'simpan', 'batal'],
    }

    def classify_intent(self, user_message: str) -> Set[str]:
        """Infer intent categories from user-message keywords

        Returns:
            Set of matched intents, e.g. {'query', 'create'}
        """
        if not user_message:
            return set()
        msg_lower = user_message.lower()
        matched = set()
        for intent, keywords in self._INTENT_KEYWORDS.items():
            for kw in keywords:
                if kw in msg_lower:
                    matched.add(intent)
                    break  # one keyword match is enough
        return matched

    def get_tools_for_intent(self, intents: Set[str], mode: str = 'agent') -> List[dict]:
        """Get related tool schemas for a set of intents

        Always includes 'query' and 'task' groups (base tools), plus any groups
        matching the given intents. Only returns tools that are enabled and
        allowed in the given mode.
        """
        # Always include base tool groups
        active_groups = {'query', 'task'} | intents

        # Collect the target tool-name set
        target_names: Set[str] = set()
        for group in active_groups:
            target_names |= self._INTENT_TOOL_GROUPS.get(group, set())

        # Add all skill tools (skills should generally always be available)
        with self._lock:
            for name, meta in self._tools.items():
                if meta.source == 'skill' and meta.enabled:
                    target_names.add(name)

        # Filter: must be in the given mode and enabled
        with self._lock:
            result = []
            for meta in self._tools.values():
                if not meta.enabled:
                    continue
                if mode not in meta.modes:
                    continue
                if meta.name in target_names:
                    result.append(meta.schema)
            return result

    def is_tool_allowed_in_mode(self, tool_name: str, mode: str) -> bool:
        """Check whether a tool is allowed in the given mode"""
        meta = self._tools.get(tool_name)
        if not meta:
            return False
        return meta.enabled and mode in meta.modes

    @property
    def initialized(self) -> bool:
        return self._initialized


# ─────────────────────────────────────────────
# Global singleton
# ─────────────────────────────────────────────

_instance: Optional[ToolRegistry] = None
_instance_lock = threading.Lock()


def get_tool_registry() -> ToolRegistry:
    """Get the ToolRegistry global singleton"""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ToolRegistry()
    return _instance
