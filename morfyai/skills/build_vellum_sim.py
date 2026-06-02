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
    "hidden": True,  # fronted by build_sim (sim_type='vellum')
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
            "description": "Use the solver's built-in ground plane (floor at y=0). No extra nodes — the "
                           "Vellum Solver already provides this. Set False for no floor.",
            "default": True,
        },
        "collider_path": {
            "type": "string",
            "description": "OPTIONAL path to existing geometry to use as a CUSTOM collider (character, "
                           "sphere, terrain) wired into the solver's Collision Geometry input. Leave empty "
                           "for just the built-in ground. This is the 'pake collider ini' hook.",
            "default": "",
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

# Constraint CHAIN per vellum type — VERIFIED against the live H21 'constrainttype'
# menu: none/distance/bend/cloth/hair/string/pin/attach/stitch/pressure/tetvolume/
# weld/glue/struts/tetfiber/tristretch/tetstretch/shapematch/surfacestruts.
# Some looks need MULTIPLE chained constraint nodes (e.g. a balloon needs surface
# stiffness from 'cloth' PLUS internal 'pressure', else it over-inflates and flops).
_TYPE_CHAIN = {
    "cloth": ["cloth"],
    "hair": ["hair"],
    "softbody": ["cloth", "struts"],     # surface stiffness + internal struts = holds shape, bounces
    "balloon": ["cloth", "pressure"],    # surface + inflation
    "grain": ["distance"],
}


def run(container_name="vellum_sim", type="cloth", source_shape="auto",
        ground_collision=True, collider_path="", duration_seconds=4.0):
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
        # raised HORIZONTAL sheet (orient 'zx' = XZ plane) so it drapes/falls.
        # orient 0 ('xy') makes a vertical sheet — wrong for a draping cloth.
        _set_parms(src, {"sizex": 4.0, "sizey": 4.0, "size": (4.0, 4.0),
                         "rows": 40, "cols": 40, "t": (0.0, 3.0, 0.0), "orient": "zx"})
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
    # Build a CHAIN of vellumconstraints nodes (some types need more than one).
    chain = _TYPE_CHAIN.get(vtype, [vtype])
    prev = None
    vc = None
    for i, token in enumerate(chain):
        node = geo.createNode(vc_type, f"vellumconstraints{i+1}")
        if prev is None:
            node.setInput(0, src)            # first: geometry only
        else:
            node.setInput(0, prev, 0)        # chain geometry + constraints through
            node.setInput(1, prev, 1)
        if not _set_parms(node, {"constrainttype": token}):
            warnings.append(f"could not set constraint type '{token}' on {node.name()}")
        created.append(node.path())
        prev = node
        vc = node  # last node feeds the solver

    # 4. Vellum Solver
    solver_type = _find_sop_type(["vellumsolver", "vellumsolver::2.0"])
    if not solver_type:
        return {"success": False,
                "error": "Vellum Solver ('vellumsolver') not available in this Houdini build",
                "created": created, "warnings": warnings}
    solver = geo.createNode(solver_type, "vellumsolver1")
    # vellumconstraints has TWO outputs: 0=Geometry, 1=Constraints. The solver needs
    # BOTH (input 0=Vellum Geometry, 1=Constraint Geometry) — wiring only output 0
    # causes "Not enough sources specified" with an empty sim.
    solver.setInput(0, vc, 0)
    solver.setInput(1, vc, 1)
    created.append(solver.path())

    # 5. ground: use the solver's BUILT-IN ground plane (verified parm 'useground').
    #    No grid node — a grid wired as collision was a vertical wall.
    _set_parms(solver, {"useground": 1 if ground_collision else 0})

    # 5b. OPTIONAL custom collider wired into the 'Collision Geometry' input.
    ground = None
    if collider_path:
        coll_geo = hou.node(collider_path)
        if coll_geo is None:
            warnings.append(f"collider_path '{collider_path}' not found — skipping custom collider")
        else:
            col_idx = _input_index_by_label(solver, ["collision", "collide"])
            if col_idx is None:
                col_idx = 2  # documented collision input index
            try:
                solver.setInput(col_idx, coll_geo)
                ground = coll_geo
            except Exception as e:
                warnings.append(f"could not wire custom collider: {e}")

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
