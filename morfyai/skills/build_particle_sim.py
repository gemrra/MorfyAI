# -*- coding: utf-8 -*-
"""Particle (POP) simulation builder skill (H20+ SOP-level POP Solver).

Builds a complete particle setup from one call:
    emitter primitive -> POP Source -> POP Solver

Deterministic Python wiring; node types and parm names resolved/guarded at
runtime. The SOP-level POP Solver was introduced in Houdini 20.
"""

SKILL_INFO = {
    "name": "build_particle_sim",
    "description": (
        "Build a complete particle (POP) simulation from one call. Creates a geo container with: "
        "emitter primitive -> POP Source -> POP Solver (SOP level), sets the playback range, turns on the "
        "display flag, and returns the created node paths. "
        "Use when the user asks to set up / build a particle, POP, points emitter, or sparks/dust sim."
    ),
    "parameters": {
        "container_name": {
            "type": "string",
            "description": "Name of the /obj geo container to create",
            "default": "particle_sim",
        },
        "emitter_shape": {
            "type": "string",
            "description": "Primitive particles are emitted from",
            "enum": ["grid", "sphere", "box", "torus"],
            "default": "grid",
        },
        "rate": {
            "type": "number",
            "description": "Particle birth rate (particles per second)",
            "default": 1000.0,
        },
        "life": {
            "type": "number",
            "description": "Particle life expectancy in seconds",
            "default": 3.0,
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


def run(container_name="particle_sim", emitter_shape="grid",
        rate=1000.0, life=3.0, duration_seconds=4.0):
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

    # 2. emitter primitive (raised so particles fall)
    emit_type = _find_sop_type([emitter_shape, "grid"])
    if not emit_type:
        return {"success": False, "error": f"no emitter primitive type available ({emitter_shape})"}
    emitter = geo.createNode(emit_type, f"emitter_{emitter_shape}")
    if emit_type == "grid":
        _set_parms(emitter, {"sizex": 4.0, "sizey": 4.0, "size": (4.0, 4.0),
                             "t": (0.0, 3.0, 0.0), "orient": 0})
    elif emit_type == "sphere":
        _set_parms(emitter, {"type": 2, "t": (0.0, 3.0, 0.0)})
    else:
        _set_parms(emitter, {"t": (0.0, 3.0, 0.0)})
    created.append(emitter.path())

    # 3. POP Source
    popsrc_type = _find_sop_type(["popsource", "popsource::2.0"])
    upstream = emitter
    if popsrc_type:
        popsrc = geo.createNode(popsrc_type, "popsource1")
        popsrc.setInput(0, emitter)
        _set_parms(popsrc, {"const_birthrate": float(rate), "birthrate": float(rate),
                            "rate": float(rate),
                            "life": float(life), "lifespan": float(life),
                            "life_expectancy": float(life)})
        created.append(popsrc.path())
        upstream = popsrc
    else:
        warnings.append("POP Source ('popsource') not found — wiring solver directly to the emitter")

    # 4. POP Solver (SOP level)
    solver_type = _find_sop_type(["popsolver", "popsolver::2.0"])
    if not solver_type:
        return {"success": False,
                "error": "POP Solver SOP ('popsolver') not available — needs Houdini 20+",
                "created": created, "warnings": warnings}
    solver = geo.createNode(solver_type, "popsolver1")
    solver.setInput(0, upstream)
    created.append(solver.path())

    # 5. display + layout + frame range
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
        "created_nodes": created,
        "frame_range": frame_range,
        "warnings": warnings,
        "message": (
            f"Built particle (POP) sim in {geo.path()}. "
            f"Display flag on {solver.path()} — press play to cook."
        ),
    }
