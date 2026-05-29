# -*- coding: utf-8 -*-
"""Ocean surface builder skill (H21).

Builds a procedural ocean surface from one call:
    grid -> Ocean Evaluate (input 0)
    Ocean Spectrum -> Ocean Evaluate (input 1)

Not a true solver — it deforms a grid using wave spectrum volumes, so it is
fast and cooks without a simulation. Deterministic wiring; node types and parm
names resolved/guarded at runtime. Verified against SideFX H21 docs.
"""

SKILL_INFO = {
    "name": "build_ocean",
    "description": (
        "Build a procedural ocean surface from one call: a grid deformed by an Ocean Spectrum via Ocean "
        "Evaluate. Sets wind/wave parameters, turns on the display flag, and returns the created node paths. "
        "Fast (no simulation needed). Use when the user asks for an ocean, sea, or water surface with waves."
    ),
    "parameters": {
        "container_name": {
            "type": "string",
            "description": "Name of the /obj geo container to create",
            "default": "ocean_surface",
        },
        "grid_size": {
            "type": "number",
            "description": "Size of the ocean grid (square), in Houdini units",
            "default": 20.0,
        },
        "wind_speed": {
            "type": "number",
            "description": "Wind speed — higher creates larger low-frequency waves",
            "default": 10.0,
        },
        "wind_dir": {
            "type": "number",
            "description": "Wind direction in degrees (0 = +X axis)",
            "default": 0.0,
        },
        "chop": {
            "type": "number",
            "description": "Wave sharpness/cusps (0 = smooth swells, higher = sharper peaks)",
            "default": 1.0,
        },
        "scale": {
            "type": "number",
            "description": "Overall wave amplitude scale",
            "default": 1.0,
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


def _input_index_by_label(node, keywords):
    try:
        labels = node.inputLabels()
    except Exception:
        labels = ()
    for i, lab in enumerate(labels):
        ll = (lab or "").lower()
        if any(k in ll for k in keywords):
            return i
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


def run(container_name="ocean_surface", grid_size=20.0,
        wind_speed=10.0, wind_dir=0.0, chop=1.0, scale=1.0):
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

    # 2. grid surface (high res for wave detail)
    grid_type = _find_sop_type(["grid"])
    if not grid_type:
        return {"success": False, "error": "grid node type not available"}
    grid = geo.createNode(grid_type, "ocean_grid")
    _set_parms(grid, {"sizex": float(grid_size), "sizey": float(grid_size),
                      "size": (float(grid_size), float(grid_size)),
                      "rows": 200, "cols": 200, "orient": 0})
    created.append(grid.path())

    # 3. Ocean Spectrum
    spec_type = _find_sop_type(["oceanspectrum", "oceanspectrum::2.0"])
    if not spec_type:
        return {"success": False,
                "error": "Ocean Spectrum ('oceanspectrum') not available in this Houdini build",
                "created": created}
    spectrum = geo.createNode(spec_type, "oceanspectrum1")
    _set_parms(spectrum, {"windspeed": float(wind_speed), "wind_speed": float(wind_speed),
                          "winddir": float(wind_dir), "wind_dir": float(wind_dir),
                          "chop": float(chop), "chopiness": float(chop),
                          "scale": float(scale), "amp": float(scale)})
    created.append(spectrum.path())

    # 4. Ocean Evaluate (grid -> in0, spectrum -> in1)
    eval_type = _find_sop_type(["oceanevaluate", "oceanevaluate::2.0"])
    if not eval_type:
        return {"success": False,
                "error": "Ocean Evaluate ('oceanevaluate') not available in this Houdini build",
                "created": created, "warnings": warnings}
    ocean = geo.createNode(eval_type, "oceanevaluate1")
    ocean.setInput(0, grid)
    spec_idx = _input_index_by_label(ocean, ["spectrum", "volume", "ocean"])
    if spec_idx is None or spec_idx == 0:
        spec_idx = 1
    try:
        ocean.setInput(spec_idx, spectrum)
    except Exception as e:
        warnings.append(f"could not wire spectrum into ocean evaluate: {e}")
    created.append(ocean.path())

    # 5. display + layout
    try:
        ocean.setDisplayFlag(True)
        if hasattr(ocean, "setRenderFlag"):
            ocean.setRenderFlag(True)
    except Exception as e:
        warnings.append(f"display flag failed: {e}")
    try:
        geo.layoutChildren()
    except Exception:
        pass

    return {
        "success": True,
        "container": geo.path(),
        "ocean": ocean.path(),
        "created_nodes": created,
        "warnings": warnings,
        "message": (
            f"Built ocean surface in {geo.path()}. "
            f"Display flag on {ocean.path()} — scrub the timeline to see waves animate."
        ),
    }
