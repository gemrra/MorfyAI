# -*- coding: utf-8 -*-
"""
Example plugin — demonstrates the full MorfyAI Hook system.

Files starting with _ are skipped during auto-load.
Rename to example_plugin.py (drop the underscore) to enable it.

Plugin contract:
  1. PLUGIN_INFO dict  — plugin metadata
  2. register(ctx)     — entry point; ctx is a PluginContext instance

★ Decorator API also supported (@hook / @tool / @ui_button) — see examples below.
"""

PLUGIN_INFO = {
    "name": "Example Plugin",
    "version": "1.1.0",
    "author": "MorfyAI Community",
    "description": "Demonstrates all plugin capabilities: hooks, tools, buttons, settings, decorators",
    "settings": [
        {
            "key": "log_level",
            "type": "string",
            "label": "Log Level",
            "default": "info",
            "options": ["debug", "info", "warning", "error"],
        },
        {
            "key": "enable_greeting",
            "type": "bool",
            "label": "Enable Greeting Tool",
            "default": True,
        },
        {
            "key": "greeting_prefix",
            "type": "string",
            "label": "Greeting Prefix",
            "default": "Hello",
        },
    ],
}


# ─────────────────────────────────────────────
# Decorator API example (optional — also works outside register())
#
# Decorators are auto-applied to ctx after register() runs.
# Note: the decorator API uses global collectors that are cleared
#       before each plugin loads, so plugins don't conflict.
# ─────────────────────────────────────────────

# from morfyai.utils.hooks import hook, tool, ui_button
#
# @hook("on_content_chunk")
# def on_content(content, iteration=0):
#     """Live-listen to every text chunk emitted by the AI."""
#     pass  # Could do word counting, content filtering, etc.
#
# @tool(name="decorator_example", description="Decorator-registered tool")
# def decorator_tool(args):
#     return {"success": True, "result": "From decorator!"}
#
# @ui_button(icon="🎯", tooltip="Decorator Button")
# def on_btn():
#     print("Decorator button clicked!")


def register(ctx):
    """Plugin entry point — ctx is a PluginContext instance.

    Available API:
      ctx.on(event, callback, priority=100)  — register an event hook
      ctx.register_tool(...)                 — register a custom tool (AI-callable)
      ctx.register_button(icon, ...)         — register a toolbar button
      ctx.insert_chat_card(widget)           — insert a custom QWidget into the chat
      ctx.get_setting(key)                   — read plugin setting
      ctx.set_setting(key, value)            — write plugin setting
      ctx.log(msg)                           — emit log

    Available events:
      on_before_request   — (messages) -> messages   (pipeline filter)
      on_after_response   — (result, model, provider)
      on_before_tool      — (tool_name, args)
      on_after_tool       — (tool_name, args, result)
      on_content_chunk    — (content, iteration)
      on_session_start    — (session_id)
      on_session_end      — (session_id)
    """

    # ─────────────────────────────────────────────
    # 1. Listen for events — log after every tool call
    # ─────────────────────────────────────────────
    log_level = ctx.get_setting("log_level", "info")

    def on_tool_done(tool_name, args, result, **kwargs):
        if log_level == "debug":
            ctx.log(f"Tool {tool_name}({args}) -> {result}")
        else:
            ctx.log(f"Tool {tool_name} -> success={result.get('success')}")

    ctx.on("on_after_tool", on_tool_done)

    # ─────────────────────────────────────────────
    # 2. Register a custom tool — callable by the AI.
    #    The tool is auto-registered into ToolRegistry and available in all modes.
    # ─────────────────────────────────────────────
    if ctx.get_setting("enable_greeting", True):
        prefix = ctx.get_setting("greeting_prefix", "Hello")

        def greet_handler(args):
            name = args.get("name", "World")
            return {
                "success": True,
                "result": f"{prefix}, {name}! This is from Example Plugin."
            }

        ctx.register_tool(
            name="example_greeting",
            description="Say hello to someone (example plugin tool)",
            schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The person to greet",
                    }
                },
                "required": ["name"],
            },
            handler=greet_handler,
        )

    # ─────────────────────────────────────────────
    # 3. Register a toolbar button
    # ─────────────────────────────────────────────
    def on_button_click():
        ctx.log("Example button clicked!")

    ctx.register_button(
        icon="👋",
        tooltip="Example Plugin Greeting",
        callback=on_button_click,
    )

    # ─────────────────────────────────────────────
    # 4. Pipeline-style prompt filter (on_before_request)
    #    Callback signature supports either (messages) or (messages, **kwargs)
    # ─────────────────────────────────────────────
    def add_custom_instruction(messages, **kwargs):
        """Append a custom instruction at the end of the system prompt."""
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] += (
                "\n\n[Example Plugin] "
                "You have access to example_greeting tool from Example Plugin."
            )
        return messages

    ctx.on("on_before_request", add_custom_instruction)

    # ─────────────────────────────────────────────
    # 5. Session-start / session-end hooks
    # ─────────────────────────────────────────────
    ctx.on("on_session_start", lambda session_id, **kw:
           ctx.log(f"Session started: {session_id}"))
    ctx.on("on_session_end", lambda session_id, **kw:
           ctx.log(f"Session ended: {session_id}"))

    ctx.log("Example Plugin registered successfully!")
