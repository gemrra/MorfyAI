# -*- coding: utf-8 -*-
"""Unified simulation builder — ONE skill that fronts all 7 dedicated sim builders.

Consolidation entry point: the AI calls `skill__build_sim` with `sim_type` and
the relevant parameters; this dispatches to the verified per-sim builder
(build_pyro_sim / build_flip_sim / build_mpm_sim / build_rbd_sim /
build_vellum_sim / build_ocean / build_particle_sim).

Design:
- The underlying builders keep their battle-tested wiring logic untouched.
- This skill exposes the UNION of their parameters (all optional except
  `sim_type`). Only parameters the caller actually provides are forwarded; each
  builder then falls back to its own defaults for the rest.
- Forwarding is filtered against each builder's real `run()` signature
  (via inspect), so extra/irrelevant params are dropped instead of raising.
- A few unified names are remapped to per-builder names:
    variant          -> preset (pyro) / material (mpm) / type (vellum)
    source_shape     -> emitter_shape (particle)
    ground_collision -> ground (flip)
"""

# sim_type -> (underlying skill name, {unified_param: builder_param} rename map)
_DISPATCH = {
    "pyro":     ("build_pyro_sim",     {"variant": "preset"}),
    "flip":     ("build_flip_sim",     {"ground_collision": "ground"}),
    "mpm":      ("build_mpm_sim",      {"variant": "material"}),
    "rbd":      ("build_rbd_sim",      {}),
    "vellum":   ("build_vellum_sim",   {"variant": "type"}),
    "ocean":    ("build_ocean",        {}),
    "particle": ("build_particle_sim", {"source_shape": "emitter_shape"}),
}

# common misspellings / synonyms -> canonical sim_type
_ALIASES = {
    "smoke": "pyro", "fire": "pyro", "explosion": "pyro",
    "liquid": "flip", "water": "flip", "fluid": "flip",
    "rigidbody": "rbd", "rigid": "rbd", "destruction": "rbd", "bullet": "rbd",
    "cloth": "vellum", "hair": "vellum", "softbody": "vellum", "balloon": "vellum", "grain": "vellum",
    "sea": "ocean", "wave": "ocean", "waves": "ocean",
    "particles": "particle", "pop": "particle", "points": "particle",
    "snow": "mpm", "sand": "mpm", "mud": "mpm", "jello": "mpm",
}

SKILL_INFO = {
    "name": "build_sim",
    "description": (
        "Build a complete, WORKING simulation from ONE call. This is the single entry point for all "
        "simulation types — set 'sim_type' and the few relevant params. Each type deterministically "
        "creates AND wires every required node (container, source, collider, solver), sets the playback "
        "range and display flag; press Play to simulate.\n"
        "sim_type guide:\n"
        "  pyro     -> smoke / fire / explosion       (set variant: smoke|fire|explosion)\n"
        "  flip     -> liquid / water / splash / FOUNTAIN (set fountain=true for an upward 'air mancur' jet)\n"
        "  mpm      -> snow / sand / mud / jello / rubber / concrete / metal / honey / water / soil (set variant)\n"
        "  rbd      -> rigid body / destruction / fracture\n"
        "  vellum   -> cloth / hair / softbody / balloon / grain (set variant)\n"
        "  ocean    -> sea / waves surface (fast, no solver)\n"
        "  particle -> sparks / dust / debris / rain / swarm (POP)\n"
        "Use 'variant' for the sub-type (pyro preset / mpm material / vellum type). Unused params are ignored.\n"
        "ONLY for DYNAMIC physics simulations you press Play to run (things that fall, flow, burn, shatter, "
        "flap, splash). Do NOT use this to scatter / place / model STATIC objects (e.g. 'scatter rocks on "
        "the ground', 'lay out props', build a mesh) — those are modeling/scatter tasks, not simulations."
    ),
    "parameters": {
        "sim_type": {
            "type": "string",
            "description": "Which simulation to build.",
            "enum": ["pyro", "flip", "mpm", "rbd", "vellum", "ocean", "particle"],
            "required": True,
        },
        "variant": {
            "type": "string",
            "description": "Sub-type / look. pyro: smoke|fire|explosion. mpm: snow|sand|mud|jello|rubber|"
                           "concrete|metal|honey|water|soil. vellum: cloth|hair|softbody|balloon|grain. "
                           "Ignored for flip/rbd/ocean/particle.",
        },
        "container_name": {"type": "string", "description": "Name of the /obj geo container (defaults per type)."},
        "source_shape": {
            "type": "string",
            "description": "Source/emitter primitive. pyro/flip/mpm: sphere|box|torus. rbd: box|sphere|torus. "
                           "vellum: auto|grid|sphere|box|torus|line. particle: grid|sphere|box|torus.",
        },
        "duration_seconds": {"type": "number", "description": "Sim length in seconds (drives playback range). Ignored for ocean."},
        # shared collision
        "ground_collision": {"type": "boolean", "description": "Use the solver's built-in ground plane (flip/mpm/rbd/vellum/particle)."},
        "collider_path": {"type": "string", "description": "OPTIONAL path to existing geo used as a custom collider (mpm/rbd/vellum)."},
        # flip
        "fountain": {"type": "boolean", "description": "flip only: upward FOUNTAIN/JET/GEYSER ('air mancur'). The only way to shoot water upward."},
        "continuous": {"type": "boolean", "description": "flip only: continuous downward falling stream (NOT a fountain). False = one-shot drop."},
        "jet_speed": {"type": "number", "description": "flip fountain only: upward launch speed (higher = taller jet)."},
        "resolution": {"type": "number", "description": "Particle separation. flip: ~0.08 (smaller=finer). mpm: 0=auto."},
        # mpm
        "initial_velocity": {"type": "array", "description": "mpm only: birth velocity [x,y,z] (e.g. [8,2,0] = thrown).", "items": {"type": "number"}},
        # rbd
        "fracture": {"type": "boolean", "description": "rbd only: insert RBD Material Fracture so the object shatters."},
        # ocean
        "grid_size": {"type": "number", "description": "ocean only: size of the ocean grid (square)."},
        "wind_speed": {"type": "number", "description": "ocean only: wind speed (larger waves)."},
        "chop": {"type": "number", "description": "ocean only: wave sharpness/cusps."},
        "scale": {"type": "number", "description": "ocean only: overall wave amplitude scale."},
        "wind_dir": {"type": "number", "description": "Wind direction in degrees (ocean & particle)."},
        # particle
        "rate": {"type": "number", "description": "particle only: birth rate (particles/sec)."},
        "life": {"type": "number", "description": "particle only: life expectancy in seconds."},
        "gravity": {"type": "boolean", "description": "particle only: apply downward gravity."},
        "wind": {"type": "number", "description": "particle only: wind strength pushing particles sideways."},
        "turbulence": {"type": "number", "description": "particle only: chaotic noise added to motion."},
    },
}


