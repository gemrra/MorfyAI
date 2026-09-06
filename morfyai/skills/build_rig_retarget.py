# -*- coding: utf-8 -*-
"""KineFX animation retarget skill (H18.5+; full chain H19.0+).

Transfers animation from a SOURCE animated skeleton (e.g. imported
Mixamo/FBX mocap) onto a TARGET skeleton (e.g. the biped built by
build_rig_skeleton), following SideFX's documented core retarget workflow:

    target skel ─►[0] Rig Match Pose [1]◄─ source skel (animated)
        |  (match rest poses; Enable Match Bounds auto-scales/aligns)
    target out  ─►[0] Map Points     [1]◄─ source out
        |  (store per-joint source->target mapping by `name`)
    target out  ─►[0] Full Body IK   [1]◄─ source out  = retargeted skeleton
        |
    [optional] skin (with boneCapture weights) ─►[0] Joint Deform
        [1]=rest target skeleton, [2]=retargeted animated skeleton  = preview

The Map Points `Mappings` multiparm can be populated PROCEDURALLY by joint
name, so this skill ships a built-in Mixamo -> MorfyAI-biped map and can also
map by exact/common name matching. That removes the only interactive step.

Node types are resolved at runtime so it tolerates version drift.
"""

# MorfyAI biped joint  ->  Mixamo joint (mixamorig: prefix is stripped by many
# FBX imports; we try both with and without the prefix when wiring).
_MIXAMO_TO_BIPED = {
    "root":        "Hips",
    "pelvis":      "Hips",
    "spine_01":    "Spine",
    "spine_02":    "Spine1",
    "chest":       "Spine2",
    "neck":        "Neck",
    "head":        "Head",
    "head_end":    "HeadTop_End",
    "l_shoulder":  "LeftShoulder",
    "l_upperarm":  "LeftArm",
    "l_forearm":   "LeftForeArm",
    "l_hand":      "LeftHand",
    "r_shoulder":  "RightShoulder",
    "r_upperarm":  "RightArm",
    "r_forearm":   "RightForeArm",
    "r_hand":      "RightHand",
    "l_thigh":     "LeftUpLeg",
    "l_calf":      "LeftLeg",
    "l_foot":      "LeftFoot",
    "l_toe":       "LeftToeBase",
    "r_thigh":     "RightUpLeg",
    "r_calf":      "RightLeg",
    "r_foot":      "RightFoot",
    "r_toe":       "RightToeBase",
}

