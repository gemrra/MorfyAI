# -*- coding: utf-8 -*-
"""Create an environment (dome) light, optionally driven by an HDRI.

Mutating — adds a light to /obj.
"""

SKILL_INFO = {
    "name": "setup_dome_light",
    "description": (
        "Create an environment/dome light in /obj that lights the whole scene from every direction. "
        "Optionally point it at an HDRI (.exr/.hdr) for image-based lighting. Use when a build needs "
        "lighting before rendering or look-dev."
    ),
    "parameters": {
        "hdri_path": {
            "type": "string",
            "description": "Path to an HDRI (.exr/.hdr) for image-based lighting. Leave empty for a plain white dome.",
            "default": "",
        },
        "intensity": {
            "type": "number",
            "description": "Light intensity multiplier.",
            "default": 1.0,
        },
        "name": {
            "type": "string",
            "description": "Name for the light node.",
            "default": "domelight",
        },
    },
}


def _apply(node, parms):
    missing = []
    for k, v in parms.items():
        p = node.parm(k) or node.parmTuple(k)
        if p is None:
            missing.append(k)
            continue
        try:
            p.set(v)
        except Exception:
            missing.append(k)
    return missing


def run(hdri_path="", intensity=1.0, name="domelight"):
    import hou  # type: ignore

    obj = hou.node("/obj")
    if obj is None:
        return {"success": False, "error": "/obj context not found"}
    try:
        light = obj.createNode("envlight", node_name=name)
    except Exception as e:
        return {"success": False, "error": f"could not create envlight: {e}"}

    parms = {"light_intensity": float(intensity)}
    if hdri_path:
        parms["env_map"] = hdri_path
    missing = _apply(light, parms)
    try:
        light.moveToGoodPosition()
    except Exception:
        pass

    import os
    warn = None
    if hdri_path and not os.path.exists(hdri_path):
        warn = f"HDRI path does not exist on disk: {hdri_path}"

    return {
        "success": True,
        "node": light.path(),
        "hdri": hdri_path or None,
        "intensity": intensity,
        "unset_parms": missing,
        "warning": warn,
        "verdict": (f"Dome light created at {light.path()}."
                    + (" HDRI applied." if hdri_path else " Plain white dome.")),
    }
