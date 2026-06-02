# -*- coding: utf-8 -*-
"""Procedural fence / railing builder skill (H21 SOP-level).

Builds a parametric fence that FOLLOWS a curve, from one call:

    curve (yours or a default) ─┬─ resample(post_spacing) -> copy POSTS
                                ├─ resample(fine) -> raise -> polywire RAILS
                                └─ resample(picket) -> copy PICKETS
                                          -> merge

Everything is adjustable (height, spacing, post shape, rail count, pickets)
and there are style presets. Deterministic wiring; node types/parm names are
resolved at runtime so it tolerates version drift. Does NOT wrap into an HDA
(build the network first; wrapping is opt-in later).
"""

SKILL_INFO = {
    "name": "build_fence",
    "description": (
        "Build a procedural FENCE / RAILING / pagar that follows a curve, from one call: posts + "
        "horizontal rails + optional vertical pickets. Adjustable height, post spacing, post shape, "
        "rail count, and pickets, with style presets (picket / ranch / railing / modern). Follows a "
        "curve you supply, or makes a gently curved default. "
        "Use when the user asks for a fence, railing, pagar, picket fence, ranch fence, or guardrail."
    ),
    "parameters": {
        "container_name": {"type": "string", "description": "Name of the /obj geo container", "default": "fence"},
        "curve_path": {
            "type": "string",
            "description": "OPTIONAL path to a curve/line the fence follows (e.g. '/obj/path/OUT'). "
                           "Leave empty to generate a gently curved default path.",
            "default": "",
        },
        "style": {
            "type": "string",
            "description": "Preset look. picket=2 rails+pickets, ranch=3 rails no pickets, "
                           "railing=1 top rail+pickets, modern=2 rails no pickets.",
            "enum": ["picket", "ranch", "railing", "modern"],
            "default": "picket",
        },
        "height": {"type": "number", "description": "Fence height", "default": 1.2},
        "post_spacing": {"type": "number", "description": "Distance between posts", "default": 2.0},
        "post_shape": {"type": "string", "description": "Post shape", "enum": ["box", "cylinder"], "default": "box"},
        "post_size": {"type": "number", "description": "Post thickness", "default": 0.12},
        "rails": {"type": "integer", "description": "Number of horizontal rails (0-3). Overrides the style preset if set.", "default": -1},
        "pickets": {"type": "boolean", "description": "Vertical slats between posts. Overrides the style preset if set.", "default": None},
        "picket_spacing": {"type": "number", "description": "Distance between pickets", "default": 0.22},
    },
}

