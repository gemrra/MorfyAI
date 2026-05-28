# -*- coding: utf-8 -*-
"""
MorfyAI plugin directory

Drop .py plugin files into this directory for auto-loading.
Files starting with _ are skipped (use for examples/templates).

Each plugin must define:
  - PLUGIN_INFO: dict  (name, version, author, description, settings)
  - register(ctx): entry point, ctx is a PluginContext instance
"""
