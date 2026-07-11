# -*- coding: utf-8 -*-
"""Set a parameter (or parm tuple) to a value directly by name.

Mutating — generic parm setter, useful when there's no dedicated skill for
the specific node type being tweaked.
"""

SKILL_INFO = {
    "name": "set_parm_value",
    "description": (
        "Set a node parameter to a value by name. Accepts a single value for one parm, or a list for a "
        "parm tuple (e.g. [1,2,3] for translate 't'). Use for quick one-off tweaks that don't need a "
        "dedicated skill."
    ),
    "parameters": {
        "node_path": {"type": "string", "description": "Node containing the parameter.", "required": True},
        "parm_name": {"type": "string", "description": "Parm or parm-tuple name, e.g. 'tx' or 't'.", "required": True},
        "value": {
            "type": "string",
            "description": "Value to set. For a tuple, comma-separate e.g. '1,2,3'. Numbers/true/false are parsed automatically.",
            "required": True,
        },
    },
}


def _coerce(s):
    s = s.strip()
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        if "." in s or "e" in low:
            return float(s)
        return int(s)
    except Exception:
        return s


def run(node_path="", parm_name="", value=""):
    import hou  # type: ignore

    node = hou.node(node_path or "")
    if node is None:
        return {"success": False, "error": f"node not found: {node_path}"}

    raw = str(value)
    parts = [p.strip() for p in raw.split(",")] if "," in raw else None

    pt = node.parmTuple(parm_name)
    if pt is not None:
        vals = [_coerce(p) for p in (parts or [raw])]
        if len(vals) != len(pt):
            return {"success": False, "error": f"'{parm_name}' has {len(pt)} components, got {len(vals)} value(s)"}
        try:
            pt.set(vals)
        except Exception as e:
            return {"success": False, "error": f"could not set {parm_name}: {e}"}
        return {"success": True, "node": node.path(), "parm": parm_name, "value": vals}

    p = node.parm(parm_name)
    if p is None:
        avail = sorted(x.name() for x in node.parms())[:30]
        return {"success": False, "error": f"parm not found: {parm_name}", "available_parms_sample": avail}

    coerced = _coerce(raw)
    try:
        p.set(coerced)
    except Exception as e:
        return {"success": False, "error": f"could not set {parm_name}: {e}"}

    return {"success": True, "node": node.path(), "parm": parm_name, "value": coerced}
