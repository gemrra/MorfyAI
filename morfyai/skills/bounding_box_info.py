# -*- coding: utf-8 -*-
"""Bounding box info skill

Compute geometry bounding box, center, size, diagonal length, volume, surface area, aspect ratio, etc.
"""

SKILL_INFO = {
    "name": "get_bounding_info",
    "description": (
        "Get bounding box info: min/max/center/size/diagonal/volume/surface area/aspect/longest axis/shortest axis. "
        "For checking model size, alignment, and scale. "
    ),
    "parameters": {
        "node_path": {
            "type": "string",
            "description": "Node path, e.g. /obj/geo1/box1",
            "required": True,
        },
    },
}


def run(node_path):
    """Entry point

    Args:
        node_path: node path
    """
    import hou  # type: ignore

    node = hou.node(node_path)
    if not node:
        return {"error": f"Node does not exist: {node_path}"}

    geo = node.geometry()
    if not geo:
        return {"error": "Cannot fetch geometry"}

    bbox = geo.boundingBox()

    min_pt = bbox.minvec()
    max_pt = bbox.maxvec()
    center = bbox.center()
    size = bbox.sizevec()

    diagonal = size.length()
    volume = size[0] * size[1] * size[2]
    surface_area = 2 * (size[0] * size[1] + size[1] * size[2] + size[0] * size[2])

    axes = {"X": size[0], "Y": size[1], "Z": size[2]}
    longest_axis = max(axes, key=axes.get)
    shortest_axis = min(axes, key=axes.get)

    return {
        "node_path": node_path,
        "min": [round(v, 4) for v in min_pt],
        "max": [round(v, 4) for v in max_pt],
        "center": [round(v, 4) for v in center],
        "size": [round(v, 4) for v in size],
        "diagonal": round(diagonal, 4),
        "bbox_volume": round(volume, 4),
        "bbox_surface_area": round(surface_area, 4),
        "longest_axis": longest_axis,
        "shortest_axis": shortest_axis,
        "aspect_ratio": round(max(size) / max(min(size), 0.0001), 4),
    }
