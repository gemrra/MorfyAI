# -*- coding: utf-8 -*-
"""Add a File Cache SOP to cache a node's result to disk.

Mutating — adds a File Cache SOP downstream. Does NOT write frames automatically
(that can be heavy); it sets the node up so the user presses "Save to Disk".
"""

SKILL_INFO = {
    "name": "cache_to_disk",
    "description": (
        "Add a File Cache SOP downstream of a heavy node so its result can be cached to disk (per-frame) "
        "and not recooked every time. This sets the node up only — it does NOT write frames automatically; "
        "the user still presses 'Save to Disk' on the node. Use to speed up slow sims/builds."
    ),
    "parameters": {
        "node_path": {
            "type": "string",
            "description": "SOP whose output to cache, e.g. '/obj/geo/dopimport'.",
            "required": True,
        },
        "name": {"type": "string", "description": "File Cache node name.", "default": "filecache"},
    },
}


def run(node_path="", name="filecache"):
    import hou  # type: ignore

    src = hou.node(node_path or "")
    if src is None:
        return {"success": False, "error": f"node not found: {node_path}"}
    parent = src.parent()
    try:
        fc = parent.createNode("filecache", node_name=name)
    except Exception as e:
        return {"success": False, "error": f"could not create filecache SOP: {e}"}

    try:
        fc.setInput(0, src)
    except Exception as e:
        return {"success": False, "error": f"could not wire filecache to {src.path()}: {e}"}

    try:
        fc.moveToGoodPosition()
        fc.setDisplayFlag(True)
        fc.setRenderFlag(True)
    except Exception:
        pass

    return {
        "success": True,
        "node": fc.path(),
        "cached_from": src.path(),
        "verdict": (f"File Cache added at {fc.path()} (fed by {src.path()}). It is NOT written yet — "
                    "press 'Save to Disk' on the node (or set a frame range first) to bake the cache."),
    }
