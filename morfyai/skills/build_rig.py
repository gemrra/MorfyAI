# -*- coding: utf-8 -*-
"""Unified rigging builder — ONE skill that fronts the KineFX rig skills.

Consolidation entry point: the AI calls `skill__build_rig` with `rig_type`
and the relevant parameters; this dispatches to the verified per-task skill
(build_rig_skeleton / build_rig_skinning / build_rig_pose).

Design mirrors build_sim:
- Underlying skills keep their wiring logic untouched (and stay hidden).
- Only parameters the caller actually provides are forwarded, filtered
  against each skill's real `run()` signature.
- After a successful build, a DATA verification pass cooks the output and
  checks it actually produced joints/deformed geometry, so the AI always
  sees whether the rig really worked — and is told to follow up with the
  visual check (viewport capture / visual_check) for anything data can't
  judge (placement inside the mesh, proportions, deformation quality).
"""

# rig_type -> (underlying skill name, {unified_param: skill_param} rename map)
_DISPATCH = {
    "skeleton": ("build_rig_skeleton", {}),
    "skinning": ("build_rig_skinning", {}),
    "pose":     ("build_rig_pose",     {}),
    "retarget": ("build_rig_retarget", {}),
}

# common synonyms -> canonical rig_type
_ALIASES = {
    "bones": "skeleton", "joints": "skeleton", "rig": "skeleton",
    "skeletons": "skeleton",
    "skin": "skinning", "bind": "skinning", "binding": "skinning",
    "capture": "skinning", "weights": "skinning", "skinweights": "skinning",
    "fk": "pose", "ik": "pose", "animate": "pose", "posing": "pose",
    "testpose": "pose",
    "mocap": "retarget", "retargeting": "retarget", "mixamo": "retarget",
    "transferanimation": "retarget", "motioncapture": "retarget",
}


def _cook_report(node):
    """Cook a node and return counts/errors (cheap intrinsics)."""
    import hou  # type: ignore
    rep = {"node": node.path(), "points": 0, "prims": 0, "errors": [],
           "joints": 0, "produced": False}
    try:
        node.cook(force=True)
    except Exception:
        pass
    try:
        rep["errors"] = list(node.errors() or [])
    except Exception:
        pass
    try:
        g = node.geometry()
        if g is not None:
            rep["points"] = int(g.intrinsicValue("pointcount"))
            rep["prims"] = int(g.intrinsicValue("primitivecount"))
            # KineFX joints = points carrying a `name` point attribute
            try:
                if g.findPointAttrib("name") is not None:
                    rep["joints"] = rep["points"]
            except Exception:
                pass
    except Exception as e:
        if not rep["errors"]:
            rep["errors"] = [str(e)]
    rep["produced"] = rep["points"] > 0 or rep["prims"] > 0
    return rep


def _verify_rig(result, rig_type):
    """Data-level verification of the built rig (the visual check is separate)."""
    import hou  # type: ignore
    path = (result.get("skeleton_output") or result.get("posed_output")
            or result.get("retargeted_skeleton") or result.get("deform_node")
            or result.get("display_node"))
    node = hou.node(path) if path else None
    if node is None:
        return {"ok": None, "note": "no output node found to verify"}

    rep = _cook_report(node)
    ok = rep["produced"] and not rep["errors"]

    hints = []
    if rep["errors"]:
        hints.append(f"{len(rep['errors'])} node error(s) — fix wiring/inputs, then re-verify.")
    if not rep["produced"]:
        hints.append("EMPTY output — the rig produced no geometry (check the source mesh / "
                     "skeleton inputs are wired).")
    if rig_type == "skeleton" and rep["joints"] == 0:
        hints.append("No `name` point attribute found — output may not be a valid KineFX "
                     "skeleton (Rig Doctor missing?).")
    if rig_type == "skinning" and ok:
        hints.append("Bind looks structurally OK. Now VISUALLY verify deformation: pose a limb "
                     "(build_rig pose) and capture the viewport — check for candy-wrapper "
                     "collapse, unbound areas left behind, or mesh intersections.")
    if rig_type == "skeleton" and ok:
        hints.append("Skeleton built. VISUALLY verify it: capture the viewport and check the "
                     "joints sit INSIDE the character mesh with plausible proportions (head at "
                     "top, limbs at the right spots). The Visualize Rig node makes this easy.")
    if rig_type == "retarget" and ok:
        hints.append("Retarget built. VISUALLY verify it: scrub the timeline, capture the "
                     "viewport, and check the target mirrors the source motion (feet planted, "
                     "limbs not twisted/crossing). If joints don't move, the Map Points mapping "
                     "is likely empty or misnamed.")

    out = {"ok": ok, "node": rep["node"], "points": rep["points"],
           "prims": rep["prims"], "joints": rep["joints"],
           "errors": rep["errors"][:5]}
    if hints:
        out["hints"] = hints
    out["verdict"] = ("LOOKS OK (data-level). Do the visual check described in hints."
                      if ok else "NOT OK — fix the issue above and re-verify before claiming success.")
    return out


