# -*- coding: utf-8 -*-
"""Read a parameter's current value(s) without cooking anything unnecessary.

Read-only.
"""

SKILL_INFO = {
    "name": "get_parm_value",
    "description": (
        "Read the current value of a node parameter (or parm tuple, e.g. 't' for translate xyz). "
        "Cheaper than dumping the whole node when you just need one value."
    ),
    "parameters": {
        "node_path": {"type": "string", "description": "Node containing the parameter.", "required": True},
        "parm_name": {"type": "string", "description": "Parm or parm-tuple name, e.g. 'tx' or 't'.", "required": True},
    },
}


def run(node_path="", parm_name=""):
    import hou  # type: ignore

    node = hou.node(node_path or "")
    if node is None:
        return {"success": False, "error": f"node not found: {node_path}"}

    pt = node.parmTuple(parm_name)
    if pt is not None:
        return {"success": True, "node": node.path(), "parm": parm_name,
                "value": list(pt.eval()), "is_tuple": True}

    p = node.parm(parm_name)
    if p is None:
        avail = sorted(x.name() for x in node.parms())[:30]
        return {"success": False, "error": f"parm not found: {parm_name}", "available_parms_sample": avail}

    return {"success": True, "node": node.path(), "parm": parm_name, "value": p.eval(), "is_tuple": False}
