# -*- coding: utf-8 -*-
"""Roles manager — switchable AI personas for MorfyAI.

A "role" is a small system-prompt block appended to the base prompt that biases
how the assistant works (e.g. HDA Architect, VEX Debugger, Technical Writer).
This mirrors Radu Cius' roles/styles feature but stays purely additive and
fully defensive: any failure returns an empty injection so the base behavior is
unchanged and the panel can never be broken by this module.

Selection is config-driven (config/houdini_ai.ini → [roles]), so it works with
no UI. A header dropdown can be layered on top later.

Pure Python, no Qt, no Houdini — safe to import anywhere.
"""

from typing import Dict, List

# Use the app's own config mechanism (flat key:value format), NOT configparser —
# config/houdini_ai.ini is NOT INI-section format, and configparser would both
# fail to read it AND, on write, wipe the API keys.
try:
    from shared.common_utils import load_config, save_config
except Exception:
    load_config = save_config = None

try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None


# ─────────────────────────────────────────────
# Role presets
# ─────────────────────────────────────────────
# key -> {label, description, block}
# 'generalist' is the default and injects nothing (base behavior).

_ROLES: Dict[str, Dict[str, str]] = {
    "generalist": {
        "label": "Houdini Generalist",
        "description": "Default balanced Houdini assistant.",
        "block": "",
    },
    "hda_architect": {
        "label": "HDA Architect",
        "description": "Designs and packages clean Houdini Digital Assets.",
        "block": (
            "ACTIVE ROLE — HDA Architect:\n"
            "- Think like a tools TD. Design a clean, reusable, non-destructive internal network first, "
            "as a subnet. Expose sensible, well-labelled parameters with good defaults; no magic numbers buried inside.\n"
            "- VALIDATE the network with check_errors / verify_and_summarize and confirm it actually WORKS "
            "before doing anything else (Architect → Builder → Validator).\n"
            "- Do NOT wrap into an HDA automatically. Only call wrap_as_hda when the user EXPLICITLY asks for "
            "an HDA AND the network is validated and working — a broken or speculative HDA just clutters the "
            "asset library. Otherwise leave it as a tidy subnet."
        ),
    },
    "vex_debugger": {
        "label": "VEX Debugger",
        "description": "Diagnoses errors, traces upstream, proposes minimal fixes.",
        "block": (
            "ACTIVE ROLE — VEX/Network Debugger:\n"
            "- Lead with diagnosis. Call check_errors and inspect the upstream input chain before changing anything.\n"
            "- Identify the ROOT cause (which node, which attribute, which parameter), not just the symptom.\n"
            "- Propose the smallest correct fix; explain why it works in one or two sentences.\n"
            "- For VEX, point to the exact line/expression at fault. Verify the fix with check_errors after applying."
        ),
    },
    "technical_writer": {
        "label": "Technical Writer",
        "description": "Produces clear, structured documentation and explanations.",
        "block": (
            "ACTIVE ROLE — Technical Writer:\n"
            "- Be precise, structured, and handoff-ready. Prefer the document_network skill for network docs.\n"
            "- Use clear headings and short paragraphs; define attributes, inputs/outputs, key parameters and pitfalls.\n"
            "- Avoid speculation; document what the network actually does."
        ),
    },
    "fx_artist": {
        "label": "FX / Sim Artist",
        "description": "Builds simulations fast using the dedicated sim-builder skills.",
        "block": (
            "ACTIVE ROLE — FX / Simulation Artist:\n"
            "- When the user asks for a sim, prefer the unified builder skill skill__build_sim "
            "(sim_type = pyro/flip/rbd/mpm/vellum/particle/ocean; whitewater via skill__build_whitewater) "
            "over wiring nodes by hand — it is deterministic and reliable.\n"
            "- If the user has a GPU plugin (Axiom/Paradigm) installed, offer the matching recipe; otherwise use native solvers.\n"
            "- Set a sensible frame range and confirm the result cooks before reporting done."
        ),
    },
}

_THINKING_LEVELS = {
    "low": "Thinking depth: LOW — keep the <think> block brief; reason only as much as the task needs.",
    "medium": "",  # default: the base framework already defines medium-depth thinking
    "high": ("Thinking depth: HIGH — in the <think> block, reason thoroughly: enumerate options, weigh trade-offs, "
             "and check assumptions before acting. Favor correctness over brevity."),
}

_DEFAULT_ROLE = "generalist"
_DEFAULT_THINKING = "medium"