SKILL_INFO = {
    "name": "build_rig",
    "description": (
        "Build a complete KineFX rig from ONE call — the single entry point for character "
        "rigging. Set 'rig_type' and the few relevant params; each type deterministically "
        "creates AND wires every required node.\n"
        "rig_type guide:\n"
        "  skeleton -> joint chain / bones (biped, quadruped, or a simple chain). Optionally "
        "              fits proportions to an existing mesh and adds control shapes + a "
        "              Visualize Rig display node.\n"
        "  skinning -> bind/capture a mesh to a skeleton (Joint Capture Proximity/Biharmonic "
        "              -> Joint Deform).\n"
        "  pose     -> add Rig Pose (FK) and optional Full Body IK; can apply a TEST POSE by "
        "              rotating a named joint for deformation checks.\n"
        "  retarget -> transfer animation from a source skeleton (Mixamo/FBX mocap) onto a "
        "              target skeleton: Rig Match Pose -> Map Points -> Full Body IK, with "
        "              auto Mixamo->biped joint mapping and an optional skinned preview.\n"
        "Typical order: skeleton -> skinning -> pose; retarget after you have a target "
        "skeleton (and optionally a bound skin). After each step a data check runs "
        "automatically; follow it with a VIEWPORT capture (or the visual_check skill) — rig "
        "correctness is mostly visual (joints inside the mesh? smooth deformation? motion "
        "tracking the source?)."
    ),
    "parameters": {
        "rig_type": {
            "type": "string",
            "description": "Which rigging task to perform.",
            "enum": ["skeleton", "skinning", "pose", "retarget"],
            "required": True,
        },
        # skeleton
        "container_name": {"type": "string", "description": "skeleton only: name of the /obj geo container to create."},
        "preset": {"type": "string", "description": "skeleton only: biped | quadruped | chain.",
                   "enum": ["biped", "quadruped", "chain"]},
        "height": {"type": "number", "description": "skeleton only: character height in units "
                   "(ignored when fit_to_geometry is set)."},
        "chain_joint_count": {"type": "integer", "description": "skeleton only, 'chain' preset: number of joints."},
        "fit_to_geometry": {"type": "string", "description": "skeleton only: OPTIONAL path to a "
                            "character mesh — the skeleton is scaled/centered to its bounds."},
        "add_controls": {"type": "boolean", "description": "skeleton only: attach control shapes "
                         "(Attach Joint Geometry)."},
        # skinning
        "skin_path": {"type": "string", "description": "skinning only: path to the character mesh (SOP or geo container)."},
        "skeleton_path": {"type": "string", "description": "skinning/pose: path to the KineFX "
                          "skeleton (e.g. build_rig skeleton's skeleton_output)."},
        "animated_skeleton_path": {"type": "string", "description": "skinning only: OPTIONAL "
                                   "separate animated skeleton (e.g. a Rig Pose output)."},
        "method": {"type": "string", "description": "skinning only: proximity (fast) | biharmonic "
                   "(higher quality, organic).", "enum": ["proximity", "biharmonic"]},
        "max_influences": {"type": "integer", "description": "skinning only: max joints per point."},
        # pose
        "use_ik": {"type": "boolean", "description": "pose only: append a Full Body IK solver (H19+)."},
        "test_joint": {"type": "string", "description": "pose only: OPTIONAL joint name to rotate "
                       "as a test pose (e.g. 'l_forearm')."},
        "test_rotate": {"type": "string", "description": "pose only: test rotation in degrees as "
                        "'rx,ry,rz' (default '0,0,-45')."},
        # retarget
        "target_skeleton_path": {"type": "string", "description": "retarget only: TARGET skeleton "
                                 "to animate (e.g. build_rig skeleton's skeleton_output)."},
        "source_skeleton_path": {"type": "string", "description": "retarget only: SOURCE animated "
                                 "skeleton (mocap, e.g. an imported Mixamo FBX SOP)."},
        "mapping_preset": {"type": "string", "description": "retarget only: mixamo | name | none "
                           "(joint name mapping).", "enum": ["mixamo", "name", "none"]},
        "match_bounds": {"type": "boolean", "description": "retarget only: auto align/scale the "
                         "source to the target via Rig Match Pose bounds match."},
        # shared
        "verify": {"type": "boolean", "description": "Auto cook+verify the built rig and attach a "
                   "'verification' report (default true)."},
    },
}


