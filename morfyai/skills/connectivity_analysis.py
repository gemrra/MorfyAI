# -*- coding: utf-8 -*-
"""Connectivity analysis skill

Analyze geometry connectivity: how many independent connected parts, and the points/prims per part.
Prefers an existing 'class' attribute (from a Connectivity node); otherwise uses union-find.
"""

SKILL_INFO = {
    "name": "analyze_connectivity",
    "description": (
        "Analyze geometry connectivity: number of independent parts, points/prims/ratio per part. "
        "Uses the existing 'class' attribute if present, otherwise computes via union-find. "
        "Useful for detecting fragments, separated meshes, and analyzing fracture effects."
    ),
    "parameters": {
        "node_path": {
            "type": "string",
            "description": "Node path, e.g. /obj/geo1/pighead1",
            "required": True,
        },
    },
}


def _analyze_with_class(geo, class_attrib):
    """使用已有的 class 属性Analyze"""
    import hou  # type: ignore

    is_prim = (class_attrib.type() == hou.attribType.Prim)

    if is_prim:
        classes = geo.primIntAttribValues("class") if class_attrib.dataType() == hou.attribData.Int else geo.primFloatAttribValues("class")
    else:
        classes = geo.pointIntAttribValues("class") if class_attrib.dataType() == hou.attribData.Int else geo.pointFloatAttribValues("class")

    unique_classes = sorted(set(classes))
    components = []

    for c in unique_classes:
        if is_prim:
            prim_count = sum(1 for v in classes if v == c)
            # 通过 prim 的顶点获取关联的点
            point_set = set()
            for prim in geo.iterPrims():
                if prim.attribValue("class") == c:
                    for v in prim.vertices():
                        point_set.add(v.point().number())
            point_count = len(point_set)
        else:
            point_count = sum(1 for v in classes if v == c)
            prim_count = 0

        components.append({
            "id": c,
            "point_count": point_count,
            "prim_count": prim_count,
        })

    return {
        "method": "class_attribute",
        "total_components": len(unique_classes),
        "total_points": geo.intrinsicValue("pointcount"),
        "total_prims": geo.intrinsicValue("primitivecount"),
        "components": components[:20],
    }


def _analyze_with_union_find(geo):
    """使用并查集算法计算连通性"""
    n = geo.intrinsicValue("pointcount")
    num_prims = geo.intrinsicValue("primitivecount")

    if n == 0:
        return {"error": "Geometry has no points"}

    # 并查集
    parent = list(range(n))

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    # 通过面的顶点建立连接
    for prim in geo.iterPrims():
        pt_nums = [v.point().number() for v in prim.vertices()]
        if len(pt_nums) > 1:
            for i in range(1, len(pt_nums)):
                union(pt_nums[0], pt_nums[i])

    # 统计连通分量
    comp_points = {}
    for i in range(n):
        root = find(i)
        if root not in comp_points:
            comp_points[root] = []
        comp_points[root].append(i)

    # 统计每个分量的面数
    comp_prims = {root: set() for root in comp_points}
    for prim in geo.iterPrims():
        verts = list(prim.vertices())
        if verts:
            pt_num = verts[0].point().number()
            root = find(pt_num)
            comp_prims[root].add(prim.number())

    # 整理result (按点数降序)
    components = []
    for root in sorted(comp_points.keys(), key=lambda r: -len(comp_points[r])):
        components.append({
            "point_count": len(comp_points[root]),
            "prim_count": len(comp_prims[root]),
            "point_ratio": round(len(comp_points[root]) / n * 100, 2),
        })

    return {
        "method": "union_find",
        "total_components": len(components),
        "total_points": n,
        "total_prims": num_prims,
        "components": components[:20],
    }


def run(node_path):
    """Entry point

    Args:
        node_path: 节点路径
    """
    import hou  # type: ignore

    node = hou.node(node_path)
    if not node:
        return {"error": f"Node does not exist: {node_path}"}

    geo = node.geometry()
    if not geo:
        return {"error": "Cannot fetch geometry"}

    # 优先使用 class 属性
    class_attrib = geo.findPrimAttrib("class")
    if not class_attrib:
        class_attrib = geo.findPointAttrib("class")

    if class_attrib:
        result = _analyze_with_class(geo, class_attrib)
    else:
        result = _analyze_with_union_find(geo)

    result["node_path"] = node_path
    return result
