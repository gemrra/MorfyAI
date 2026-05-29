# -*- coding: utf-8 -*-
"""FLIP fluid simulation builder skill (H21+ SOP-level FLIP Solver)

Builds a complete, ready-to-cook FLIP liquid setup from a single call:
    source primitive -> FLIP Solver SOP   (+ optional ground collider)

Deterministic Python wiring so the chain is always correct. Node types and
the collision input port are resolved at runtime (input ports matched by
label) so it tolerates version drift.
"""

SKILL_INFO = {
    "name": "build_flip_sim",
    "description": (
        "Build a complete FLIP liquid/fluid simulation from one call. Creates a geo container with: "
        "source primitive -> FLIP Solver SOP, optionally adds a ground grid wired into the solver's "
        "collision input, sets the playback range, and turns on the display flag. Returns created paths. "
        "Use when the user asks to set up / build a FLIP, liquid, water, or fluid sim."
    ),
    "parameters": {
        "container_name": {
            "type": "string",
            "description": "Name of the /obj geo container to create",
            "default": "flip_sim",
        },
        "source_shape": {
            "type": "string",
            "description": "Primitive used as the initial fluid volume",
            "enum": ["sphere", "box", "torus"],
            "default": "sphere",
        },
        "ground_collision": {
            "type": "boolean",
            "description": "Add a ground grid wired into the solver's collision input",
            "default": True,
        },
        "duration_seconds": {
            "type": "number",
            "description": "Simulation length in seconds (drives the playback range)",
            "default": 4.0,
        },
    },
}


# ── runtime resolvers (kept self-contained per skill) ────────────────

def _find_sop_type(candidates):
    import hou  # type: ignore
    try:
        types = hou.sopNodeTypeCategory().nodeTypes()
    except Exception:
        types = {}
    for c in candidates:
        if c in types:
            return c
    return None


def _input_index_by_label(node, keywords):
    """Find an input port whose label matches any keyword (case-insensitive)."""
    try:
        labels = node.inputLabels()
    except Exception:
        labels = ()
    for i, lab in enumerate(labels):
        ll = (lab or "").lower()
        if any(k in ll for k in keywords):
            return i
    return None


def _set_parms(node, parm_values):
    applied = {}
    for name, val in parm_values.items():
        try:
            p = node.parm(name) or node.parmTuple(name)
            if p is not None:
                p.set(val)
                applied[name] = val
        except Exception:
            continue
    return applied


def _set_frame_range(duration_seconds):
    import hou  # type: ignore
    try:
        fps = hou.fps() or 24.0
        start = 1
        end = int(round(start + max(0.1, float(duration_seconds)) * fps))
        hou.playbar.setFrameRange(start, end)
        hou.playbar.setPlaybackRange(start, end)
        return [start, end]
    except Exception:
        return None


def run(container_name="flip_sim", source_shape="sphere",
        ground_collision=True, duration_seconds=4.0):
    import hou  # type: ignore

    obj = hou.node("/obj")
    if obj is None:
        return {"success": False, "error": "/obj context not found"}

    warnings = []
    created = []

    # 1. geo container
    try:
        geo = obj.createNode("geo", container_name)
    except Exception as e:
        return {"success": False, "error": f"failed to create container: {e}"}
    created.append(geo.path())

    # 2. source primitive (raised above origin so it falls)
    src_type = _find_sop_type([source_shape, "sphere"])
    if not src_type:
        return {"success": False, "error": f"no source primitive type available ({source_shape})"}
    src = geo.createNode(src_type, f"source_{source_shape}")
    if src_type == "sphere":
        _set_parms(src, {"scale": 0.5, "type": 2, "ty": 2.0, "t": (0.0, 2.0, 0.0)})
    created.append(src.path())

    # 3. FLIP Solver SOP
    solver_type = _find_sop_type(["flipsolver", "flipsolver::2.0"])
    if not solver_type:
        return {"success": False,
                "error": "FLIP Solver SOP ('flipsolver') not available in this Houdini build",
                "created": created, "warnings": warnings}
    solver = geo.createNode(solver_type, "flipsolver1")
    solver.setInput(0, src)
    created.append(solver.path())

    # 4. optional ground collider
    ground = None
    if ground_collision:
        grid_type = _find_sop_type(["grid"])
        if grid_type:
            ground = geo.createNode(grid_type, "ground")
            _set_parms(ground, {"sizex": 10.0, "sizey": 10.0,
                                 "size": (10.0, 10.0), "orient": 0})
            created.append(ground.path())
            col_idx = _input_index_by_label(solver, ["collision", "collide", "ground", "static"])
            if col_idx is not None:
                try:
                    solver.setInput(col_idx, ground)
                except Exception as e:
                    warnings.append(f"could not wire ground to collision input: {e}")
            else:
                warnings.append("collision input port not found on FLIP solver — ground left unconnected")

    # 5. display flag + layout + frame range
    try:
        solver.setDisplayFlag(True)
        if hasattr(solver, "setRenderFlag"):
            solver.setRenderFlag(True)
    except Exception as e:
        warnings.append(f"display flag failed: {e}")

    try:
        geo.layoutChildren()
    except Exception:
        pass

    frame_range = _set_frame_range(duration_seconds)

    return {
        "success": True,
        "container": geo.path(),
        "solver": solver.path(),
        "ground": ground.path() if ground else None,
        "created_nodes": created,
        "frame_range": frame_range,
        "warnings": warnings,
        "message": (
            f"Built FLIP liquid sim in {geo.path()}. "
            f"Display flag on {solver.path()} — press play to cook."
        ),
    }
