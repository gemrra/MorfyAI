<div align="center">

# MorfyAI

### Houdini Assistant

*AI co-pilot for SideFX Houdini — part of the **MorfyFX** ecosystem.*

[![Version](https://img.shields.io/badge/version-1.2-fb7a1a)](VERSION)
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

- **Three modes** — *Agent* (full control), *Ask* (read-only Q&A), *Plan* (review-before-execute with DAG flow)
- **40+ Houdini tools** — create / modify / connect / delete nodes, set parameters, run VEX, execute Python in scene, capture viewport, save HIP
- **Multi-provider** — DeepSeek v4, GLM-4.7, GPT-5.x, Claude, Ollama (local), OpenRouter, any custom OpenAI-compatible endpoint
- **Long-term memory** — three-tier brain-inspired store (episodic, semantic, procedural) with reflection-driven learning across sessions
- **Skill scripts** — pre-optimized analysis utilities (cook performance, normal quality, attribute stats, connectivity, dead-node detection, dependency tracing)
- **Plugin hooks** — extend with `@hook` / `@tool` / `@ui_button` decorators; per-plugin settings UI
- **Persistent rules** — Cursor-style context rules auto-injected into every request
- **Modern UI** — monochrome dark theme, browser-style tabs, in-app Debug Console, About panel, markdown chat with VEX/Python syntax highlight, code-block one-click *Create Wrangle*

## Install

1. Clone or download this repo somewhere on disk (e.g. `E:\AILocal\MorfyAI`).
2. In Houdini, open the **Python Source Editor** or a shelf-tool script:

   ```python
   import sys
   sys.path.insert(0, r"E:\AILocal\MorfyAI")
   import launcher
   launcher.show_tool()
   ```

3. The MorfyAI panel will open. Pick a provider, enter your API key, and start prompting.

A shelf-tool snippet is provided at `morfyai/shelf_tool.py` if you want one-click launch.

## Configuration

- **Provider & model** — top header dropdowns
- **API keys** — overflow menu `···` → *API Key* (stored in `config/houdini_ai.ini`, never committed)
- **Custom endpoint** — provider `Custom` opens a config dialog for any OpenAI-compatible URL
- **Rules** — overflow menu → *Rules* — write persistent context that's injected into every prompt
- **Plugins / Skills** — overflow menu → *Plugins* — toggle tools and skills

## Project Structure

```
MorfyAI/
├── morfyai/                Main plugin package
│   ├── core/               Main window, session manager, agent runner
│   ├── ui/                 Chat UI, header, input area, dialogs, theme
│   ├── utils/              AI client (multi-provider), MCP client (Houdini tools), memory, hooks
│   ├── skills/             Pre-built analysis scripts
│   └── assets/             Icons, logos
├── plugins/                Drop community plugins here
├── rules/                  Markdown context rules (auto-loaded)
├── shared/                 Cross-cutting utilities
├── lib/                    Vendored Python deps (loaded into Houdini's sys.path)
├── Doc/                    Houdini help cache (for local doc search)
├── launcher.py             Entry point
└── VERSION                 Version string
```

## Roadmap

High-priority next:

- **MorfyFX integration layer** — sync state across MorfyFX plugins
- **Workflow templates** — one-prompt setups for MPM, FLIP, pyro, RBD
- **Visual node diff** — review AI changes as before/after graph
- **USD / Solaris workflow support**

## Credits & License

MorfyAI is maintained by **[gemrra](mailto:hello.gemrra@gmail.com)** as part of the **MorfyFX** ecosystem.

The plugin is a continuation of the open-source [**Houdini Agent**](https://github.com/Kazama-Suichiku/Houdini-Agent) (v1.5.5) by **KazamaSuichiku**, released under the MIT License. The core agent engine, tool integrations, multi-session management, and underlying functionality come from that work — full attribution preserved in the in-plugin About dialog and in this distribution. Original upstream commit history is archived on the [`upstream-houdini-agent`](../../tree/upstream-houdini-agent) branch of this repo for transparency.

The MorfyAI rebrand — UI redesign, theme, this README, About panel, feature trimming — was developed by gemrra with iterative assistance from **Claude** (Anthropic).

### License

MIT — see [LICENSE](LICENSE). Original copyright notice preserved.

### Contact

Bug reports, feature requests, feedback: **hello.gemrra@gmail.com**
