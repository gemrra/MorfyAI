# -*- coding: utf-8 -*-
"""Pyro simulation builder skill (H21 SOP-level Pyro Solver).

VERIFIED working recipe (tested live in Houdini 21.0.512):
    source primitive -> scatter -> attribwrangle (@density/@temperature)
        -> Volume Rasterize Attributes (density temperature) -> Pyro Solver

Why this shape: the Pyro Solver sources from NAMED VOLUMES, and its default
Sourcing tab already maps volume "density"->density and "temperature"->temperature.
The Pyro Source SOP does NOT emit those attributes unless its (callback-only)
Initialize menu is triggered from the UI — which scripting can't do — so we
create density/temperature on points directly with a wrangle and rasterize them.
No "Initialize" button is needed; the solver picks the volumes up automatically.
"""

SKILL_INFO = {
    "name": "build_pyro_sim",
    "description": (
        "Build a complete, WORKING sparse Pyro (smoke/fire/explosion) simulation from one call. "
        "Chain: source -> scatter -> wrangle (density/temperature) -> Volume Rasterize -> Pyro Solver "
        "(sources the volumes automatically). Sets the playback range and display flag. "
        "Use when the user asks to set up / build a pyro, smoke, fire, or explosion sim. "
        "Press Play from frame 1 to simulate (pyro cooks sequentially)."
    ),
    "parameters": {
        "container_name": {"type": "string", "description": "Name of the /obj geo container", "default": "pyro_sim"},
        "source_shape": {
            "type": "string", "description": "Primitive the pyro emits from",
            "enum": ["sphere", "box", "torus"], "default": "sphere",
        },
        "preset": {
            "type": "string", "description": "smoke (cool billowy), fire (hot), or explosion (very hot)",
            "enum": ["smoke", "fire", "explosion"], "default": "smoke",
        },
        "duration_seconds": {"type": "number", "description": "Simulation length in seconds", "default": 4.0},
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
        end = int(round(1 + max(0.1, float(duration_seconds)) * fps))
        hou.playbar.setFrameRange(1, end)
        hou.playbar.setPlaybackRange(1, end)
        return [1, end]
    except Exception:
        return None


def _node_errors(node):
    try:
        return list(node.errors() or [])
    except Exception:
        return []


# preset -> (temperature value, scatter count). Hotter temperature => more
# buoyancy / energy. Density stays 1.0 for all.
_PRESET = {
    "smoke":     (1.0, 3000),
    "fire":      (3.0, 4000),
    "explosion": (6.0, 6000),
}


def run(container_name="pyro_sim", source_shape="sphere", preset="smoke", duration_seconds=4.0):
    import hou  # type: ignore

    obj = hou.node("/obj")
    if obj is None:
        return {"success": False, "error": "/obj context not found"}

    temp, npts = _PRESET.get(preset, _PRESET["smoke"])
    warnings = []
    created = []

    try:
        geo = obj.createNode("geo", container_name)
    except Exception as e:
        return {"success": False, "error": f"failed to create container: {e}"}
    created.append(geo.path())

    # 1. source primitive (polygonal so scatter works)
    src_type = _find_sop_type([source_shape, "sphere"])
    if not src_type:
        return {"success": False, "error": f"no source primitive type available ({source_shape})"}
    src = geo.createNode(src_type, f"source_{source_shape}")
    if src_type == "sphere":
        _set_parms(src, {"type": 2, "scale": 0.5})
    created.append(src.path())

    # 2. scatter points to source from
    sc_type = _find_sop_type(["scatter", "scatter::2.0"])
    upstream = src
    if sc_type:
        sc = geo.createNode(sc_type, "scatter")
        sc.setInput(0, src)
        _set_parms(sc, {"npts": int(npts)})
        created.append(sc.path())
        upstream = sc
    else:
        warnings.append("scatter SOP not found — sourcing from raw primitive points")

    # 3. wrangle: author the source fields the solver reads by name
    w_type = _find_sop_type(["attribwrangle", "attribwrangle::3.0"])
    if not w_type:
        return {"success": False, "error": "Attribute Wrangle not available", "created": created}
    w = geo.createNode(w_type, "source_fields")
    w.setInput(0, upstream)
    _set_parms(w, {"class": 2})  # run over points
    try:
        w.parm("snippet").set(
            f"f@density = 1.0;\nf@temperature = {temp};\nf@pscale = 0.12;")
    except Exception as e:
        warnings.append(f"could not set wrangle snippet: {e}")
    created.append(w.path())

    # 4. rasterize the point attributes into named VDB volumes
    rast_type = _find_sop_type(["volumerasterizeattributes", "volumerasterizeattributes::2.0"])
    if not rast_type:
        return {"success": False,
                "error": "Volume Rasterize Attributes not available — pyro can't source",
                "created": created, "warnings": warnings}
    rast = geo.createNode(rast_type, "rasterize")
    rast.setInput(0, w)
    _set_parms(rast, {"attributes": "density temperature"})
    created.append(rast.path())

    # 5. Pyro Solver — default Sourcing already maps density/temperature
    solver_type = _find_sop_type(["pyrosolver", "pyrosolver::2.0"])
    if not solver_type:
        return {"success": False, "error": "Pyro Solver ('pyrosolver') not available",
                "created": created, "warnings": warnings}
    solver = geo.createNode(solver_type, "pyrosolver1")
    solver.setInput(0, rast)
    created.append(solver.path())

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
    errs = _node_errors(solver)

    return {
        "success": True,
        "preset": preset,
        "container": geo.path(),
        "solver": solver.path(),
        "created_nodes": created,
        "frame_range": frame_range,
        "solver_errors": errs,
        "warnings": warnings,
        "message": (
            f"Built {preset} pyro sim in {geo.path()}. Display flag on {solver.path()}. "
            "Go to frame 1 and press Play to simulate (pyro cooks sequentially)."
            + (f" ⚠ solver errors: {errs}" if errs else "")
        ),
    }
