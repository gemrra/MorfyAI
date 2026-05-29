# -*- coding: utf-8 -*-
"""Vellum simulation builder skill (H21 SOP-level Vellum).

Builds a complete Vellum setup from one call:
    source primitive -> Vellum Constraints (typed) -> Vellum Solver
    (+ optional ground collision)

Covers cloth, hair, softbody, balloon and grain via the constraint type.
Deterministic Python wiring; node types and parm names resolved/guarded at
runtime. Verified against SideFX H21 docs:
  vellumsolver inputs: 0=surface geo, 1=constraint geo, 2=collision
  vellumconstraints constraint types: Cloth / Hair / Softbody / Pressure(balloon) / Grain
"""

SKILL_INFO = {
    "name": "build_vellum_sim",
    "description": (
        "Build a complete Vellum simulation from one call — cloth, hair, softbody, balloon, or grain. "
        "Creates a geo container with: source primitive -> Vellum Constraints (set to the chosen type) -> "
        "Vellum Solver, optionally adds a ground collider, sets the playback range, turns on the display "
        "flag, and returns the created node paths. "
        "Use when the user asks to set up / build a vellum, cloth, fabric, hair, softbody, balloon, or grain sim."
    ),
    "parameters": {
        "container_name": {
            "type": "string",
            "description": "Name of the /obj geo container to create",
            "default": "vellum_sim",
        },
        "type": {
            "type": "string",
            "description": "Vellum constraint type / behavior",
            "enum": ["cloth", "hair", "softbody", "balloon", "grain"],
            "default": "cloth",
        },
        "source_shape": {
            "type": "string",
            "description": "Source primitive. Default picks a sensible shape for the type (grid for cloth, sphere for softbody/balloon).",
            "enum": ["auto", "grid", "sphere", "box", "torus", "line"],
            "default": "auto",
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


# default source shape per vellum type
_DEFAULT_SHAPE = {
    "cloth": "grid", "hair": "line", "softbody": "sphere",
    "balloon": "sphere", "grain": "box",
}

# candidate constraint-type tokens per vellum type (parm enum varies by build)
_TYPE_TOKENS = {
    "cloth": ["cloth"],
    "hair": ["hair"],
    "softbody": ["softbody", "soft", "tetrahedral"],
    "balloon": ["pressure", "balloon"],
    "grain": ["grain", "grains"],
}


def run(container_name="vellum_sim", type="cloth", source_shape="auto",
        ground_collision=True, duration_seconds=4.0):
    import hou  # type: ignore

    obj = hou.node("/obj")
    if obj is None:
        return {"success": False, "error": "/obj context not found"}

    warnings = []
    created = []
    vtype = (type or "cloth").lower()

    # 1. geo container
    try:
        geo = obj.createNode("geo", container_name)
    except Exception as e:
        return {"success": False, "error": f"failed to create container: {e}"}
    created.append(geo.path())

    # 2. source primitive
    shape = source_shape if source_shape and source_shape != "auto" else _DEFAULT_SHAPE.get(vtype, "grid")
    src_type = _find_sop_type([shape, "grid", "sphere"])
    if not src_type:
        return {"success": False, "error": f"no source primitive type available ({shape})"}
    src = geo.createNode(src_type, f"source_{shape}")
    if src_type == "grid":
        # raised, with enough rows/cols to drape
        _set_parms(src, {"sizex": 4.0, "sizey": 4.0, "size": (4.0, 4.0),
                         "rows": 40, "cols": 40, "t": (0.0, 3.0, 0.0), "orient": 0})
    elif src_type == "sphere":
        _set_parms(src, {"type": 2, "t": (0.0, 3.0, 0.0)})
    else:
        _set_parms(src, {"t": (0.0, 3.0, 0.0)})
    created.append(src.path())

    # 3. Vellum Constraints (typed)
    vc_type = _find_sop_type(["vellumconstraints", "vellumconstraints::2.0"])
    if not vc_type:
        return {"success": False,
                "error": "Vellum Constraints ('vellumconstraints') not available in this Houdini build",
                "created": created}
    vc = geo.createNode(vc_type, "vellumconstraints1")
    vc.setInput(0, src)
    created.append(vc.path())
    # set constraint type via candidate parm names + tokens
    applied_type = False
    for parm in ("constrainttype", "constraint_type", "type"):
        for token in _TYPE_TOKENS.get(vtype, [vtype]):
            if _set_parms(vc, {parm: token}):
                applied_type = True
                break
        if applied_type:
            break
    if not applied_type:
        warnings.append(f"could not set vellum constraint type '{vtype}' (version parm differs) — "
                        f"set the constraint type manually on {vc.name()}")

    # 4. Vellum Solver
    solver_type = _find_sop_type(["vellumsolver", "vellumsolver::2.0"])
    if not solver_type:
        return {"success": False,
                "error": "Vellum Solver ('vellumsolver') not available in this Houdini build",
                "created": created, "warnings": warnings}
    solver = geo.createNode(solver_type, "vellumsolver1")
    solver.setInput(0, vc)  # constrained geometry stream
    created.append(solver.path())

    # 5. optional ground collider (solver collision input, matched by label)
    ground = None
    if ground_collision:
        grid_type = _find_sop_type(["grid"])
        if grid_type:
            ground = geo.createNode(grid_type, "ground")
            _set_parms(ground, {"sizex": 10.0, "sizey": 10.0, "size": (10.0, 10.0), "orient": 0})
            created.append(ground.path())
            col_idx = _input_index_by_label(solver, ["collision", "collide", "static"])
            if col_idx is None:
                col_idx = 2  # documented collision input index
            try:
                solver.setInput(col_idx, ground)
            except Exception as e:
                warnings.append(f"could not wire ground to collision input: {e}")

    # 6. display + layout + frame range
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
        "type": vtype,
        "container": geo.path(),
        "solver": solver.path(),
        "ground": ground.path() if ground else None,
        "created_nodes": created,
        "frame_range": frame_range,
        "warnings": warnings,
        "message": (
            f"Built Vellum '{vtype}' sim in {geo.path()}. "
            f"Display flag on {solver.path()} — press play to cook."
        ),
    }