def run(sim_type=None, variant=None, container_name=None, source_shape=None,
        duration_seconds=None, ground_collision=None, collider_path=None,
        fountain=None, continuous=None, jet_speed=None, resolution=None,
        initial_velocity=None, fracture=None,
        grid_size=None, wind_speed=None, chop=None, scale=None, wind_dir=None,
        rate=None, life=None, gravity=None, wind=None, turbulence=None):
    import inspect

    if not sim_type:
        return {"success": False, "error": "sim_type is required (pyro/flip/mpm/rbd/vellum/ocean/particle)."}

    st = str(sim_type).strip().lower()
    st = _ALIASES.get(st, st)
    if st not in _DISPATCH:
        return {"success": False,
                "error": f"unknown sim_type '{sim_type}'. Valid: {', '.join(_DISPATCH.keys())}."}

    builder, rename = _DISPATCH[st]

    # collect only the params the caller actually provided (non-None)
    unified = {
        "container_name": container_name, "source_shape": source_shape,
        "duration_seconds": duration_seconds, "ground_collision": ground_collision,
        "collider_path": collider_path, "fountain": fountain, "continuous": continuous,
        "jet_speed": jet_speed, "resolution": resolution, "initial_velocity": initial_velocity,
        "fracture": fracture, "grid_size": grid_size, "wind_speed": wind_speed, "chop": chop,
        "scale": scale, "wind_dir": wind_dir, "rate": rate, "life": life, "gravity": gravity,
        "wind": wind, "turbulence": turbulence,
    }
    provided = {k: v for k, v in unified.items() if v is not None}
    if variant is not None:
        provided["variant"] = variant

    # remap unified names -> this builder's param names
    for u_name, b_name in rename.items():
        if u_name in provided:
            provided[b_name] = provided.pop(u_name)

    # resolve the underlying builder module (kept in the registry even though
    # it is hidden from the AI tool list)
    try:
        from morfyai import skills as _skills
        _skills._load_all()
        mod = _skills._registry.get(builder)
    except Exception as e:
        return {"success": False, "error": f"could not load skill registry: {e}"}
    if mod is None or not callable(getattr(mod, "run", None)):
        return {"success": False, "error": f"underlying builder '{builder}' not found or has no run()."}

    # forward only params this builder actually accepts; report what we dropped
    accepted = set(inspect.signature(mod.run).parameters.keys())
    kwargs = {k: v for k, v in provided.items() if k in accepted}
    ignored = sorted(k for k in provided if k not in accepted)

    try:
        result = mod.run(**kwargs)
    except Exception as e:
        import traceback
        return {"success": False, "error": f"{builder} failed: {e}\n{traceback.format_exc()[:400]}",
                "sim_type": st, "builder": builder}

    if not isinstance(result, dict):
        result = {"result": str(result)}
    result.setdefault("success", True)
    result["sim_type"] = st
    result["builder"] = builder
    if ignored:
        result["ignored_params"] = ignored
    return result
