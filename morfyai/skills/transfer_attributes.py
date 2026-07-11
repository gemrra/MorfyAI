# -*- coding: utf-8 -*-
"""Transfer attributes from a source surface onto another by proximity.

Mutating — adds an Attribute Transfer SOP (dest = input 0, source = input 1).
"""

SKILL_INFO = {
    "name": "transfer_attributes",
    "description": (
        "Add an Attribute Transfer SOP that copies attributes from a source geometry onto a destination "
        "by nearest-point proximity (e.g. bake Cd from a hi-res mesh onto scattered points). The "
        "destination is the node being modified; the source provides the values."
    ),
    "parameters": {
        "dest_node": {
            "type": "string",
            "description": "SOP that RECEIVES the attributes (input 0), e.g. '/obj/geo/scatter_pts'.",
            "required": True,
        },
        "source_node": {
            "type": "string",
            "description": "SOP that PROVIDES the attributes (input 1), e.g. '/obj/geo/color_mesh'.",
            "required": True,
        },
        "attributes": {
            "type": "string",
            "description": "Space-separated attribute names to transfer, e.g. 'Cd' or 'Cd N'.",
            "default": "Cd",
        },
        "attr_class": {
            "type": "string", "description": "Which class the attributes live on.",
            "enum": ["point", "primitive"], "default": "point",
        },
        "distance": {
            "type": "number",
            "description": "Max transfer distance (threshold). Larger = looser matching.",
            "default": 1.0,
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


def run(dest_node="", source_node="", attributes="Cd", attr_class="point", distance=1.0):
    import hou  # type: ignore

    dest = hou.node(dest_node or "")
    source = hou.node(source_node or "")
    if dest is None:
        return {"success": False, "error": f"dest_node not found: {dest_node}"}
    if source is None:
        return {"success": False, "error": f"source_node not found: {source_node}"}

    parent = dest.parent()
    try:
        at = parent.createNode("attribtransfer", node_name="attrib_transfer")
    except Exception as e:
        return {"success": False, "error": f"could not create attribtransfer SOP: {e}"}

    try:
        at.setInput(0, dest)
        at.setInput(1, source)
    except Exception as e:
        return {"success": False, "error": f"could not wire attribtransfer: {e}"}

    parms = {"distthreshold": float(distance)}
    if attr_class == "point":
        parms["pointattribs"] = attributes
        parms["enablepoint"] = 1
    else:
        parms["primattribs"] = attributes
        parms["enableprim"] = 1
    missing = _apply(at, parms)
    try:
        at.moveToGoodPosition()
        at.setDisplayFlag(True)
        at.setRenderFlag(True)
    except Exception:
        pass

    return {
        "success": True,
        "node": at.path(),
        "attributes": attributes,
        "attr_class": attr_class,
        "unset_parms": missing,
        "verdict": (f"Attribute transfer added at {at.path()} — '{attributes}' from {source.path()} "
                    f"onto {dest.path()}. Verify with analyze_point_attrib."),
    }
