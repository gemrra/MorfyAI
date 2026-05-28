# -*- coding: utf-8 -*-
"""Attribute reference search skill

Find every node in the network that references a given attribute — including VEX code, parameter expressions, and string parameter values.
"""

SKILL_INFO = {
    "name": "find_attribute_references",
    "description": (
        "Find every node in the network that references a given attribute. "
        "Checks: VEX code (wrangle), parameter expressions, and string parameter values. "
        "Useful for tracking attribute usage, renaming attributes, and pipeline debugging."
    ),
    "parameters": {
        "network_path": {
            "type": "string",
            "description": "Network path, e.g. /obj/geo1",
            "required": True,
        },
        "attr_name": {
            "type": "string",
            "description": "Attribute name, e.g. P, Cd, class, piece",
            "required": True,
        },
        "recursive": {
            "type": "boolean",
            "description": "Recursively search subnets, default False",
            "required": False,
        },
    },
}


def run(network_path, attr_name, recursive=False):
    """Entry point"""
    import hou  # type: ignore

    network = hou.node(network_path)
    if not network:
        return {"error": f"Network does not exist: {network_path}"}

    if not attr_name:
        return {"error": "Missing attr_name parameter"}

    results = []

    _VEX_TYPES = {
        "attribwrangle", "pointwrangle", "volumewrangle",
        "primitivewrangle", "vertexwrangle",
    }

    def search_in_network(net):
        for node in net.children():
            references = []

            # Check VEX 代码 (wrangle 节点)
            if node.type().name() in _VEX_TYPES:
                try:
                    snippet_parm = node.parm("snippet")
                    if snippet_parm:
                        vex_code = snippet_parm.eval()
                        if attr_name in vex_code:
                            lines_with_ref = []
                            for i, line in enumerate(vex_code.split("\n"), 1):
                                if attr_name in line and not line.strip().startswith("//"):
                                    lines_with_ref.append(f"L{i}: {line.strip()[:60]}")
                            if lines_with_ref:
                                references.append({
                                    "type": "VEX code",
                                    "lines": lines_with_ref[:5],
                                })
                except Exception:
                    pass

            # Check参数表达式 and 字符串参数值
            for parm in node.parms():
                # 表达式
                try:
                    expr = parm.expression()
                    if attr_name in expr:
                        references.append({
                            "type": "parameter expression",
                            "param": parm.name(),
                            "expr": expr[:80],
                        })
                except Exception:
                    pass
                # 字符串参数值
                try:
                    val = parm.eval()
                    if isinstance(val, str) and attr_name in val and parm.name() != "snippet":
                        references.append({
                            "type": "parameter value",
                            "param": parm.name(),
                            "value": val[:80],
                        })
                except Exception:
                    pass

            if references:
                results.append({
                    "node": node.name(),
                    "node_type": node.type().name(),
                    "path": node.path(),
                    "references": references,
                })

            # 递归搜索子网络
            if recursive and node.children():
                search_in_network(node)

    search_in_network(network)

    return {
        "attribute": attr_name,
        "network": network_path,
        "total_references": len(results),
        "nodes": results,
    }