def _load() -> dict:
    """Load houdini_ai config as a flat dict (matches the app's key:value format)."""
    try:
        if load_config is None:
            return {}
        cfg, _ = load_config("ai", dcc_type="houdini")
        return cfg or {}
    except Exception as e:
        _dbg(f"[Roles] config read failed: {e}")
        return {}


def _save(key: str, value: str) -> bool:
    """Set ONE key, preserving every other key (API keys, endpoints, etc.)."""
    try:
        if load_config is None or save_config is None:
            return False
        cfg, _ = load_config("ai", dcc_type="houdini")
        cfg = cfg or {}
        cfg[key] = value
        save_config("ai", cfg, dcc_type="houdini")
        return True
    except Exception as e:
        _dbg(f"[Roles] config save failed: {e}")
        return False


def list_roles() -> List[Dict[str, str]]:
    """Return [{key, label, description}] for every available role."""
    return [{"key": k, "label": v["label"], "description": v["description"]}
            for k, v in _ROLES.items()]


def get_active_role() -> str:
    """Return the active role key (defaults to 'generalist')."""
    try:
        role = (_load().get("active_role", _DEFAULT_ROLE) or _DEFAULT_ROLE).strip().lower()
        return role if role in _ROLES else _DEFAULT_ROLE
    except Exception:
        return _DEFAULT_ROLE


def set_active_role(role_key: str) -> bool:
    """Persist the active role (preserving all other config keys). True on success."""
    role_key = (role_key or "").strip().lower()
    if role_key not in _ROLES:
        return False
    return _save("active_role", role_key)


def get_role_injection() -> str:
    """Return the system-prompt block for the active role (empty for generalist/errors)."""
    try:
        return _ROLES.get(get_active_role(), {}).get("block", "") or ""
    except Exception:
        return ""


def get_thinking_level() -> str:
    """Return the active thinking level key (low/medium/high)."""
    try:
        lvl = (_load().get("thinking_level", _DEFAULT_THINKING) or _DEFAULT_THINKING).strip().lower()
        return lvl if lvl in _THINKING_LEVELS else _DEFAULT_THINKING
    except Exception:
        return _DEFAULT_THINKING


def set_thinking_level(level: str) -> bool:
    level = (level or "").strip().lower()
    if level not in _THINKING_LEVELS:
        return False
    return _save("thinking_level", level)


def get_thinking_injection() -> str:
    """Return the thinking-level directive for the active level (empty for medium/errors)."""
    try:
        return _THINKING_LEVELS.get(get_thinking_level(), "") or ""
    except Exception:
        return ""


# ─────────────────────────────────────────────
# Simulation builder policy (always on outside Ask mode)
# ─────────────────────────────────────────────
# This steers the model to use the deterministic builder skills instead of
# wiring sim networks node-by-node. Critical for cheaper models (e.g. DeepSeek
# V4) which otherwise build from memory and miss required nodes (e.g. the MPM
# Container), producing broken setups.

_SIM_POLICY = (
    "Simulation Builder Policy (HIGHEST PRIORITY — overrides every other instruction below, "
    "including any suggestion to use Plan mode):\n"
    "- A simulation request is ONE skill call, NOT a complex multi-step task. Do NOT suggest Plan "
    "mode, do NOT describe an 8-step manual pipeline, do NOT ask whether to proceed — immediately "
    "call the matching builder skill as your very first action.\n"
    "- For ANY simulation request, you MUST call the unified builder skill skill__build_sim as your "
    "FIRST action, NOT build the network node-by-node. Set 'sim_type' (and 'variant' for the sub-look):\n"
    "  - pyro / smoke / fire / explosion  -> skill__build_sim sim_type='pyro'  (variant: smoke|fire|explosion)\n"
    "  - FLIP / liquid / water / fluid     -> skill__build_sim sim_type='flip'  (fountain=true for an upward 'air mancur')\n"
    "  - RBD / rigid body / destruction    -> skill__build_sim sim_type='rbd'\n"
    "  - MPM / snow / sand / mud / jello   -> skill__build_sim sim_type='mpm'   (variant: snow|sand|mud|jello|rubber|...)\n"
    "  - Vellum / cloth / hair / softbody  -> skill__build_sim sim_type='vellum'(variant: cloth|hair|softbody|balloon|grain)\n"
    "  - particles / POP / grains          -> skill__build_sim sim_type='particle'\n"
    "  - ocean / sea / waves               -> skill__build_sim sim_type='ocean'\n"
    "  - whitewater / foam / spray         -> skill__build_whitewater (post-process on an existing FLIP sim)\n"
    "- This skill deterministically creates AND wires EVERY required node — including containers, "
    "colliders and solvers — correctly. Building sims manually is error-prone (e.g. MPM needs an MPM "
    "Container wired to the source, collider AND solver) and is NOT allowed when a builder skill exists.\n"
    "- HARD RULE: for a simulation request, do NOT use create_node, create_nodes_batch, copy_node or "
    "execute_python to assemble the network yourself. Call the build_* skill ONCE; it returns the created "
    "node paths. Manual assembly of a sim when a builder exists is a policy violation.\n"
    "- After the skill runs, only adjust specific parameters the user asked for. If a network ever looks "
    "messy (e.g. you did build manually for a non-sim task), call skill__tidy_network to lay it out cleanly.\n"
    "- Also prefer: skill__wrap_as_hda (package an HDA), skill__document_network (docs), "
    "skill__discover_plugins + skill__inspect_node_type (use third-party plugin nodes like Axiom/Paradigm/MoPs).\n"
    "- Only fall back to manual node creation if the builder skill genuinely does not exist or returns an error."
)


