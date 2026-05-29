# -*- coding: utf-8 -*-
"""Generic geometry attribute analysis skill

Analyze attribute statistics on a Houdini node's geometry; supports
point/vertex/prim/detail attribute categories.
Without an attribute name, returns the attribute list; with one, returns
statistics (min/max/mean/std/nan/inf).
"""

SKILL_INFO = {
    "name": "analyze_geometry_attribs",
    "description": (
        "Analyze node geometry attributes. Supports point/vertex/prim/detail categories. "
        "Without attrib_name, returns attribute list; with attrib_name returns stats (min/max/mean/std/nan/inf). "
    ),
    "parameters": {
        "node_path": {
            "type": "string",
            "description": "Node path, e.g. /obj/geo1/box1",
            "required": True,
        },
        "attrib_name": {
            "type": "string",
            "description": "Attribute name (e.g. P, N, uv, Cd). leave empty to list attributes of the category",
            "required": False,
        },
        "attrib_class": {
            "type": "string",
            "description": "attribute category: point, vertex, prim, detail (default point)",
            "required": False,
        },
        "max_sample": {
            "type": "integer",
            "description": "Max sample count (default 100000, randomly sampled above this)",
            "required": False,
        },
    },
}


def run(node_path, attrib_name=None, attrib_class="point", max_sample=100000):
    """Entry point

    Args:
        node_path: node path
        attrib_name: attribute name (None to return the attribute list)
        attrib_class: attribute category - point/vertex/prim/detail
        max_sample: max sample count
    """
    import hou  # type: ignore
    import numpy as np

    node = hou.node(node_path)
    if not node:
        return {"error": f"Node does not exist: {node_path}"}

    geo = node.geometry()
    if not geo:
        return {"error": "Cannot fetch geometry"}

    # Attribute category map
    attrib_map = {
        "point": (
            geo.findPointAttrib,
            geo.pointFloatAttribValues,
            geo.pointIntAttribValues,
            geo.pointStringAttribValues,
            geo.intrinsicValue("pointcount"),
        ),
        "vertex": (
            geo.findVertexAttrib,
            geo.vertexFloatAttribValues,
            geo.vertexIntAttribValues,
            geo.vertexStringAttribValues,
            geo.intrinsicValue("vertexcount"),
        ),
        "prim": (
            geo.findPrimAttrib,
            geo.primFloatAttribValues,
            geo.primIntAttribValues,
            geo.primStringAttribValues,
            geo.intrinsicValue("primitivecount"),
        ),
        "detail": (
            geo.findGlobalAttrib,
            None,
            None,
            None,
            1,
        ),
    }

    if attrib_class not in attrib_map:
        return {"error": f"Invalid attribute category: {attrib_class}, options: point, vertex, prim, detail"}

    find_func, float_func, int_func, str_func, elem_count = attrib_map[attrib_class]

    # If no attribute name given, return the attribute list
    if attrib_name is None:
        attrib_list_map = {
            "point": geo.pointAttribs,
            "vertex": geo.vertexAttribs,
            "prim": geo.primAttribs,
            "detail": geo.globalAttribs,
        }
        attribs = attrib_list_map[attrib_class]()
        return {
            "node_path": node_path,
            "attrib_class": attrib_class,
            "element_count": elem_count,
            "attribs": [
                {
                    "name": a.name(),
                    "size": a.size(),
                    "type": str(a.dataType()).split(".")[-1],
                }
                for a in attribs
            ],
        }

    # Look up the requested attribute
    attrib = find_func(attrib_name)
    if not attrib:
        return {"error": f"Attribute does not exist: {attrib_name} (category: {attrib_class})"}

    size = attrib.size()
    data_type = str(attrib.dataType()).split(".")[-1]

    # Detail attributes get special-case handling
    if attrib_class == "detail":
        if data_type == "Float":
            val = (
                geo.floatAttribValue(attrib_name)
                if size == 1
                else list(geo.floatListAttribValue(attrib_name))
            )
        elif data_type == "Int":
            val = (
                geo.intAttribValue(attrib_name)
                if size == 1
                else list(geo.intListAttribValue(attrib_name))
            )
        else:
            val = (
                geo.stringAttribValue(attrib_name)
                if size == 1
                else list(geo.stringListAttribValue(attrib_name))
            )
        return {
            "node_path": node_path,
            "name": attrib_name,
            "type": data_type,
            "size": size,
            "value": val,
        }

    # Fetch attribute values
    if data_type == "Float":
        vals = np.array(float_func(attrib_name))
    elif data_type == "Int":
        vals = np.array(int_func(attrib_name))
    else:  # String
        vals = str_func(attrib_name)
        unique = list(set(vals))
        return {
            "node_path": node_path,
            "name": attrib_name,
            "type": "String",
            "count": len(vals),
            "unique_count": len(unique),
            "unique_values": unique[:20],
        }

    # Reshape multi-dimensional attributes
    if size > 1:
        vals = vals.reshape((-1, size))

    # Sample (for large datasets)
    max_sample = min(int(max_sample), 500000)
    n = len(vals) if vals.ndim == 1 else vals.shape[0]
    sampled = False
    if n > max_sample:
        idx = np.random.choice(n, max_sample, replace=False)
        vals = vals[idx] if vals.ndim == 1 else vals[idx, :]
        sampled = True

    # Return summary statistics
    result = {
        "node_path": node_path,
        "name": attrib_name,
        "type": data_type,
        "size": size,
        "count": int(n),
        "sampled": sampled,
        "min": vals.min(axis=0).tolist() if size > 1 else float(vals.min()),
        "max": vals.max(axis=0).tolist() if size > 1 else float(vals.max()),
        "mean": vals.mean(axis=0).tolist() if size > 1 else float(vals.mean()),
        "std": vals.std(axis=0).tolist() if size > 1 else float(vals.std()),
    }

    # NaN/Inf detection (float only)
    if data_type == "Float":
        result["nan_count"] = int(np.isnan(vals).sum())
        result["inf_count"] = int(np.isinf(vals).sum())

    return result
