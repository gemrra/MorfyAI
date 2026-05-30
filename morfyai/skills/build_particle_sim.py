# -*- coding: utf-8 -*-
"""Particle (POP) simulation builder skill (H21 DOP-level POP network).

In Houdini 21 the POP nodes live in the DOP context (there is no SOP-level
'popsolver'/'popsource'). This builds the canonical POP network and imports
the result back to SOPs for display — VERIFIED live:

    emitter -> scatter (points) ─┐
                                 │  (soppath)
    dopnet 'popnet':             ▼
        popobject ──► popsolver ──► output
        popsource ─(vel merge)─┘
        popforce  ─(vel merge)─┘   (gravity)
    dopimport  ◄── reads the sim back to SOPs (display)

The two non-obvious gotchas, both fixed here: the dopnet's 'output' node must
be wired to the solver (else the sim is empty), and a popforce supplies gravity
(particles otherwise hang in mid-air).
"""

SKILL_INFO = {
    "name": "build_particle_sim",
    "description": (
        "Build a complete particle (POP) simulation from one call — sparks, dust, debris, rain, swarm. "
        "Creates an emitter, a DOP POP network (popobject + popsolver + popsource + gravity), and a "
        "dopimport so the particles show at SOP level. Sets the playback range and display flag. "
        "Use when the user asks for a particle, POP, points emitter, sparks, dust, or debris sim."
    ),
    "parameters": {
        "container_name": {
            "type": "string",
            "description": "Name of the /obj geo container to create",
            "default": "particle_sim",
        },
        "emitter_shape": {
            "type": "string",
            "description": "Primitive particles are emitted from (scattered into points)",
            "enum": ["grid", "sphere", "box", "torus"],
            "default": "grid",
        },
        "rate": {
            "type": "number",
            "description": "Approx particle birth rate (particles per second)",
            "default": 3000.0,
        },
        "life": {
            "type": "number",
            "description": "Particle life expectancy in seconds",
            "default": 3.0,
        },
        "gravity": {
            "type": "boolean",
            "description": "Apply downward gravity so particles fall. False = they keep their birth motion.",
            "default": True,
        },
        "ground_collision": {
            "type": "boolean",
            "description": "Add a ground plane the particles land on and slide across (instead of falling forever).",
            "default": True,
        },
        "wind": {
            "type": "number",
            "description": "Wind strength — pushes particles sideways so they don't fall in a straight column. "
                           "0 = no wind, ~3 = a gentle breeze, 8+ = strong gusts.",
            "default": 3.0,
        },
        "wind_dir": {
            "type": "number",
            "description": "Wind direction in degrees (0 = +X). Particles drift this way.",
            "default": 25.0,
        },
        "turbulence": {
            "type": "number",
            "description": "Chaotic noise added to the motion so the stream breaks up naturally. "
                           "0 = none, ~0.5 = subtle (default), 1-2 = lively, 3+ = very turbulent.",
            "default": 0.5,
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


def _fps():
    import hou  # type: ignore
    try:
        return hou.fps() or 24.0
    except Exception:
        return 24.0


def _set_frame_range(duration_seconds):
    import hou  # type: ignore
    try:
        fps = _fps()
        end = int(round(1 + max(0.1, float(duration_seconds)) * fps))
        hou.playbar.setFrameRange(1, end)
        hou.playbar.setPlaybackRange(1, end)
        return [1, end]
    except Exception:
        return None


def run(container_name="particle_sim", emitter_shape="grid",
        rate=3000.0, life=3.0, gravity=True, ground_collision=True,
        wind=3.0, wind_dir=25.0, turbulence=0.5, duration_seconds=4.0):
    import hou  # type: ignore
    import math

    obj = hou.node("/obj")
    if obj is None:
        return {"success": False, "error": "/obj context not found"}

    warnings = []
    created = []
    fps = _fps()

    # 1. geo container
    try:
        geo = obj.createNode("geo", container_name)
    except Exception as e:
        return {"success": False, "error": f"failed to create container: {e}"}
    created.append(geo.path())

    # 2. emitter primitive (raised so particles fall through space)
    emit_type = _find_sop_type([emitter_shape, "grid"])
    if not emit_type:
        return {"success": False, "error": f"no emitter primitive type available ({emitter_shape})"}
    emitter = geo.createNode(emit_type, f"emitter_{emitter_shape}")
    if emit_type == "grid":
        # horizontal sheet up high (orient 'zx'); orient 0 would be a vertical wall
        _set_parms(emitter, {"sizex": 4.0, "sizey": 4.0, "size": (4.0, 4.0),
                             "t": (0.0, 5.0, 0.0), "orient": "zx"})
    elif emit_type == "sphere":
        _set_parms(emitter, {"type": 2, "t": (0.0, 5.0, 0.0)})
    else:
        _set_parms(emitter, {"t": (0.0, 5.0, 0.0)})
    created.append(emitter.path())

    # 2b. scatter to points the POP source emits from (emittype 'allpoint')
    upstream = emitter
    if _find_sop_type(["scatter"]):
        scatter = geo.createNode("scatter", "scatter")
        scatter.setInput(0, emitter)
        # allpoint births ~npts particles per frame; npts ≈ rate / fps
        npts = max(10, int(round(float(rate) / max(1.0, fps))))
        _set_parms(scatter, {"npts": npts, "forcetotal": 1})
        created.append(scatter.path())
        upstream = scatter

    # 3. DOP POP network
    if not _find_sop_type(["dopnet"]):
        return {"success": False, "error": "dopnet not available", "created": created}
    dopnet = geo.createNode("dopnet", "popnet")
    created.append(dopnet.path())

    try:
        import doptoolutils  # type: ignore
    except Exception as e:
        return {"success": False,
                "error": f"doptoolutils unavailable, cannot build POP network: {e}", "created": created}

    def _dop(type_candidates, name):
        for t in type_candidates:
            try:
                return dopnet.createNode(t, name)
            except Exception:
                continue
        return None

    popobj = _dop(["popobject"], "popobject1")
    popsolver = _dop(["popsolver::2.0", "popsolver"], "popsolver1")
    if popobj is None or popsolver is None:
        return {"success": False, "error": "POP DOP nodes (popobject/popsolver) not available",
                "created": created}
    try:
        doptoolutils.addObjectToSolver(popobj, popsolver, False)
    except Exception as e:
        warnings.append(f"addObjectToSolver failed: {e}")
        try:
            popsolver.setInput(0, popobj)
        except Exception:
            pass

    # 3b. POP source (emit from the scattered points)
    popsource = _dop(["popsource"], "popsource1")
    if popsource is None:
        return {"success": False, "error": "popsource DOP not available", "created": created}
    _set_parms(popsource, {"soppath": upstream.path(), "emittype": "allpoint",
                           "life": float(life) * fps, "constantrate": float(rate)})

    # source/force merge feeding the solver
    merge = None
    try:
        merge = doptoolutils.findOrCreateNamedMerge(popsolver, 'vel')
        merge.setNextInput(popsource)
    except Exception as e:
        warnings.append(f"source merge wiring failed: {e}")

    def _wire(node):
        try:
            if node is not None and merge is not None:
                merge.setNextInput(node)
        except Exception as e:
            warnings.append(f"wiring {node.name() if node else '?'} failed: {e}")

    # 3c. gravity + turbulence (one POP Force). Turbulence breaks up the straight column.
    #     NOTE: 'turb' is an int TOGGLE (0/1), not a strength — strength is 'amp'.
    if gravity or float(turbulence) > 0:
        popforce = _dop(["popforce"], "popforce1")
        if popforce is not None:
            _set_parms(popforce, {"force": (0.0, -9.81 if gravity else 0.0, 0.0)})
            if float(turbulence) > 0:
                _set_parms(popforce, {"turb": 1,                        # toggle ON
                                      "amp": 3.0 * float(turbulence),   # actual strength
                                      "swirlsize": 1.0})
            _wire(popforce)

    # 3d. wind — pushes particles sideways so they don't fall straight down
    if float(wind) > 0:
        popwind = _dop(["popwind"], "popwind1")
        if popwind is not None:
            rad = math.radians(float(wind_dir))
            _set_parms(popwind, {"windx": math.cos(rad), "windy": 0.0, "windz": math.sin(rad),
                                 "windspeed": float(wind), "airresist": 1.5})
            _wire(popwind)

    # 3e. ground collision — REAL collision response (not just detection).
    #     A 'groundplane' DOP is an infinite collider with bounce/friction. The key:
    #     it must feed the SOLVER's object input (merged with the popobject) so the
    #     solver sees it as a collider — merging it into the output does NOT collide.
    if ground_collision:
        groundplane = _dop(["groundplane"], "groundplane1")
        if groundplane is not None:
            _set_parms(groundplane, {"bounce": 0.2, "friction": 0.4})
            try:
                objmerge = dopnet.createNode("merge", "obj_merge")
                objmerge.setInput(0, popobj)
                objmerge.setInput(1, groundplane)
                popsolver.setInput(0, objmerge)   # solver now sees the ground collider
                _set_parms(popsolver, {"docollision": 1, "collisionresponse": "slide"})
            except Exception as e:
                warnings.append(f"ground collider wiring failed: {e}")

    # 3d. ★ wire the solver into the dopnet output (else the sim is empty)
    try:
        out_node = dopnet.node("output") or dopnet.createNode("output", "output")
        out_node.setInput(0, popsolver)
    except Exception as e:
        warnings.append(f"could not wire solver to dopnet output: {e}")
    try:
        dopnet.layoutChildren()
    except Exception:
        pass

    # 4. import the simulation back to SOPs for display
    solver_path = None
    if _find_sop_type(["dopimport"]):
        di = geo.createNode("dopimport", "import_particles")
        _set_parms(di, {"doppath": dopnet.path()})
        try:
            di.setDisplayFlag(True)
            if hasattr(di, "setRenderFlag"):
                di.setRenderFlag(True)
        except Exception:
            pass
        created.append(di.path())
        solver_path = di.path()
    else:
        warnings.append("dopimport not available — display the dopnet directly")
        solver_path = dopnet.path()

    try:
        geo.layoutChildren()
    except Exception:
        pass

    frame_range = _set_frame_range(duration_seconds)

    return {
        "success": True,
        "container": geo.path(),
        "solver": solver_path,
        "dopnet": dopnet.path(),
        "created_nodes": created,
        "frame_range": frame_range,
        "warnings": warnings,
        "message": (
            f"Built particle (POP) sim in {geo.path()}. "
            f"Display flag on {solver_path} — go to frame 1 and press Play. "
            "Particles emit from the scattered emitter and fall under gravity."
        ),
    }
