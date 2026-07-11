# -*- coding: utf-8 -*-
"""Create a camera framed on a target's geometry.

Mutating — adds a camera to /obj.
"""

SKILL_INFO = {
    "name": "setup_camera",
    "description": (
        "Create a camera in /obj positioned to frame a target's geometry — fits the whole bounding box "
        "in view, looking down -Z. Use to get a quick, usable camera on a build before rendering. Adjust "
        "the camera's rotation afterwards for other angles."
    ),
    "parameters": {
        "target": {
            "type": "string",
            "description": "Path of a SOP node (or object) whose geometry to frame, e.g. '/obj/box1/OUT'.",
            "required": True,
        },
        "name": {"type": "string", "description": "Camera node name.", "default": "cam1"},
        "margin": {
            "type": "number",
            "description": "Framing margin multiplier (1.0 = tight, 1.5 = looser).",
            "default": 1.4,
        },
    },
}


def run(target="", name="cam1", margin=1.4):
    import hou  # type: ignore

    node = hou.node(target or "")
    if node is None:
        return {"success": False, "error": f"target node not found: {target}"}

    geo = None
    try:
        geo = node.geometry()
    except Exception:
        geo = None
    if geo is None:
        try:
            disp = node.displayNode()
            geo = disp.geometry() if disp else None
        except Exception:
            geo = None
    if geo is None:
        return {"success": False,
                "error": "could not read geometry from target (need a SOP, or an object with a display SOP)"}

    bbox = geo.boundingBox()
    center = bbox.center()
    size = bbox.sizevec()

    # World transform of the containing object (SOP geometry is object-local).
    obj = node
    try:
        while obj is not None and obj.type().category().name() != "Object":
            obj = obj.parent()
        xform = obj.worldTransform() if obj is not None else hou.hmath.identityTransform()
    except Exception:
        xform = hou.hmath.identityTransform()
    wc = center * xform

    maxdim = max(size) if max(size) > 0 else 1.0
    dist = maxdim * 2.2 * float(margin) + 1.0

    cam = hou.node("/obj").createNode("cam", node_name=name)
    try:
        cam.parmTuple("t").set((wc[0], wc[1], wc[2] + dist))
        cam.parmTuple("r").set((0, 0, 0))
    except Exception:
        pass
    try:
        cam.moveToGoodPosition()
    except Exception:
        pass

    return {
        "success": True,
        "node": cam.path(),
        "framed": node.path(),
        "look_at": [round(wc[0], 3), round(wc[1], 3), round(wc[2], 3)],
        "distance": round(dist, 3),
        "verdict": (f"Camera {cam.path()} placed to frame {node.path()} (looking down -Z). "
                    "Rotate it around the subject for other angles."),
    }
