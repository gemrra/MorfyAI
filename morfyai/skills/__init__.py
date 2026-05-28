# -*- coding: utf-8 -*-
"""
Skill 注册表 & 加载器

Skill 是预定义的 Python 代码片段,  in  Houdini 环境中执行. 
每个 skill 文件放 in  skills/ 目录下, containing:
  - SKILL_INFO: dict  (name, description, parameters)
  - run(**kwargs) -> dict  入口函数

★ v1.3.5+: Skill 自动注册到 ToolRegistry, 可作为独立工具暴露给 AI. 
★ 支持用户自定义 Skill 目录 (config/houdini_ai.ini → [skills] user_skill_dir)
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


# 全局注册表: skill_name -> module
_registry: Dict[str, Any] = {}
_loaded = False


def _skill_info_to_openai_schema(info: dict, skill_name: str) -> dict:
    """将 SKILL_INFO 转换为 OpenAI function calling schema"""
    properties = {}
    required = []
    # JSON Schema 不支持 'float', 需映射为 'number'
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
            "name": f"skill:{skill_name}",
            "description": f"[Skill] {info.get('description', skill_name)}",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            }
        }
    }


def _get_user_skill_dir() -> Optional[Path]:
    """从 config/houdini_ai.ini 读取用户自定义 Skill 目录"""
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
    """从指定目录加载 skill 模块"""
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
    """扫描 skills/ 目录 (内置 + 用户), 加载所skill 模块"""
    global _registry, _loaded
    if _loaded:
        return

    # 1. 内置 skill 目录
    builtin_dir = Path(__file__).parent
    _load_skills_from_dir(builtin_dir)

    # 2. 用户自定义 skill 目录
    user_dir = _get_user_skill_dir()
    if user_dir:
        _load_skills_from_dir(user_dir, prefix="user_")
        _dbg(f"[Skills] User skill directory: {user_dir}")

    _loaded = True
    if _registry:
        _dbg(f"[Skills] Loaded {len(_registry)} skill(s): {', '.join(_registry.keys())}")

    # ★ 自动注册到 ToolRegistry
    _register_skills_to_registry()


def _register_skills_to_registry():
    """将所有已加载 Skill 注册到 ToolRegistry"""
    try:
        from ..utils.tool_registry import get_tool_registry
        reg = get_tool_registry()
        for name, mod in _registry.items():
            info = getattr(mod, "SKILL_INFO", {})
            schema = _skill_info_to_openai_schema(info, name)
            run_fn = getattr(mod, "run", None)

            def _make_handler(m):
                """创建闭包, 避免 lambda 捕获变量问题"""
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

            reg.register(
                name=f"skill:{name}",
                schema=schema,
                handler=_make_handler(mod),
                source="skill",
                tags={"readonly", "geometry", "skill"},
                modes={"agent", "ask", "plan_executing"},
            )
        if _registry:
            _dbg(f"[Skills] Registered {len(_registry)} skill(s) to ToolRegistry")
    except Exception as e:
        _dbg(f"[Skills] ToolRegistry register failed (non-fatal): {e}")


def list_skills() -> List[Dict[str, Any]]:
    """Return所有已注册 skill 的元数据"""
    _load_all()
    result = []
    for name, mod in _registry.items():
        info = dict(getattr(mod, "SKILL_INFO", {}))
        info.setdefault("name", name)
        result.append(info)
    return result


def run_skill(skill_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """执行指定 skill

    Args:
        skill_name: skill name
        params: 传给 run() 的参数

    Returns:
        skill Return的字典,  or containing error 的字典
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
    """重新加载所skill (开发调试用)"""
    global _registry, _loaded
    # 先从 ToolRegistry 注销旧的 skill 工具
    try:
        from ..utils.tool_registry import get_tool_registry
        get_tool_registry().unregister_by_source("skill")
    except Exception:
        pass
    _registry.clear()
    _loaded = False
    _load_all()
