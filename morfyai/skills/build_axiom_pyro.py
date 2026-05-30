# -*- coding: utf-8 -*-
"""Curated recipe: Axiom GPU pyro (third-party plugin by Theory Accelerated).

Auto-disables with a clear message if Axiom is not installed. When present,
drops an Axiom Solver fed from a source primitive (+ native Pyro Source for
fields when available) so the user gets a GPU pyro setup from one prompt.

Because Axiom's exact node names/params vary by version, this is a thin,
defensive wrapper — it recommends inspect_node_type('axiom...') for fine
parameter control. Verify wiring in Houdini.
"""

SKILL_INFO = {
    "name": "build_axiom_pyro",
    "description": (
        "Build a GPU pyro/fire/smoke setup using the Axiom plugin (Theory Accelerated), if installed. "
        "Creates a source primitive feeding an Axiom Solver. Auto-disables with a clear message if Axiom "
        "is not installed. Use when the user asks for Axiom pyro, or fast/GPU smoke/fire and Axiom is available."
    ),
    "parameters": {
        "container_name": {"type": "string", "description": "Name of the /obj geo container", "default": "axiom_pyro"},
        "source_shape": {"type": "string", "enum": ["sphere", "box", "torus"], "description": "Emission primitive", "default": "sphere"},
        "duration_seconds": {"type": "number", "description": "Simulation length in seconds", "default": 4.0},
    },
}


def _find_type_any(candidates=None, keywords=None):
    """Find a node type across SOP/OBJ/DOP categories by exact candidate or keyword."""
    import hou  # type: ignore
    cats = []
    for fn in (hou.sopNodeTypeCategory, hou.objNodeTypeCategory, hou.dopNodeTypeCategory):
        try:
            cats.append(fn())
        except Exception:
            continue
    candidates = candidates or []
    keywords = keywords or []
    # exact candidates first
    for cat in cats:
        try:
            types = cat.nodeTypes()
        except Exception:
            continue
        for c in candidates:
            if c in types:
                return c, types[c].category().name()
    # keyword match (handles namespaced names like axiom::axiom_solver)
    for cat in cats:
        try:
            types = cat.nodeTypes()
        except Exception:
            continue
        for name in types:
            nl = name.lower()
            if all(k in nl for k in keywords) and keywords:
                return name, types[name].category().name()
    return None, None


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


def run(container_name="axiom_pyro", source_shape="sphere", duration_seconds=4.0):
    import hou  # type: ignore

    # guard: is Axiom installed?
    solver_type, _cat = _find_type_any(
        candidates=["axiom_solver", "axiom::axiom_solver", "axiomsolver"],
        keywords=["axiom", "solver"],
    )
    if not solver_type:
        return {"success": False, "plugin": "Axiom", "installed": False,
                "error": "Axiom plugin not installed (no axiom solver node found). "
                         "Install Axiom (Theory Accelerated), or use build_pyro_sim for native pyro."}

    obj = hou.node("/obj")
    if obj is None:
        return {"success": False, "error": "/obj context not found"}

    warnings = ["Axiom node names/params vary by version — verify wiring and run "
                "inspect_node_type('axiom') for exact parameters."]
    created = []
    try:
        geo = obj.createNode("geo", container_name)
    except Exception as e:
        return {"success": False, "error": f"failed to create container: {e}"}
    created.append(geo.path())

    # source primitive (small emitter)
    src_type = None
    try:
        if source_shape in hou.sopNodeTypeCategory().nodeTypes():
            src_type = source_shape
    except Exception:
        pass
    src = geo.createNode(src_type or "sphere", f"source_{source_shape}")
    if (src_type or "sphere") == "sphere":
        _set_parms(src, {"scale": 0.3, "type": 2})
    created.append(src.path())

    upstream = src
    # native Pyro Source to author density/temperature fields (if present)
    try:
        if "pyrosource" in hou.sopNodeTypeCategory().nodeTypes():
            psrc = geo.createNode("pyrosource", "pyrosource1")
            psrc.setInput(0, src)
            created.append(psrc.path())
            upstream = psrc
    except Exception:
        pass

    # Axiom solver
    try:
        solver = geo.createNode(solver_type, "axiom_solver1")
    except Exception:
        # namespaced create may need exact name; retry raw
        solver = geo.createNode(solver_type.split("::")[-1], "axiom_solver1")
    try:
        solver.setInput(0, upstream)
    except Exception as e:
        warnings.append(f"could not wire source into Axiom solver input 0: {e}")
    created.append(solver.path())

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
        "success": True, "plugin": "Axiom", "installed": True,
        "container": geo.path(), "solver": solver.path(),
        "solver_type": solver_type, "created_nodes": created,
        "frame_range": frame_range, "warnings": warnings,
        "message": f"Built Axiom GPU pyro in {geo.path()} (solver: {solver_type}). Verify inputs, then play.",
    }
