# -*- coding: utf-8 -*-
"""Import a geometry file from disk into a new geometry object.

Mutating — creates a /obj/geo object with a loader SOP inside.
"""

SKILL_INFO = {
    "name": "import_geo_file",
    "description": (
        "Create a new geometry object in /obj and load a file from disk into it. Uses an Alembic SOP for "
        ".abc, otherwise a File SOP (handles .bgeo/.bgeo.sc/.obj/.ply/.fbx/.vdb/.usd where supported). "
        "Use to bring an external asset into the scene."
    ),
    "parameters": {
        "file_path": {
            "type": "string",
            "description": "Absolute path to the geometry file on disk.",
            "required": True,
        },
        "name": {
            "type": "string",
            "description": "Name for the new object. Defaults to the file's base name.",
            "default": "",
        },
    },
}


def _apply(node, parms):
    missing = []
    for k, v in parms.items():
        p = node.parm(k) or node.parmTuple(k)
        if p is None:
            missing.append(k)
            continue
        try:
            p.set(v)
        except Exception:
            missing.append(k)
    return missing


def run(file_path="", name=""):
    import hou  # type: ignore
    import os

    if not file_path:
        return {"success": False, "error": "file_path is required"}

    exists = os.path.exists(file_path)
    base = name or os.path.splitext(os.path.basename(file_path))[0] or "imported"
    # Sanitize to a legal node name.
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in base) or "imported"

    obj = hou.node("/obj")
    if obj is None:
        return {"success": False, "error": "/obj context not found"}
    try:
        geo = obj.createNode("geo", node_name=safe)
    except Exception as e:
        return {"success": False, "error": f"could not create geo object: {e}"}

    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == ".abc":
            loader = geo.createNode("alembic", node_name="import")
            missing = _apply(loader, {"fileName": file_path})
        else:
            loader = geo.createNode("file", node_name="import")
            missing = _apply(loader, {"file": file_path})
    except Exception as e:
        return {"success": False, "error": f"could not create loader SOP: {e}", "object": geo.path()}

    try:
        loader.moveToGoodPosition()
        loader.setDisplayFlag(True)
        loader.setRenderFlag(True)
    except Exception:
        pass

    return {
        "success": True,
        "object": geo.path(),
        "node": loader.path(),
        "loader_type": loader.type().name(),
        "file_exists": exists,
        "unset_parms": missing,
        "warning": None if exists else f"file not found on disk: {file_path}",
        "verdict": (f"Imported into {loader.path()}." if exists
                    else f"Loader created at {loader.path()}, but the file does not exist yet: {file_path}"),
    }
