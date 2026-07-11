# -*- coding: utf-8 -*-
"""Promote an attribute between classes (point / vertex / primitive / detail).

Mutating — adds an Attribute Promote SOP downstream.
"""

SKILL_INFO = {
    "name": "promote_attribute",
    "description": (
        "Add an Attribute Promote SOP to move/convert an attribute from one class to another "
        "(e.g. point Cd to primitive, or vertex N to point), with a combine method for when many "
        "values map to one."
    ),
    "parameters": {
        "node_path": {"type": "string", "description": "SOP carrying the attribute.", "required": True},
        "attribute": {"type": "string", "description": "Attribute name to promote, e.g. 'Cd'.", "required": True},
        "from_class": {
            "type": "string", "description": "Source class.",
            "enum": ["point", "vertex", "primitive", "detail"], "default": "point",
        },
        "to_class": {
            "type": "string", "description": "Target class.",
            "enum": ["point", "vertex", "primitive", "detail"], "default": "primitive",
        },
        "method": {
            "type": "string", "description": "Combine method when many values map to one.",
            "enum": ["max", "min", "mean", "median", "mode", "sum", "first", "last"], "default": "mean",
        },
    },
}

# attribpromote menu orderings (stable across recent Houdini versions).
_CLASS = {"point": 0, "vertex": 1, "primitive": 2, "detail": 3}
_METHOD = {"max": 0, "min": 1, "mean": 2, "median": 3, "mode": 4,
           "sum": 5, "sumsquare": 6, "rms": 7, "first": 8, "last": 9}


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


def run(node_path="", attribute="", from_class="point", to_class="primitive", method="mean"):
    import hou  # type: ignore

    if not attribute:
        return {"success": False, "error": "attribute name is required"}
    src = hou.node(node_path or "")
    if src is None:
        return {"success": False, "error": f"node not found: {node_path}"}
    parent = src.parent()
    try:
        ap = parent.createNode("attribpromote", node_name=f"promote_{attribute}")
    except Exception as e:
        return {"success": False, "error": f"could not create attribpromote SOP: {e}"}

    try:
        ap.setInput(0, src)
    except Exception as e:
        return {"success": False, "error": f"could not wire attribpromote to {src.path()}: {e}"}

    missing = _apply(ap, {
        "inname": attribute,
        "inclass": _CLASS.get(from_class, 0),
        "outclass": _CLASS.get(to_class, 2),
        "method": _METHOD.get(method, 2),
    })
    try:
        ap.moveToGoodPosition()
        ap.setDisplayFlag(True)
        ap.setRenderFlag(True)
    except Exception:
        pass

    return {
        "success": True,
        "node": ap.path(),
        "attribute": attribute,
        "from_class": from_class,
        "to_class": to_class,
        "method": method,
        "unset_parms": missing,
        "verdict": (f"Attribute '{attribute}' promoted {from_class} -> {to_class} ({method}) at "
                    f"{ap.path()}. Inspect with analyze_point_attrib / verify_geo."),
    }