def get_sim_policy_injection() -> str:
    """Return the simulation-builder steering block (empty on error)."""
    try:
        return _SIM_POLICY
    except Exception:
        return ""


# Keywords that indicate a simulation request. Used to inject the sim policy
# ONLY for sim work, so procedural requests stay lean (and the model isn't
# nudged toward sim builders when modeling / writing VEX / building networks).
_SIM_KEYWORDS = (
    "sim", "simulation", "simulasi", "solver",
    "pyro", "smoke", "asap", "fire", "api", "explosion", "ledakan", "flame",
    "flip", "liquid", "cairan", "water", "air ", "fluid", "splash",
    "rbd", "rigid", "destruction", "hancur", "fracture", "bullet",
    "mpm", "snow", "salju", "sand", "pasir", "mud", "lumpur", "jello",
    "vellum", "cloth", "kain", "hair", "rambut", "softbody", "balloon", "grain",
    "particle", "partikel", "pop ", "whitewater", "foam", "busa",
    "ocean", "laut", "wave", "gelombang", "ombak",
)


def is_sim_request(text: str) -> bool:
    """True if the text looks like a simulation request (so the sim policy applies)."""
    try:
        t = (text or "").lower()
        return any(k in t for k in _SIM_KEYWORDS)
    except Exception:
        return False


# ─────────────────────────────────────────────
# Procedural Build Competence (the "cookbook")
# ─────────────────────────────────────────────
# Distilled, hard-won rules + a build/verify protocol so the model builds ANY
# procedural setup reliably instead of guessing node/parm names and claiming
# success blindly. Injected for build requests that are NOT covered by a
# dedicated builder skill (sim requests use _SIM_POLICY instead).

