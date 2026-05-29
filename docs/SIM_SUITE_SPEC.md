# MorfyAI Sim Suite — Research & Design Spec

> Status: **IMPLEMENTED (untested in live Houdini).** All code written, compiles, self-reviewed,
> defensive. Phases 1-fix, A, B, C, and core Roles/Debug/thinking are done as of this pass.
> Next step: test in Houdini 21 → iterate. Reference doc for the build.
> Target: Houdini 21+. Model target: DeepSeek V4 Pro (native), scales up on Opus/GPT.
> All node names verified against SideFX docs (links at bottom).

---

## 1. Goal

Match and exceed Radu Cius' *Houdini AI Assistant* by giving MorfyAI:
- **A.** Deterministic builders for every native H21 solver (one prompt → full setup).
- **B.** A generic *plugin-awareness* layer so the agent can use ANY third-party node the user installed (Axiom, Paradigm, MoPs, qLib, …) via dynamic discovery.
- **C.** Curated recipes for the most popular third-party plugins (auto-disabled if not installed).

Radu Cius has neither dedicated sim builders nor plugin-awareness — this is our differentiator, on top of MorfyAI's existing edge (memory, plan mode, plugins, rules, self-learning).

---

## 2. Native solver spec (verified H21 node chains)

Pattern for every builder: create `/obj` geo container → build the verified chain →
resolve node types at runtime (`_find_sop_type`) → match collision/aux inputs by label
(`inputLabels()`) → guarded `set_parms` → display flag → `layoutChildren` → set frame range.

### Already built (Phase 1)
| Skill | Chain | Note |
|---|---|---|
| `build_pyro_sim` | `pyrosource` → `pyrosolver` | **FIX**: smoke/fire preset lives on `pyrosolver` (Initialize Smoke/Fire + Emit Density/Temp From Flame), NOT pyrosource. May need Volume Rasterize between source→solver — verify in Houdini. |
| `build_flip_sim` | source → `flipsolver` (+ground collision input) | OK |
| `build_rbd_sim` | `rbdmaterialfracture` → `rbdbulletsolver` (+ground) | OK. H21 also has RBD Car Fracture SOP (future). |

### To build (Phase A)

**MPM** — `build_mpm_sim`
- Nodes: `mpmsource`, `mpmcollider`, `mpmcontainer`, `mpmsolver`
- Wiring: `mpmcontainer` → `mpmsource`(in1) + `mpmcollider`(container in) + `mpmsolver`(in2);
  `mpmsource` → `mpmsolver`(in0); `mpmcollider` → `mpmsolver`(in1)
- `mpmsolver` inputs (verified): 0=MPM Sources, 1=MPM Colliders, 2=MPM Container
- `mpmsource` inputs: 0=geometry to fill, 1=MPM Container
- Key params:
  - `mpmsource`: Material Preset (behavior: Elastic/Chunky/Liquid/Viscous/Sandy; named materials: snow/soil/mud/concrete/metal/jello/rubber/water/honey/sand), Emission Type (Once/Continuous), Point Separation
  - `mpmcontainer`: Particle Separation (resolution), Grid Scale (default 2)
  - `mpmsolver`: Global Substeps, CFL Condition, Gravity, Air Drag, Wind Velocity, Ground Plane (Friction, Sticky)
- Skill params: `material` (enum), `source_shape`, `ground`, `duration_seconds`, `resolution`

**Vellum** — `build_vellum_sim`
- Nodes: `vellumconstraints` (preset via Configure Cloth/Hair/Softbody/Balloon/Grain) → `vellumsolver`
- `vellumsolver` inputs (verified): 0=surface geo, 1=constraint geo (from vellumconstraints), 2=collision
- Constraint types: Cloth, Hair, String, Softbody, Pressure(balloon), Grain (+ many low-level)
- Key params: `vellumconstraints` stiffness/bend/breaking; `vellumsolver` Substeps, Constraint Iterations, Forces (Gravity, Wind, Drag, Friction)
- Skill params: `type` (cloth/hair/softbody/balloon/grain — enum), `source_shape`, `ground`, `duration_seconds`

**Particles/POP** — `build_particle_sim`
- SOP-level POP Solver (H20+). Chain: emitter geo → `popsource` → `popsolver`
- `popsource`: emission rate, life, initial velocity, attributes
- `popsolver`: forces via wired POP microsolvers; substeps
- Skill params: `emitter_shape`, `rate`, `life`, `gravity`, `duration_seconds`

**Whitewater** — `build_whitewater` (DEPENDS on existing FLIP sim)
- Nodes: `whitewatersource` → `whitewatersolver`
- `whitewatersolver` inputs (verified): 0=Emission+Fluid Fields (emit/surface/vel from source), 1=Container, 2=Collisions
- **Dependency**: requires a FLIP sim's vel + surface SDF. Post-process, not standalone.
- Key params: Whitewater Scale, Voxel Size, Foam Location, Emission Amount, Lifespan, Gravity/Buoyancy/Advection, Wind
- Skill params: `flip_path` (existing FLIP container, required), `scale`, `duration_seconds`

