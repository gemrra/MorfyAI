# -*- coding: utf-8 -*-
"""Pyro simulation builder skill (H21 SOP-level Pyro Solver).

Correct, verified chain (SideFX docs):
    source primitive -> Pyro Source -> Volume Rasterize Attributes -> Pyro Solver

The Pyro Solver sources from NAMED VOLUMES (density/temperature/fuel), so the
Pyro Source points MUST be rasterized to VDBs first, and the solver's Sourcing
tab must be initialized (Initialize Smoke/Fire/Explosion) so it reads them.
Without those steps the sim is empty. This builder does both, then self-checks.
"""

SKILL_INFO = {
    "name": "build_pyro_sim",
    "description": (
        "Build a complete, working sparse Pyro (smoke/fire/explosion) simulation from one call. "
        "Chain: source -> Pyro Source -> Volume Rasterize Attributes -> Pyro Solver, with the solver's "
        "Initialize Smoke/Fire/Explosion run so it actually sources and renders. Sets the playback range, "
        "display flag, and reports any solver errors. "
        "Use when the user asks to set up / build a pyro, smoke, fire, or explosion sim."
    ),
    "parameters": {
        "container_name": {"type": "string", "description": "Name of the /obj geo container", "default": "pyro_sim"},
        "source_shape": {
            "type": "string", "description": "Primitive the pyro emits from",
            "enum": ["sphere", "box", "torus", "grid"], "default": "sphere",
        },
        "preset": {
            "type": "string", "description": "Pyro look: billowy smoke, fire, or a one-shot explosion",
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


def _press_button(node, keyword_sets):
    """Press the first button-like parm whose name/label matches ALL keywords in
    any set, trying sets in priority order.

    Returns (pressed_name_or_None, catalog) where catalog is a list of
    "name | label" for every button-like / init-like parm found — so if nothing
    matched we can see exactly what the node exposes and target it precisely.
    """
    import hou  # type: ignore
    try:
        parms = node.parms()
    except Exception:
        return None, []
    buttons = []   # (name_lower, label_lower, parm, display)
    catalog = []
    for p in parms:
        try:
            tmpl = p.parmTemplate()
            nm = p.name()
            lbl = ""
            try:
                lbl = tmpl.label() or ""
            except Exception:
                pass
            is_button = isinstance(tmpl, hou.ButtonParmTemplate)
            txt = (nm + " " + lbl).lower()
            # treat as candidate if it's a button OR clearly an init/setup control
            if is_button or any(k in txt for k in ("init", "setup", "explosion", "smoke", "fire")):
                buttons.append((nm.lower(), lbl.lower(), p))
                catalog.append(f"{nm} | {lbl}" + ("" if is_button else " (non-button)"))
        except Exception:
            continue
    for kws in keyword_sets:
        for nm, lbl, p in buttons:
            text = nm + " " + lbl
            if all(k in text for k in kws):
                try:
                    p.pressButton()
                    return p.name(), catalog
                except Exception:
                    continue
    return None, catalog


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
    """Best-effort error/warning read (no forced cook, so it can't hang)."""
    errs, warns = [], []
    try:
        errs = list(node.errors() or [])
    except Exception:
        pass
    try:
        warns = list(node.warnings() or [])
    except Exception:
        pass
    return errs, warns


def run(container_name="pyro_sim", source_shape="sphere", preset="smoke", duration_seconds=4.0):
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

    # 1. source primitive (small emitter)
    src_type = _find_sop_type([source_shape, "sphere"])
    if not src_type:
        return {"success": False, "error": f"no source primitive type available ({source_shape})"}
    src = geo.createNode(src_type, f"source_{source_shape}")
    if src_type == "sphere":
        _set_parms(src, {"scale": 0.3, "type": 2})
    created.append(src.path())

    # 2. Pyro Source (points with density/temperature/fuel attributes)
    pyrosrc_type = _find_sop_type(["pyrosource", "pyrosource::2.0"])
    if not pyrosrc_type:
        return {"success": False, "error": "Pyro Source ('pyrosource') not available", "created": created}
    pyrosrc = geo.createNode(pyrosrc_type, "pyrosource1")
    pyrosrc.setInput(0, src)
    created.append(pyrosrc.path())

    # 3. Volume Rasterize Attributes — turn the source points into named VDBs.
    #    This is REQUIRED: the Pyro Solver sources from volumes, not points.
    upstream = pyrosrc
    rast_type = _find_sop_type(["volumerasterizeattributes", "volumerasterizeattributes::2.0"])
    if rast_type:
        rast = geo.createNode(rast_type, "volumerasterize1")
        rast.setInput(0, pyrosrc)
        attribs = "density temperature" + (" fuel flame" if preset in ("fire", "explosion") else "")
        _set_parms(rast, {"attributes": attribs, "attriblist": attribs})
        created.append(rast.path())
        upstream = rast
    else:
        warnings.append("Volume Rasterize Attributes not found — pyro may not source correctly")

    # 4. Pyro Solver
    solver_type = _find_sop_type(["pyrosolver", "pyrosolver::2.0"])
    if not solver_type:
        return {"success": False, "error": "Pyro Solver ('pyrosolver') not available",
                "created": created, "warnings": warnings}
    solver = geo.createNode(solver_type, "pyrosolver1")
    solver.setInput(0, upstream)
    created.append(solver.path())

    # 5. Initialize the solver for the preset — this configures the fields AND
    #    populates the Sourcing tab from the incoming volumes (the step that makes
    #    it actually source). Press the matching button via introspection.
    init_kw = {"smoke": ("initialize", "smoke"), "fire": ("initialize", "fire"),
               "explosion": ("initialize", "explosion")}[preset]
    pressed, solver_buttons = _press_button(solver, [
        init_kw, (preset,),
        ("initialize", "source"), ("populate", "sourc"), ("initialize",), ("init",),
    ])
    if pressed:
        warnings.append(f"initialized solver via '{pressed}' button")
    else:
        warnings.append("could not auto-press an Initialize button — see solver_buttons for the exact "
                        "control names; press Initialize " + preset.title() + " manually meanwhile")

    # 6. display the SOLVER (shows the volume; bake nodes often don't preview)
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

    # 7. self-check
    errs, warns = _node_errors(solver)

    return {
        "success": True,
        "preset": preset,
        "container": geo.path(),
        "solver": solver.path(),
        "created_nodes": created,
        "frame_range": frame_range,
        "solver_errors": errs,
        "solver_warnings": warns,
        "solver_buttons": solver_buttons,
        "initialized": pressed,
        "warnings": warnings,
        "message": (
            f"Built {preset} pyro sim in {geo.path()}. Display flag on {solver.path()}. "
            + (f"Initialized via '{pressed}'. " if pressed
               else "NOT auto-initialized — solver_buttons lists the available controls. ")
            + "Go to frame 1 and press Play (pyro cooks sequentially)."
            + (f" ⚠ solver errors: {errs}" if errs else "")
        ),
    }
