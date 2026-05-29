# -*- coding: utf-8 -*-
"""Dead node detection skill

Find "dead" nodes in the network: no downstream connection and not a display/render node.
Distinguishes fully isolated nodes (no input, no output) from chain-tail unused nodes (has input, no output).
"""

SKILL_INFO = {
    "name": "find_dead_nodes",
    "description": (
        "Find dead nodes in the network (no downstream connections, not display/render). "
        "Distinguishes fully isolated nodes (no input, no output) from chain-tail unused nodes. "
        "Useful for cleaning up the network and pipeline optimization."
    ),
    "parameters": {
        "network_path": {
            "type": "string",
            "description": "Network path, e.g. /obj/geo1",
            "required": True,
        },
    },
}


def run(network_path):
    """Entry point

    Args:
        network_path: network path
    """
    import hou  # type: ignore

    network = hou.node(network_path)
    if not network:
        return {"error": f"Network does not exist: {network_path}"}

    children = network.children()
    if not children:
        return {
            "network": network_path,
            "total_nodes": 0,
            "dead_node_count": 0,
            "orphan_nodes": [],
            "unused_end_nodes": [],
        }

    dead_nodes = []
    display_node = None
    render_node = None

    for node in children:
        if node.isDisplayFlagSet():
            display_node = node.path()
        if hasattr(node, 'isRenderFlagSet') and node.isRenderFlagSet():
            render_node = node.path()

    for node in children:
        outputs = node.outputs()
        is_dead = (
            len(outputs) == 0
            and not node.isDisplayFlagSet()
            and (not hasattr(node, 'isRenderFlagSet') or not node.isRenderFlagSet())
        )

        if is_dead:
            has_error = False
            try:
                has_error = bool(node.errors() or node.warnings())
            except Exception:
                pass

            dead_nodes.append({
                "name": node.name(),
                "type": node.type().name(),
                "path": node.path(),
                "has_inputs": len(node.inputs()) > 0,
                "has_error": has_error,
            })

    orphan_nodes = [n for n in dead_nodes if not n["has_inputs"]]
    end_nodes = [n for n in dead_nodes if n["has_inputs"]]

    return {
        "network": network_path,
        "total_nodes": len(children),
        "display_node": display_node,
        "render_node": render_node,
        "dead_node_count": len(dead_nodes),
        "orphan_nodes": orphan_nodes,
        "unused_end_nodes": end_nodes,
    }
