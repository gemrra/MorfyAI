# -*- coding: utf-8 -*-
"""Pyro simulation builder skill (H21 SOP-level Pyro Solver) — ONE skill, 3 presets.

VERIFIED working recipe (tested live in Houdini 21.0.512):
    source primitive -> scatter -> attribwrangle (source fields)
        -> Volume Rasterize Attributes -> Pyro Solver

Key findings (the reason naive setups produce an empty sim):
- The Pyro Solver sources from NAMED VOLUMES. Its default Sourcing maps
  density->density, temperature->temperature, and the fuel field "burn"->flame.
- The Pyro Source SOP does NOT emit those attributes unless its Initialize menu
  is triggered from the UI (a callback menu, not scriptable), so we author the
  fields on points with a wrangle and rasterize them. No "Initialize" needed.

Presets:
- smoke     : continuous cool smoke (density + temperature)
- fire      : continuous fire (adds 'burn' fuel -> flame, emit density from flame)
- explosion : one-shot fire burst (source gated to the first 2 frames) then dies
"""

SKILL_INFO = {
    "name": "build_pyro_sim",
    "hidden": True,  # fronted by build_sim (sim_type='pyro')
    "description": (
        "Build a complete, WORKING Pyro simulation from one call — ONE skill, choose the look via 'preset': "
        "smoke (billowy), fire (continuous flames), or explosion (one-shot fiery burst that dies out). "
        "Builds source -> scatter -> wrangle -> Volume Rasterize -> Pyro Solver (auto-sourced), sets the "
        "playback range and display flag. Press Play from frame 1 to simulate. "
        "Use whenever the user asks for pyro / smoke / fire / explosion."
    ),
    "parameters": {
        "container_name": {"type": "string", "description": "Name of the /obj geo container", "default": "pyro_sim"},
        "preset": {
            "type": "string", "description": "smoke = billowy smoke, fire = continuous flames, explosion = one-shot fiery burst",
            "enum": ["smoke", "fire", "explosion"], "default": "smoke",
        },
        "source_shape": {
            "type": "string", "description": "Primitive the pyro emits from",
            "enum": ["sphere", "box", "torus"], "default": "sphere",
        },
        "duration_seconds": {"type": "number", "description": "Simulation length in seconds", "default": 4.0},
    },
}

# Per-preset recipe (all values verified live).
#   gate: VEX expr deciding when the source is active (one-shot vs continuous)
#   attribs: which volumes to rasterize for the solver to source
#   solver: parms to set for the look (emit density from flame, buoyancy, etc.)
_PRESET = {
    "smoke": {
        "gate": "1.0", "density": 1.0, "temperature": 1.0, "burn": 0.0,
        "npts": 3000, "attribs": "density temperature",
        "solver": {"buoyancylift": 1.0},
    },
    "fire": {
        "gate": "1.0", "density": 0.6, "temperature": 6.0, "burn": 6.0,
        "npts": 4000, "attribs": "density temperature burn",
        "solver": {"doflamedensity": 1, "buoyancylift": 2.0, "flames_lifespan": 1.6, "tempcooling": 0.6},
    },
    "explosion": {
        "gate": "(@Frame<=2.0)?1.0:0.0", "density": 0.6, "temperature": 7.0, "burn": 7.0,
        "npts": 6000, "attribs": "density temperature burn",
        "solver": {"doflamedensity": 1, "buoyancylift": 3.0, "flames_lifespan": 1.2, "tempcooling": 0.6},
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
    for name, val in parm_values.items():
        try:
            p = node.parm(name) or node.parmTuple(name)
            if p is not None:
                p.set(val)
        except Exception:
            continue


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


def run(container_name="pyro_sim", preset="smoke", source_shape="sphere", duration_seconds=4.0):
    import hou  # type: ignore

    obj = hou.node("/obj")
    if obj is None:
        return {"success": False, "error": "/obj context not found"}

    cfg = _PRESET.get(preset, _PRESET["smoke"])
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
        _set_parms(src, {"type": 2, "scale": 0.45})
    created.append(src.path())

    # 2. scatter points
    sc_type = _find_sop_type(["scatter", "scatter::2.0"])
    upstream = src
    if sc_type:
        sc = geo.createNode(sc_type, "scatter")
        sc.setInput(0, src)
        _set_parms(sc, {"npts": int(cfg["npts"])})
        created.append(sc.path())
        upstream = sc
    else:
        warnings.append("scatter SOP not found — sourcing from raw primitive points")

    # 3. author the source fields the solver reads by name (density / temperature / burn)
    w_type = _find_sop_type(["attribwrangle", "attribwrangle::3.0"])
    if not w_type:
        return {"success": False, "error": "Attribute Wrangle not available", "created": created}
    w = geo.createNode(w_type, "source_fields")
    w.setInput(0, upstream)
    _set_parms(w, {"class": 2})  # run over points
    snippet = f"float gate = {cfg['gate']};\nf@density = gate*{cfg['density']};\nf@temperature = gate*{cfg['temperature']};\n"
    if cfg["burn"] > 0:
        snippet += f"f@burn = gate*{cfg['burn']};\n"   # fuel -> solver 'burn' source -> flame field
    snippet += "f@pscale = 0.11;"
    try:
        w.parm("snippet").set(snippet)
    except Exception as e:
        warnings.append(f"could not set wrangle snippet: {e}")
    created.append(w.path())

    # 4. rasterize point attributes into named VDB volumes
    rast_type = _find_sop_type(["volumerasterizeattributes", "volumerasterizeattributes::2.0"])
    if not rast_type:
        return {"success": False,
                "error": "Volume Rasterize Attributes not available — pyro can't source",
                "created": created, "warnings": warnings}
    rast = geo.createNode(rast_type, "rasterize")
    rast.setInput(0, w)
    _set_parms(rast, {"attributes": cfg["attribs"]})
    created.append(rast.path())

    # 5. Pyro Solver — default Sourcing maps these volumes automatically
    solver_type = _find_sop_type(["pyrosolver", "pyrosolver::2.0"])
    if not solver_type:
        return {"success": False, "error": "Pyro Solver ('pyrosolver') not available",
                "created": created, "warnings": warnings}
    solver = geo.createNode(solver_type, "pyrosolver1")
    solver.setInput(0, rast)
    _set_parms(solver, cfg["solver"])
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
    try:
        errs = list(solver.errors() or [])
    except Exception:
        errs = []

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
            "Go to frame 1 and press Play to simulate."
            + (" (one-shot burst — watch the first ~30 frames)" if preset == "explosion" else "")
            + (f" ⚠ solver errors: {errs}" if errs else "")
        ),
    }
