# -*- coding: utf-8 -*-
"""Network tidy / layout skill.

Cleanly arranges the nodes inside a network so the connector wires read clearly
(no crossing / overlapping). Optionally wraps the result in a labelled, colored
Network Box. Uses Houdini's own layoutChildren, with a per-node fallback.

Mutating (it moves nodes), so it is offered in Agent/Plan modes only.
"""

SKILL_INFO = {
    "name": "tidy_network",
    "description": (
        "Tidy up / auto-layout the nodes inside a network so the connection wires read clearly. "
        "Re-arranges node positions (and can wrap them in a labelled Network Box). "
        "Use when a node network looks messy, wires overlap, or after building something manually. "
        "Pass the container path, e.g. /obj/geo1."
    ),
    "parameters": {
        "network_path": {
            "type": "string",
            "description": "Path of the network/container whose children to lay out, e.g. /obj/geo1. Empty = /obj.",
            "default": "",
        },
        "spacing": {
            "type": "number",
            "description": "Spacing multiplier between nodes (1.0 = default, larger = more spread out)",
            "default": 1.2,
        },
        "add_network_box": {
            "type": "boolean",
            "description": "Wrap all children in a labelled Network Box after laying out",
            "default": False,
        },
        "box_label": {
            "type": "string",
            "description": "Comment shown on the Network Box (only if add_network_box is true)",
            "default": "",
        },
    },
}


def run(network_path="", spacing=1.2, add_network_box=False, box_label=""):
    import hou  # type: ignore

    path = network_path or "/obj"
    net = hou.node(path)
    if net is None:
        return {"success": False, "error": f"network not found: {path}"}

    children = list(net.children())
    if not children:
        return {"success": True, "network": net.path(), "laid_out": 0,
                "message": f"{net.path()} has no child nodes to tidy."}

    warnings = []

    # 1. layout — prefer layoutChildren with spacing, fall back to moveToGoodPosition
    laid_out = 0
    try:
        try:
            # newer signature supports horizontal/vertical spacing
            sp = float(spacing)
            net.layoutChildren(items=(), horizontal_spacing=sp, vertical_spacing=sp)
        except TypeError:
            net.layoutChildren()
        laid_out = len(children)
    except Exception as e:
        warnings.append(f"layoutChildren failed ({e}) — falling back to per-node positioning")
        for n in children:
            try:
                n.moveToGoodPosition()
                laid_out += 1
            except Exception:
                continue

    # 2. optional network box around everything
    box_path = None
    if add_network_box:
        try:
            box = net.createNetworkBox()
            for n in children:
                box.addItem(n)
            if box_label:
                box.setComment(box_label)
            try:
                box.fitAroundContents()
            except Exception:
                pass
            box_path = box.name()
        except Exception as e:
            warnings.append(f"network box creation failed: {e}")

    return {
        "success": True,
        "network": net.path(),
        "laid_out": laid_out,
        "network_box": box_path,
        "warnings": warnings,
        "message": f"Tidied {laid_out} node(s) in {net.path()}."
                   + (f" Wrapped in a Network Box." if box_path else ""),
    }
