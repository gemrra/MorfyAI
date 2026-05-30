# -*- coding: utf-8 -*-
"""Node type introspection skill — build a usable profile for ANY node type.

Given a node type name (native or third-party plugin), returns a structured
"profile": category, inputs (labels), outputs, key parameters (name, label,
type, default, menu options), and whether it's a digital asset (+ library path).

This is the second half of MorfyAI's plugin-awareness: after discover_plugins
finds what's installed, this lets the agent understand an unfamiliar node well
enough to wire it and set its parameters correctly — even plugins MorfyAI has
never seen before. Read-only.
"""

SKILL_INFO = {
    "name": "inspect_node_type",
    "description": (
        "Introspect a node type (native or third-party plugin) and return a usable profile: category, input "
        "port labels, outputs, key parameters (name/label/type/default/menu), and digital-asset info. "
        "Read-only. Use to learn how to wire and parameterize an unfamiliar node — especially plugin nodes "
        "found via discover_plugins — before building with create_node / connect_nodes / set_node_parameter."
    ),
    "parameters": {
        "node_type": {
            "type": "string",
            "description": "Node type name, e.g. 'axiom::axiom_solver', 'mops_instancer', 'pyrosolver'",
            "required": True,
        },
        "category": {
            "type": "string",
            "description": "Node category to look in",
            "enum": ["sop", "obj", "dop", "vop", "cop", "rop", "lop", "any"],
            "default": "any",
        },
        "max_parms": {
            "type": "integer",
            "description": "Maximum number of parameters to return (default 30)",
            "default": 30,
        },
    },
}


def _categories(which):
    import hou  # type: ignore
    table = {
        "sop": hou.sopNodeTypeCategory,
        "obj": hou.objNodeTypeCategory,
        "dop": hou.dopNodeTypeCategory,
        "vop": hou.vopNodeTypeCategory,
        "rop": hou.ropNodeTypeCategory,
        "lop": getattr(hou, "lopNodeTypeCategory", None),
        "cop": getattr(hou, "cop2NodeTypeCategory", None) or getattr(hou, "copNodeTypeCategory", None),
    }
    if which and which != "any":
        fn = table.get(which)
        return [fn()] if fn else []
    cats = []
    for fn in table.values():
        if fn:
            try:
                cats.append(fn())
            except Exception:
                continue
    return cats


def _resolve_type(node_type, category):
    """Find a node type by exact name first, then by suffix/substring match."""
    cats = _categories(category)
    # 1. exact match
    for cat in cats:
        try:
            types = cat.nodeTypes()
        except Exception:
            continue
        if node_type in types:
            return types[node_type]
    # 2. fuzzy: namespaced name ends with the query, or query is a substring
    q = node_type.lower()
    best = None
    for cat in cats:
        try:
            types = cat.nodeTypes()
        except Exception:
            continue
        for name, nt in types.items():
            nl = name.lower()
            if nl == q or nl.endswith("/" + q) or nl.split("::")[-1] == q:
                return nt
            if best is None and q in nl:
                best = nt
    return best


def _parm_profile(ptg, max_parms):
    import hou  # type: ignore
    out = []
    try:
        templates = ptg.entries()
    except Exception:
        return out

    def walk(entries):
        for t in entries:
            if len(out) >= max_parms:
                return
            try:
                # folders: recurse
                if isinstance(t, hou.FolderParmTemplate):
                    walk(t.parmTemplates())
                    continue
                if isinstance(t, hou.SeparatorParmTemplate) or isinstance(t, hou.LabelParmTemplate):
                    continue
                info = {
                    "name": t.name(),
                    "label": t.label(),
                    "type": type(t).__name__.replace("ParmTemplate", ""),
                }
                try:
                    if hasattr(t, "defaultValue"):
                        dv = t.defaultValue()
                        info["default"] = list(dv) if isinstance(dv, (tuple, list)) else dv
                except Exception:
                    pass
                try:
                    if isinstance(t, hou.MenuParmTemplate) or t.menuItems():
                        info["menu"] = list(t.menuItems())[:12]
                except Exception:
                    pass
                out.append(info)
            except Exception:
                continue

    walk(templates)
    return out


def run(node_type, category="any", max_parms=30):
    import hou  # type: ignore

    nt = _resolve_type(node_type, category)
    if nt is None:
        return {"success": False,
                "error": f"node type not found: '{node_type}' (category={category}). "
                         "Try discover_plugins or search_node_types to find the exact name."}

    profile = {
        "success": True,
        "type": nt.name(),
        "label": "",
        "category": "",
        "inputs": [],
        "outputs": [],
        "is_digital_asset": False,
    }
    try:
        profile["label"] = nt.description()
    except Exception:
        pass
    try:
        profile["category"] = nt.category().name()
    except Exception:
        pass

    # input / output labels
    try:
        profile["inputs"] = [{"index": i, "label": lab}
                             for i, lab in enumerate(nt.inputLabels() or [])]
    except Exception:
        pass
    try:
        profile["max_inputs"] = nt.maxNumInputs()
    except Exception:
        pass
    try:
        profile["outputs"] = list(nt.outputLabels() or [])
    except Exception:
        pass

    # digital asset (plugin) info
    try:
        d = nt.definition()
        if d is not None:
            profile["is_digital_asset"] = True
            try:
                profile["library_path"] = d.libraryFilePath()
            except Exception:
                pass
    except Exception:
        pass

    # parameters
    try:
        ptg = nt.parmTemplateGroup()
        profile["parameters"] = _parm_profile(ptg, int(max_parms))
    except Exception:
        profile["parameters"] = []

    profile["message"] = (
        f"{profile['type']} ({profile['category']}) — "
        f"{len(profile['inputs'])} input(s), {len(profile.get('parameters', []))} key parm(s)"
        + (" [plugin HDA]" if profile["is_digital_asset"] else "")
    )
    return profile