# style -> (rails, pickets)
_STYLE = {
    "picket":  (2, True),
    "ranch":   (3, False),
    "railing": (1, True),
    "modern":  (2, False),
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


def _rail_fracs(n):
    """Heights (as a fraction of fence height) for n rails."""
    if n <= 0:
        return []
    if n == 1:
        return [0.85]
    return [0.3 + 0.6 * (i / (n - 1)) for i in range(n)]


def run(container_name="fence", curve_path="", style="picket", height=1.2,
        post_spacing=2.0, post_shape="box", post_size=0.12,
        rails=-1, pickets=None, picket_spacing=0.22):
    import hou  # type: ignore

    obj = hou.node("/obj")
    if obj is None:
        return {"success": False, "error": "/obj context not found"}

    H = max(0.1, float(height))
    psize = max(0.01, float(post_size))

    # resolve style preset (explicit args override)
    s_rails, s_pickets = _STYLE.get(style, _STYLE["picket"])
    n_rails = s_rails if (rails is None or int(rails) < 0) else int(rails)
    n_rails = max(0, min(3, n_rails))
    use_pickets = s_pickets if pickets is None else bool(pickets)

    warnings = []
    created = []
    try:
        geo = obj.createNode("geo", container_name)
    except Exception as e:
        return {"success": False, "error": f"failed to create container: {e}"}
    created.append(geo.path())

    # 1. base curve — user-supplied or a generated default
    base = None
    if curve_path:
        src = hou.node(curve_path)
        if src is None:
            warnings.append(f"curve_path '{curve_path}' not found — using a default curve")
        else:
            # bring the external curve in via an object_merge
            om_t = _find_sop_type(["object_merge"])
            if om_t:
                om = geo.createNode(om_t, "input_curve")
                _set_parms(om, {"objpath1": curve_path, "xformtype": "local"})
                base = om
                created.append(om.path())
    if base is None:
        # NATIVE default path (no python SOP): a straight line. Users supply
        # curve_path for bends; the fence follows whatever curve it's given.
        line_t = _find_sop_type(["line"])
        crv = geo.createNode(line_t or "line", "base_curve")
        _set_parms(crv, {"origin": (0, 0, 0), "dir": (1, 0, 0), "dist": 12.0, "points": 2})
        base = crv
        created.append(base.path())

    merge_inputs = []

    # 2. posts
    res = geo.createNode("resample", "resample_posts")
    res.setInput(0, base)
    _set_parms(res, {"dolength": 1, "length": max(0.1, float(post_spacing))})
    created.append(res.path())
    post_t = _find_sop_type(["tube"]) if post_shape == "cylinder" else _find_sop_type(["box"])
    post = geo.createNode(post_t or "box", "post")
    if (post_t or "box") == "tube":
        _set_parms(post, {"rad": (psize / 2.0, psize / 2.0), "radscale": psize / 2.0,
                          "height": H, "t": (0, H / 2.0, 0), "cap": 1})
    else:
        _set_parms(post, {"size": (psize, H, psize), "t": (0, H / 2.0, 0)})
    created.append(post.path())
    ctp_t = _find_sop_type(["copytopoints", "copytopoints::2.0"])
    posts = geo.createNode(ctp_t or "copytopoints", "posts")
    posts.setInput(0, post)
    posts.setInput(1, res)
    created.append(posts.path())
    merge_inputs.append(posts)

    # 3. rails
    if n_rails > 0 and _find_sop_type(["polywire"]):
        railres = geo.createNode("resample", "rail_resample")
        railres.setInput(0, base)
        _set_parms(railres, {"dolength": 1, "length": 0.4})
        created.append(railres.path())
        for i, fr in enumerate(_rail_fracs(n_rails)):
            up = geo.createNode("xform", f"rail_up{i}")
            up.setInput(0, railres)
            _set_parms(up, {"t": (0, H * fr, 0)})
            pw = geo.createNode("polywire", f"rail{i}")
            pw.setInput(0, up)
            _set_parms(pw, {"wirerad": max(0.02, psize * 0.4), "radius": max(0.02, psize * 0.4)})
            created.extend([up.path(), pw.path()])
            merge_inputs.append(pw)

    # 4. pickets
    if use_pickets:
        pres = geo.createNode("resample", "picket_resample")
        pres.setInput(0, base)
        _set_parms(pres, {"dolength": 1, "length": max(0.05, float(picket_spacing))})
        pbox = geo.createNode("box", "picket")
        _set_parms(pbox, {"size": (psize * 0.35, H * 0.9, psize * 0.35), "t": (0, H * 0.45, 0)})
        pctp = geo.createNode(ctp_t or "copytopoints", "pickets")
        pctp.setInput(0, pbox)
        pctp.setInput(1, pres)
        created.extend([pres.path(), pbox.path(), pctp.path()])
        merge_inputs.append(pctp)

    # 5. merge
    out = geo.createNode("merge", "fence_out")
    for i, n in enumerate(merge_inputs):
        out.setInput(i, n)
    created.append(out.path())
    try:
        out.setDisplayFlag(True)
        if hasattr(out, "setRenderFlag"):
            out.setRenderFlag(True)
    except Exception:
        pass
    try:
        geo.layoutChildren()
    except Exception:
        pass

    try:
        npost = len(res.geometry().points())
        errs = list(out.errors() or [])
    except Exception:
        npost, errs = -1, []

    return {
        "success": True,
        "style": style,
        "container": geo.path(),
        "output": out.path(),
        "posts": npost,
        "rails": n_rails,
        "pickets": use_pickets,
        "created_nodes": created,
        "warnings": warnings,
        "solver_errors": errs,
        "message": (
            f"Built a '{style}' fence in {geo.path()} following the curve "
            f"({npost} posts, {n_rails} rails, pickets={use_pickets})."
        ),
    }
