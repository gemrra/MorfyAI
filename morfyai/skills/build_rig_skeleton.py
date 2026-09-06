# -*- coding: utf-8 -*-
"""KineFX skeleton builder skill (H18.5+; KineFX ships with H19.5 baseline).

Builds a complete geometry-based (KineFX) skeleton from one call:

    skeleton preset (biped / quadruped / custom chain)
      -> Python SOP writes joint points + polyline + name/transform attrs
      -> Rig Doctor (initialize transforms, validate hierarchy)
      -> Orient Joints (auto-orient axes, aim at child)
      -> [optional] Attach Joint Geometry (control shapes)
      -> [optional] Visualize Rig (fat visible joint axes for viewport/vision)

Why a Python SOP instead of the Skeleton SOP: the Skeleton SOP
('kinefx--skeleton') is interactive-only — it has no parameters to fill
joints with. Rig Doctor is the documented procedural way to turn a
polyline (points with `name` + `transform` point attrs, parent/child by
vertex order) into a valid KineFX joint chain. Verified against SideFX
docs (Working with Skeletons / Rig Doctor).

Deterministic wiring so the chain is always correct; node types are
resolved at runtime so it tolerates version drift.
"""

SKILL_INFO = {
    "name": "build_rig_skeleton",
    "hidden": True,  # fronted by build_rig (rig_type='skeleton')
    "description": (
        "Build a KineFX skeleton from one call. Creates a geo container with a procedurally "
        "generated joint chain (biped, quadruped, or a custom chain) wired through Rig Doctor "
        "(initializes the point transform attributes that make points real joints) and Orient "
        "Joints (aims axes at children). Optional: fit the skeleton's proportions to an existing "
        "character mesh (bounding box), attach control shapes (Attach Joint Geometry), and add a "
        "Visualize Rig node so the joints are clearly visible in the viewport (needed for visual "
        "verification). Use when the user asks for a skeleton, joints, bones, or a rig base for a "
        "character. Pair with build_rig_skinning to bind a mesh and build_rig_pose to pose it."
    ),
    "parameters": {
        "container_name": {
            "type": "string",
            "description": "Name of the /obj geo container to create",
            "default": "character_rig",
        },
        "preset": {
            "type": "string",
            "description": "Skeleton preset layout to generate",
            "enum": ["biped", "quadruped", "chain"],
            "default": "biped",
        },
        "height": {
            "type": "number",
            "description": "Total character height in Houdini units (biped/quadruped). Ignored "
                           "when fit_to_geometry is set (taken from the mesh bounds instead).",
            "default": 1.8,
        },
        "chain_joint_count": {
            "type": "integer",
            "description": "Number of joints for the 'chain' preset (a straight vertical chain "
                           "— tail, tentacle, rope, simple limb)",
            "default": 5,
        },
        "fit_to_geometry": {
            "type": "string",
            "description": "OPTIONAL path to an existing character/skin mesh. The skeleton is "
                           "scaled and centered to its bounding box (feet at the mesh bottom, "
                           "head near the top). Leave empty to use 'height'.",
            "default": "",
        },
        "add_controls": {
            "type": "boolean",
            "description": "Append an Attach Joint Geometry node with simple control shapes so "
                           "the joints are selectable via visible controls in KineFX tools",
            "default": False,
        },
        "add_visualizer": {
            "type": "boolean",
            "description": "Append a Visualize Rig node at the end (thick joint axes/links). "
                           "Strongly recommended — it makes the skeleton clearly visible in "
                           "viewport captures for visual verification.",
            "default": True,
        },
    },
}


# ── runtime resolvers (self-contained per skill) ─────────────────────

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


# ── joint layout presets ─────────────────────────────────────────────
# Each joint: (name, parent_name_or_None, position(x,y,z) in a 1.8-unit-tall
# normalized space, y-up, character facing +Z). Positions are scaled to the
# target height at build time.

