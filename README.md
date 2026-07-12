<div align="center">

# MorfyAI

### Houdini Assistant

*AI co-pilot for SideFX Houdini — part of the **MorfyFX** ecosystem.*

[![Version](https://img.shields.io/badge/version-2.8-fb7a1a)](VERSION)
[![License](https://img.shields.io/badge/license-MIT-94a3b8)](#license)
[![Houdini](https://img.shields.io/badge/Houdini-19.5%2B-FF6B00)](https://www.sidefx.com)

</div>

---

## What is MorfyAI?

MorfyAI is an in-Houdini AI assistant that reads your scene, builds and modifies node networks, writes VEX, runs Python, and ships full procedural setups from natural-language prompts. It runs as a Python panel inside Houdini and talks to your preferred LLM (DeepSeek, OpenAI, Anthropic, Ollama, local, or any OpenAI-compatible endpoint).

```
You:  "Buat MPM simulation dengan sphere collider, 5 detik"
AI:   ✓ created /obj/geo1/mpmsource1 (sphere emitter)
      ✓ created /obj/geo1/mpmcollider1 (ground)
      ✓ created /obj/geo1/mpmsolver1 (5 second range)
      ✓ created /obj/geo1/mpmobject1
      ✓ connected, display flag set
      Done — try playback now.
```

## Key Features

- **Web-based panel** — runs inside Houdini via a real browser engine (QWebEngineView), driven by the same real agent underneath — rules, memory, auto-compression, and MCP tools all included
- **Two modes** — *Auto* (full control) and *Plan* (review-before-execute)
- **40+ Houdini tools** — create / modify / connect / delete nodes, set parameters, run VEX, execute Python in scene, capture viewport, save HIP
- **Multi-provider, opt-in** — DeepSeek, Anthropic (native), Google Gemini, xAI (Grok), Groq, Mistral, Moonshot (Kimi), Together AI, Perplexity, OpenCode Zen, OpenRouter, Ollama (local), or any custom OpenAI-compatible endpoint — providers and models are off by default, auto-fetched model lists, auto-detected capabilities/pricing
- **MCP server** — expose the same Houdini toolset over streamable-HTTP so any MCP client (Claude Code, Claude Desktop, OpenCode, Codex CLI, Cursor, …) can drive the scene directly
- **Long-term memory** — three-tier brain-inspired store (episodic, semantic, procedural) with reflection-driven learning across sessions
- **50+ built-in skills** — look-dev, modeling, attributes, pipeline, sim builders (FLIP/RBD/Vellum/MPM/Pyro/ocean/particles), node/parm housekeeping utilities, and analysis scripts (cook performance, normal quality, connectivity, dead-node detection, dependency tracing)
- **Plugin hooks** — extend with `@hook` / `@tool` / `@ui_button` decorators; per-plugin settings UI
- **Persistent rules** — Cursor-style context rules auto-injected into every request
- **Node-op ledger** — every mutating tool call gets a per-op Undo/Keep, plus an Undo All / Keep All batch bar
- **Modern chat** — markdown replies with VEX/Python/JSON syntax highlighting, one-click *Create Wrangle*, clickable node-path links, slash commands, @ node-mentions, edit & resend
- **Token usage analytics** — a dedicated window with a cost-per-request chart, per-model cost breakdown, and a USD/IDR toggle
- **Dev-mode install** — an isolated second package (`MorfyAI Dev`) so you can iterate on a git clone without touching your daily-driver install
- **Built-in updater** — Settings → Updates checks GitHub for new releases and installs them with one click, no manual re-download

## Install

Download the latest release and drop it straight into Houdini's `packages/` folder — no script to run:

1. Grab `MorfyAI-<version>.zip` from the [Releases page](../../releases/latest).
2. Extract it directly into `$HOUDINI_USER_PREF_DIR/packages/` (e.g. `Documents/houdini20.5/packages/`). The zip already contains both `MorfyAI.json` (the package pointer) and the `MorfyAI/` folder — nothing to edit.
3. Restart Houdini. The MorfyAI shelf button appears automatically.
4. Pick a provider, enter your API key, and start prompting.

From then on, **Settings → Updates** checks for new versions and installs them with one click — no need to repeat this process manually.

### Development / running from a git clone

If you're working on MorfyAI itself (not just using it), you can run it straight from a cloned repo instead of a release zip:

```python
import sys; sys.path.insert(0, r"E:\AILocal\MorfyAI")
import install; install.install()
```

Run that once inside Houdini's Python Shell — it writes a package file pointing at your clone, so you never edit paths by hand. Restart Houdini afterward.

## Configuration

- **Provider & model** — composer toolbar, bottom right
- **API keys** — Settings → Providers (stored in `config/houdini_ai.ini`, never committed)
- **Custom endpoint** — add a custom provider in Settings → Providers for any OpenAI-compatible URL
- **Rules** — Settings → Rules — write persistent context that's injected into every prompt
- **Plugins / Skills** — Settings → Plugins & Skills — toggle tools and skills
- **MCP Server** — Settings → MCP Server — run a local streamable-HTTP MCP endpoint so external MCP clients can drive Houdini too
- **Updates** — Settings → Updates — check for and install new releases

## Project Structure

```
MorfyAI/
├── morfyai/                Main plugin package
│   ├── core/               Main window, session manager, agent runner
│   ├── ui/                 Headless AITab engine, web_panel.py (QWebChannel bridge), dialogs, theme
│   ├── webui/              index.html — the web panel UI (chat, settings, everything)
│   ├── utils/              AI client (multi-provider), MCP client (Houdini tools), memory, hooks
│   ├── skills/             Pre-built analysis scripts
│   └── assets/             Icons, logos
├── plugins/                Drop community plugins here
├── rules/                  Markdown context rules (auto-loaded)
├── shared/                 Cross-cutting utilities
├── lib/                    Vendored Python deps (loaded into Houdini's sys.path)
├── Doc/                    Houdini help cache (for local doc search)
├── tools/release/          Release zip builder (build_zip.py)
├── launcher.py             Entry point
├── install.py              One-click package installer (for a git-clone dev setup)
├── CHANGELOG.md            Release notes, one entry per version
└── VERSION                 Version string
```

## Roadmap

High-priority next:

- **MorfyFX integration layer** — sync state across MorfyFX plugins
- **Visual node diff** — review AI changes as before/after graph
- **USD / Solaris workflow support**

Already shipped (moved out of roadmap): the web-based panel rewrite, MCP server, opt-in multi-provider support, deterministic sim builders (FLIP/RBD/Vellum/MPM/Pyro/ocean/particles), and 50+ built-in skills — see [CHANGELOG.md](CHANGELOG.md).

## Credits & License

MorfyAI is maintained by **gemrra** as part of the **MorfyFX** ecosystem.

The plugin is a continuation of the open-source [**Houdini Agent**](https://github.com/Kazama-Suichiku/Houdini-Agent) (v1.5.5) by **KazamaSuichiku**, released under the MIT License. Full attribution is preserved here and in [LICENSE](LICENSE), as the MIT License requires. Original upstream commit history is archived on the [`upstream-houdini-agent`](../../tree/upstream-houdini-agent) branch of this repo for transparency.

The MorfyAI rebrand — UI redesign, theme, this README, About panel, feature trimming — was developed by gemrra with iterative assistance from **Claude** (Anthropic).

### License

MIT — see [LICENSE](LICENSE). Original copyright notice preserved.

### Contact

Bug reports, feature requests, feedback: join the [MorfyFX Discord](https://discord.gg/vpqC66mUY3) (also linked from Settings → About inside the app).
