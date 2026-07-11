# -*- coding: utf-8 -*-
"""Clean geometry — fuse coincident points, drop degenerate prims, remove unused points.

Mutating — adds a Clean SOP downstream of the target.
"""

SKILL_INFO = {
    "name": "clean_geo",
    "description": (
        "Add a Clean SOP downstream to tidy geometry: fuse coincident points, delete degenerate/zero-area "
        "primitives, and remove unused points. Use before booleans/exports, or when a mesh has artifacts."
    ),
    "parameters": {
        "node_path": {
            "type": "string",
            "description": "SOP to clean, e.g. '/obj/model/OUT'.",
            "required": True,
        },
        "fuse": {"type": "boolean", "description": "Fuse coincident points.", "default": True},
        "remove_degenerate": {
            "type": "boolean",
            "description": "Delete degenerate/zero-area primitives.",
            "default": True,
        },
    },
}


def _apply(node, parms):
    missing = []
    for k, v in parms.items():
        p = node.parm(k) or node.parmTuple(k)
        if p is None:
            missing.append(k)
            continue
        try:
            p.set(v)
        except Exception:
            missing.append(k)
    return missing


def run(node_path="", fuse=True, remove_degenerate=True):
    import hou  # type: ignore

    src = hou.node(node_path or "")
    if src is None:
        return {"success": False, "error": f"node not found: {node_path}"}
    parent = src.parent()
    try:
        cl = parent.createNode("clean", node_name="clean")
    except Exception as e:
        return {"success": False, "error": f"could not create clean SOP: {e}"}

    try:
        cl.setInput(0, src)
    except Exception as e:
        return {"success": False, "error": f"could not wire clean to {src.path()}: {e}"}

    missing = _apply(cl, {
        "fuse": 1 if fuse else 0,
        "deldegen": 1 if remove_degenerate else 0,
        "delunusedpts": 1,
    })
    try:
        cl.moveToGoodPosition()
        cl.setDisplayFlag(True)
        cl.setRenderFlag(True)
    except Exception:
        pass

    return {
        "success": True,
        "node": cl.path(),
        "unset_parms": missing,
        "verdict": (f"Clean added at {cl.path()}. Compare point/primitive counts before vs after with "
                    "verify_geo to see what it removed."),
    }
