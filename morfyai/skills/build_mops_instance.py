# -*- coding: utf-8 -*-
"""Curated recipe: MOPs Instancer (third-party motion-graphics plugin by toadstorm).

Auto-disables with a clear message if MOPs is not installed. When present,
sets up a MOPs Instancer that copies a template primitive onto a grid of
points — a classic motion-graphics starting point from one prompt.

MOPs node names vary slightly by version — defensive wrapper; use
inspect_node_type('mops') for exact ports/params. Verify wiring in Houdini.
"""

SKILL_INFO = {
    "name": "build_mops_instance",
    "description": (
        "Set up a MOPs Instancer (motion-graphics) that copies a template shape onto a grid of points, if "
        "the MOPs plugin (toadstorm) is installed. Auto-disables with a clear message if MOPs is not "
        "installed. Use when the user asks for MOPs / motion-graphics instancing / mograph-style copies."
    ),
    "parameters": {
        "container_name": {"type": "string", "description": "Name of the /obj geo container", "default": "mops_instance"},
        "template_shape": {"type": "string", "enum": ["box", "sphere", "torus"], "description": "Shape to instance", "default": "box"},
        "grid_size": {"type": "number", "description": "Size of the point grid to instance onto", "default": 10.0},
    },
}


def _find_type_any(candidates=None, keywords=None):
    import hou  # type: ignore
    cats = []
    for fn in (hou.sopNodeTypeCategory, hou.objNodeTypeCategory):
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


def _input_index_by_label(node, keywords):
    try:
        labels = node.inputLabels()
    except Exception:
        labels = ()
    for i, lab in enumerate(labels):
        if any(k in (lab or "").lower() for k in keywords):
            return i
    return None


def run(container_name="mops_instance", template_shape="box", grid_size=10.0):
    import hou  # type: ignore

    instancer_type = _find_type_any(
        candidates=["mops_instancer", "mops::instancer", "mopsinstancer"],
        keywords=["mops", "instanc"],
    )
    if not instancer_type:
        return {"success": False, "plugin": "MOPs", "installed": False,
                "error": "MOPs plugin not installed (no MOPs Instancer node found). "
                         "Install MOPs (motionoperators.com), or use native copytopoints instead."}

    obj = hou.node("/obj")
    if obj is None:
        return {"success": False, "error": "/obj context not found"}

    warnings = ["MOPs node ports/params vary by version — verify wiring and run "
                "inspect_node_type('mops') for exact details."]
    created = []
    try:
        geo = obj.createNode("geo", container_name)
    except Exception as e:
        return {"success": False, "error": f"failed to create container: {e}"}
    created.append(geo.path())

    # points to instance onto (a grid of points)
    grid = geo.createNode("grid", "points")
    _set_parms(grid, {"sizex": float(grid_size), "sizey": float(grid_size),
                      "size": (float(grid_size), float(grid_size)),
                      "rows": 10, "cols": 10, "orient": 0})
    created.append(grid.path())

    # template shape to instance
    tmpl = geo.createNode(template_shape if template_shape in ("box", "sphere", "torus") else "box",
                          f"template_{template_shape}")
    if template_shape == "sphere":
        _set_parms(tmpl, {"type": 2, "scale": 0.3})
    else:
        _set_parms(tmpl, {"scale": 0.3, "size": (0.3, 0.3, 0.3)})
    created.append(tmpl.path())

    # MOPs Instancer
    try:
        inst = geo.createNode(instancer_type, "mops_instancer1")
    except Exception:
        inst = geo.createNode(instancer_type.split("::")[-1], "mops_instancer1")
    created.append(inst.path())

    # wire: points -> input 0, template -> the "instance/template" input (by label, else 1)
    try:
        inst.setInput(0, grid)
    except Exception as e:
        warnings.append(f"could not wire points into MOPs Instancer input 0: {e}")
    tmpl_idx = _input_index_by_label(inst, ["template", "instance", "geometry", "shape"])
    if tmpl_idx is None or tmpl_idx == 0:
        tmpl_idx = 1
    try:
        inst.setInput(tmpl_idx, tmpl)
    except Exception as e:
        warnings.append(f"could not wire template into MOPs Instancer input {tmpl_idx}: {e}")

    try:
        inst.setDisplayFlag(True)
        if hasattr(inst, "setRenderFlag"):
            inst.setRenderFlag(True)
    except Exception:
        pass
    try:
        geo.layoutChildren()
    except Exception:
        pass

    return {
        "success": True, "plugin": "MOPs", "installed": True,
        "container": geo.path(), "instancer": inst.path(),
        "instancer_type": instancer_type, "created_nodes": created,
        "warnings": warnings,
        "message": f"Built MOPs instancer in {geo.path()} ({instancer_type}). Verify the template input, then tweak.",
    }