def _biped_joints():
    # proportions roughly humanoid; y = height above ground in a 1.8 m body
    return [
        ("root",        None,           (0.0,   0.95,  0.0)),
        ("pelvis",      "root",         (0.0,   0.98,  0.0)),
        ("spine_01",    "pelvis",       (0.0,   1.10,  0.0)),
        ("spine_02",    "spine_01",     (0.0,   1.22,  0.0)),
        ("chest",       "spine_02",     (0.0,   1.34,  0.0)),
        ("neck",        "chest",        (0.0,   1.50,  0.0)),
        ("head",        "neck",         (0.0,   1.62,  0.0)),
        ("head_end",    "head",         (0.0,   1.80,  0.0)),
        # left arm
        ("l_shoulder",  "chest",        (0.12,  1.46,  0.0)),
        ("l_upperarm",  "l_shoulder",   (0.30,  1.44,  0.0)),
        ("l_forearm",   "l_upperarm",   (0.55,  1.42,  0.0)),
        ("l_hand",      "l_forearm",    (0.78,  1.40,  0.0)),
        # right arm
        ("r_shoulder",  "chest",        (-0.12, 1.46,  0.0)),
        ("r_upperarm",  "r_shoulder",   (-0.30, 1.44,  0.0)),
        ("r_forearm",   "r_upperarm",   (-0.55, 1.42,  0.0)),
        ("r_hand",      "r_forearm",    (-0.78, 1.40,  0.0)),
        # left leg
        ("l_thigh",     "pelvis",       (0.10,  0.95,  0.0)),
        ("l_calf",      "l_thigh",      (0.11,  0.50,  0.0)),
        ("l_foot",      "l_calf",       (0.12,  0.08,  0.0)),
        ("l_toe",       "l_foot",       (0.12,  0.02,  0.14)),
        # right leg
        ("r_thigh",     "pelvis",       (-0.10, 0.95,  0.0)),
        ("r_calf",      "r_thigh",      (-0.11, 0.50,  0.0)),
        ("r_foot",      "r_calf",       (-0.12, 0.08,  0.0)),
        ("r_toe",       "r_foot",       (-0.12, 0.02,  0.14)),
    ]


def _quadruped_joints():
    # dog/horse-like; facing +Z, y = height (normalized ~0.9 tall, scaled by height)
    return [
        ("root",        None,           (0.0,   0.45,  0.0)),
        ("pelvis",      "root",         (0.0,   0.50, -0.45)),
        ("spine_01",    "pelvis",       (0.0,   0.55, -0.20)),
        ("spine_02",    "spine_01",     (0.0,   0.58,  0.05)),
        ("chest",       "spine_02",     (0.0,   0.58,  0.30)),
        ("neck",        "chest",        (0.0,   0.70,  0.50)),
        ("head",        "neck",         (0.0,   0.78,  0.70)),
        ("jaw_end",     "head",         (0.0,   0.72,  0.92)),
        # tail
        ("tail_01",     "pelvis",       (0.0,   0.52, -0.62)),
        ("tail_02",     "tail_01",      (0.0,   0.48, -0.80)),
        # front left leg
        ("l_front_upper",  "chest",     (0.14,  0.55,  0.32)),
        ("l_front_lower",  "l_front_upper", (0.15, 0.28, 0.34)),
        ("l_front_foot",   "l_front_lower", (0.15, 0.04, 0.36)),
        # front right leg
        ("r_front_upper",  "chest",     (-0.14, 0.55,  0.32)),
        ("r_front_lower",  "r_front_upper", (-0.15, 0.28, 0.34)),
        ("r_front_foot",   "r_front_lower", (-0.15, 0.04, 0.36)),
        # back left leg
        ("l_back_upper",   "pelvis",    (0.14,  0.48, -0.44)),
        ("l_back_lower",   "l_back_upper", (0.15, 0.26, -0.42)),
        ("l_back_foot",    "l_back_lower", (0.15, 0.04, -0.40)),
        # back right leg
        ("r_back_upper",   "pelvis",    (-0.14, 0.48, -0.44)),
        ("r_back_lower",   "r_back_upper", (-0.15, 0.26, -0.42)),
        ("r_back_foot",    "r_back_lower", (-0.15, 0.04, -0.40)),
    ]


