# -*- coding: utf-8 -*-
"""Houdini core operation layer — shared low-level Houdini API wrappers for server.py and client.py.

Architecture:
    server.py  → external MCP client-facing (via HTTP); returns {status, message, data}
    client.py  → internal AI-agent-facing (direct Python calls); returns {success, result, error}

    This module provides low-level Houdini operation functions with no
    response-format wrapping. The two upper-layer modules wrap them via an
    adaptation layer and format the return values themselves.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

try:
    import hou  # type: ignore
except Exception:
    hou = None  # type: ignore


def hou_available() -> bool:
    """check Houdini API whethercanuse"""
    return hou is not None


def resolve_node(path: str) -> Optional[Any]:
    """viapathgetnode, failedreturn None"""
    if hou is None:
        return None
    try:
        return hou.node(path)
    except Exception:
        return None


def create_node(parent_path: str, node_type: str, node_name: str = "") -> Tuple[bool, str, Optional[Any]]:
    """createnode
    
    Returns:
        (success, message, node_or_None)
    """
    if hou is None:
        return False, "Houdini environmentunavailable", None
    parent = hou.node(parent_path)
    if not parent:
        return False, f"parentnode {parent_path} does not exist", None
    try:
        node = parent.createNode(node_type, node_name or None)
        return True, f"alreadycreatenode {node.path()}", node
    except Exception as e:
        return False, f"createnodefailed: {e}", None


def delete_node(node_path: str) -> Tuple[bool, str]:
    """deletenode"""
    if hou is None:
        return False, "Houdini environmentunavailable"
    node = hou.node(node_path)
    if not node:
        return False, f"node '{node_path}' does not exist"
    try:
        node.destroy()
        return True, f"alreadydeletenode '{node_path}'"
    except Exception as e:
        return False, f"deletefailed: {e}"


def connect_nodes(output_path: str, input_path: str, input_index: int = 0) -> Tuple[bool, str]:
    """connecttwonode"""
    if hou is None:
        return False, "Houdini environmentunavailable"
    output_node = hou.node(output_path)
    input_node = hou.node(input_path)
    if output_node is None:
        return False, f"outputnode '{output_path}' does not exist"
    if input_node is None:
        return False, f"inputnode '{input_path}' does not exist"
    max_inputs = input_node.type().maxNumInputs()
    if input_index < 0 or input_index >= max_inputs:
        return False, f"inputportindex {input_index} invalid (validrange 0~{max_inputs - 1})"
    try:
        input_node.setInput(input_index, output_node, 0)
        return True, f"alreadyconnect {output_path} -> {input_path}[{input_index}]"
    except Exception as e:
        return False, f"connectfailed: {e}"


def set_parameter(node_path: str, param_name: str, value: Any) -> Tuple[bool, str]:
    """setnodeparameter"""
    if hou is None:
        return False, "Houdini environmentunavailable"
    node = hou.node(node_path)
    if not node:
        return False, f"node '{node_path}' does not exist"
    parm = node.parm(param_name)
    if parm is None:
        # try parmTuple
        pt = node.parmTuple(param_name)
        if pt is not None:
            try:
                pt.set(value)
                return True, f"alreadyset {node_path}/{param_name} = {value}"
            except Exception as e:
                return False, f"setfailed: {e}"
        return False, f"parameter '{param_name}' does not exist"
    try:
        parm.set(value)
        return True, f"alreadyset {node_path}/{param_name} = {value}"
    except Exception as e:
        return False, f"setfailed: {e}"


def get_node_info(node_path: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """getnodeinfo"""
    if hou is None:
        return False, "Houdini environmentunavailable", None
    node = hou.node(node_path)
    if not node:
        return False, f"node '{node_path}' does not exist", None
    info = {
        "type": node.type().name(),
        "path": node.path(),
        "inputs": [i.path() for i in node.inputs() if i],
        "outputs": [o.path() for o in node.outputs() if o],
    }
    return True, "querysucceeded", info


def set_display_flag(node_path: str) -> Tuple[bool, str]:
    """setnodeshowflag"""
    if hou is None:
        return False, "Houdini environmentunavailable"
    node = hou.node(node_path)
    if not node:
        return False, f"node '{node_path}' does not exist"
    try:
        node.setDisplayFlag(True)
        node.setRenderFlag(True)
        return True, f"alreadyset {node_path} asshownode"
    except Exception as e:
        return False, f"setfailed: {e}"


def check_errors(node_path: Optional[str] = None) -> Tuple[bool, str, List[str]]:
    """checknodeerror"""
    if hou is None:
        return False, "Houdini environmentunavailable", []
    if node_path:
        node = hou.node(node_path)
        if not node:
            return False, f"node '{node_path}' does not exist", []
        errors = node.errors() or []
        return True, ("saveinerror" if errors else "noerror"), errors
    else:
        error_nodes = []
        for n in hou.node('/').allSubChildren():
            try:
                if n.errors():
                    error_nodes.append(n.path())
            except Exception:
                continue
        return True, (f"discover {len(error_nodes)} errornode" if error_nodes else "noerrornode"), error_nodes


def layout_children(parent_path: str) -> Tuple[bool, str]:
    """autolayoutsubnode"""
    if hou is None:
        return False, "Houdini environmentunavailable"
    parent = hou.node(parent_path)
    if not parent:
        return False, f"node '{parent_path}' does not exist"
    try:
        parent.layoutChildren()
        return True, f"alreadyautolayout {parent_path}  subnode"
    except Exception as e:
        return False, f"layoutfailed: {e}"


# ============================================================
# nodelayouttool
# ============================================================

def layout_nodes(
    parent_path: str = "",
    node_paths: Optional[List[str]] = None,
    method: str = "auto",
    spacing: float = 1.0,
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """multistrategynodelayout

    Args:
        parent_path: parentnetwork path, keepemptyusecurrentactivenetwork
        node_paths: needlayout node pathlist; asemptywhenlayoutwholenetwork
        method: layoutmethod auto / grid / columns
        spacing: spacing multiplier (default 1.0)

    Returns:
        (success, message, positions_list)
        positions_list ineachitem: {name, path, x, y}
    """
    if hou is None:
        return False, "Houdini environmentunavailable", []

    # parseparentnetwork
    parent = None
    if parent_path:
        parent = hou.node(parent_path)
    if parent is None:
        # trycurrentnetworkedit   pwd
        try:
            editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
            if editor:
                parent = editor.pwd()
        except Exception:
            pass
    if parent is None:
        try:
            parent = hou.node("/obj")
        except Exception:
            pass
    if parent is None:
        return False, "notfindtotargetnetwork", []

    try:
        # ---------- collectsettargetnode ----------
        if node_paths:
            nodes = [hou.node(p) for p in node_paths if hou.node(p)]
            if not nodes:
                return False, "All specified node paths are invalid", []
        else:
            nodes = list(parent.children())
            if not nodes:
                return False, f"{parent.path()} belownothassubnode", []

        # ---------- executelayout ----------
        layout_method_used = method

        if method == "auto":
            if node_paths:
                # hasspecifiednode → preferreduse NetworkEditor.layoutNodes
                try:
                    editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
                    if editor and hasattr(editor, "layoutNodes"):
                        editor.layoutNodes(nodes)
                        layout_method_used = "NetworkEditor.layoutNodes"
                    else:
                        raise AttributeError("layoutNodes unavailable")
                except Exception:
                    # downgrade: one by one moveToGoodPosition
                    for n in nodes:
                        try:
                            n.moveToGoodPosition()
                        except Exception:
                            pass
                    layout_method_used = "moveToGoodPosition"
            else:
                # allnetwork → layoutChildren (supportbetweendistance) 
                h_sp = 2.0 * spacing
                v_sp = 1.0 * spacing
                try:
                    parent.layoutChildren(
                        horizontal_spacing=h_sp,
                        vertical_spacing=v_sp,
                    )
                    layout_method_used = "layoutChildren"
                except TypeError:
                    # oldversion Houdini maynot supportedbetweendistanceparameter
                    parent.layoutChildren()
                    layout_method_used = "layoutChildren(no-spacing)"

        elif method == "grid":
            _layout_grid(nodes, spacing)
            layout_method_used = "grid"

        elif method == "columns":
            _layout_columns(nodes, spacing)
            layout_method_used = "columns"

        else:
            return False, f"notknowlayoutmethod: {method}", []

        # ---------- collectsetresultposition ----------
        positions = []
        for n in nodes:
            pos = n.position()
            positions.append({
                "name": n.name(),
                "path": n.path(),
                "x": round(pos[0], 3),
                "y": round(pos[1], 3),
            })

        return (
            True,
            f"alreadylayout {len(nodes)} node (method: {layout_method_used}) ",
            positions,
        )

    except Exception as e:
        return False, f"layoutfailed: {e}", []


def _layout_grid(nodes: list, spacing: float = 1.0) -> None:
    """netgridlayout: bynodelistorderorderarrangebecome N columnnetgrid"""
    if not nodes:
        return
    import math
    cols = max(1, int(math.ceil(math.sqrt(len(nodes)))))
    h_sp = 3.5 * spacing
    v_sp = 1.5 * spacing
    for idx, node in enumerate(nodes):
        col = idx % cols
        row = idx // cols
        node.setPosition(hou.Vector2(col * h_sp, -row * v_sp))


def _layout_columns(nodes: list, spacing: float = 1.0) -> None:
    """Topological depth-based column layout: root nodes go on the first column, descendants flow downward column by column."""
    if not nodes:
        return
    node_set = set(id(n) for n in nodes)

    # computeeachnode depth (inputchainlength) 
    depth_map: Dict[int, int] = {}

    def _depth(n) -> int:
        nid = id(n)
        if nid in depth_map:
            return depth_map[nid]
        inputs = [inp for inp in (n.inputs() or []) if inp and id(inp) in node_set]
        if not inputs:
            depth_map[nid] = 0
            return 0
        d = max(_depth(inp) for inp in inputs) + 1
        depth_map[nid] = d
        return d

    for n in nodes:
        _depth(n)

    # bydepthgroup
    layers: Dict[int, list] = {}
    for n in nodes:
        d = depth_map.get(id(n), 0)
        layers.setdefault(d, []).append(n)

    h_sp = 3.5 * spacing
    v_sp = 2.0 * spacing
    for depth in sorted(layers.keys()):
        layer_nodes = layers[depth]
        for idx, node in enumerate(layer_nodes):
            x = (idx - len(layer_nodes) / 2.0 + 0.5) * h_sp
            y = -depth * v_sp
            node.setPosition(hou.Vector2(x, y))


def get_node_positions(
    parent_path: str = "",
    node_paths: Optional[List[str]] = None,
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """getnodepositioninfo

    Args:
        parent_path: parentnetwork path (when node_paths asemptywhenuse) 
        node_paths: specialfixednode pathlist

    Returns:
        (success, message, positions_list)
        positions_list eachitem: {name, path, x, y, type}
    """
    if hou is None:
        return False, "Houdini environmentunavailable", []

    nodes = []
    if node_paths:
        for p in node_paths:
            n = hou.node(p)
            if n:
                nodes.append(n)
        if not nodes:
            return False, "All specified node paths are invalid", []
    else:
        parent = hou.node(parent_path) if parent_path else None
        if parent is None:
            try:
                editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
                if editor:
                    parent = editor.pwd()
            except Exception:
                pass
        if parent is None:
            return False, "notfindtotargetnetwork", []
        nodes = list(parent.children())
        if not nodes:
            return False, f"{parent.path()} belownothassubnode", []

    positions = []
    for n in nodes:
        pos = n.position()
        positions.append({
            "name": n.name(),
            "path": n.path(),
            "x": round(pos[0], 3),
            "y": round(pos[1], 3),
            "type": n.type().name(),
        })

    return True, f"get {len(positions)} node position", positions


# ============================================================
# NetworkBox operation
# ============================================================

# NetworkBox semanticcolorpre-set
_BOX_COLORS: Dict[str, Tuple[float, float, float]] = {
    "input":      (0.2, 0.4, 0.8),   # bluecolor - datainput
    "processing": (0.3, 0.7, 0.3),   # greencolor - geometryprocess
    "deform":     (0.8, 0.6, 0.2),   # orangecolor - changeshape/movedraw
    "output":     (0.7, 0.2, 0.3),   # redcolor - output/render
    "simulation": (0.6, 0.3, 0.7),   # purplecolor - physicssimulation
    "utility":    (0.5, 0.5, 0.5),   # graycolor - helpertool
}


def create_network_box(
    parent_path: str,
    name: str = "",
    comment: str = "",
    color_preset: str = "",
    node_paths: Optional[List[str]] = None
) -> Tuple[bool, str, Optional[Any]]:
    """create NetworkBox andoptionalplacewillnodeaddenteritsin

    Args:
        parent_path: parentnetwork path (such as /obj/geo1) 
        name: box name
        comment: comment (shown in the title bar, describes what this node group does)
        color_preset: colorpre-set (input/processing/deform/output/simulation/utility) 
        node_paths: needaddenter box  node pathlist

    Returns:
        (success, message, network_box_or_None)
    """
    if hou is None:
        return False, "Houdini environmentunavailable", None

    parent = hou.node(parent_path)
    if not parent:
        return False, f"parentnetwork '{parent_path}' does not exist", None

    try:
        box = parent.createNetworkBox(name or None)

        if comment:
            box.setComment(comment)

        # setcolor
        if color_preset and color_preset in _BOX_COLORS:
            r, g, b = _BOX_COLORS[color_preset]
            box.setColor(hou.Color((r, g, b)))

        # addnode
        added = []
        if node_paths:
            for np in node_paths:
                node = hou.node(np)
                if node:
                    box.addNode(node)
                    added.append(np)

            if added:
                box.fitAroundContents()

        msg = f"alreadycreate NetworkBox: {box.name()}"
        if comment:
            msg += f" ({comment})"
        if added:
            msg += f", packagecontaining {len(added)} node"

        return True, msg, box
    except Exception as e:
        return False, f"create NetworkBox failed: {e}", None


def add_nodes_to_box(
    parent_path: str,
    box_name: str,
    node_paths: List[str],
    auto_fit: bool = True
) -> Tuple[bool, str]:
    """willnodeaddtoalreadyhas  NetworkBox

    Args:
        parent_path: parentnetwork path
        box_name: target NetworkBox name
        node_paths: needadd node pathlist
        auto_fit: whetherautoadjustwhole box largesmall

    Returns:
        (success, message)
    """
    if hou is None:
        return False, "Houdini environmentunavailable"

    parent = hou.node(parent_path)
    if not parent:
        return False, f"parentnetwork '{parent_path}' does not exist"

    # lookup NetworkBox
    target_box = None
    for box in parent.networkBoxes():
        if box.name() == box_name:
            target_box = box
            break

    if not target_box:
        return False, f"notfindto NetworkBox: {box_name}"

    added = []
    for np in node_paths:
        node = hou.node(np)
        if node:
            target_box.addNode(node)
            added.append(np)

    if auto_fit and added:
        target_box.fitAroundContents()

    return True, f"alreadywill {len(added)} nodeaddto {box_name}"


def list_network_boxes(parent_path: str) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """columnoutnetworkinall NetworkBox anditscontent

    Args:
        parent_path: parentnetwork path

    Returns:
        (success, message, boxes_info_list)
    """
    if hou is None:
        return False, "Houdini environmentunavailable", []

    parent = hou.node(parent_path)
    if not parent:
        return False, f"parentnetwork '{parent_path}' does not exist", []

    boxes_info = []
    for box in parent.networkBoxes():
        nodes = box.nodes()
        boxes_info.append({
            "name": box.name(),
            "comment": box.comment() or "",
            "node_count": len(nodes),
            "nodes": [n.path() for n in nodes],
            "minimized": box.isMinimized(),
        })

    return True, f"findto {len(boxes_info)}  NetworkBox", boxes_info