_PROCEDURAL_COOKBOOK = (
    "Procedural Build Competence (applies to ANY build/create/model request that has no dedicated "
    "builder skill — e.g. fences, stairs, buildings, roads, scatter layouts, modeling):\n"
    "\n"
    "WORKFLOW — follow in order, never skip:\n"
    "1. INTROSPECT before guessing. Confirm a node type exists (get_available_node_types) and read the "
    "REAL parameter names (get_node_parameters) before setting them. If unsure how to build something, "
    "call skill__find_recipe FIRST — it returns SideFX's own shelf-tool recipe to adapt.\n"
    "2. BUILD deterministically. For multi-node setups prefer execute_python_code, wrapping all logic in "
    "ONE function so variables are shared (split globals/locals otherwise break top-level names).\n"
    "3. COOK + VERIFY BY DATA. Cook the output and prove it is actually right: non-empty (point/prim "
    "count > 0), bounding box sane (a floor is flat+wide; a dropped object rests ON the ground, lowest "
    "Y ~0 not negative), and node errors empty. Use skill__verify_geo for a one-call check.\n"
    "3b. VERIFY BY SIGHT (if a vision key is set). For anything whose LOOK matters, call skill__visual_check "
    "after the data check — a cheap vision model looks at the render and catches what data can't "
    "(upside-down, floating, wrong proportions). Act on its verdict before reporting success.\n"
    "4. FIX and re-verify. Only report success after the data checks pass.\n"
    "\n"
    "GOLDEN RULES (each one cost real debugging):\n"
    "- CONTEXT: SOP nodes (box, grid, line, copytopoints, resample, merge, polywire, etc.) live INSIDE a "
    "'geo' object — create a geo container first (hou.node('/obj').createNode('geo', name)), then build the "
    "SOPs inside it. Only object-level nodes (geo, cam, light, null, subnet, dopnet) go directly under /obj. "
    "To list SOP types in code use hou.sopNodeTypeCategory().nodeTypes() (or the get_available_node_types tool).\n"
    "- NATIVE-FIRST: prefer existing Houdini SOP nodes. VEX (attribwrangle) is fine and idiomatic, but do "
    "NOT leave a 'python' SOP in the result network — most users can't read Python and it's not the Houdini "
    "way. Use the execute_python tool only to CREATE native nodes, never to embed a python SOP as the build.\n"
    "- '0 errors' does NOT mean correct — always sanity-check the geometry, not just the error list.\n"
    "- SPATIAL SENSE: reason about placement, not just counts. Objects rest ON the ground (base at Y~0, not "
    "centered through it); legs/supports go BELOW a surface (negative Y from the top); parts must connect "
    "where they should. A valid-but-upside-down/floating result still fails — picture the layout before building.\n"
    "- A flat ground/floor grid uses orient 'zx' (XZ plane); orient 'xy' makes a VERTICAL wall.\n"
    "- Native solvers (MPM/RBD/Vellum/FLIP/POP) have a BUILT-IN ground (useground/groundactive) — use it, "
    "don't add a redundant grid. A real collider must feed the SOLVER's input, not the output/merge.\n"
    "- Need a curve/path? Use NATIVE nodes: 'line' (straight), 'circle' (ring/arc), 'spiral' (3D helix — "
    "has height/turns/radius), or 'add' SOP for explicit points. The H21 'curve' SOP has no 'coords' parm, "
    "so don't try to script it — pick the native node that fits (or call find_recipe).\n"
    "- POP particle nodes (popsolver/popsource) are DOP nodes, not SOPs — build them inside a 'dopnet' "
    "and read the result back to SOPs with 'dopimport'.\n"
    "- vellumconstraints has TWO outputs (geometry, constraints); the solver needs BOTH.\n"
    "- Set ordinal menu parms by their string token; INT toggles (e.g. popforce 'turb') take 0/1 — the "
    "strength is a SEPARATE parm (e.g. 'amp').\n"
    "\n"
    "COMMON PATTERNS:\n"
    "- Copies on a surface: scatter -> copytopoints (template on input 0, points on input 1).\n"
    "- Distribute along a curve: resample (length=spacing) -> copytopoints.\n"
    "- Bar/tube along a curve: polywire (wirerad) or sweep with a cross-section profile.\n"
    "- Combine/cut: boolean. Thicken: polyextrude. Round edges: polybevel. Smooth: subdivide.\n"
    "- Rows/grids of copies (bricks, tiles, fence pickets): make the points with a 'line' or 'grid' "
    "(+ a wrangle for per-row offset like a running bond) -> copytopoints. Do NOT fight the 'add' SOP's "
    "point multiparm — line/grid is far simpler and native.\n"
    "\n"
    "CLEAN OUTPUT: leave ONE final result node (a merge/null named clearly), and DELETE any scratch / "
    "test / support geometry you created along the way — stray blocks in the scene are a defect.\n"
    "\n"
    "Do NOT auto-wrap results into an HDA — leave a tidy subnet unless the user explicitly asks for an HDA."
)


def get_procedural_cookbook_injection() -> str:
    """Return the procedural build cookbook block (empty on error)."""
    try:
        return _PROCEDURAL_COOKBOOK
    except Exception:
        return ""


# Keywords that indicate a generic BUILD/modeling request (procedural geometry),
# used to inject the cookbook. Sim requests are handled by _SIM_POLICY instead.
_BUILD_KEYWORDS = (
    "build", "create", "make", "generate", "model", "bikin", "buat", "bikinin", "buatin",
    "procedural", "prosedural", "scatter", "sebar", "susun", "array", "instance",
    "fence", "pagar", "railing", "wall", "tembok", "stair", "tangga", "road", "jalan",
    "building", "gedung", "rumah", "house", "city", "kota", "tower", "menara",
    "bridge", "jembatan", "pillar", "tiang", "column", "kolom", "pipe", "pipa",
    "curve", "kurva", "extrude", "bevel", "boolean", "voronoi", "pattern", "pola",
)


def is_build_request(text: str) -> bool:
    """True if the text looks like a generic procedural build request.

    Used to inject the cookbook. Callers should gate with `and not is_sim_request()`
    so simulations use the dedicated sim policy instead.
    """
    try:
        t = (text or "").lower()
        return any(k in t for k in _BUILD_KEYWORDS)
    except Exception:
        return False