def _chain_joints(count):
    joints = [("root", None, (0.0, 0.0, 0.0))]
    count = max(2, int(count))
    for i in range(1, count):
        parent = "root" if i == 1 else "joint_%02d" % (i - 1)
        joints.append(("joint_%02d" % i, parent, (0.0, i * 0.3, 0.0)))
    return joints


# Python SOP snippet that materializes the joint list as KineFX geometry:
# one point per joint (with `name` + identity matrix3 `transform`), plus one
# open polyline per root-to-leaf chain so Rig Doctor can read the hierarchy
# from vertex order (the documented KineFX skeleton representation).
_PY_SOP_SNIPPET = r'''
import hou
node = hou.pwd()
geo = node.geometry()

joints = JOINT_DATA  # [(name, parent, (x,y,z)), ...] injected by the skill

geo.clear()
pos_by_name = {}
pt_by_name = {}
for name, parent, pos in joints:
    pt = geo.createPoint()
    pt.setPosition(hou.Vector3(*pos))
    pt.setAttribValue("name", name)
    pt.setAttribValue("transform", hou.Matrix3(((1,0,0),(0,1,0),(0,0,1))))
    pos_by_name[name] = hou.Vector3(*pos)
    pt_by_name[name] = pt

# one open polyline per parent->child chain segment set, ordered root->leaf
children = {}
for name, parent, pos in joints:
    if parent:
        children.setdefault(parent, []).append(name)

def chain_lines(start):
    # depth-first; each (parent, child) edge emitted in order
    lines = []
    def walk(n, acc):
        kids = children.get(n, [])
        if not kids:
            if len(acc) > 1:
                lines.append(acc)
            return
        for k in kids:
            walk(k, acc + [k])
    walk(start, [start])
    return lines

roots = [n for n, p, _ in joints if not p]
for r in roots:
    for line in chain_lines(r):
        poly = geo.createPolygon(is_closed=False)
        for n in line:
            poly.addVertex(pt_by_name[n])
'''


