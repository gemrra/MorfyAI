# -*- coding: utf-8 -*-
"""Set the network-view color of one or more nodes.

Mutating — changes node display color (cosmetic only, no scene-data change).
"""

SKILL_INFO = {
    "name": "color_nodes",
    "description": (
        "Set the network-view color of every node under a parent that matches a glob pattern. Use to "
        "visually flag nodes (e.g. color everything named 'debug_*' red, or a build's output node green)."
    ),
    "parameters": {
        "parent_path": {"type": "string", "description": "Network to search in, e.g. '/obj/geo1'.", "required": True},
        "match": {"type": "string", "description": "Glob pattern to match node names, e.g. '*' or 'debug_*'.", "default": "*"},
        "color": {
            "type": "string",
            "description": "Named color or 'r,g,b' floats 0-1, e.g. 'red' or '1,0.5,0'.",
            "default": "red",
        },
    },
}

_NAMED = {
    "red": (1.0, 0.15, 0.15), "green": (0.2, 0.85, 0.2), "blue": (0.25, 0.5, 1.0),
    "yellow": (1.0, 0.9, 0.1), "orange": (1.0, 0.55, 0.1), "purple": (0.6, 0.3, 0.85),
    "cyan": (0.2, 0.85, 0.85), "white": (0.9, 0.9, 0.9), "gray": (0.5, 0.5, 0.5),
    "grey": (0.5, 0.5, 0.5), "black": (0.05, 0.05, 0.05), "pink": (1.0, 0.5, 0.7),
}


def _parse_color(spec):
    s = (spec or "").strip().lower()
    if s in _NAMED:
        return _NAMED[s]
    if "," in s:
        try:
            parts = [float(x) for x in s.split(",")]
            if len(parts) == 3:
                return tuple(parts)
        except Exception:
            pass
    return None


def run(parent_path="", match="*", color="red"):
    import hou  # type: ignore

    rgb = _parse_color(color)
    if rgb is None:
        return {"success": False, "error": f"unrecognized color: {color!r} (use a name like 'red' or 'r,g,b' floats)"}

    parent = hou.node(parent_path or "")
    if parent is None:
        return {"success": False, "error": f"parent not found: {parent_path}"}

    matched = parent.glob(match) if hasattr(parent, "glob") else []
    if not matched:
        return {"success": True, "colored": [], "verdict": f"No nodes under {parent_path} matched '{match}'."}

    colored = []
    for node in matched:
        try:
            node.setColor(hou.Color(rgb))
            colored.append(node.path())
        except Exception:
            pass

    return {
        "success": True,
        "colored": colored,
        "count": len(colored),
        "color": color,
        "verdict": f"Colored {len(colored)} node(s) under {parent_path} matching '{match}' -> {color}.",
    }
