# -*- coding: utf-8 -*-
"""
Skill registry & loader.

A skill is a predefined Python snippet that runs in the Houdini environment.
Each skill file lives in skills/ and contains:
  - SKILL_INFO: dict (name, description, parameters)
  - run(**kwargs) -> dict   (entry function)

★ v1.3.5+: skills are auto-registered to ToolRegistry so they can be exposed
  to the AI as standalone tools.
★ Supports a user-defined skill directory (config/houdini_ai.ini → [skills] user_skill_dir)
"""

import os
import importlib
import traceback
from typing import Dict, Any, Optional, List
from pathlib import Path

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None


# Global registry: skill_name -> module
_registry: Dict[str, Any] = {}
_loaded = False


def _skill_info_to_openai_schema(info: dict, skill_name: str) -> dict:
    """Convert SKILL_INFO into an OpenAI function-calling schema."""
    properties = {}
    required = []
    # JSON Schema does not support 'float'; map to 'number'
    _TYPE_MAP = {"float": "number", "int": "integer", "bool": "boolean"}
    for param_name, param_def in info.get("parameters", {}).items():
        raw_type = param_def.get("type", "string")
        prop: Dict[str, Any] = {
            "type": _TYPE_MAP.get(raw_type, raw_type),
            "description": param_def.get("description", ""),
        }
        if "enum" in param_def:
            prop["enum"] = param_def["enum"]
        if "default" in param_def:
            prop["default"] = param_def["default"]
        properties[param_name] = prop
        if param_def.get("required", False):
            required.append(param_name)

    return {
        "type": "function",
        "function": {
            # NOTE: function names must match ^[a-zA-Z0-9_-]+$ (DeepSeek/OpenAI).
            # A ':' is illegal, so the skill namespace uses '__' as the separator.
            "name": f"skill__{skill_name}",
            "description": f"[Skill] {info.get('description', skill_name)}",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            }
        }
    }


def _get_user_skill_dir() -> Optional[Path]:
    """Read the user-defined skill directory from config/houdini_ai.ini."""
    try:
        import configparser
        config_dir = Path(__file__).resolve().parent.parent.parent / "config"
        ini_path = config_dir / "houdini_ai.ini"
        if not ini_path.exists():
            return None
        cfg = configparser.ConfigParser()
        cfg.read(str(ini_path), encoding='utf-8')
        user_dir = cfg.get("skills", "user_skill_dir", fallback="").strip()
        if user_dir:
            p = Path(user_dir)
            if p.is_dir():
                return p
            else:
                _dbg(f"[Skills] User skill directory not found: {user_dir}")
    except Exception:
        pass
    return None


def _load_skills_from_dir(skill_dir: Path, prefix: str = ""):
    """Load skill modules from a given directory."""
    if not skill_dir.is_dir():
        return

    for f in sorted(skill_dir.glob("*.py")):
        if f.name.startswith("_"):
            continue
        module_name = f.stem
        try:
            spec = importlib.util.spec_from_file_location(
                f"houdini_skills.{prefix}{module_name}", str(f))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            info = getattr(mod, "SKILL_INFO", None)
            run_fn = getattr(mod, "run", None)
            if info and run_fn and callable(run_fn):
                name = info.get("name", module_name)
                _registry[name] = mod
        except Exception as e:
            _dbg(f"[Skills] Failed to load {prefix}{module_name}: {e}")


def _load_all():
    """Scan the skills/ directory (builtin + user) and load all skill modules."""
    global _registry, _loaded
    if _loaded:
        return

    # 1. Built-in skill directory
    builtin_dir = Path(__file__).parent
    _load_skills_from_dir(builtin_dir)

    # 2. User-defined skill directory
    user_dir = _get_user_skill_dir()
    if user_dir:
        _load_skills_from_dir(user_dir, prefix="user_")
        _dbg(f"[Skills] User skill directory: {user_dir}")

    _loaded = True
    if _registry:
        _dbg(f"[Skills] Loaded {len(_registry)} skill(s): {', '.join(_registry.keys())}")

    # ★ Auto-register to ToolRegistry
    _register_skills_to_registry()


