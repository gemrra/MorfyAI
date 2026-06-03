# -*- coding: utf-8 -*-
"""Whitewater (foam/spray/bubbles) builder skill (H21).

Builds whitewater on top of an EXISTING FLIP simulation:
    <flip output> -> Whitewater Source -> Whitewater Solver

Whitewater is a post-process: it needs a FLIP sim's surface (SDF) and velocity
fields. Pass the path of the FLIP container/solver built earlier (e.g. via
build_flip_sim). Deterministic wiring; node types resolved/guarded at runtime.
Verified against SideFX H21 docs:
  whitewatersolver inputs: 0=Emission+Fluid Fields, 1=Container, 2=Collisions
  (all three come from the Whitewater Source outputs)
"""

SKILL_INFO = {
    "name": "build_whitewater",
    "description": (
        "Add whitewater (foam, spray, bubbles) on top of an EXISTING FLIP simulation. Creates a Whitewater "
        "Source + Whitewater Solver fed from the given FLIP node, sets the playback range, and turns on the "
        "display flag. Requires a FLIP sim to already exist (build_flip_sim first). "
        "Use when the user asks for foam/spray/whitewater on a liquid sim."
    ),
    "parameters": {
        "flip_path": {
            "type": "string",
            "description": "Path of the existing FLIP solver/container node to source whitewater from, e.g. /obj/flip_sim/flipsolver1",
            "required": True,
        },
        "scale": {
            "type": "number",
            "description": "Whitewater scale (smaller = more, finer particles). Default 0.1",
            "default": 0.1,
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


def run(flip_path, scale=0.1, duration_seconds=4.0):
    import hou  # type: ignore

    flip = hou.node(flip_path)
    if flip is None:
        return {"success": False, "error": f"FLIP node not found: {flip_path}. Build a FLIP sim first."}

    # build whitewater inside the same geo container as the FLIP node
    geo = flip.parent()
    if geo is None:
        return {"success": False, "error": f"cannot resolve parent network of {flip_path}"}

    warnings = []
    created = []

    # 1. Whitewater Source (reads FLIP surface + velocity)
    wsrc_type = _find_sop_type(["whitewatersource", "whitewatersource::2.0"])
    if not wsrc_type:
        return {"success": False,
                "error": "Whitewater Source ('whitewatersource') not available in this Houdini build"}
    wsrc = geo.createNode(wsrc_type, "whitewatersource1")
    # The FLIP solver exposes THREE outputs (Fluid Particles, Container, Collisions)
    # and the Whitewater Source has matching inputs (Liquid Simulation, Container,
    # Collisions, Extra Sources). Wiring ONLY input 0 leaves the source without the
    # Container — which carries the velocity/bounds fields whitewater emits from — so
    # it produces ZERO foam (verified: 0 particles vs non-zero once 1+2 are wired).
    # So thread all three FLIP outputs into the source's first three inputs.
    _wired = 0
    for _i in range(3):
        try:
            wsrc.setInput(_i, flip, _i)
            _wired += 1
        except Exception:
            if _i == 0:
                warnings.append("could not wire FLIP into whitewater source input 0 — "
                                "connect the FLIP Liquid Simulation/Container/Collisions manually")
    created.append(wsrc.path())
    if _wired < 3:
        warnings.append(f"only wired {_wired}/3 FLIP outputs into the Whitewater Source — the FLIP node "
                        "should be the flipsolver (it has Fluid Particles / Container / Collisions outputs).")

    # 2. Whitewater Solver (inputs 0/1/2 from the source outputs)
    wsolver_type = _find_sop_type(["whitewatersolver", "whitewatersolver::2.0"])
    if not wsolver_type:
        return {"success": False,
                "error": "Whitewater Solver ('whitewatersolver') not available in this Houdini build",
                "created": created, "warnings": warnings}
    wsolver = geo.createNode(wsolver_type, "whitewatersolver1")
    # source typically exposes: out0=emission+fluid fields, out1=container, out2=collisions
    for idx in range(3):
        try:
            wsolver.setInput(idx, wsrc, idx)
        except Exception:
            # fall back to feeding output 0 if the source has fewer outputs
            try:
                wsolver.setInput(idx, wsrc, 0)
            except Exception:
                pass
    _set_parms(wsolver, {"whitewaterscale": float(scale), "ww_scale": float(scale),
                         "scale": float(scale)})
    created.append(wsolver.path())

    # 3. display + layout + frame range
    try:
        wsolver.setDisplayFlag(True)
        if hasattr(wsolver, "setRenderFlag"):
            wsolver.setRenderFlag(True)
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
        "source": wsrc.path(),
        "solver": wsolver.path(),
        "flip_source": flip.path(),
        "created_nodes": created,
        "frame_range": frame_range,
        "warnings": warnings,
        "message": (
            f"Added whitewater in {geo.path()} from FLIP {flip.path()}. "
            f"Display flag on {wsolver.path()}. Verify source inputs, then play."
        ),
    }
