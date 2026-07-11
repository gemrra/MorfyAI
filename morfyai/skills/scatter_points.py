# -*- coding: utf-8 -*-
"""Scatter points across a surface.

Mutating — adds a Scatter SOP downstream of the target.
"""

SKILL_INFO = {
    "name": "scatter_points",
    "description": (
        "Add a Scatter SOP downstream of a surface node to distribute a set number of points across it "
        "(for instancing, copy-to-points, or point-based effects). Optionally relax for even spacing."
    ),
    "parameters": {
        "node_path": {
            "type": "string",
            "description": "Surface SOP to scatter on, e.g. '/obj/grid1/grid1'.",
            "required": True,
        },
        "count": {"type": "integer", "description": "Total number of points to scatter.", "default": 1000},
        "relax": {"type": "boolean", "description": "Even out spacing (relax iterations).", "default": True},
        "seed": {"type": "integer", "description": "Random seed.", "default": 0},
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


def run(node_path="", count=1000, relax=True, seed=0):
    import hou  # type: ignore

    src = hou.node(node_path or "")
    if src is None:
        return {"success": False, "error": f"node not found: {node_path}"}
    parent = src.parent()
    try:
        sc = parent.createNode("scatter", node_name="scatter_pts")
    except Exception as e:
        return {"success": False, "error": f"could not create scatter SOP: {e}"}

    try:
        sc.setInput(0, src)
    except Exception as e:
        return {"success": False, "error": f"could not wire scatter to {src.path()}: {e}"}

    # Force an exact count; parm names vary slightly by version, so set defensively.
    missing = _apply(sc, {
        "npts": int(count),
        "forcetotal": 1,
        "randseed": int(seed),
        "relaxpoints": 1 if relax else 0,
    })
    try:
        sc.moveToGoodPosition()
        sc.setDisplayFlag(True)
        sc.setRenderFlag(True)
    except Exception:
        pass

    return {
        "success": True,
        "node": sc.path(),
        "requested_count": count,
        "unset_parms": missing,
        "verdict": (f"Scatter added at {sc.path()} — targeting {count} points on {src.path()}. "
                    "Run verify_geo on it to confirm the actual point count."),
    }