def _register_skills_to_registry():
    """Register every loaded skill into ToolRegistry."""
    try:
        from ..utils.tool_registry import get_tool_registry
        reg = get_tool_registry()
        for name, mod in _registry.items():
            info = getattr(mod, "SKILL_INFO", {})
            # Hidden skills stay loadable/callable (e.g. via build_sim dispatch or
            # run_skill) but are NOT exposed to the AI as standalone tools. Used to
            # consolidate the 7 sim builders behind the single build_sim entry.
            if info.get("hidden"):
                continue
            schema = _skill_info_to_openai_schema(info, name)
            run_fn = getattr(mod, "run", None)

            def _make_handler(m):
                """Build a closure to avoid lambda variable-capture pitfalls."""
                def handler(args: dict) -> dict:
                    fn = getattr(m, "run", None)
                    if not callable(fn):
                        return {"success": False, "error": "Skill has no run() function"}
                    try:
                        result = fn(**args)
                        if not isinstance(result, dict):
                            result = {"result": str(result)}
                        result.setdefault("success", True)
                        return result
                    except Exception as e:
                        return {"success": False, "error": f"Skill execution failed: {e}"}
                return handler

            # Classify skill: builders/wrappers MUTATE the scene, so they must NOT
            # appear in read-only Ask mode. Analysis/discovery skills stay read-only.
            _MUTATING_PREFIXES = (
                "build_", "wrap_", "create_", "make_", "setup_", "add_",
                "import_", "export_", "cache_", "scatter_", "clean_",
                "promote_", "transfer_", "assign_", "boolean_", "convert_",
                "fuse_", "delete_", "remove_",
            )
            _mutating = name.startswith(_MUTATING_PREFIXES)
            if _mutating:
                _tags = {"geometry", "skill", "simulation"}
                _modes = {"agent", "plan_executing"}
            else:
                _tags = {"readonly", "geometry", "skill"}
                _modes = {"agent", "ask", "plan_executing"}

            reg.register(
                name=f"skill__{name}",  # key MUST match the schema function name above
                schema=schema,
                handler=_make_handler(mod),
                source="skill",
                tags=_tags,
                modes=_modes,
            )
        if _registry:
            _dbg(f"[Skills] Registered {len(_registry)} skill(s) to ToolRegistry")
    except Exception as e:
        _dbg(f"[Skills] ToolRegistry register failed (non-fatal): {e}")


def list_skills() -> List[Dict[str, Any]]:
    """Return metadata for every registered skill."""
    _load_all()
    result = []
    for name, mod in _registry.items():
        info = dict(getattr(mod, "SKILL_INFO", {}))
        info.setdefault("name", name)
        result.append(info)
    return result


def run_skill(skill_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Run the specified skill.

    Args:
        skill_name: skill name
        params: kwargs passed to run()

    Returns:
        The dict returned by the skill, or a dict containing an error message.
    """
    _load_all()

    mod = _registry.get(skill_name)
    if mod is None:
        available = ", ".join(_registry.keys()) or "(none)"
        return {"error": f"Skill not found: {skill_name}\navailable skills: {available}"}

    run_fn = getattr(mod, "run", None)
    if not callable(run_fn):
        return {"error": f"Skill '{skill_name}' has no run() function"}

    try:
        result = run_fn(**params)
        if not isinstance(result, dict):
            result = {"result": str(result)}
        return result
    except Exception as e:
        return {"error": f"Skill execution failed: {e}\n{traceback.format_exc()[:500]}"}


def reload_skills():
    """Reload every skill (for development / debugging)."""
    global _registry, _loaded
    # First, unregister stale skill tools from ToolRegistry
    try:
        from ..utils.tool_registry import get_tool_registry
        get_tool_registry().unregister_by_source("skill")
    except Exception:
        pass
    _registry.clear()
    _loaded = False
    _load_all()
