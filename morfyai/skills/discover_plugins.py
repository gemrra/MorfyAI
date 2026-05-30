# -*- coding: utf-8 -*-
"""Plugin discovery skill — find installed third-party node libraries.

Scans the HDA libraries loaded into the current Houdini session, filters out
the ones shipped with Houdini ($HFS), and reports the third-party node types
available — grouped by library file. This is how MorfyAI becomes "plugin-aware":
it can see what the user actually installed (Axiom, Paradigm, MoPs, qLib, …)
and then use those nodes via inspect_node_type + the standard create tools.

Read-only. Never modifies the scene.
"""

SKILL_INFO = {
    "name": "discover_plugins",
    "description": (
        "Discover installed third-party Houdini plugins / HDA libraries (e.g. Axiom, Paradigm, MoPs, qLib, "
        "SideFX Labs). Returns the node types each library provides, grouped by file, and tags well-known "
        "plugins. Read-only. Use to find out which non-native nodes are available before building with them, "
        "or when the user mentions a plugin you should use."
    ),
    "parameters": {
        "filter": {
            "type": "string",
            "description": "Optional keyword to filter node types / libraries (e.g. 'axiom', 'mops'). Empty = list all third-party.",
            "default": "",
        },
    },
}


# well-known plugin signatures: keyword -> friendly name
_KNOWN = {
    "axiom": "Axiom (GPU pyro/fluid)",
    "paradigm": "Paradigm (GPU FLIP liquid)",
    "mops": "MOPs (motion graphics)",
    "qlib": "qLib (helper nodes)",
    "aelib": "aelib",
    "sidefxlabs": "SideFX Labs",
    "labs": "SideFX Labs",
    "redshift": "Redshift",
    "octane": "Octane",
}


def _tag_known(text):
    t = (text or "").lower()
    for kw, name in _KNOWN.items():
        if kw in t:
            return name
    return None


def run(filter=""):
    import hou  # type: ignore
    import os

    flt = (filter or "").lower().strip()

    # Houdini install root — anything under here is "native", not third-party
    hfs = ""
    try:
        hfs = os.path.normcase(os.path.normpath(hou.expandString("$HFS")))
    except Exception:
        pass

    try:
        loaded = list(hou.hda.loadedFiles())
    except Exception as e:
        return {"success": False, "error": f"could not read loaded HDA files: {e}"}

    libraries = []
    known_found = {}

    for path in loaded:
        if not path or path == "Embedded":
            continue
        norm = os.path.normcase(os.path.normpath(path))
        # skip Houdini's own libraries
        if hfs and norm.startswith(hfs):
            continue

        try:
            defs = hou.hda.definitionsInFile(path)
        except Exception:
            defs = []

        node_types = []
        for d in defs:
            try:
                tname = d.nodeTypeName()
                cat = d.nodeTypeCategory().name()
                label = ""
                try:
                    label = d.description() or ""
                except Exception:
                    pass
                node_types.append({"type": tname, "category": cat, "label": label})
            except Exception:
                continue

        if not node_types:
            continue

        fname = os.path.basename(path)
        known = _tag_known(path) or _tag_known(" ".join(n["type"] for n in node_types))

        # apply filter
        if flt:
            hay = (path + " " + " ".join(n["type"] + " " + n["label"] for n in node_types)).lower()
            if flt not in hay:
                continue

        if known:
            known_found[known] = known_found.get(known, 0) + len(node_types)

        libraries.append({
            "file": fname,
            "path": path,
            "known_plugin": known,
            "node_type_count": len(node_types),
            "node_types": node_types[:40],  # cap to keep context lean
        })

    libraries.sort(key=lambda x: (x["known_plugin"] is None, x["file"].lower()))
    total_types = sum(l["node_type_count"] for l in libraries)

    return {
        "success": True,
        "third_party_library_count": len(libraries),
        "third_party_node_type_count": total_types,
        "known_plugins": sorted(known_found.keys()),
        "libraries": libraries,
        "message": (
            f"Found {len(libraries)} third-party HDA librar"
            f"{'y' if len(libraries) == 1 else 'ies'} "
            f"({total_types} node types)."
            + (f" Known: {', '.join(sorted(known_found.keys()))}." if known_found else "")
            + " Use inspect_node_type to learn how to build with any of them."
        ),
    }
