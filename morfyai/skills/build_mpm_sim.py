# -*- coding: utf-8 -*-
"""MPM simulation builder skill (H21 Material Point Method).

Builds a complete MPM setup from one call:
    source primitive -> MPM Source ┐
    ground grid      -> MPM Collider┤-> MPM Solver
                        MPM Container┘  (container feeds all three)

Great for snow, sand, mud, jello, rubber, etc. Deterministic Python wiring;
node types and parameter names are resolved/guarded at runtime so it tolerates
version drift. Verified against SideFX H21 docs:
  mpmsolver inputs: 0=MPM Sources, 1=MPM Colliders, 2=MPM Container
  mpmsource inputs: 0=geometry to fill, 1=MPM Container
"""

SKILL_INFO = {
    "name": "build_mpm_sim",
    "description": (
        "Build a complete MPM (Material Point Method) simulation from one call — snow, sand, mud, jello, "
        "rubber, concrete, metal, honey, water, etc. Creates a geo container with MPM Source + MPM Container "
        "(+ optional ground MPM Collider) wired into an MPM Solver, sets the playback range, turns on the "
        "display flag, and returns the created node paths. "
        "Use when the user asks to set up / build an MPM sim or any granular/elastic/viscous material."
    ),
    "parameters": {
        "container_name": {
            "type": "string",
            "description": "Name of the /obj geo container to create",
            "default": "mpm_sim",
        },
        "material": {
            "type": "string",
            "description": "MPM material preset",
            "enum": ["snow", "sand", "mud", "jello", "rubber", "concrete",
                     "metal", "honey", "water", "soil"],
            "default": "snow",
        },
        "source_shape": {
            "type": "string",
            "description": "Primitive the material is created from",
            "enum": ["sphere", "box", "torus"],
            "default": "sphere",
        },
        "ground_collision": {
            "type": "boolean",
            "description": "Use the solver's built-in ground plane (floor at y=0). No extra nodes — the "
                           "MPM solver already provides this. Set False for no floor (free fall).",
            "default": True,
        },
        "collider_path": {
            "type": "string",
            "description": "OPTIONAL path to existing geometry (e.g. '/obj/bowl/OUT') to use as a CUSTOM "
                           "MPM collider — a wall, bowl, terrain, character, etc. Leave empty for just the "
                           "built-in ground. This is the 'pake collider ini' hook.",
            "default": "",
        },
        "initial_velocity": {
            "type": "array",
            "description": "Optional initial velocity [x, y, z] given to the material at birth — e.g. "
                           "[8, 2, 0] throws it sideways+up (a thrown snowball). Default [0,0,0] = just drops.",
            "items": {"type": "number"},
            "default": [0, 0, 0],
        },
        "resolution": {
            "type": "number",
            "description": "Particle separation on the MPM Container (smaller = higher detail, slower). "
                           "0 = auto (scaled to the object so snow has enough particles to read correctly).",
            "default": 0,
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


# Granular materials that collapse and PACK (vs elastic ones that spring back).
_GRANULAR = {"snow", "sand", "mud", "soil"}

# H21 MPM Source 'materialtype' (Behavior) menu tokens — VERIFIED live:
#   elastic / chunky / liquid / viscous / sandy
# Setting the right behavior is THE correctness lever (the dynamic 'materialpreset'
# menu is unreliable to set programmatically). materialtype accepts the token string.
_BEHAVIOR = {
    "snow": "chunky", "sand": "sandy", "soil": "sandy", "mud": "sandy",
    "jello": "elastic", "rubber": "elastic", "concrete": "elastic", "metal": "elastic",
    "honey": "viscous", "water": "liquid",
}

# Approximate real-world densities (kg/m^3) for a believable scale.
_DENSITY = {
    "snow": 400, "sand": 1600, "soil": 1500, "mud": 1400, "jello": 1000,
    "rubber": 1100, "concrete": 2400, "metal": 7800, "honey": 1400, "water": 1000,
}


def _auto_particle_sep(src_node, across=40):
    """Pick a particle separation that gives ~`across` particles over the source's
    largest dimension — scale-robust resolution.

    Resolution is THE lever for MPM snow reading correctly: too few particles and
    snow can't fracture/pack, so it behaves like a uniform jelly/pancake blob
    regardless of material values (per SideFX docs). Returns None on failure.
    """
    import hou  # type: ignore
    try:
        bb = src_node.geometry().boundingBox()
        size = max(bb.sizevec())
        if size and size > 0:
            sep = size / float(max(8, across))
            return max(0.01, min(0.2, sep))
    except Exception:
        pass
    return None


def _tune_snow_shape(node):
    """Make granular material HOLD its shape instead of collapsing flat (pancake).

    Per SideFX troubleshooting: raise Critical Compression / Critical Stretch to
    resist excessive compression and keep shape. We do NOT lower Young's modulus
    (E) — lowering it is what makes it deflate. Uses the exact verified param
    names and only nudges values that exist.
    """
    changed = {}
    # H21 verified parm names: criticalcompressionstretchx = Critical Compression,
    # criticalcompressionstretchy = Critical Stretch (old c_compress/c_stretch were wrong).
    for name, factor in (("criticalcompressionstretchx", 1.8),
                         ("criticalcompressionstretchy", 1.8)):
        try:
            p = node.parm(name)
            if p is not None:
                v = p.eval()
                if isinstance(v, (int, float)) and v > 0:
                    p.set(v * factor)
                    changed[name] = round(v * factor, 4)
        except Exception:
            continue
    return changed


def run(container_name="mpm_sim", material="snow", source_shape="sphere",
        ground_collision=True, collider_path="", initial_velocity=None,
        resolution=0, duration_seconds=4.0):
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

    # 2. MPM Container (defines resolution; feeds every MPM node)
    container_type = _find_sop_type(["mpmcontainer", "mpmcontainer::2.0"])
    if not container_type:
        return {"success": False,
                "error": "MPM Container ('mpmcontainer') not available — MPM needs Houdini 20.5+",
                "created": created}
    container = geo.createNode(container_type, "mpmcontainer1")
    created.append(container.path())

    # 3. source primitive (raised so it falls onto the ground)
    src_type = _find_sop_type([source_shape, "sphere"])
    if not src_type:
        return {"success": False, "error": f"no source primitive type available ({source_shape})"}
    src = geo.createNode(src_type, f"source_{source_shape}")
    if src_type == "sphere":
        _set_parms(src, {"type": 2, "t": (0.0, 3.0, 0.0)})
    else:
        _set_parms(src, {"t": (0.0, 3.0, 0.0)})
    created.append(src.path())

    # optional initial velocity (e.g. throw the material sideways). MPM reads the
    # source geometry's v@v as the birth velocity.
    iv = list(initial_velocity) if initial_velocity else [0.0, 0.0, 0.0]
    iv = (iv + [0.0, 0.0, 0.0])[:3]
    fill_geo = src
    if any(abs(float(c)) > 1e-6 for c in iv):
        vw = geo.createNode("attribwrangle", "throw_velocity")
        vw.setInput(0, src)
        _set_parms(vw, {"class": 2})  # points
        vp = vw.parm("snippet")
        if vp is not None:
            vp.set("v@v = set(%.5f, %.5f, %.5f);" % (float(iv[0]), float(iv[1]), float(iv[2])))
        created.append(vw.path())
        fill_geo = vw

    # resolution: auto-scale to the object so snow has enough particles to
    # fracture/pack (resolution is the #1 lever for snow look). 0 = auto.
    sep = float(resolution) if resolution and float(resolution) > 0 else _auto_particle_sep(src)
    if sep:
        _set_parms(container, {"particlesep": sep, "particle_separation": sep, "particlesize": sep})
    else:
        warnings.append("could not auto-compute particle separation — using node default")

    # 4. MPM Source
    mpmsrc_type = _find_sop_type(["mpmsource", "mpmsource::2.0"])
    if not mpmsrc_type:
        return {"success": False,
                "error": "MPM Source ('mpmsource') not available in this Houdini build",
                "created": created}
    mpmsrc = geo.createNode(mpmsrc_type, "mpmsource1")
    mpmsrc.setInput(0, fill_geo)
    mpmsrc.setInput(1, container)
    # Set the physical BEHAVIOR (materialtype) — the reliable correctness lever.
    behavior = _BEHAVIOR.get(material, "chunky")
    mat_applied = _set_parms(mpmsrc, {"materialtype": behavior})
    if not mat_applied:
        warnings.append(f"could not set materialtype='{behavior}' — set Behavior manually on the MPM Source")
    # Density for believable scale.
    dens = _DENSITY.get(material)
    if dens:
        _set_parms(mpmsrc, {"density": float(dens)})
    created.append(mpmsrc.path())

    # ★ Granular materials (snow/sand/mud): raise critical compression/stretch so
    #   they hold shape and don't collapse flat (do NOT lower stiffness E).
    if material in _GRANULAR:
        tuned = _tune_snow_shape(mpmsrc)
        if tuned:
            warnings.append(f"tuned {material} to hold shape (c_compress/c_stretch raised): {tuned}")

    # 5. CUSTOM MPM Collider — ONLY when the user supplies real collision geometry.
    #    The plain floor is the solver's built-in ground plane (set below), so we do
    #    NOT make a redundant grid+collider for the ground. mpmcollider is reserved
    #    for actual objects (a bowl, wall, terrain, character) via collider_path.
    collider = None
    if collider_path:
        coll_geo = hou.node(collider_path)
        coll_type = _find_sop_type(["mpmcollider", "mpmcollider::2.0"])
        if coll_geo is None:
            warnings.append(f"collider_path '{collider_path}' not found — skipping custom collider")
        elif not coll_type:
            warnings.append("MPM Collider ('mpmcollider') not available in this build — skipping custom collider")
        else:
            collider = geo.createNode(coll_type, "mpmcollider1")
            collider.setInput(0, coll_geo)
            try:
                collider.setInput(1, container)
            except Exception:
                pass
            created.append(collider.path())

    # 6. MPM Solver
    solver_type = _find_sop_type(["mpmsolver", "mpmsolver::2.0"])
    if not solver_type:
        return {"success": False,
                "error": "MPM Solver ('mpmsolver') not available in this Houdini build",
                "created": created, "warnings": warnings}
    solver = geo.createNode(solver_type, "mpmsolver1")
    solver.setInput(0, mpmsrc)
    if collider is not None:
        solver.setInput(1, collider)
    solver.setInput(2, container)
    created.append(solver.path())

    # ★ More substeps = stable MPM that isn't mushy (confirmed H21 parm names).
    _set_parms(solver, {"doglobalsubsteps": 1, "globalsubsteps": 6})

    # Built-in ground plane (solver default is ON). This IS the floor — verified
    # parm name 'groundactive'. Toggle it from ground_collision; no extra nodes.
    _set_parms(solver, {"groundactive": 1 if ground_collision else 0})
    if ground_collision and material in _GRANULAR:
        _set_parms(solver, {"groundfriction": 0.8})  # granular reads better with friction

    # 7. display + layout + frame range
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
        "material": material,
        "container": geo.path(),
        "solver": solver.path(),
        "created_nodes": created,
        "frame_range": frame_range,
        "warnings": warnings,
        "message": (
            f"Built MPM '{material}' sim in {geo.path()}. "
            f"Display flag on {solver.path()} — press play to cook."
        ),
    }
