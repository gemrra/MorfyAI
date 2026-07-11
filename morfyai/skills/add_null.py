# -*- coding: utf-8 -*-
"""Cap a chain with a Null SOP — the standard Houdini convention for a clean output.

Mutating — adds a Null SOP downstream.
"""

SKILL_INFO = {
    "name": "add_null",
    "description": (
        "Add a Null SOP downstream of a node and set it as the display/render node — the standard Houdini "
        "convention for marking a clean, stable output point (e.g. 'OUT_geo'). Use to cap off a finished "
        "chain before wiring it elsewhere."
    ),
    "parameters": {
        "node_path": {"type": "string", "description": "SOP to cap, e.g. '/obj/geo1/clean1'.", "required": True},
        "name": {"type": "string", "description": "Null node name.", "default": "OUT"},
    },
}


def run(node_path="", name="OUT"):
    import hou  # type: ignore

    src = hou.node(node_path or "")
    if src is None:
        return {"success": False, "error": f"node not found: {node_path}"}
    parent = src.parent()
    try:
        null = parent.createNode("null", node_name=name)
        null.setInput(0, src)
    except Exception as e:
        return {"success": False, "error": f"could not create/wire null: {e}"}

    try:
        null.moveToGoodPosition()
        null.setDisplayFlag(True)
        null.setRenderFlag(True)
    except Exception:
        pass

    return {
        "success": True,
        "node": null.path(),
        "capped": src.path(),
        "verdict": f"Null '{null.name()}' added at {null.path()}, capping {src.path()}.",
    }
