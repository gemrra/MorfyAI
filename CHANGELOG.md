# Changelog

All notable changes to MorfyAI are documented here. One entry per release —
this is also what gets pasted into the GitHub Release notes and the public
changelog page at morfyfx.com/morfyai/changelog.

## 2.14 — 2026-09-06

**New built-in skill: mocap retargeting (KineFX)**
- The rigging set is now end-to-end: build a skeleton, bind a mesh, pose it,
  and now RETARGET animation onto it — all from natural language. The new
  `build_rig rig_type='retarget'` follows SideFX's documented core retarget
  workflow: Rig Match Pose (with bounding-box match to auto align/scale the
  source to the target) -> Map Points (per-joint source->target mapping) ->
  Full Body IK, with an optional skinned preview through Joint Deform.
- **Automatic joint mapping.** The only interactive step of a retarget
  (mapping joints between two skeletons) is now done procedurally by name: a
  built-in Mixamo -> MorfyAI-biped table maps the standard clip out of the
  box, and a `name` mode matches joints whose names line up for custom
  skeletons. Node types are resolved at runtime to tolerate version drift.
- The agent is instructed to verify a retarget visually: scrub the timeline,
  capture the viewport, and confirm the target mirrors the source motion
  (feet planted, limbs not twisted) — flagging an empty/misnamed Map Points
  mapping when nothing moves.
- Added the retarget nodes to the MCP node-input reference
  (`kinefx--rigmatchpose`, `kinefx--mappoints`, `kinefx--rigstashpose`).

## 2.13 — 2026-08-28

**New built-in skills: character rigging (KineFX)**
- MorfyAI can now build full character rigs from a natural-language prompt,
  closing the biggest gap in its workflow coverage (sims, look-dev, and
  modeling were covered; rigging wasn't). All using stock KineFX SOPs
  (H19.5+), verified against SideFX docs:
  - **Skeleton** — `build_rig rig_type='skeleton'` procedurally generates a
    joint chain (biped / quadruped / simple chain) as a polyline with
    `name`+`transform` point attributes, then runs it through Rig Doctor and
    Orient Joints. Can fit the skeleton's proportions to an existing
    character mesh's bounding box (`fit_to_geometry`), attach control shapes
    (Attach Joint Geometry), and appends a Visualize Rig node so the joints
    are clearly visible in the viewport.
  - **Skinning** — `build_rig rig_type='skinning'` binds a mesh: skin ->
    Joint Capture Proximity (or Biharmonic for higher-quality organic
    weights) -> Joint Deform, wiring the skeleton as both rest/capture pose
    and animated pose (Joint Deform's three inputs).
  - **Pose** — `build_rig rig_type='pose'` appends Rig Pose (FK) and
    optional Full Body IK (H19+), and can apply a TEST POSE by rotating a
    named joint purely through parameters — no viewport interaction needed.
- **Vision-assisted verification.** Rig correctness is mostly visual, so the
  agent is now instructed to LOOK at the rig after each step: after building
  a skeleton it captures the viewport to confirm the joints sit inside the
  mesh with plausible proportions, and after skinning it applies a test pose
  and captures the deformation to catch candy-wrapper collapse or unbound
  areas — using `capture_viewport` when the main model has vision, or the
  `visual_check` skill (cheap vision model) otherwise. The unified
  `build_rig` skill also runs a data-level check (cooks the output, counts
  joints/points, reports errors) after every build and surfaces a `next_step`
  pointer to the visual pass.
- **Dispatcher pattern.** Like `build_sim` for sims, the single
  `skill__build_rig` entry point fronts three hidden per-task skills
  (`build_rig_skeleton` / `build_rig_skinning` / `build_rig_pose`), so the
  AI sees one tool with a `rig_type` switch instead of three near-duplicate
  tools. Aliases (bones/joints, bind/capture/weights, fk/ik) map to the
  canonical rig_type.
- Added the full modern KineFX node set to the MCP node-input reference
  (`kinefx--skeleton`, `rigdoctor`, `kinefx--orientjoints`,
  `kinefx--rigpose`, `kinefx--jointcaptureproximity`,
  `kinefx--jointcapturebiharmonic`, `kinefx--jointdeform`,
  `kinefx--visualizerig`, `kinefx--attachjointgeo`, `kinefx--fullbodyik`) so
  the AI wires these chains with the correct input ports.

## 2.12 — 2026-08-27

**Fixes**
- Fixed AI auto-layouting nodes without being asked, destroying carefully arranged
  node networks. The agent was calling `layout_nodes` / `layoutChildren()` /
  `moveToGoodPosition()` automatically as part of unrelated tasks (e.g. after
  `verify_and_summarize`), which is the programmatic equivalent of pressing `L` in
  the Network Editor. Two-layer fix: the system prompt now explicitly forbids any
  auto-layout unless the user's message contains an explicit tidy/arrange request,
  and a hard guard in `_execute_tool_with_todo` blocks `layout_nodes` at the
  dispatcher level — returning a clear error message — unless the
  `_layout_explicitly_requested` flag is set from keyword detection on the user's
  input text.

## 2.11 — 2026-07-17

**Fixes**
- Fixed Houdini 22 (Python 3.13) still loading the Python-3.11 vendor folder
  for MCP and the AI client, breaking `import pywintypes`/`fastmcp` even
  after v2.10's dual-Python packaging. Four call sites (`ai_client.py`,
  `mcp/client.py`, `mcp/proxy.py`, `launch_web.py`) each independently
  hardcoded a bare `lib/` path instead of using the version-aware picker
  added in v2.10 — one of them ran later in the same import chain and
  silently re-inserted the wrong folder ahead of the correct one. All
  vendor-path lookups now go through the single shared
  `shared.common_utils.get_lib_dir()` (or an inlined equivalent for
  standalone entrypoints) instead of being reimplemented per file.
  Verified end-to-end against a real Houdini 22.0.368 + Python 3.13
  session — `ensure_mcp_running()` now actually binds a port.

## 2.10 — 2026-07-16

**Houdini 22 support**
- Houdini 22 ships Python 3.13 by default (up from 3.11 in H21 and earlier),
  and MorfyAI's vendored binary dependencies (fastmcp, numpy, pywin32,
  cryptography, etc.) are ABI-locked to one Python minor version. Rather than
  requiring users to install the alternate Python-3.11 build of Houdini 22,
  MorfyAI now ships a second vendored dependency set built for Python 3.13
  and picks whichever one matches the running interpreter automatically —
  MorfyAI adapts to whatever Houdini version is installed, not the other way
  around. Houdini 19.5–21 (Python 3.11) is unaffected and keeps using the
  original `lib/` folder.

