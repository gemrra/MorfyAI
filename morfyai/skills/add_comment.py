# -*- coding: utf-8 -*-
"""Attach a sticky comment to a node.

Mutating — sets the node's comment (shown under it in the network view).
"""

SKILL_INFO = {
    "name": "add_comment",
    "description": (
        "Set a node's comment text (shown under it in the network editor) and turns comment display on. "
        "Use to leave quick documentation on a build without a separate sticky note."
    ),
    "parameters": {
        "node_path": {"type": "string", "description": "Node to comment on.", "required": True},
        "text": {"type": "string", "description": "Comment text.", "required": True},
    },
}


def run(node_path="", text=""):
    import hou  # type: ignore

    node = hou.node(node_path or "")
    if node is None:
        return {"success": False, "error": f"node not found: {node_path}"}
    try:
        node.setComment(text or "")
        node.setGenericFlag(hou.nodeFlag.DisplayComment, bool(text))
    except Exception as e:
        return {"success": False, "error": f"could not set comment: {e}"}

    return {
        "success": True,
        "node": node.path(),
        "text": text,
        "verdict": f"Comment set on {node.path()}." if text else f"Comment cleared on {node.path()}.",
    }