def run(container_name="character_rig", preset="biped", height=1.8,
        chain_joint_count=5, fit_to_geometry="",
        add_controls=False, add_visualizer=True):
    import hou  # type: ignore

    obj = hou.node("/obj")
    if obj is None:
        return {"success": False, "error": "/obj context not found"}

    warnings = []
    created = []

    # 1. joint layout (normalized, then scaled to height/bounds)
    if preset == "quadruped":
        joints = _quadruped_joints()
        norm_height = 0.92
    elif preset == "chain":
        joints = _chain_joints(chain_joint_count)
        norm_height = max(0.3, (len(joints) - 1) * 0.3)
    else:
        joints = _biped_joints()
        norm_height = 1.8

    scale = float(height) / norm_height if norm_height else 1.0
    offset = hou.Vector3(0, 0, 0)

    # optional: fit proportions to an existing mesh's bounding box
    if fit_to_geometry:
        src = hou.node(fit_to_geometry)
        if src is None:
            warnings.append(f"fit_to_geometry '{fit_to_geometry}' not found — using height instead")
        else:
            try:
                bbox = src.geometry().boundingBox()
                mn, mx = bbox.minvec(), bbox.maxvec()
                size = mx - mn
                target_h = size.y() if size.y() > 1e-6 else max(size.x(), size.z())
                scale = target_h / norm_height
                # center skeleton in X/Z of the mesh, feet at its bottom
                offset = hou.Vector3((mn.x() + mx.x()) / 2.0, mn.y(),
                                     (mn.z() + mx.z()) / 2.0)
            except Exception as e:
                warnings.append(f"could not read bounds of {fit_to_geometry}: {e}")

    scaled = [(n, p, (pos[0] * scale + offset.x(),
                      pos[1] * scale + offset.y(),
                      pos[2] * scale + offset.z()))
              for n, p, pos in joints]

    # 2. container
    try:
        geo_node = obj.createNode("geo", container_name)
    except Exception as e:
        return {"success": False, "error": f"failed to create container: {e}"}
    created.append(geo_node.path())

    # 3. Python SOP materializing the joints
    py_type = _find_sop_type(["python", "python::2.0"])
    if not py_type:
        return {"success": False,
                "error": "Python SOP not available in this Houdini build",
                "created": created}
    py = geo_node.createNode(py_type, "skeleton_joints")
    snippet = _PY_SOP_SNIPPET.replace("JOINT_DATA", repr(scaled))
    try:
        py.parm("python").set(snippet)
    except Exception as e:
        return {"success": False, "error": f"failed to set Python SOP code: {e}",
                "created": created}
    created.append(py.path())
    upstream = py

    # 4. Rig Doctor — turn polyline + name/transform attrs into valid joints
    rd_type = _find_sop_type(["rigdoctor", "rigdoctor::2.0"])
    if rd_type:
        rd = geo_node.createNode(rd_type, "rigdoctor1")
        rd.setInput(0, upstream)
        _set_parms(rd, {"inittransforms": 1})
        created.append(rd.path())
        upstream = rd
    else:
        warnings.append("Rig Doctor SOP not found — skeleton left as raw polyline "
                        "(joints may lack initialized local transforms)")

    # 5. Orient Joints — aim each joint's axes at its child
    oj_type = _find_sop_type(["kinefx--orientjoints", "orientjoints"])
    if oj_type:
        oj = geo_node.createNode(oj_type, "orientjoints1")
        oj.setInput(0, upstream)
        created.append(oj.path())
        upstream = oj
    else:
        warnings.append("Orient Joints SOP not found — joint axes left as identity")

    # 6. optional control shapes
    if add_controls:
        ctl_type = _find_sop_type(["kinefx--attachjointgeo", "attachjointgeo"])
        if ctl_type:
            ctl = geo_node.createNode(ctl_type, "attach_controls")
            ctl.setInput(0, upstream)
            created.append(ctl.path())
            upstream = ctl
        else:
            warnings.append("Attach Joint Geometry SOP not found — controls skipped")

    # 7. optional Visualize Rig (fat visible axes — also what the vision check needs)
    viz = None
    if add_visualizer:
        viz_type = _find_sop_type(["kinefx--visualizerig", "visualizerig"])
        if viz_type:
            viz = geo_node.createNode(viz_type, "visualize_rig")
            viz.setInput(0, upstream)
            created.append(viz.path())
        else:
            warnings.append("Visualize Rig SOP not found — display falls back to the raw skeleton")

    display_node = viz if viz is not None else upstream
    try:
        display_node.setDisplayFlag(True)
        if hasattr(display_node, "setRenderFlag"):
            display_node.setRenderFlag(True)
    except Exception as e:
        warnings.append(f"display flag failed: {e}")

    try:
        geo_node.layoutChildren()
    except Exception:
        pass

    joint_names = [n for n, _p, _pos in scaled]
    return {
        "success": True,
        "container": geo_node.path(),
        "skeleton_output": upstream.path(),
        "display_node": display_node.path(),
        "preset": preset,
        "joint_count": len(scaled),
        "joint_names": joint_names,
        "fit_to_geometry": fit_to_geometry or None,
        "created_nodes": created,
        "warnings": warnings,
        "message": (
            f"Built a {preset} KineFX skeleton ({len(scaled)} joints) in {geo_node.path()}. "
            f"Skeleton output: {upstream.path()}. Next: bind a mesh with build_rig_skinning, "
            f"or pose it with build_rig_pose. For visual verification, capture the viewport "
            f"and check the skeleton's proportions/placement inside the character."
        ),
    }
