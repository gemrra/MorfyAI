# -*- coding: utf-8 -*-
"""Attribute comparison skill

Compare attribute differences between two nodes: which attributes are added/removed/changed type.
Covers all four categories: point/vertex/prim/detail.
"""

SKILL_INFO = {
    "name": "compare_attributes",
    "description": (
        "Compare attribute differences between two nodes (which are added/removed/changed type). "
        "Covers all four categories: point/vertex/prim/detail. "
        "Useful for pipeline debugging and checking data changes before/after a node."
    ),
    "parameters": {
        "node_path_a": {
            "type": "string",
            "description": "First node path",
            "required": True,
        },
        "node_path_b": {
            "type": "string",
            "description": "Second node path",
            "required": True,
        },
    },
}


def run(node_path_a, node_path_b):
    """Entry point

    Args:
        node_path_a: First node path
        node_path_b: Second node path
    """
    import hou  # type: ignore

    node_a = hou.node(node_path_a)
    node_b = hou.node(node_path_b)

    if not node_a:
        return {"error": f"Node does not exist: {node_path_a}"}
    if not node_b:
        return {"error": f"Node does not exist: {node_path_b}"}

    geo_a = node_a.geometry()
    geo_b = node_b.geometry()

    if not geo_a:
        return {"error": f"Cannot fetch geometry: {node_path_a}"}
    if not geo_b:
        return {"error": f"Cannot fetch geometry: {node_path_b}"}

    def get_attrib_info(geo):
        attribs = {}
        for cls, method in [
            ("point", geo.pointAttribs),
            ("vertex", geo.vertexAttribs),
            ("prim", geo.primAttribs),
            ("detail", geo.globalAttribs),
        ]:
            for attr in method():
                key = f"{cls}:{attr.name()}"
                attribs[key] = {
                    "class": cls,
                    "name": attr.name(),
                    "type": str(attr.dataType()),
                    "size": attr.size(),
                }
        return attribs

    attribs_a = get_attrib_info(geo_a)
    attribs_b = get_attrib_info(geo_b)

    keys_a = set(attribs_a.keys())
    keys_b = set(attribs_b.keys())

    only_in_a = keys_a - keys_b
    only_in_b = keys_b - keys_a
    common = keys_a & keys_b

    type_diff = []
    for key in sorted(common):
        a, b = attribs_a[key], attribs_b[key]
        if a["type"] != b["type"] or a["size"] != b["size"]:
            type_diff.append({
                "name": key,
                "a": f"{a['type']}[{a['size']}]",
                "b": f"{b['type']}[{b['size']}]",
            })

    return {
        "node_a": node_path_a,
        "node_b": node_path_b,
        "attrib_count_a": len(attribs_a),
        "attrib_count_b": len(attribs_b),
        "only_in_a": sorted([attribs_a[k]["name"] for k in only_in_a]),
        "only_in_b": sorted([attribs_b[k]["name"] for k in only_in_b]),
        "common_count": len(common),
        "type_differences": type_diff,
        "identical": len(only_in_a) == 0 and len(only_in_b) == 0 and len(type_diff) == 0,
    }
