# -*- coding: utf-8 -*-
"""
User Rules Manager

Cursor Rules-like functionality, letting the user define long-lived context rules.
Rules are global and automatically injected into every AI request's system prompt.

Two management modes are supported:
  1. UI rules: created/edited via the Rules editor dialog, stored in config/user_rules.json
  2. File rules: automatically scanned from .md and .txt files under the rules/ directory

Design principles:
  - UI rules can be enabled/disabled individually
  - File rules are always enabled (files starting with _ are treated as drafts/templates)
  - All enabled rules are merged and wrapped in a <user_rules> tag injected into the system prompt
"""

from __future__ import annotations

import json
import time
import uuid

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None
from pathlib import Path
from typing import Any, Dict, List, Optional

# ============================================================
# Path constants
# ============================================================

_PROJECT_ROOT = Path(__file__).parent.parent.parent          # DCC-ASSET-MANAGER/
_CONFIG_DIR = _PROJECT_ROOT / "config"
_RULES_FILE = _CONFIG_DIR / "user_rules.json"
_RULES_DIR = _PROJECT_ROOT / "rules"

# ============================================================
# Data structures
# ============================================================

def _new_rule(title: str = "", content: str = "", enabled: bool = True) -> Dict[str, Any]:
    """Create a new UI rule data entry"""
    return {
        "id": uuid.uuid4().hex[:12],
        "title": title,
        "content": content,
        "enabled": enabled,
        "created_at": time.time(),
    }


# ============================================================
# Load / save UI rules (config/user_rules.json)
# ============================================================

def _load_ui_rules() -> List[Dict[str, Any]]:
    """Load UI rules list from config/user_rules.json"""
    if not _RULES_FILE.exists():
        return []
    try:
        with open(_RULES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        _dbg(f"[Rules] Failed to load user_rules.json: {e}")
        return []


def _save_ui_rules(rules: List[Dict[str, Any]]):
    """Save UI rules to config/user_rules.json"""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(_RULES_FILE, "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _dbg(f"[Rules] Failed to save user_rules.json: {e}")


# ============================================================
# File rule scanning (rules/*.md, *.txt)
# ============================================================

def _scan_file_rules() -> List[Dict[str, Any]]:
    """Scan .md / .txt files under rules/ and return the rule list"""
    if not _RULES_DIR.exists():
        return []

    result: List[Dict[str, Any]] = []
    for ext in ("*.md", "*.txt"):
        for f in sorted(_RULES_DIR.glob(ext)):
            # Files starting with _ are treated as templates/drafts and skipped
            if f.name.startswith("_"):
                continue
            try:
                content = f.read_text(encoding="utf-8").strip()
                if not content:
                    continue
                result.append({
                    "id": f"file:{f.name}",
                    "title": f.stem,                 # filename (without extension) as title
                    "content": content,
                    "enabled": True,
                    "source": "file",                # mark the source
                    "file_path": str(f),
                })
            except Exception as e:
                _dbg(f"[Rules] Failed to read rule file {f.name}: {e}")
    return result


# ============================================================
# Public API - module-level functions (singleton style)
# ============================================================

# Internal cache
_ui_rules_cache: Optional[List[Dict[str, Any]]] = None


def get_all_rules(force_reload: bool = False) -> List[Dict[str, Any]]:
    """Get all rules (UI rules + file rules)

    Each rule in the returned list contains:
        id, title, content, enabled, source("ui"|"file"), ...
    """
    global _ui_rules_cache
    if force_reload or _ui_rules_cache is None:
        _ui_rules_cache = _load_ui_rules()

    ui_rules = []
    for r in _ui_rules_cache:
        rule = dict(r)
        rule.setdefault("source", "ui")
        ui_rules.append(rule)

    file_rules = _scan_file_rules()
    return ui_rules + file_rules


def get_ui_rules() -> List[Dict[str, Any]]:
    """Get UI rules only"""
    global _ui_rules_cache
    if _ui_rules_cache is None:
        _ui_rules_cache = _load_ui_rules()
    return list(_ui_rules_cache)


def add_rule(title: str = "", content: str = "") -> Dict[str, Any]:
    """Add a new UI rule"""
    global _ui_rules_cache
    if _ui_rules_cache is None:
        _ui_rules_cache = _load_ui_rules()
    rule = _new_rule(title=title, content=content, enabled=True)
    _ui_rules_cache.append(rule)
    _save_ui_rules(_ui_rules_cache)
    return rule


def update_rule(rule_id: str, **kwargs):
    """Update fields (title, content, enabled) of the specified UI rule"""
    global _ui_rules_cache
    if _ui_rules_cache is None:
        _ui_rules_cache = _load_ui_rules()
    for r in _ui_rules_cache:
        if r.get("id") == rule_id:
            for k in ("title", "content", "enabled"):
                if k in kwargs:
                    r[k] = kwargs[k]
            _save_ui_rules(_ui_rules_cache)
            return True
    return False


def delete_rule(rule_id: str) -> bool:
    """Delete the specified UI rule"""
    global _ui_rules_cache
    if _ui_rules_cache is None:
        _ui_rules_cache = _load_ui_rules()
    before = len(_ui_rules_cache)
    _ui_rules_cache = [r for r in _ui_rules_cache if r.get("id") != rule_id]
    if len(_ui_rules_cache) < before:
        _save_ui_rules(_ui_rules_cache)
        return True
    return False


def set_rule_enabled(rule_id: str, enabled: bool) -> bool:
    """Set the enabled/disabled state of a UI rule"""
    return update_rule(rule_id, enabled=enabled)


def save_all_ui_rules(rules: List[Dict[str, Any]]):
    """Batch save UI rules (full write-back from the editor)"""
    global _ui_rules_cache
    _ui_rules_cache = rules
    _save_ui_rules(_ui_rules_cache)


def reload_rules():
    """Force reload all rules (clears cache)"""
    global _ui_rules_cache
    _ui_rules_cache = None


# ============================================================
# Prompt injection
# ============================================================

def get_rules_for_prompt() -> str:
    """Merge all enabled rules into a single block wrapped in <user_rules> tags

    Returns an empty string when no rule is enabled.
    """
    all_rules = get_all_rules()
    enabled = [r for r in all_rules if r.get("enabled", True)]
    if not enabled:
        return ""

    parts: List[str] = []
    for r in enabled:
        title = r.get("title", "").strip()
        content = r.get("content", "").strip()
        if not content:
            continue
        if title:
            parts.append(f"## {title}\n{content}")
        else:
            parts.append(content)

    if not parts:
        return ""

    body = "\n\n".join(parts)
    return (
        "<user_rules>\n"
        "The following are custom rules defined by the user. "
        "You MUST follow them in every response.\n\n"
        f"{body}\n"
        "</user_rules>"
    )


# ============================================================
# Helpers
# ============================================================

def get_rules_dir() -> Path:
    """Return the rules/ directory path"""
    return _RULES_DIR


def ensure_rules_dir():
    """Ensure the rules/ directory exists"""
    _RULES_DIR.mkdir(parents=True, exist_ok=True)
