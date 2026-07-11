# -*- coding: utf-8 -*-
"""Bypass or un-bypass a set of nodes matching a pattern.

Mutating — toggles the bypass flag.
"""

SKILL_INFO = {
    "name": "bypass_toggle",
    "description": (
        "Set (or clear) the bypass flag on every node under a parent matching a glob pattern. Use to "
        "quickly A/B a chain of effects, or bulk-disable a set of nodes (e.g. everything named 'debug_*')."
    ),
    "parameters": {
        "parent_path": {"type": "string", "description": "Network to search in.", "required": True},
        "match": {"type": "string", "description": "Glob pattern to match node names.", "default": "*"},
        "bypass": {"type": "boolean", "description": "True to bypass, False to un-bypass.", "default": True},
    },
}


def run(parent_path="", match="*", bypass=True):
    import hou  # type: ignore

    parent = hou.node(parent_path or "")
    if parent is None:
        return {"success": False, "error": f"parent not found: {parent_path}"}

    matched = parent.glob(match) if hasattr(parent, "glob") else []
    if not matched:
        return {"success": True, "changed": [], "verdict": f"No nodes under {parent_path} matched '{match}'."}

    changed = []
    for node in matched:
        try:
            node.bypass(bool(bypass))
            changed.append(node.path())
        except Exception:
            pass

    return {
        "success": True,
        "changed": changed,
        "count": len(changed),
        "bypass": bypass,
        "verdict": f"{'Bypassed' if bypass else 'Un-bypassed'} {len(changed)} node(s) matching '{match}'.",
    }