## 2.9 — 2026-07-14

**Fixes (critical)**
- Fixed `.gitignore`'s `*.py[cod]` pattern silently matching `.pyd` files too
  (the `[cod]` character class matches `d` as well as `c`/`o`) — every Windows
  compiled binary extension under `lib/` (numpy's core binary, pydantic_core,
  cryptography, pywin32, and 70+ others) has never been committed to git, and
  therefore never included in any release zip. This is the real cause behind
  the MCP server refusing to start on release installs: `fastmcp` depends on
  `pydantic_core`'s compiled backend, which was silently missing, and the
  failure was swallowed without an error message. All 75 previously-excluded
  binaries are now tracked and ship in the release package.

## 2.8 — 2026-07-12

**Fixes**
- Fixed the v2.6 MCP port fix actually causing the release install's MCP to
  bind the wrong port. Houdini package env vars are merged into the single
  houdini.exe process's environment, not scoped per package — so the dev
  package's `MORFYAI_MCP_PORT=9001` was equally visible to the release
  install's code in the same session, and the release server started on
  9001 too, leaving 9000 (the port external clients expect) empty. The port
  is now derived from each install's own filesystem instead: whether its
  repo root ships `launcher_dev.py`, a dev-only file the release zip build
  always excludes. This can't leak between installs, since each resolves
  its own root.

## 2.7 — 2026-07-08

