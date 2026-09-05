# -*- coding: utf-8 -*-
"""KineFX skinning/capture setup skill (H19.0+).

Wires a full bind from a skin mesh + a KineFX skeleton in one call:

    skin geometry ──► Joint Capture Proximity (or Biharmonic) ──► Joint Deform ──► OUT
    skeleton (rest) ───────┬────────────────────────┬───────────────────┘
                           └────────────────────────┘
                     (capture pose & animated pose inputs)

This is the modern KineFX pipeline — NOT the legacy object-level bones
workflow (Bone Capture Proximity / Bone Deform, which expect `cregion`
objects). Joint Deform takes THREE inputs (verified against SideFX docs):
  [0] skin geometry carrying the `boneCapture` point attribute (weights)
  [1] capture/rest pose skeleton  (points with `name` + `transform` + `P`)
  [2] animated pose skeleton      (same signature; falls back to rest)

Node types are resolved at runtime so it tolerates version drift.
"""

SKILL_INFO = {
    "name": "build_rig_skinning",
    "hidden": True,  # fronted by build_rig (rig_type='skinning')
    "description": (
        "Bind a character mesh to a KineFX skeleton (skinning). Creates the capture + deform "
        "chain inside the mesh's geo container: skin -> Joint Capture Proximity (or Joint Capture "
        "Biharmonic for higher-quality tet-based weights) -> Joint Deform, with the skeleton wired "
        "as capture/rest pose and animated pose. Use when the user asks to skin, bind, capture, or "
        "attach a mesh to a skeleton/rig. After binding, verify deformation visually: pose a limb "
        "with build_rig_pose and capture the viewport to check for candy-wrapper/collapse artifacts."
    ),
    "parameters": {
        "skin_path": {
            "type": "string",
            "description": "Path to the skin/character mesh node (SOP or its geo container). "
                           "The chain is built inside this container, downstream of this node.",
            "default": "",
        },
        "skeleton_path": {
            "type": "string",
            "description": "Path to the KineFX skeleton output (e.g. the orientjoints/rigdoctor "
                           "node from build_rig_skeleton). Wired as BOTH the rest/capture pose "
                           "and the animated pose unless animated_skeleton_path is given.",
            "default": "",
        },
        "animated_skeleton_path": {
            "type": "string",
            "description": "OPTIONAL separate animated skeleton (e.g. downstream of a Rig Pose). "
                           "Leave empty to reuse skeleton_path for both capture and anim inputs.",
            "default": "",
        },
        "method": {
            "type": "string",
            "description": "Weight computation method. 'proximity' = fast distance-based weights; "
                           "'biharmonic' = higher-quality smooth weights (slower, tet-mesh based, "
                           "best for organic characters)",
            "enum": ["proximity", "biharmonic"],
            "default": "proximity",
        },
        "max_influences": {
            "type": "integer",
            "description": "Max number of joints influencing each point (weight cap)",
            "default": 4,
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


def _resolve_geo_and_node(path):
    """Return (geo_container, node) — accepts a SOP path or a geo container path."""
    import hou  # type: ignore
    n = hou.node(path)
    if n is None:
        return None, None
    if n.type().category() == hou.sopNodeTypeCategory():
        return n.parent(), n
    # obj-level container: use its display SOP as the skin source
    try:
        disp = n.displayNode()
    except Exception:
        disp = None
    return n, disp


def run(skin_path="", skeleton_path="", animated_skeleton_path="",
        method="proximity", max_influences=4):
    import hou  # type: ignore

    warnings = []
    created = []

    if not skin_path:
        return {"success": False, "error": "skin_path is required (the character mesh)"}
    if not skeleton_path:
        return {"success": False, "error": "skeleton_path is required (the KineFX skeleton)"}

    geo, skin = _resolve_geo_and_node(skin_path)
    if geo is None or skin is None:
        return {"success": False,
                "error": f"skin_path '{skin_path}' not found or has no displayable geometry"}

    skeleton = hou.node(skeleton_path)
    if skeleton is None:
        return {"success": False,
                "error": f"skeleton_path '{skeleton_path}' not found"}

    anim = hou.node(animated_skeleton_path) if animated_skeleton_path else skeleton
    if animated_skeleton_path and anim is None:
        warnings.append(f"animated_skeleton_path '{animated_skeleton_path}' not found — "
                        f"reusing rest skeleton for the animated input")
        anim = skeleton

    # 1. capture weights
    if method == "biharmonic":
        cap_type = _find_sop_type(["kinefx--jointcapturebiharmonic",
                                   "jointcapturebiharmonic"])
        if cap_type is None:
            warnings.append("Joint Capture Biharmonic not available — falling back to proximity")
            method = "proximity"
    if method == "proximity":
        cap_type = _find_sop_type(["kinefx--jointcaptureproximity",
                                   "jointcaptureproximity"])
    if not cap_type:
        return {"success": False,
                "error": "No KineFX joint capture SOP available "
                         "('kinefx--jointcaptureproximity' / 'kinefx--jointcapturebiharmonic')"}

    cap = geo.createNode(cap_type, "capture_%s" % method)
    cap.setInput(0, skin)
    try:
        cap.setInput(1, skeleton)
    except Exception as e:
        warnings.append(f"could not wire skeleton into capture input 2: {e}")
    _set_parms(cap, {"maxinfluences": int(max_influences)})
    created.append(cap.path())

    # 2. joint deform — 3 inputs: skin+weights / capture pose / animated pose
    jd_type = _find_sop_type(["kinefx--jointdeform", "jointdeform"])
    if not jd_type:
        return {"success": False,
                "error": "Joint Deform SOP ('kinefx--jointdeform') not available in this build",
                "created": created, "warnings": warnings}
    jd = geo.createNode(jd_type, "jointdeform1")
    jd.setInput(0, cap)
    try:
        jd.setInput(1, skeleton)   # capture/rest pose
    except Exception as e:
        warnings.append(f"could not wire rest pose (input 2): {e}")
    try:
        jd.setInput(2, anim)       # animated pose
    except Exception as e:
        warnings.append(f"could not wire animated pose (input 3): {e}")
    created.append(jd.path())

    try:
        jd.setDisplayFlag(True)
        if hasattr(jd, "setRenderFlag"):
            jd.setRenderFlag(True)
    except Exception as e:
        warnings.append(f"display flag failed: {e}")

    try:
        geo.layoutChildren()
    except Exception:
        pass

    return {
        "success": True,
        "container": geo.path(),
        "capture_node": cap.path(),
        "deform_node": jd.path(),
        "method": method,
        "rest_skeleton": skeleton.path(),
        "animated_skeleton": anim.path(),
        "created_nodes": created,
        "warnings": warnings,
        "message": (
            f"Bound {skin.path()} to the skeleton with {method} weights; deforming through "
            f"{jd.path()}. To verify visually: pose a limb via build_rig_pose, then capture the "
            f"viewport and check the deformation (smooth bends, no candy-wrapper collapse, no "
            f"unbound verts left behind)."
        ),
    }
