# -*- coding: utf-8 -*-
"""Node dependency tracing skill

Trace the upstream dependency tree or downstream impact of a node — outputs a tiered structure and a visual tree text.
"""

SKILL_INFO = {
    "name": "trace_node_dependencies",
    "description": (
        "Trace a node's upstream dependency tree or downstream impact. "
        "upstream: see which upstream nodes this node depends on; "
        "downstream: see which downstream nodes are affected when this node changes. "
        "Returns a tiered list plus a visual tree text."
    ),
    "parameters": {
        "node_path": {
            "type": "string",
            "description": "Node path, e.g. /obj/geo1/OUT",
            "required": True,
        },
        "direction": {
            "type": "string",
            "description": "Direction: upstream (deps) or downstream (impact), default upstream",
            "required": False,
        },
        "max_depth": {
            "type": "integer",
            "description": "Maximum trace depth, default 10",
            "required": False,
        },
    },
}


def run(node_path, direction="upstream", max_depth=10):
    """Entry point"""
    import hou  # type: ignore

    node = hou.node(node_path)
    if not node:
        return {"error": f"Node does not exist: {node_path}"}

    max_depth = min(int(max_depth), 50)
    if direction not in ("upstream", "downstream"):
        return {"error": f"Invalid direction: {direction}, options upstream / downstream"}

    visited = set()
    levels = []

    def traverse(n, depth):
        if depth > max_depth or n.path() in visited:
            return None
        visited.add(n.path())

        connected = n.inputs() if direction == "upstream" else n.outputs()

        children = {}
        for conn in connected:
            if conn:
                child_tree = traverse(conn, depth + 1)
                if child_tree is not None:
                    children[conn.name()] = child_tree

        while len(levels) <= depth:
            levels.append([])
        levels[depth].append({
            "name": n.name(),
            "type": n.type().name(),
            "path": n.path(),
        })

        return {
            "type": n.type().name(),
            "path": n.path(),
            "connections": children,
        }

    def tree_to_text(t, indent=0):
        if t is None:
            return ""
        lines = []
        name = t["path"].split("/")[-1]
        prefix = "  " * indent + ("└─ " if indent > 0 else "")
        lines.append(f"{prefix}{name} ({t['type']})")
        for _child_name, child_tree in t.get("connections", {}).items():
            lines.append(tree_to_text(child_tree, indent + 1))
        return "\n".join(lines)

    tree = traverse(node, 0)

    return {
        "root": node.name(),
        "direction": direction,
        "total_nodes": len(visited),
        "max_depth": len(levels) - 1 if levels else 0,
        "levels": levels,
        "tree_text": tree_to_text(tree),
    }
