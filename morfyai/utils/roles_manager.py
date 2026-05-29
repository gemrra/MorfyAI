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
            "- When the user asks for a sim, prefer the dedicated builder skills (build_pyro_sim, build_flip_sim, "
            "build_rbd_sim, build_mpm_sim, build_vellum_sim, build_particle_sim, build_whitewater, build_ocean) "
            "over wiring nodes by hand — they are deterministic and reliable.\n"
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
    "- For ANY simulation request, you MUST call the dedicated builder skill as your FIRST action, "
    "NOT build the network node-by-node:\n"
    "  - pyro / smoke / fire / explosion  -> skill__build_pyro_sim\n"
    "  - FLIP / liquid / water / fluid     -> skill__build_flip_sim\n"
    "  - RBD / rigid body / destruction    -> skill__build_rbd_sim\n"
    "  - MPM / snow / sand / mud / jello   -> skill__build_mpm_sim\n"
    "  - Vellum / cloth / hair / softbody  -> skill__build_vellum_sim\n"
    "  - particles / POP / grains          -> skill__build_particle_sim\n"
    "  - whitewater / foam / spray         -> skill__build_whitewater\n"
    "  - ocean / sea / waves               -> skill__build_ocean\n"
    "- These skills deterministically create AND wire EVERY required node — including containers, "
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
