# -*- coding: utf-8 -*-
"""KineFX posing skill (H18.5+ Rig Pose; H19.0+ Full Body IK).

Appends posing controls downstream of a skeleton:

    skeleton ──► Rig Pose (FK) ──► [optional Full Body IK] ──► posed skeleton

Rig Pose is interactive (viewport handles), but its per-joint transforms are
stored in ordered `transforms*` multiparm parameters, so a pose can ALSO be
set fully procedurally — which is exactly what the 'test pose' does: rotate a
named joint so a skinning check has something visible to deform.

Use the posed output as Joint Deform's animated-pose (3rd) input, keeping the
upstream skeleton as the rest/capture pose (2nd input).
"""

SKILL_INFO = {
    "name": "build_rig_pose",
    "hidden": True,  # fronted by build_rig (rig_type='pose')
    "description": (
        "Add posing to a KineFX skeleton. Appends a Rig Pose (FK) node — and optionally a Full "
        "Body IK solver — downstream of the skeleton, and can apply a TEST POSE by rotating a "
        "named joint (e.g. bend an arm 45 deg) purely through parameters, no viewport interaction "
        "needed. The posed output is what you wire into Joint Deform's animated (3rd) input when "
        "verifying skinning. Use when the user asks to pose, animate, FK/IK, bend a limb, or do a "
        "deformation test. After applying a test pose on a skinned character, capture the viewport "
        "to visually check the deformation quality."
    ),
    "parameters": {
        "skeleton_path": {
            "type": "string",
            "description": "Path to the KineFX skeleton to pose (e.g. the orientjoints output "
                           "from build_rig_skeleton). The pose chain is appended in the same "
                           "geo container.",
            "default": "",
        },
        "use_ik": {
            "type": "boolean",
            "description": "Append a Full Body IK solver after the Rig Pose (H19+). Best with "
                           "the standard biped joint naming from build_rig_skeleton.",
            "default": False,
        },
        "test_joint": {
            "type": "string",
            "description": "OPTIONAL joint name to rotate as a test pose (e.g. 'l_forearm'). "
                           "Leave empty for no test pose.",
            "default": "",
        },
        "test_rotate": {
            "type": "string",
            "description": "Rotation in degrees as 'rx,ry,rz' applied to test_joint "
                           "(e.g. '0,0,-45' bends a left arm downward). Default '0,0,-45'.",
            "default": "0,0,-45",
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


def _parse_vec3(text, default=(0.0, 0.0, -45.0)):
    try:
        parts = [float(x) for x in str(text).split(",")]
        if len(parts) == 3:
            return tuple(parts)
    except Exception:
        pass
    return default


def run(skeleton_path="", use_ik=False, test_joint="", test_rotate="0,0,-45"):
    import hou  # type: ignore

    warnings = []
    created = []

    if not skeleton_path:
        return {"success": False, "error": "skeleton_path is required"}

    src = hou.node(skeleton_path)
    if src is None:
        return {"success": False, "error": f"skeleton_path '{skeleton_path}' not found"}

    # allow passing a geo container: pose its display SOP
    if src.type().category() != hou.sopNodeTypeCategory():
        try:
            disp = src.displayNode()
        except Exception:
            disp = None
        if disp is None:
            return {"success": False,
                    "error": f"'{skeleton_path}' has no displayable SOP to pose"}
        src = disp

    geo = src.parent()
    upstream = src

    # 1. Rig Pose (FK)
    rp_type = _find_sop_type(["kinefx--rigpose", "rigpose"])
    if not rp_type:
        return {"success": False,
                "error": "Rig Pose SOP ('kinefx--rigpose') not available in this build"}
    rp = geo.createNode(rp_type, "rigpose1")
    rp.setInput(0, upstream)
    created.append(rp.path())
    upstream = rp

    # 2. optional test pose via the transforms multiparm
    posed_joint = None
    if test_joint:
        rot = _parse_vec3(test_rotate)
        applied = False
        # Rig Pose stores per-joint transforms in an ordered multiparm
        # (transforms1group / transforms1name / transforms1r ...). Parm names
        # vary slightly across versions, so we probe a couple of conventions.
        for base in ("transforms", "xforms"):
            try:
                count_p = rp.parm(base)
                if count_p is None:
                    continue
                idx = int(count_p.eval()) + 1
                _set_parms(rp, {
                    "%s%dgroup" % (base, idx): test_joint,
                    "%s%dname" % (base, idx): test_joint,
                    "%s%dr" % (base, idx): rot,
                })
                count_p.set(idx)
                applied = True
                break
            except Exception:
                continue
        if applied:
            posed_joint = test_joint
        else:
            warnings.append(
                "Could not set the test pose procedurally (Rig Pose multiparm layout not "
                "recognized in this Houdini version). The Rig Pose node is still in place — "
                "pose it in the viewport, or set its per-joint transform parameters manually.")

    # 3. optional Full Body IK
    ik = None
    if use_ik:
        ik_type = _find_sop_type(["kinefx--fullbodyik", "fullbodyik"])
        if ik_type:
            ik = geo.createNode(ik_type, "fullbodyik1")
            ik.setInput(0, upstream)
            created.append(ik.path())
            upstream = ik
        else:
            warnings.append("Full Body IK SOP not available (needs H19+) — FK only")

    try:
        upstream.setDisplayFlag(True)
        if hasattr(upstream, "setRenderFlag"):
            upstream.setRenderFlag(True)
    except Exception as e:
        warnings.append(f"display flag failed: {e}")

    try:
        geo.layoutChildren()
    except Exception:
        pass

    return {
        "success": True,
        "container": geo.path(),
        "rigpose_node": rp.path(),
        "ik_node": ik.path() if ik else None,
        "posed_output": upstream.path(),
        "posed_joint": posed_joint,
        "created_nodes": created,
        "warnings": warnings,
        "message": (
            f"Posing chain ready: {rp.path()}"
            + (f" (+ Full Body IK {ik.path()})" if ik else "")
            + (f"; test pose applied to '{posed_joint}'" if posed_joint else "")
            + f". Posed output: {upstream.path()} — wire it into Joint Deform's animated (3rd) "
            f"input for a deformation check, then capture the viewport to verify visually."
        ),
    }
