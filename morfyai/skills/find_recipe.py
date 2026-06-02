# -*- coding: utf-8 -*-
"""Recipe finder — read SideFX's own shelf-tool scripts for a concept.

This generalizes the technique that cracked the FLIP and Particle builders:
SideFX shelf tools (and their toolutils helpers) ARE the canonical, working
recipes for building things in Houdini. Instead of guessing node names and
wiring, the model can read the official recipe and adapt it.

Read-only. Given a concept ('fountain', 'fence', 'spiral stair', 'rbd',
'crowd'...), it finds matching shelf tools, returns their scripts, and resolves
the source of the toolutils helper functions they call (one level deep).
"""

SKILL_INFO = {
    "name": "find_recipe",
    "description": (
        "Look up SideFX's OWN node recipe for an UNCOMMON build by reading the matching shelf-tool script. "
        "Use this ONLY when NO dedicated build_* skill fits the request (there are already skills for "
        "pyro/flip/rbd/mpm/vellum/particle/ocean/whitewater sims and for fences — call those directly, NOT "
        "this). Reach for find_recipe for custom modeling / layout / uncommon tools (e.g. spiral stair, "
        "wire/cable, crowd, terrain scatter) where you'd otherwise be guessing node names. Returns the "
        "canonical script + helper sources to adapt deterministically."
    ),
    "parameters": {
        "concept": {
            "type": "string",
            "description": "What you want to build, e.g. 'fountain', 'pop particles', 'rbd fracture', "
                           "'spiral stair', 'scatter trees', 'crowd', 'ocean', 'wire/cable'.",
            "required": True,
        },
        "max_results": {
            "type": "integer",
            "description": "How many matching shelf tools to return (default 4)",
            "default": 4,
        },
    },
}


def _tokens(s):
    import re
    return [t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(t) > 1]


def run(concept="", max_results=4):
    import hou  # type: ignore
    import re

    concept = (concept or "").strip()
    if not concept:
        return {"success": False, "error": "concept is required"}

    want = set(_tokens(concept))
    if not want:
        return {"success": False, "error": f"could not parse concept '{concept}'"}

    # 1. Rank shelf tools by how well name/label match the concept tokens.
    try:
        tools = hou.shelves.tools()
    except Exception as e:
        return {"success": False, "error": f"could not access shelf tools: {e}"}

    scored = []
    for name, tool in tools.items():
        try:
            label = tool.label() or ""
        except Exception:
            label = ""
        hay = set(_tokens(name)) | set(_tokens(label))
        hits = len(want & hay)
        # also reward substring matches (e.g. 'fountain' inside a label)
        sub = sum(1 for w in want if any(w in h for h in hay))
        score = hits * 2 + sub
        if score > 0:
            scored.append((score, name, label, tool))
    scored.sort(key=lambda x: -x[0])

    if not scored:
        return {"success": True, "concept": concept, "matches": [],
                "message": f"No shelf tool matched '{concept}'. Try a broader keyword, or build manually "
                           "after introspecting node types with get_available_node_types."}

    # 2. For the top matches, read the script + resolve directly-called toolutils helpers.
    import importlib, inspect
    HELPER_MODS = ("doptoolutils", "doppoptoolutils", "soptoolutils", "toolutils",
                   "objecttoolutils", "kinefxtoolutils", "crowdtoolutils", "dragdroputils")
    resolved_cache = {}

    def resolve_helpers(script):
        out = {}
        # find  module.func(  references for known toolutils modules
        for mod_name in HELPER_MODS:
            for m in re.finditer(re.escape(mod_name) + r"\.([A-Za-z_][A-Za-z0-9_]*)\s*\(", script):
                fn = m.group(1)
                kkey = f"{mod_name}.{fn}"
                if kkey in out or kkey in resolved_cache:
                    if kkey in resolved_cache:
                        out[kkey] = resolved_cache[kkey]
                    continue
                try:
                    mod = importlib.import_module(mod_name)
                    src = inspect.getsource(getattr(mod, fn))
                    if len(src) > 1800:
                        src = src[:1800] + "\n    # ...(truncated)"
                    out[kkey] = src
                    resolved_cache[kkey] = src
                except Exception:
                    continue
                if len(out) >= 4:
                    return out
        return out

    matches = []
    for score, name, label, tool in scored[: max(1, int(max_results))]:
        try:
            script = tool.script() or ""
        except Exception as e:
            script = f"(could not read script: {e})"
        if len(script) > 2500:
            script = script[:2500] + "\n# ...(truncated)"
        matches.append({
            "name": name,
            "label": label,
            "score": score,
            "script": script,
            "helpers": resolve_helpers(script),
        })

    return {
        "success": True,
        "concept": concept,
        "matches": matches,
        "message": (
            f"Found {len(matches)} SideFX recipe(s) for '{concept}'. Read the script(s) and helper "
            "function source to learn the canonical node recipe, then build + adapt it deterministically. "
            "Verify the result by data (counts/bbox/errors) before reporting success."
        ),
    }
