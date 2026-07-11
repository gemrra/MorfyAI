# -*- coding: utf-8 -*-
"""List the child nodes of a network — a lightweight look inside a subnet.

Read-only.
"""

SKILL_INFO = {
    "name": "list_children",
    "description": (
        "List the immediate child nodes of a network (name, type, position, bypass/display flags). "
        "Use to see what's inside a subnet/geo node before deciding what to change."
    ),
    "parameters": {
        "parent_path": {"type": "string", "description": "Network to list, e.g. '/obj/geo1'.", "required": True},
    },
}


def run(parent_path=""):
    import hou  # type: ignore

    parent = hou.node(parent_path or "")
    if parent is None:
        return {"success": False, "error": f"node not found: {parent_path}"}

    kids = []
    for c in parent.children():
        entry = {"name": c.name(), "path": c.path(), "type": c.type().name()}
        try:
            entry["bypassed"] = c.isBypassed()
        except Exception:
            pass
        try:
            entry["display"] = c.isDisplayFlagSet()
        except Exception:
            pass
        kids.append(entry)

    return {
        "success": True,
        "parent": parent.path(),
        "count": len(kids),
        "children": kids,
        "verdict": f"{parent.path()} has {len(kids)} child node(s)." if kids else f"{parent.path()} is empty.",
    }
