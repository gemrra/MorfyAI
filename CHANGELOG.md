# Changelog

All notable changes to MorfyAI are documented here. One entry per release —
this is also what gets pasted into the GitHub Release notes and the public
changelog page at morfyfx.com/morfyai/changelog.

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
