# -*- coding: utf-8 -*-
"""Select (highlight) every node of a given type under a network.

Read-only — selection is a UI/navigation aid, not a scene-data change.
"""

SKILL_INFO = {
    "name": "select_by_type",
    "description": (
        "Select every node of a given type name (e.g. 'sphere', 'box', 'attribwrangle') under a parent "
        "network, so they're highlighted in the network editor. Use to find/inspect all instances of a "
        "node type at once."
    ),
    "parameters": {
        "parent_path": {"type": "string", "description": "Network to search in, e.g. '/obj/geo1'.", "required": True},
        "node_type": {"type": "string", "description": "Node type name to match, e.g. 'attribwrangle'.", "required": True},
    },
}


def run(parent_path="", node_type=""):
    import hou  # type: ignore

    if not node_type:
        return {"success": False, "error": "node_type is required"}
    parent = hou.node(parent_path or "")
    if parent is None:
        return {"success": False, "error": f"parent not found: {parent_path}"}

    matches = [c for c in parent.children() if c.type().name() == node_type]
    try:
        for c in parent.children():
            c.setSelected(False)
        for c in matches:
            c.setSelected(True)
    except Exception:
        pass

    return {
        "success": True,
        "parent": parent.path(),
        "node_type": node_type,
        "count": len(matches),
        "nodes": [c.path() for c in matches],
        "verdict": f"{len(matches)} node(s) of type '{node_type}' selected under {parent.path()}.",
    }