SKILL_INFO = {
    "name": "build_rig_retarget",
    "hidden": True,  # fronted by build_rig (rig_type='retarget')
    "description": (
        "Retarget animation from a source animated skeleton (Mixamo/FBX mocap) onto a target "
        "KineFX skeleton (e.g. a biped from build_rig skeleton). Builds the documented chain: "
        "Rig Match Pose (auto bounds-match) -> Map Points (per-joint name mapping) -> Full Body "
        "IK, and can drive a skinned mesh through Joint Deform as a live preview. Auto-maps the "
        "standard MorfyAI biped to Mixamo joint names out of the box; falls back to exact/common "
        "name matching for custom skeletons. Use when the user asks to retarget, transfer mocap/"
        "animation, or apply a Mixamo clip to their character. After retargeting, scrub the "
        "timeline and capture the viewport to visually verify the motion tracks the source."
    ),
    "parameters": {
        "target_skeleton_path": {
            "type": "string",
            "description": "Path to the TARGET skeleton (the one to animate — e.g. build_rig "
                           "skeleton's skeleton_output).",
            "default": "",
        },
        "source_skeleton_path": {
            "type": "string",
            "description": "Path to the SOURCE animated skeleton (mocap, e.g. from an imported "
                           "FBX — a SOP whose points are animated joints with a `name` attr).",
            "default": "",
        },
        "mapping_preset": {
            "type": "string",
            "description": "Joint name mapping: 'mixamo' uses the built-in Mixamo->biped table; "
                           "'name' maps joints whose names match exactly; 'none' leaves mapping "
                           "empty (user fills Map Points manually).",
            "enum": ["mixamo", "name", "none"],
            "default": "mixamo",
        },
        "skin_path": {
            "type": "string",
            "description": "OPTIONAL path to the skinned mesh (with boneCapture weights, e.g. "
                           "the capture node from build_rig skinning). When set, a Joint Deform "
                           "preview is appended so you SEE the character move.",
            "default": "",
        },
        "rest_skeleton_path": {
            "type": "string",
            "description": "OPTIONAL separate REST pose of the target skeleton for the Joint "
                           "Deform's capture (2nd) input. Defaults to target_skeleton_path.",
            "default": "",
        },
        "match_bounds": {
            "type": "boolean",
            "description": "Enable Rig Match Pose's bounding-box match to auto align/scale the "
                           "source to the target (handles different units/proportions).",
            "default": True,
        },
        "container_name": {
            "type": "string",
            "description": "Name for a NEW geo container to build the retarget chain in. If "
                           "empty, the chain is built inside the target skeleton's container.",
            "default": "",
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


def _as_sop(path):
    import hou  # type: ignore
    n = hou.node(path) if path else None
    if n is None:
        return None
    if n.type().category() == hou.sopNodeTypeCategory():
        return n
    try:
        return n.displayNode()
    except Exception:
        return None


def _joint_names(sop):
    """Return the set of joint names on a KineFX skeleton SOP (lowercased)."""
    names = set()
    try:
        g = sop.geometry()
        if g is not None and g.findPointAttrib("name") is not None:
            for pt in g.points():
                names.add((pt.attribValue("name") or "").lower())
    except Exception:
        pass
    return names


def _object_merge_into(container, source_sop, name):
    """Bring an external SOP's geometry into `container` via Object Merge."""
    import hou  # type: ignore
    om_type = _find_sop_type(["object_merge", "objectmerge"])
    om = container.createNode(om_type, name)
    _set_parms(om, {"objpath1": source_sop.path(), "xformtype": 1})
    return om


def _populate_mappings(map_node, mapping):
    """Fill the Map Points `Mappings` multiparm with target->source name pairs.

    Parm names vary slightly across versions, so probe a couple of conventions
    and report how many pairs were applied.
    """
    if not mapping:
        return 0
    # conventions: (count_parm, target_tpl, source_tpl)
    conventions = [
        ("mappings", "mappingstarget%d", "mappingssource%d"),
        ("mappings", "target%d", "source%d"),
        ("mapcount", "maptarget%d", "mapsource%d"),
    ]
    items = list(mapping.items())
    for count_name, t_tpl, s_tpl in conventions:
        try:
            count_p = map_node.parm(count_name)
            if count_p is None:
                continue
            applied = 0
            for i, (t, s) in enumerate(items, start=1):
                ok = False
                for tpl, val in ((t_tpl, t), (s_tpl, s)):
                    for cand in (tpl % i, tpl % (i - 1)):
                        try:
                            p = map_node.parm(cand)
                            if p is not None:
                                p.set(val)
                                ok = True
                                break
                        except Exception:
                            continue
                if ok:
                    applied += 1
            if applied:
                try:
                    count_p.set(len(items))
                except Exception:
                    pass
                return applied
        except Exception:
            continue
    return 0


def run(target_skeleton_path="", source_skeleton_path="", mapping_preset="mixamo",
        skin_path="", rest_skeleton_path="", match_bounds=True, container_name=""):
    import hou  # type: ignore

    warnings = []
    created = []

    target = _as_sop(target_skeleton_path)
    source = _as_sop(source_skeleton_path)
    if target is None:
        return {"success": False,
                "error": f"target_skeleton_path '{target_skeleton_path}' not found / not displayable"}
    if source is None:
        return {"success": False,
                "error": f"source_skeleton_path '{source_skeleton_path}' not found / not displayable"}

    # container for the chain
    obj = hou.node("/obj")
    if container_name:
        try:
            container = obj.createNode("geo", container_name)
            created.append(container.path())
        except Exception as e:
            return {"success": False, "error": f"failed to create container: {e}"}
        target_in = _object_merge_into(container, target, "target_skel")
        source_in = _object_merge_into(container, source, "source_skel")
        created += [target_in.path(), source_in.path()]
    else:
        container = target.parent()
        target_in = target
        # bring the (likely external) source in via Object Merge for a self-contained chain
        if source.parent() != container:
            source_in = _object_merge_into(container, source, "source_skel")
            created.append(source_in.path())
        else:
            source_in = source

    # 1. Rig Match Pose — conform rest poses; optional bounds match
    rmp_type = _find_sop_type(["kinefx--rigmatchpose", "rigmatchpose"])
    if not rmp_type:
        return {"success": False,
                "error": "Rig Match Pose SOP ('kinefx--rigmatchpose') not available",
                "created": created}
    rmp = container.createNode(rmp_type, "rigmatchpose1")
    rmp.setInput(0, target_in)
    rmp.setInput(1, source_in)
    if match_bounds:
        _set_parms(rmp, {"enablematchbounds": 1, "setpivotfrombounds": 1})
    created.append(rmp.path())

    # 2. Map Points — store the joint mapping (by name) on the target
    mp_type = _find_sop_type(["kinefx--mappoints", "mappoints"])
    if not mp_type:
        return {"success": False,
                "error": "Map Points SOP ('kinefx--mappoints') not available",
                "created": created}
    mappoints = container.createNode(mp_type, "mappoints1")
    # Map Points input 0 = target skeleton (to store mapping on), 1 = source
    try:
        mappoints.setInput(0, rmp, 0)
    except Exception:
        mappoints.setInput(0, target_in)
    try:
        mappoints.setInput(1, rmp, 1)
    except Exception:
        mappoints.setInput(1, source_in)
    _set_parms(mappoints, {"refattrib": "name"})
    created.append(mappoints.path())

    # build the actual mapping dict
    mapping = {}
    if mapping_preset == "mixamo":
        src_names = _joint_names(source_in)
        for tj, mj in _MIXAMO_TO_BIPED.items():
            for cand in (mj, "mixamorig:" + mj, "mixamorig_" + mj):
                if cand.lower() in src_names:
                    mapping[tj] = cand
                    break
        if not mapping:
            # source may already use plain Mixamo names without us reading them
            mapping = {tj: mj for tj, mj in _MIXAMO_TO_BIPED.items()}
            warnings.append("Could not read source joint names — applied the full Mixamo "
                            "map by name (verify in the Map Points node).")
    elif mapping_preset == "name":
        tgt_names = _joint_names(target_in)
        src_names = _joint_names(source_in)
        common = sorted(tgt_names & src_names)
        mapping = {n: n for n in common}
        if not mapping:
            warnings.append("No common joint names found between target and source — "
                            "mapping left empty (fill Map Points manually).")
    mapped_count = _populate_mappings(mappoints, mapping)
    if mapping and mapped_count == 0:
        warnings.append("Could not populate the Map Points multiparm procedurally in this "
                        "Houdini version — the chain is wired; set the Mappings in the Map "
                        "Points node (import/click) to complete the retarget.")

    # 3. Full Body IK — solve the retarget
    fbik_type = _find_sop_type(["kinefx--fullbodyik", "fullbodyik"])
    if not fbik_type:
        return {"success": False,
                "error": "Full Body IK SOP ('kinefx--fullbodyik') not available (needs H19+)",
                "created": created, "warnings": warnings}
    fbik = container.createNode(fbik_type, "retarget_fbik")
    try:
        fbik.setInput(0, mappoints, 0)   # target skeleton (with mapping)
    except Exception:
        fbik.setInput(0, mappoints)
    try:
        fbik.setInput(1, mappoints, 1)   # source animated skeleton
    except Exception:
        fbik.setInput(1, source_in)
    created.append(fbik.path())

    retargeted = fbik

    # 4. optional skinned preview via Joint Deform
    deform = None
    skin = _as_sop(skin_path) if skin_path else None
    if skin_path and skin is None:
        warnings.append(f"skin_path '{skin_path}' not found — preview skipped")
    if skin is not None:
        jd_type = _find_sop_type(["kinefx--jointdeform", "jointdeform"])
        if jd_type:
            rest = _as_sop(rest_skeleton_path) if rest_skeleton_path else target
            skin_in = _object_merge_into(container, skin, "skin_geo")
            rest_in = rest if rest.parent() == container else _object_merge_into(container, rest, "rest_skel")
            deform = container.createNode(jd_type, "retarget_preview")
            deform.setInput(0, skin_in)      # skin with weights
            try:
                deform.setInput(1, rest_in)  # rest/capture pose
            except Exception as e:
                warnings.append(f"could not wire rest pose: {e}")
            try:
                deform.setInput(2, retargeted)  # animated retargeted skeleton
            except Exception as e:
                warnings.append(f"could not wire animated pose: {e}")
            created += [skin_in.path(), deform.path()]
            if rest_in.path() not in created:
                created.append(rest_in.path())
        else:
            warnings.append("Joint Deform not available — retarget built but no skinned preview")

    display_node = deform if deform is not None else retargeted
    try:
        display_node.setDisplayFlag(True)
        if hasattr(display_node, "setRenderFlag"):
            display_node.setRenderFlag(True)
    except Exception as e:
        warnings.append(f"display flag failed: {e}")

    try:
        container.layoutChildren()
    except Exception:
        pass

    return {
        "success": True,
        "container": container.path(),
        "rig_match_pose": rmp.path(),
        "map_points": mappoints.path(),
        "retargeted_skeleton": retargeted.path(),
        "deform_node": deform.path() if deform else None,
        "display_node": display_node.path(),
        "mapping_preset": mapping_preset,
        "mapped_joints": len(mapping),
        "created_nodes": created,
        "warnings": warnings,
        "message": (
            f"Retarget chain built in {container.path()}: Rig Match Pose -> Map Points "
            f"({len(mapping)} joints mapped, {mapped_count} applied) -> Full Body IK"
            + (" -> Joint Deform preview." if deform else ".")
            + " Scrub the timeline and capture the viewport to verify the motion tracks the source."
        ),
    }
