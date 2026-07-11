# -*- coding: utf-8 -*-
"""Batch-rename nodes matching a pattern.

Mutating — renames existing nodes.
"""

SKILL_INFO = {
    "name": "rename_nodes",
    "description": (
        "Rename every node under a parent whose name matches a glob pattern (e.g. 'debug_*'), giving each "
        "a new base name with an auto-incrementing number (name1, name2, ...). Use for quick batch cleanup "
        "of node names."
    ),
    "parameters": {
        "parent_path": {"type": "string", "description": "Network to search in, e.g. '/obj/geo1'.", "required": True},
        "match": {"type": "string", "description": "Glob pattern to match existing names, e.g. 'debug_*' or '*'.", "default": "*"},
        "new_base": {"type": "string", "description": "New base name; nodes become new_base1, new_base2, ...", "required": True},
    },
}


def run(parent_path="", match="*", new_base=""):
    import hou  # type: ignore

    if not new_base:
        return {"success": False, "error": "new_base is required"}
    parent = hou.node(parent_path or "")
    if parent is None:
        return {"success": False, "error": f"parent not found: {parent_path}"}

    matched = parent.glob(match) if hasattr(parent, "glob") else []
    if not matched:
        return {"success": True, "renamed": [], "verdict": f"No nodes under {parent_path} matched '{match}'."}

    renamed = []
    for i, node in enumerate(matched, start=1):
        old = node.path()
        try:
            node.setName(f"{new_base}{i}", unique_name=True)
            renamed.append({"from": old, "to": node.path()})
        except Exception as e:
            renamed.append({"from": old, "error": str(e)})

    return {
        "success": True,
        "renamed": renamed,
        "count": len(renamed),
        "verdict": f"Renamed {len(renamed)} node(s) under {parent_path} matching '{match}'.",
    }
