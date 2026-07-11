# -*- coding: utf-8 -*-
"""Duplicate a single node (with its parm values), placed just beside the original.

Mutating — creates a copied node. Does NOT duplicate upstream nodes; the
copy's inputs can be reconnected via include_inputs.
"""

SKILL_INFO = {
    "name": "duplicate_node",
    "description": (
        "Duplicate a single node (copies its parameter values) and place it just beside the original. "
        "Does not duplicate anything upstream. Use to branch off a variant without starting from scratch."
    ),
    "parameters": {
        "node_path": {"type": "string", "description": "Node to duplicate.", "required": True},
        "new_name": {"type": "string", "description": "Name for the copy. Leave empty to auto-name.", "default": ""},
        "include_inputs": {
            "type": "boolean",
            "description": "Wire the copy to the same input connections as the original.",
            "default": True,
        },
    },
}


def run(node_path="", new_name="", include_inputs=True):
    import hou  # type: ignore

    node = hou.node(node_path or "")
    if node is None:
        return {"success": False, "error": f"node not found: {node_path}"}
    parent = node.parent()

    try:
        copies = parent.copyItems([node])
    except Exception as e:
        return {"success": False, "error": f"could not duplicate node: {e}"}
    if not copies:
        return {"success": False, "error": "duplicate produced no node"}
    new_node = copies[0]

    if new_name:
        try:
            new_node.setName(new_name, unique_name=True)
        except Exception:
            pass
    try:
        pos = node.position()
        new_node.setPosition(hou.Vector2(pos[0] + 2, pos[1] - 1))
    except Exception:
        pass

    if include_inputs:
        try:
            for i, inp in enumerate(node.inputs()):
                if inp is not None:
                    new_node.setInput(i, inp)
        except Exception:
            pass

    return {
        "success": True,
        "original": node.path(),
        "duplicate": new_node.path(),
        "include_inputs": include_inputs,
        "verdict": f"Duplicated {node.path()} -> {new_node.path()}"
                   + (" (same inputs)." if include_inputs else " (unconnected)."),
    }
