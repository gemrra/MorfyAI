# -*- coding: utf-8 -*-
"""Cook performance analysis skill

遍历网络中所有节点, 收集 cook 时间、cook 次数、几何体大小等指标, 
识别瓶颈节点 and 几何体膨胀点, Return结构化Analyze报告. 

不依赖 hou.perfMon, 直接使用 node.lastCookTime() 等 HOM API, 
适合快速诊断场景. 
"""

SKILL_INFO = {
    "name": "analyze_cook_performance",
    "description": (
        "Analyze cook performance for all nodes in a network: timing rank, geometry growth, "
        "error/warning nodes, total cook time. For performance diagnosis and optimization."
    ),
    "parameters": {
        "network_path": {
            "type": "string",
            "description": "Network path, e.g. /obj/geo1",
            "required": True,
        },
        "top_n": {
            "type": "integer",
            "description": "Return top N slowest nodes (default 10)",
            "required": False,
        },
        "force_cook": {
            "type": "boolean",
            "description": "Force re-cook before analyzing to get latest data (default false)",
            "required": False,
        },
    },
}


def run(network_path, top_n=10, force_cook=False):
    """Analyze network cook performance

    Args:
        network_path: 网络路径
        top_n: Return最慢的前 N 个节点
        force_cook: 是否强制 cook
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
            "total_cook_time_ms": 0,
            "slow_nodes": [],
            "geometry_growth": [],
            "error_nodes": [],
            "suggestions": ["Network is empty, no nodes to analyze."],
        }

    # options: 强制 cook 以获取最新数据
    if force_cook:
        # 找到 display 节点并强制 cook 整条链
        display_node = None
        for node in children:
            if node.isDisplayFlagSet():
                display_node = node
                break
        if display_node:
            try:
                display_node.cook(force=True)
            except Exception:
                pass  # cook 可能因节点错误而失败, 继续Analyze

    # ---- 收集数据 ----
    node_data = []
    error_nodes = []

    for node in children:
        info = {
            "name": node.name(),
            "type": node.type().name(),
            "path": node.path(),
        }

        # cook 时间 (毫秒)
        try:
            info["cook_time_ms"] = round(node.lastCookTime() * 1000, 3)
        except Exception:
            info["cook_time_ms"] = 0.0

        # cook 次数
        try:
            info["cook_count"] = node.cookCount()
        except Exception:
            info["cook_count"] = 0

        # 几何体大小
        try:
            geo = node.geometry()
            if geo:
                info["points"] = geo.intrinsicValue("pointcount")
                info["prims"] = geo.intrinsicValue("primitivecount")
            else:
                info["points"] = 0
                info["prims"] = 0
        except Exception:
            info["points"] = 0
            info["prims"] = 0

        # 是否 time dependent
        try:
            info["time_dependent"] = node.isTimeDependent()
        except Exception:
            info["time_dependent"] = False

        # 错误 / 警告
        has_error = False
        has_warning = False
        try:
            errs = node.errors()
            warns = node.warnings()
            has_error = bool(errs)
            has_warning = bool(warns)
        except Exception:
            pass

        if has_error or has_warning:
            error_nodes.append({
                "name": info["name"],
                "path": info["path"],
                "type": info["type"],
                "has_error": has_error,
                "has_warning": has_warning,
            })

        node_data.append(info)

    # ---- 按 cook 时间降序排列 ----
    node_data.sort(key=lambda x: x["cook_time_ms"], reverse=True)
    total_cook_time = sum(n["cook_time_ms"] for n in node_data)
    slow_nodes = node_data[:top_n]

    # ---- 检测几何体膨胀点 ----
    # 沿连接链追踪, 找到输出点数远大于输入点数的节点
    geometry_growth = []
    for node_obj in children:
        try:
            inputs = node_obj.inputs()
            if not inputs:
                continue
            # 取第一个有效输入
            input_node = inputs[0]
            if input_node is None:
                continue
            out_geo = node_obj.geometry()
            in_geo = input_node.geometry()
            if out_geo is None or in_geo is None:
                continue

            out_pts = out_geo.intrinsicValue("pointcount")
            in_pts = in_geo.intrinsicValue("pointcount")

            if in_pts > 0 and out_pts > in_pts * 2:
                ratio = round(out_pts / in_pts, 2)
                geometry_growth.append({
                    "name": node_obj.name(),
                    "path": node_obj.path(),
                    "type": node_obj.type().name(),
                    "input_points": in_pts,
                    "output_points": out_pts,
                    "growth_ratio": ratio,
                })
        except Exception:
            continue

    geometry_growth.sort(key=lambda x: x["growth_ratio"], reverse=True)

    # ---- 生成建议 ----
    suggestions = []

    if slow_nodes and slow_nodes[0]["cook_time_ms"] > 100:
        top = slow_nodes[0]
        suggestions.append(
            f"Slowest node {top['name']}({top['type']}) took {top['cook_time_ms']:.1f}ms, "
            f"Consider adding a Cache node after it to reduce redundant cooks."
        )

    time_dep_count = sum(1 for n in node_data if n.get("time_dependent"))
    if time_dep_count > 3:
        suggestions.append(
            f"{time_dep_count} time-dependent node(s), "
            "Check for unnecessary time expressions causing per-frame cook."
        )

    if geometry_growth:
        worst = geometry_growth[0]
        suggestions.append(
            f"Node {worst['name']} grew geometry from {worst['input_points']} points to "
            f"{worst['output_points']} points (x{worst['growth_ratio']}), "
            "Consider lowering subdivision/scatter count or using Packed Primitives."
        )

    if error_nodes:
        err_names = ", ".join(n["name"] for n in error_nodes[:3])
        suggestions.append(
            f"{len(error_nodes)}  error/warning node(s) ({err_names}), "
            "Error nodes can cause cascading cook issues upstream/downstream."
        )

    # 检测 Python SOP (性能远低于 VEX)
    python_sops = [
        n for n in node_data
        if "python" in n["type"].lower() and n["cook_time_ms"] > 10
    ]
    if python_sops:
        names = ", ".join(n["name"] for n in python_sops[:3])
        suggestions.append(
            f"Detected Python SOP node(s) ({names}), "
            "Python SOP is much slower than VEX — consider replacing with Wrangle."
        )

    if not suggestions:
        suggestions.append("No obvious performance bottleneck detected.")

    return {
        "network": network_path,
        "total_nodes": len(node_data),
        "total_cook_time_ms": round(total_cook_time, 3),
        "bottleneck_count": sum(1 for n in node_data if n["cook_time_ms"] > 50),
        "slow_nodes": slow_nodes,
        "geometry_growth": geometry_growth[:5],
        "error_nodes": error_nodes,
        "time_dependent_count": sum(1 for n in node_data if n.get("time_dependent")),
        "suggestions": suggestions,
    }
