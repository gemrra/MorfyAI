# -*- coding: utf-8 -*-
"""FLIP liquid simulation builder skill (H21 SOP-level FLIP).

VERIFIED working recipe (extracted from SideFX's own "FLIP Configure Flip!" shelf
tool and tested live in Houdini 21.0.512 -> 1731 particles, 0 errors):

    flipcontainer (3 outputs) ┐
                              ├-> flipboundary (geometry on input 3) -> flipsolver
    fluid shape -> subdivide ─┘

Why naive setups fail ("Not enough sources"): the FLIP solver does NOT source
from a flipsource SOP. The real source is a **flipboundary** node that threads
the container's 3 outputs (0,1,2) through and takes the fluid geometry on input 3;
its `activate` expression controls one-shot vs continuous. The solver then reads
the boundary's 3 outputs. None of this is scriptable from flipsource.
"""

SKILL_INFO = {
    "name": "build_flip_sim",
    "description": (
        "Build a complete, WORKING FLIP liquid / water simulation from one call. THREE modes: "
        "(1) one-shot 'drop' that falls and splashes (default), (2) a continuous falling stream, or "
        "(3) a FOUNTAIN/JET that shoots water UPWARD ('air mancur', fountain, jet, geyser, water spout) — "
        "set fountain=True for this. flipcontainer -> flipboundary -> flipsolver, with a ground plane. "
        "Use when the user asks for FLIP / liquid / water / fluid / splash / fountain / air mancur."
    ),
    "parameters": {
        "container_name": {"type": "string", "description": "Name of the /obj geo container", "default": "flip_sim"},
        "source_shape": {
            "type": "string", "description": "Fluid blob shape",
            "enum": ["sphere", "box", "torus"], "default": "sphere",
        },
        "fountain": {
            "type": "boolean",
            "description": "★ Set True for a FOUNTAIN / JET / GEYSER / 'air mancur' — a nozzle shoots water "
                           "UPWARD that arcs back down. This is the ONLY way to get upward-shooting water; "
                           "do NOT use 'continuous' for a fountain (continuous only falls downward).",
            "default": False,
        },
        "continuous": {
            "type": "boolean",
            "description": "True = a downward FALLING stream (water poured/emitted that drops). "
                           "False (default) = one-shot drop. For an upward fountain use 'fountain', NOT this.",
            "default": False,
        },
        "jet_speed": {
            "type": "number",
            "description": "Fountain only: upward launch speed (higher = taller jet). Default 9.0",
            "default": 9.0,
        },
        "resolution": {
            "type": "number",
            "description": "Particle separation (smaller = finer/slower). Default 0.08",
            "default": 0.08,
        },
        "ground": {"type": "boolean", "description": "Add the solver's ground plane", "default": True},
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


def run(container_name="flip_sim", source_shape="sphere", continuous=False,
        fountain=False, jet_speed=9.0, resolution=0.08, ground=True, duration_seconds=4.0):
    import hou  # type: ignore

    obj = hou.node("/obj")
    if obj is None:
        return {"success": False, "error": "/obj context not found"}

    warnings = []
    created = []
    try:
        geo = obj.createNode("geo", container_name)
    except Exception as e:
        return {"success": False, "error": f"failed to create container: {e}"}
    created.append(geo.path())

    # 1. FLIP container (domain) — has 3 outputs
    cont_type = _find_sop_type(["flipcontainer", "flipcontainer::2.0"])
    if not cont_type:
        return {"success": False, "error": "FLIP Container ('flipcontainer') not available", "created": created}
    tank = geo.createNode(cont_type, "flipcontainer1")
    _set_parms(tank, {"particlesep": float(resolution)})
    if fountain:
        # tall, raised domain so the jet arc fits inside the container
        _set_parms(tank, {"size": (4.0, 8.0, 4.0), "t": (0.0, 3.6, 0.0)})
    created.append(tank.path())

    if fountain:
        # 2f. small nozzle near the ground + upward velocity = a jet/fountain
        noz = geo.createNode("sphere", "nozzle")
        _set_parms(noz, {"type": 2, "rad": (0.22, 0.22, 0.22), "t": (0.0, 0.4, 0.0)})
        created.append(noz.path())
        vel = geo.createNode("attribwrangle", "add_velocity")
        vel.setInput(0, noz)
        _set_parms(vel, {"class": 2})  # run over points
        spd = float(jet_speed)
        vp = vel.parm("snippet")
        if vp is not None:
            vp.set("v@v = set( (rand(@ptnum*1.7)-0.5)*1.5, %.4f, (rand(@ptnum*3.1)-0.5)*1.5 );" % spd)
        created.append(vel.path())
        fluid_geo = vel
        continuous = True  # a fountain is inherently continuous
    else:
        # 2. fluid shape (raised so it falls)
        src_type = _find_sop_type([source_shape, "sphere"])
        if not src_type:
            return {"success": False, "error": f"no source primitive type available ({source_shape})"}
        src = geo.createNode(src_type, f"fluid_{source_shape}")
        if src_type == "sphere":
            _set_parms(src, {"type": 2, "scale": 0.6, "ty": 3.0})
        else:
            _set_parms(src, {"ty": 3.0})
        created.append(src.path())
        sub = geo.createNode("subdivide", "subdivide") if _find_sop_type(["subdivide"]) else None
        if sub:
            sub.setInput(0, src)
            created.append(sub.path())
        fluid_geo = sub or src

    # 3. flipboundary = the real source: container 0/1/2 threaded + geometry on input 3
    b_type = _find_sop_type(["flipboundary", "flipboundary::2.0"])
    if not b_type:
        return {"success": False, "error": "FLIP Boundary ('flipboundary') not available", "created": created}
    source = geo.createNode(b_type, "source")
    source.setInput(0, tank, 0)
    source.setInput(1, tank, 1)
    source.setInput(2, tank, 2)
    source.setInput(3, fluid_geo, 0)
    ap = source.parm("activate")
    if ap is not None:
        if continuous:
            ap.set(1)
        else:
            ap.setExpression("$F==1")  # one-shot fill at frame 1
    created.append(source.path())

    # 4. FLIP solver reads the boundary's 3 outputs
    solver_type = _find_sop_type(["flipsolver", "flipsolver::2.0"])
    if not solver_type:
        return {"success": False, "error": "FLIP Solver ('flipsolver') not available", "created": created}
    solver = geo.createNode(solver_type, "flipsolver1")
    solver.setInput(0, source, 0)
    solver.setInput(1, source, 1)
    solver.setInput(2, source, 2)
    _set_parms(solver, {"doreseeding": 0, "donarrowband": 0})
    if ground:
        _set_parms(solver, {"useground": "ground", "ground_posy": 0.0 if fountain else -2.0})
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
        "mode": "fountain/jet" if fountain else ("continuous" if continuous else "one-shot drop"),
        "container": geo.path(),
        "solver": solver.path(),
        "created_nodes": created,
        "frame_range": frame_range,
        "solver_errors": errs,
        "warnings": warnings,
        "message": (
            f"Built FLIP liquid sim in {geo.path()} ({'continuous' if continuous else 'one-shot drop'}). "
            f"Display flag on {solver.path()}. Go to frame 1 and press Play to simulate."
            + (f" ⚠ solver errors: {errs}" if errs else "")
        ),
    }