**Ocean** — `build_ocean` (procedural, not a true solver)
- Chain: `oceanspectrum` → `oceanevaluate`; input plane (grid) → `oceanevaluate`(in0), `oceanspectrum` → `oceanevaluate`(in1)
- Key params: `oceanspectrum` Wind Speed, Wind Direction, Spectrum Type (Phillips/TMA), Scale, Chop, Depth, Resolution Exponent
- Skill params: `wind_speed`, `wind_dir`, `scale`, `chop`, `grid_size`

---

## 3. Plugin-awareness layer (B + C)

### Why not hardcode every plugin
Third-party nodes use namespaced, versioned type names (`axiom::axiom_solver`,
`mops::...`, `...::qLib::...`) and may or may not be installed. Hardcoding is brittle.

### B. Generic discovery (works for ANY plugin)
MorfyAI already has the primitives — enhance them:
- `search_node_types(keyword)` → finds installed types (e.g. "axiom" → `axiom::axiom_solver`)
- `semantic_search_nodes(desc)` → NL → node
- `get_node_inputs`, `get_houdini_node_doc` → read ports & help
- `node_inputs.json` → curated input cache

**To add:**
- Installed-HDA-library scan (`hou.hda.loadedFiles()` / installed definitions) → know which plugins are present.
- Auto-introspect a plugin node: read `parmTemplateGroup()` + input labels + help → build an on-the-fly "node profile" the agent can use.
- Cache profiles to a store (extend `node_inputs.json` pattern) so repeat use is cheap.

### C. Curated recipes (top plugins, auto-disabled if absent)
| Plugin | What | Recipe skill | Detect via |
|---|---|---|---|
| **Axiom** | GPU sparse pyro/fluid (Matt Puchala / Theory Accelerated) | `build_axiom_pyro` | type `axiom::axiom_solver` present |
| **Paradigm** | GPU FLIP liquid (Theory Accelerated, 2026) | `build_paradigm_liquid` | Paradigm node present |
| **MoPs** | Motion graphics (toadstorm) — Instancer/Apply Attributes, generators/modifiers/falloffs | `build_mops_instance` | `MOPs`/`mops::` types present |
| **qLib** | helper nodes | (discovery only) | `::qLib::` namespace |

Each recipe begins with a guard: if the plugin's type isn't found, return a clear
"plugin not installed" message instead of failing.

---

## 4. DeepSeek V4 native optimization (verified)

- **Context caching**: cache-hit = full prefix match; hit costs ~1/10 (V4 Pro ~98% saving).
  → Keep `[system prompt + tools]` prefix STABLE; put volatile scene-state/tool-results LATER.
- **Strict mode (beta)**: `"strict": true` requires base_url `/beta`, all object props `required`,
  `additionalProperties:false`. **Decision: stay non-strict + retry** (keep optional+default params
  ergonomic for V4), but add `additionalProperties:false` + tight enums where cheap.
- **Reliability**: JSON tool-call parse 85%→97% with regex retry — MorfyAI already has
  `agent_loop_json_mode` + `_parse_json_tool_calls`. Keep retry.
- **`reasoning_content` passback**: must be returned every multi-turn or 400 error — already handled.
- **Biggest lever**: deterministic skills carry capability; V4 only orchestrates. Intent-aware
  tool filtering (`get_tools_for_intent`) keeps the tool list small for the weak model.

---

## 5. Build plan (phases)

1. **Phase 1 fix** — correct `build_pyro_sim` presets (solver-side Initialize Smoke/Fire).
2. **Phase A** — `build_mpm_sim`, `build_vellum_sim`, `build_particle_sim`, `build_whitewater`, `build_ocean`.
3. **Phase B** — generic plugin-awareness (installed-HDA scan + node introspection + profile cache).
4. **Phase C** — curated recipes: `build_axiom_pyro`, `build_paradigm_liquid`, `build_mops_instance`.
5. **Phase 2 (UX)** — Roles (Houdini Generalist / HDA Architect / VEX Debugger / Tech Writer), Debug mode, thinking-level control.
6. **Phase 3 (v4)** — cache-prefix discipline, tighten schemas, few-shot exemplars, auto-validate loop.

**Hard constraint:** every skill is untested in live Houdini (no `hou` access during dev).
Each phase must go through a Houdini test → iterate loop before being called "done".

---

## Sources
- MPM: https://www.sidefx.com/docs/houdini/mpm/workflow.html · https://www.sidefx.com/docs/houdini/nodes/sop/mpmsolver.html · https://www.sidefx.com/docs/houdini/nodes/sop/mpmsource.html
- Vellum: https://www.sidefx.com/docs/houdini/nodes/sop/vellumsolver.html · https://www.sidefx.com/docs/houdini/nodes/sop/vellumconstraints.html
- Pyro/FLIP H21: https://www.sidefx.com/docs/houdini/news/21/pyro.html · https://www.sidefx.com/docs/houdini/nodes/sop/pyrosolver.html
- Whitewater: https://www.sidefx.com/docs/houdini/nodes/sop/whitewatersolver.html
- Ocean: https://www.sidefx.com/docs/houdini/nodes/sop/oceanspectrum.html
- POP Solver SOP: https://www.sidefx.com/tutorials/introducing-houdini-20-pop-solver-sop/
- DeepSeek: https://api-docs.deepseek.com/guides/kv_cache · https://api-docs.deepseek.com/guides/function_calling
- Plugins: Axiom/Paradigm https://www.theoryaccelerated.com · MoPs https://www.motionoperators.com