def run(rig_type=None, container_name=None, preset=None, height=None,
        chain_joint_count=None, fit_to_geometry=None, add_controls=None,
        skin_path=None, skeleton_path=None, animated_skeleton_path=None,
        method=None, max_influences=None,
        use_ik=None, test_joint=None, test_rotate=None,
        target_skeleton_path=None, source_skeleton_path=None,
        mapping_preset=None, match_bounds=None, verify=True):
    import inspect

    if not rig_type:
        return {"success": False,
                "error": "rig_type is required (skeleton / skinning / pose)."}

    rt = _ALIASES.get(str(rig_type).strip().lower(), str(rig_type).strip().lower())
    if rt not in _DISPATCH:
        return {"success": False,
                "error": f"unknown rig_type '{rig_type}'. Valid: {', '.join(_DISPATCH.keys())}."}

    skill_name, rename = _DISPATCH[rt]

    unified = {
        "container_name": container_name, "preset": preset, "height": height,
        "chain_joint_count": chain_joint_count, "fit_to_geometry": fit_to_geometry,
        "add_controls": add_controls,
        "skin_path": skin_path, "skeleton_path": skeleton_path,
        "animated_skeleton_path": animated_skeleton_path, "method": method,
        "max_influences": max_influences,
        "use_ik": use_ik, "test_joint": test_joint, "test_rotate": test_rotate,
        "target_skeleton_path": target_skeleton_path,
        "source_skeleton_path": source_skeleton_path,
        "mapping_preset": mapping_preset, "match_bounds": match_bounds,
    }
    provided = {k: v for k, v in unified.items() if v is not None}
    for u_name, s_name in rename.items():
        if u_name in provided:
            provided[s_name] = provided.pop(u_name)

    try:
        from morfyai import skills as _skills
        _skills._load_all()
        mod = _skills._registry.get(skill_name)
    except Exception as e:
        return {"success": False, "error": f"could not load skill registry: {e}"}
    if mod is None or not callable(getattr(mod, "run", None)):
        return {"success": False, "error": f"underlying skill '{skill_name}' not found or has no run()."}

    accepted = set(inspect.signature(mod.run).parameters.keys())
    kwargs = {k: v for k, v in provided.items() if k in accepted}
    ignored = sorted(k for k in provided if k not in accepted)

    try:
        result = mod.run(**kwargs)
    except Exception as e:
        import traceback
        return {"success": False, "error": f"{skill_name} failed: {e}\n{traceback.format_exc()[:400]}",
                "rig_type": rt, "builder": skill_name}

    if not isinstance(result, dict):
        result = {"result": str(result)}
    result.setdefault("success", True)
    result["rig_type"] = rt
    result["builder"] = skill_name
    if ignored:
        result["ignored_params"] = ignored

    if verify and result.get("success"):
        try:
            rep = _verify_rig(result, rt)
        except Exception as e:
            rep = {"ok": None, "note": f"verify skipped: {e}"}
        result["verification"] = rep
        if rep.get("ok") is False:
            result["needs_fix"] = True

    # surface the vision follow-up so the main model always remembers it
    result["next_step"] = (
        "Run a VISUAL verification now: capture_viewport (or skill__visual_check) and judge "
        "what data cannot — skeleton placement/proportions, or deformation quality in a pose."
    )
    return result
