# -*- coding: utf-8 -*-
"""Curated recipe: Paradigm GPU liquid (third-party plugin by Theory Accelerated).

Auto-disables with a clear message if Paradigm is not installed. When present,
drops a Paradigm liquid solver fed from a source primitive (+ optional ground)
for a GPU FLIP-style splash from one prompt.

Paradigm's exact node names/params vary by version — defensive wrapper; use
inspect_node_type('paradigm') for fine control. Verify wiring in Houdini.
"""

SKILL_INFO = {
    "name": "build_paradigm_liquid",
    "description": (
        "Build a GPU liquid/splash setup using the Paradigm plugin (Theory Accelerated), if installed. "
        "Creates a source primitive feeding a Paradigm solver (+ optional ground). Auto-disables with a "
        "clear message if Paradigm is not installed. Use when the user asks for Paradigm, or fast/GPU "
        "liquid and Paradigm is available."
    ),
    "parameters": {
        "container_name": {"type": "string", "description": "Name of the /obj geo container", "default": "paradigm_liquid"},
        "source_shape": {"type": "string", "enum": ["sphere", "box"], "description": "Initial fluid primitive", "default": "sphere"},
        "ground_collision": {"type": "boolean", "description": "Add a ground grid", "default": True},
        "duration_seconds": {"type": "number", "description": "Simulation length in seconds", "default": 4.0},
    },
}


def _find_type_any(candidates=None, keywords=None):
    import hou  # type: ignore
    cats = []
    for fn in (hou.sopNodeTypeCategory, hou.objNodeTypeCategory, hou.dopNodeTypeCategory):
        try:
            cats.append(fn())
        except Exception:
            continue
    candidates = candidates or []
    keywords = keywords or []
    for cat in cats:
        try:
            types = cat.nodeTypes()
        except Exception:
            continue
        for c in candidates:
            if c in types:
                return c
    for cat in cats:
        try:
            types = cat.nodeTypes()
        except Exception:
            continue
        for name in types:
            nl = name.lower()
            if keywords and all(k in nl for k in keywords):
                return name
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


def run(container_name="paradigm_liquid", source_shape="sphere",
        ground_collision=True, duration_seconds=4.0):
    import hou  # type: ignore

    solver_type = _find_type_any(
        candidates=["paradigm_solver", "paradigm::solver", "paradigmsolver"],
        keywords=["paradigm", "solver"],
    ) or _find_type_any(keywords=["paradigm"])
    if not solver_type:
        return {"success": False, "plugin": "Paradigm", "installed": False,
                "error": "Paradigm plugin not installed (no paradigm node found). "
                         "Install Paradigm (Theory Accelerated), or use build_flip_sim for native FLIP."}

    obj = hou.node("/obj")
    if obj is None:
        return {"success": False, "error": "/obj context not found"}

    warnings = ["Paradigm node names/params vary by version — verify wiring and run "
                "inspect_node_type('paradigm') for exact parameters."]
    created = []
    try:
        geo = obj.createNode("geo", container_name)
    except Exception as e:
        return {"success": False, "error": f"failed to create container: {e}"}
    created.append(geo.path())

    # source primitive (raised so it falls / splashes)
    src = geo.createNode(source_shape if source_shape in ("sphere", "box") else "sphere",
                         f"source_{source_shape}")
    if source_shape == "sphere":
        _set_parms(src, {"scale": 0.5, "type": 2, "t": (0.0, 2.0, 0.0)})
    else:
        _set_parms(src, {"t": (0.0, 2.0, 0.0)})
    created.append(src.path())

    # Paradigm solver
    try:
        solver = geo.createNode(solver_type, "paradigm_solver1")
    except Exception:
        solver = geo.createNode(solver_type.split("::")[-1], "paradigm_solver1")
    try:
        solver.setInput(0, src)
    except Exception as e:
        warnings.append(f"could not wire source into Paradigm solver input 0: {e}")
    created.append(solver.path())

    # optional ground via label-matched input
    if ground_collision:
        try:
            ground = geo.createNode("grid", "ground")
            _set_parms(ground, {"sizex": 10.0, "sizey": 10.0, "size": (10.0, 10.0), "orient": 0})
            created.append(ground.path())
            col_idx = None
            try:
                for i, lab in enumerate(solver.inputLabels() or []):
                    if any(k in (lab or "").lower() for k in ("collision", "collide", "ground", "static")):
                        col_idx = i
                        break
            except Exception:
                pass
            if col_idx is not None:
                solver.setInput(col_idx, ground)
            else:
                warnings.append("collision input not found on Paradigm solver — ground left unconnected")
        except Exception as e:
            warnings.append(f"ground setup failed: {e}")

    try:
        solver.setDisplayFlag(True)
        if hasattr(solver, "setRenderFlag"):
            solver.setRenderFlag(True)
    except Exception:
        pass
    try:
        geo.layoutChildren()
    except Exception:
        pass
    frame_range = _set_frame_range(duration_seconds)

    return {
        "success": True, "plugin": "Paradigm", "installed": True,
        "container": geo.path(), "solver": solver.path(),
        "solver_type": solver_type, "created_nodes": created,
        "frame_range": frame_range, "warnings": warnings,
        "message": f"Built Paradigm GPU liquid in {geo.path()} (solver: {solver_type}). Verify inputs, then play.",
    }