**New built-in skills (wave 1)**
- Broadened the built-in skill set beyond sims/analysis into everyday
  look-dev, modeling, attribute, and pipeline tasks — all using stock
  Houdini nodes (no SideFX Labs / Redshift dependency):
  - **Look-dev:** `setup_dome_light` (envlight, optional HDRI),
    `setup_camera` (creates a camera framed on a target's bounds).
  - **Modeling:** `scatter_points` (Scatter SOP by count),
    `clean_geo` (fuse points, drop degenerate prims).
  - **Attributes:** `promote_attribute` (Attribute Promote between classes),
    `transfer_attributes` (Attribute Transfer by proximity).
  - **Pipeline:** `import_geo_file` (new geo object + File/Alembic loader),
    `cache_to_disk` (File Cache SOP set up for on-demand baking).
- Skills that create or modify nodes are now correctly classified as
  scene-mutating (kept out of read-only Ask mode) via a broader set of
  action-verb name prefixes.

**New built-in skills (small utilities)**
- 11 everyday node/parm utilities, useful across almost any build:
  `rename_nodes`, `color_nodes`, `add_comment`, `bypass_toggle`,
  `get_parm_value`, `set_parm_value`, `list_children`, `set_frame_range`,
  `duplicate_node`, `select_by_type`, `add_null`.

## 2.6 — 2026-07-08

**Fixes**
- Fixed the MCP server going dead/red when both the release and dev-mode
  installs are used. Both defaulted to port 9000, so whichever started first
  bound it and the other's MCP couldn't come up. The port is now overridable
  via a `MORFYAI_MCP_PORT` env var; the dev package uses 9001, leaving 9000
  (the port external MCP clients expect) for the release install, so both can
  run at once.

## 2.5 — 2026-07-08

**Fixes**
- Fixed "Open MorfyAI" launching the dev-mode copy instead of the installed
  release. Both installs ship a top-level `launcher.py` and both roots sit on
  PYTHONPATH, so the menu's bare `import launcher` could bind to the dev
  copy's file and open that — no amount of restarting helped, since it wasn't
  a stale-session issue. The menu now forces its own package root to the
  front of the path (and drops any stale `launcher`) before importing, so
  each menu always opens its own copy. This is the real cause behind the
  release and dev installs appearing to "share" data.

## 2.4 — 2026-07-08

**Polish**
- The context-usage ring now gets a bright hover highlight, matching the
  other composer-toolbar controls.

## 2.3 — 2026-07-08

**Fixes**
- Fixed the release and dev-mode installs sharing data when switched without
  restarting Houdini. The release launcher only isolated its own modules on
  first import, so after the dev copy had been opened in the same session its
  cached modules lingered and the release panel resolved its config, history,
  and memory through the dev install — showing identical chats and settings
  across both. Module isolation now re-runs on every launch, so each install
  always reads its own data.

## 2.2 — 2026-07-07

**Token usage analytics, redesigned**
- The "Usage & cost stats" view is rebuilt as a proper dashboard and now
  opens in its own window (like Settings) instead of a cramped in-panel box.
- One summary widget up top: estimated cost, requests, total tokens, cache
  hit rate, plus a full token-mix bar (cached vs fresh input, output,
  reasoning) with how many tokens were reused via cache.
- A cost-per-request chart with the priciest call highlighted, and a new
  **By model** breakdown — per-model requests, tokens, cache rate, and cost
  share, so you can see which model is spending your budget.
- Call details table with a per-row usage bar; app-styled scrollbars.
- Currency toggle is back — switch between USD and IDR with a live exchange
  rate (falls back to USD if the rate can't be fetched).

## 2.1 — 2026-07-07

**Providers**
- Added 9 built-in providers: Anthropic (native), Google Gemini, xAI (Grok),
  Groq, Mistral, Moonshot (Kimi), Together AI, Perplexity, and OpenCode Zen.
  Their model lists auto-fetch live from each provider once a key is added,
  so nothing goes stale.
- Providers are now opt-in — none are active until you enable them, and each
  provider's models default OFF too, so the composer picker only shows what
  you've turned on instead of every model at once.
- Removed the always-present "Custom" entry; custom endpoints only appear
  after you add one via "+ Add Provider".

**Onboarding & fixes**
- A "set up a provider" card on the welcome screen (when nothing is
  configured yet) opens Settings straight to Providers.
- Fixed Plan mode getting stuck: after a plan finishes executing it now
  returns to Auto, so the next message works normally.
- Staged context (Read Selection / Analyze Scene / Read Viewport) now shows
  as a chip above your message, like attached images.
- Fixed sessions being unreliable — deleted chats could reappear and new ones
  vanish after reopening the panel; the session list is now saved immediately
  on every new/delete/rename.
- Removed the Vision (eyes) setup card from Settings.

## 2.0 — 2026-07-07

The whole panel, rebuilt. MorfyAI now runs as a web-based UI (QWebEngineView),
driven by the same real agent engine underneath — same rules, memory,
auto-compression, and MCP tools as before, just a completely new front end
with a lot more surfaced.

**Providers & models**
- Multi-provider support — add, remove, and switch between any number of
  custom OpenAI-compatible providers (URL + API key + auto-fetched model list).
- Auto-detected per-model capabilities (context length, vision support,
  reasoning support) and pricing, pulled from a live model catalog.
- Per-model effort/reasoning level detection — e.g. GLM gets a 5-level dial
  (low/medium/high/max/extra), MiMo gets 2 (low/medium), matched to what each
  model actually supports instead of one-size-fits-all.
- Fixed a bug where custom-provider API keys could silently fail to save,
  causing every request to go out with no Authorization header.

**Rules, Memory, Plugins & Skills**
- Rules editor (UI rules + auto-scanned file rules) injected into every turn.
- Long-term memory toggle and tiered recall exposed in Settings.
- Plugins & Skills manager rebuilt with all three tabs (Tools, Skills,
  Plugins) — a real parity gap from earlier in the redesign.

**Chat & composer**
- Node-op ledger — every node create/modify/delete gets a per-op Undo/Keep,
  plus an Undo All / Keep All batch bar.
- Confirm mode and Plan mode.
- Slash commands (/) and @ node-mention popups in the composer.
- VEX/Python/JSON syntax highlighting in replies, a one-click "Create
  Wrangle" action on VEX code blocks, and clickable node-path links that jump
  to the node in Houdini.
- Edit & resend a previously sent message.
- Image and text attachments (paste, file picker, Read Selection/Viewport,
  Analyze Scene) rendered as proper attachment chips instead of raw text.
- Real usage/cost stats and a token-accurate context ring (previously a fake
  counter unrelated to actual token usage).
- Session persistence across restarts.

**MCP Server**
- Live connection status, universal setup prompt, and console-spam cleanup
  (the server no longer leaks its startup banner into the Houdini Console).

**Settings & About**
- Settings panel fully redesigned — pixel-aligned provider/model lists,
  reworked navigation.
- About page redesigned with working Discord/Changelog links (Discord
  branded, with the official icon).
- A new Updates page — check, download, and install new versions from
  inside the app.

**Housekeeping**
- Removed dead EN/ZH language-switcher remnants and CJK-specific token
  estimation — MorfyAI is English-only by design.
- Vendored numpy 1.26.4 — the memory system imported it unconditionally
  with no fallback, so a clean Houdini install without numpy already
  present would crash on first use.
- Simplified the Houdini top menu bar to a single "Open MorfyAI" entry
  (dropped a confusing second "Dockable Panel" option and "About"), and
  fixed its position — it now sits next to qLib/Redshift instead of at
  the far left of the menu bar.
- Fixed the drop-in release package pointing at an invalid Houdini
  variable (`$HOUDINI_PACKAGE_DIR`), which left the plugin path empty so
  nothing loaded — now uses `$HOUDINI_PACKAGE_PATH` like other packages.
- Fixed an "Access denied" crash on machines that also have the separate
  Houdini Agent product installed — its top-level `shared` module was
  shadowing MorfyAI's, redirecting the config folder into Program Files.
  MorfyAI now isolates its own modules at startup.

## 1.0 — 2026-05-28

- First public release: a full rebrand and redesign of the Houdini Agent
  plugin as MorfyAI, part of the MorfyFX ecosystem (fork attribution
  preserved in the license/README, per MIT terms).
- Procedural build tooling: a full simulation suite (FLIP, RBD, Vellum, MPM,
  Pyro, ocean, whitewater, particles) plus a general cookbook/recipe system
  for procedural HDA-style builds.
- MCP server support — drive Houdini from Claude Code, Claude Desktop,
  OpenCode, or any MCP client.
- Long-term memory system (episodic/semantic/procedural), Rules, and a
  Plugins & Skills manager.
- Visual refinement loop — the agent renders and iterates on its own results.
- In-app Debug Console (replaces Houdini Console spam).
