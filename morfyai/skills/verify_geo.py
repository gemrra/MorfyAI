# -*- coding: utf-8 -*-
"""Verify geometry — cook a node and report the data needed to judge correctness.

The model cannot see the viewport (no vision on cheaper models), so it must
judge a build by DATA. This cooks a node and returns point/prim counts, the
bounding box, and errors/warnings in one call — plus a few sanity hints — so
the build/verify protocol is a single, easy step.

Read-only.
"""

SKILL_INFO = {
    "name": "verify_geo",
    "description": (
        "Cook a SOP node and report whether the result looks correct: point/primitive counts, bounding "
        "box (min/max/size), node errors and warnings, plus sanity hints (empty? degenerate? resting on "
        "the ground or sunk below it?). Use after building anything to VERIFY by data before claiming "
        "success — '0 errors' alone is not enough."
    ),
    "parameters": {
        "node_path": {
            "type": "string",
            "description": "Path of the SOP node to cook and inspect, e.g. '/obj/fence/fence_out'.",
            "required": True,
        },
        "expect_on_ground": {
            "type": "boolean",
            "description": "If True, flags when the lowest point is well below Y=0 (fell through the floor).",
            "default": False,
        },
    },
}


def run(node_path="", expect_on_ground=False):
    import hou  # type: ignore

    node = hou.node(node_path or "")
    if node is None:
        return {"success": False, "error": f"node not found: {node_path}"}

    try:
        geo = node.geometry()
    except Exception as e:
        return {"success": False, "error": f"could not cook/read geometry: {e}",
                "errors": list(node.errors() or [])}

    if geo is None:
        return {"success": True, "node": node.path(), "empty": True,
                "errors": list(node.errors() or []), "warnings": list(node.warnings() or []),
                "verdict": "NO GEOMETRY — node produced nothing. Check inputs/wiring."}

    npts = len(geo.points())
    nprims = len(geo.prims())
    errs = list(node.errors() or [])
    warns = list(node.warnings() or [])

    bbox = geo.boundingBox()
    mn = [round(x, 3) for x in bbox.minvec()]
    mx = [round(x, 3) for x in bbox.maxvec()]
    size = [round(x, 3) for x in bbox.sizevec()]

    hints = []
    if npts == 0:
        hints.append("EMPTY: no points — the build produced nothing (check wiring/source).")
    if nprims == 0 and npts > 0:
        hints.append("points but no primitives — result may be just points (ok for particles, wrong for mesh).")
    if size and max(size) > 0 and min(size) == 0:
        hints.append("flat in one axis (size 0 on an axis) — fine for a ground/plane, suspicious for a solid.")
    if expect_on_ground and mn and mn[1] < -0.1:
        hints.append(f"SUNK: lowest Y is {mn[1]} (below the floor) — it fell THROUGH the ground; "
                     "fix collision (collider must feed the solver input, response not 'none').")
    if errs:
        hints.append(f"{len(errs)} node error(s) — must be resolved.")

    ok = npts > 0 and not errs
    return {
        "success": True,
        "node": node.path(),
        "points": npts,
        "prims": nprims,
        "bbox_min": mn,
        "bbox_max": mx,
        "bbox_size": size,
        "errors": errs,
        "warnings": warns[:5],
        "hints": hints,
        "verdict": ("LOOKS OK (non-empty, no errors) — still sanity-check the bbox/counts match intent."
                    if ok else "NOT OK — see hints/errors above; fix before reporting success."),
    }
