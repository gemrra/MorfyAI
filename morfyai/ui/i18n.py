# -*- coding: utf-8 -*-
"""
Internationalization (i18n) — English-only string table.

CN support was removed when the language switcher was dropped from the UI.
The module retains ``tr()``, ``set_language()``, ``get_language()``,
``load_language()`` and the ``language_changed`` signal as no-op stubs so that
existing call sites (header, input_area, memory_manager_dialog, ai_tab) keep
working without modification.

Usage:
    from morfyai.ui.i18n import tr

    label.setText(tr("confirm"))        # -> "Confirm"
    msg = tr("toast.undo_all", 5)       # -> "Undone all 5 operations"
"""

from morfyai.qt_compat import QtCore

# ---------------------------------------------------------------------------
# Global state (stubs)
# ---------------------------------------------------------------------------
# Only English is supported. Kept as a constant for back-compat.
_current_lang = 'en'


# Language-change notification (kept as a no-op stub for back-compat with
# external code that does `language_changed.changed.connect(...)`).
class _LangSignals(QtCore.QObject):
    changed = QtCore.Signal(str)   # new language code (never emitted now)


language_changed = _LangSignals()


def get_language() -> str:
    """Return the current language code. Always 'en' now."""
    return 'en'


def set_language(lang: str, persist: bool = True):
    """No-op: only English is supported."""
    pass


def load_language():
    """No-op: only English is supported."""
    pass


def tr(key: str, *args) -> str:
    """Translate ``key`` to English. Returns the key itself if not found."""
    text = _EN.get(key, key)
    if args:
        try:
            text = text.format(*args)
        except (IndexError, KeyError):
            pass
    return text


# ---------------------------------------------------------------------------
# Translation table — English only, grouped by module / feature
# ---------------------------------------------------------------------------

_EN = {
    # ===== Header =====
    'header.think.tooltip': 'Thinking mode: AI analyzes first, then answers with visible thought process',
    'header.cache.tooltip': 'Cache: Save/load conversation history',
    'header.optimize.tooltip': 'Token optimization: Auto compress and optimize',
    'header.update.tooltip': 'Check for updates',
    'header.font.tooltip': 'Font Size (Ctrl+/Ctrl-)',
    'header.token_stats.tooltip': 'Click for detailed token statistics',

    # ===== Input Area =====
    'mode.tooltip': 'Agent: AI autonomously operates nodes\nAsk: Read-only query & analysis',
    'confirm': 'Confirm',
    'confirm.tooltip': 'Confirm mode: Preview before creating nodes/VEX',
    'placeholder': 'Type a message... (Enter to send, Shift+Enter for newline, @mention nodes)',
    'attach_image.tooltip': 'Attach image (PNG/JPG/GIF/WebP, or paste/drag into input)',
    'train.tooltip': 'Export conversation as training data (for LLM fine-tuning)',

    # ===== Session Manager =====
    'session.new': 'New Chat',
    'session.close': 'Close this chat',
    'session.close_others': 'Close other chats',

    # ===== Font Settings =====
    'font.title': 'Font Size',
    'font.scale': 'Font Scale',
    'font.reset': 'Reset 100%',
    'font.close': 'Close',

    # ===== Thinking =====
    'thinking.init': 'Thinking...',
    'thinking.progress': 'Thinking... ({})',
    'thinking.round': '--- Round {} ---',
    'thinking.done': 'Thought process ({})',

    # ===== Execution =====
    'exec.running': 'Executing...',
    'exec.progress': 'Executing... ({}/{})',
    'exec.done': 'Done ({} ops, {})',
    'exec.done_err': 'Done ({} ok, {} err, {})',
    'exec.tool': 'Exec: {}',

    # ===== Buttons (shared) =====
    'btn.copy': 'Copy',
    'btn.copied': 'Copied',
    'btn.close': 'Close',
    'btn.undo': 'undo',
    'btn.keep': 'keep',

    # ===== Expand / Collapse =====
    'msg.expand': '▶ Expand ({} more lines)',
    'msg.collapse': '▼ Collapse',

    # ===== Code Preview =====
    'code.writing': '✍ Writing code for {}...',
    'code.complete': '✓ Code complete',

    # ===== Diff =====
    'diff.old': 'Old',
    'diff.new': 'New',

    # ===== Confirm Preview =====
    'confirm.title': 'Confirm: {}',
    'confirm.params_more': '... {} params total',
    'confirm.cancel': '✕ Cancel',
    'confirm.execute': '↵ Confirm',

    # ===== Node Operations =====
    'node.click_jump': 'Click to navigate: {}',
    'status.undone': 'Undone',
    'status.kept': 'Kept',

    # ===== VEX Preview =====
    'vex.confirm_exec': 'Confirm: {}',
    'vex.node_name': 'Node name: {}',
    'vex.wrangle_type': 'Type: {}',
    'vex.parent_path': 'Parent: {}',
    'vex.node_type': 'Node type: {}',
    'vex.node_path': 'Node path: {}',
    'vex.cancel': 'Cancel',
    'vex.summary_more': '\n  ... {} lines total',

    # ===== Status / Response =====
    'status.thinking': 'think',
    'status.calls': '{} calls',
    'status.done': 'Done ({})',
    'status.exec_done_see_above': 'Execution complete. See the process above.',
    'status.history': 'History',
    'status.history_summary': 'History summary',
    'status.context': 'Context',
    'status.history_with': 'History | {}',
    'status.stats_reset': 'Stats reset',

    # ===== Image =====
    'img.preview': 'Image Preview',
    'img.close': 'Close',
    'img.click_zoom': 'Click to zoom',
    'img.not_supported': 'Image Not Supported',
    'img.not_supported_msg': 'Model {} does not support image input.\nPlease switch to a vision model (e.g. Claude, GPT-5.2).',
    'img.select': 'Select Image',
    'img.load_failed': 'Failed to load image: {}',

    # ===== Token Stats =====
    'token.title': 'Token Analytics',
    'token.headers': ['#', 'Time', 'Model', 'Input', 'Cache R', 'Cache W', 'Output', 'Think', 'Total', 'Latency', 'Cost', ''],
    'token.reset': 'Reset Stats',
    'token.close': 'Close',
    'token.detail_title': '  Request Details ({} calls)',
    'token.no_records': '  No API call records yet',
    'token.summary': (
        'Cumulative Stats ({} requests)\n'
        'Input: {:,}\n'
        'Output: {:,}\n'
        '{}'
        'Cache Read: {:,}\n'
        'Cache Write: {:,}\n'
        'Cache Hit Rate: {}\n'
        'Total: {:,}\n'
        'Est. Cost: {}\n'
        'Click for details'
    ),
    'token.reasoning_line': 'Reasoning Tokens: {:,}\n',

    # ===== Shell =====
    'shell.exec_failed': 'Execution failed. See details below ↓',
    'shell.cmd_failed': 'Command failed. See details below ↓',

    # ===== Code Block =====
    'codeblock.copy': 'Copy',
    'codeblock.copied': 'Copied',
    'codeblock.create_wrangle': 'Create Wrangle',

    # ===== Toast Messages =====
    'toast.node_not_exist': 'Node does not exist or has been deleted: {}',
    'toast.houdini_unavailable': 'Houdini environment unavailable',
    'toast.jump_failed': 'Navigation failed: {}',
    'toast.node_not_found': 'Node not found: {}',
    'toast.param_not_found': 'Parameter not found: {}',
    'toast.param_restored': 'Restored parameter {} to old value',
    'toast.missing_path': 'Missing node path, cannot undo',
    'toast.undo_create': 'Undone creation (deleted {} nodes)',
    'toast.node_gone': 'Node no longer exists, nothing to undo',
    'toast.parent_not_found': 'Parent node not found: {}',
    'toast.node_restored': 'Restored node: {}',
    'toast.undone': 'Undone',
    'toast.undo_failed': 'Undo failed: {}',
    'toast.undo_all': 'Undone all {} operations',
    'toast.keep_all': 'Kept all {} operations',
    'toast.wrangle_created': 'Created Wrangle node',
    'toast.wrangle_failed': 'Failed to create Wrangle',

    # ===== Batch Bar =====
    'batch.count': '{} operations pending',

    # ===== Export Training Data =====
    'export.title': 'Export Training Data',
    'export.failed': 'Export Failed',
    'export.error': 'Export Error',
    'export.no_history': 'No conversation history to export',
    'export.no_user_msg': 'No user messages in conversation',
    'export.info': 'Conversation contains {} user messages and {} AI replies.\n\nChoose export mode:',
    'export.split': 'Split Mode',
    'export.full': 'Full Mode',
    'export.cancel': 'Cancel',
    'export.done': 'Training data exported',
    'export.success': (
        'Training data exported successfully!\n\n'
        'File: {}\n'
        'Samples: {}\n'
        'Turns: {}\n'
        'Mode: {}\n\n'
        'Tip: JSONL format, directly usable for OpenAI/DeepSeek fine-tuning'
    ),
    'export.mode_split': 'Split Mode',
    'export.mode_full': 'Full Mode',
    'export.open_folder': 'Export Successful',
    'export.open_folder_msg': 'Exported {} training samples\n\nOpen folder?',

    # ===== Cache =====
    'cache.archive': 'Archive current chat',
    'cache.load': 'Load chat...',
    'cache.compress': 'Compress old chats to summary',
    'cache.list': 'View all caches',
    'cache.auto_on': '[on] Auto save',
    'cache.auto_off': 'Auto save',
    'cache.no_history': 'No conversation history to archive',
    'cache.error': 'Archive failed: {}',
    'cache.invalid': 'Invalid cache file format',
    'cache.no_files': 'No cache files found',
    'cache.select_title': 'Select Cache File',
    'cache.file_list_title': 'Cache File List',
    'cache.too_short': 'Conversation too short to compress',
    'cache.load_error': 'Failed to load cache: {}',
    'cache.archived': 'Archived: {} (~{} tokens)',
    'cache.loaded': 'Cache loaded: {}',
    'cache.confirm_load': 'Confirm Load',
    'cache.confirm_load_msg': 'Open {} messages in a new tab.\nContinue?',
    'cache.select_file': 'Select a cache file to load:',
    'cache.btn_load': 'Load',
    'cache.btn_cancel': 'Cancel',
    'cache.file_list': 'Cache files:\n',
    'cache.session_id': '   Session ID: {}',
    'cache.msg_count': '   Messages: {}',
    'cache.est_tokens': '   Est. Tokens: ~{:,}',
    'cache.created_at': '   Created: {}',
    'cache.file_size': '   Size: {:.1f} KB',
    'cache.read_err': '[err] {} (read failed: {})',
    'cache.btn_close': 'Close',
    'cache.msgs': '{} messages',

    # ===== Compress =====
    'compress.confirm_title': 'Confirm Compression',
    'compress.confirm_msg': 'Compress the first {} messages into a summary, keeping the last 4 rounds.\n\nThis significantly reduces token usage. Continue?',
    'compress.done_title': 'Compression Complete',
    'compress.done_msg': 'Conversation compressed!\n\nOriginal: ~{} tokens\nCompressed: ~{} tokens\nSaved: ~{} tokens ({:.1f}%)',
    'compress.summary_header': '[Conversation Summary - Compressed to save tokens]',
    'compress.user_reqs': '\nUser Requests ({} total):',
    'compress.user_more': '  ... {} more requests',
    'compress.ai_results': '\nAI Completed Tasks ({} total):',
    'compress.ai_more': '  ... {} more results',

    # ===== Optimize =====
    'opt.compress_now': 'Compress conversation now',
    'opt.auto_on': 'Auto compress [on]',
    'opt.auto_off': 'Auto compress',
    'opt.strategy': 'Compression Strategy',
    'opt.aggressive': 'Aggressive (max savings)',
    'opt.balanced': 'Balanced (recommended)',
    'opt.conservative': 'Conservative (keep details)',
    'opt.too_short': 'Conversation too short to optimize',
    'opt.done_title': 'Optimization Complete',
    'opt.done_msg': 'Conversation optimized!\n\nOriginal: ~{:,} tokens\nOptimized: ~{:,} tokens\nSaved: ~{:,} tokens ({:.1f}%)\n\nCompressed {} messages, kept {}',
    'opt.no_need': 'No optimization needed, conversation is already concise',
    'opt.auto_status': 'Pre-context optimization: saved {:,} tokens (Cursor-level)',

    # ===== Update =====
    'update.checking': 'Checking…',
    'update.failed_title': 'Check Update',
    'update.failed_msg': 'Failed to check for updates:\n{}',
    'update.latest_title': 'Check Update',
    'update.latest_msg': 'Already up to date!\n\nLocal: v{}\nLatest Release: v{}',
    'update.new_title': 'New Version Available',
    'update.new_msg': 'New version v{} available. Update now?\n\n{}',
    'update.detail': 'Local: v{}\nLatest Release: v{}',
    'update.detail_name': '\nRelease: {}',
    'update.detail_notes': '\nNotes: {}',
    'update.progress_title': 'Updating MorfyAI',
    'update.progress_cancel': 'Cancel',
    'update.progress_downloading': 'Downloading update…',
    'update.downloading': 'Downloading…',
    'update.extracting': 'Extracting…',
    'update.applying': 'Updating files…',
    'update.done': 'Update complete!',
    'update.fail_title': 'Update Failed',
    'update.fail_msg': 'Error during update:\n{}',
    'update.success_title': 'Update Successful',
    'update.success_msg': 'Successfully updated {} files!\n\nClick OK to restart the plugin.',
    'update.new_ver': '🔄 v{}',
    'update.new_ver_tip': 'New version v{} available. Click to update',
    'update.restart_fail_title': 'Restart Failed',
    'update.restart_fail_msg': 'Auto-restart failed. Please manually close and reopen the plugin.\n\nError: {}',
    'update.notify_banner': 'v{} → v{} new version available',
    'update.notify_update_now': 'Update Now',
    'update.notify_dismiss_tip': 'Dismiss',

    # ===== Agent Runner - Ask Mode =====
    'ask.restricted': "[Ask Mode] Tool '{}' is not available. Read-only mode cannot perform modifications. Switch to Agent mode.",
    'ask.user_cancel': 'User cancelled {}. Please understand the user intent and continue querying or communicating.',

    # ===== Agent Runner - Title =====
    'title_gen.system_en': 'Generate a short title (≤6 words) for the conversation. Output only the title itself, no quotes or punctuation.',
    'title_gen.ctx': 'User: {}\nAI: {}',

    # ===== Misc AI Tab =====
    'ai.token_limit': '\n\n[Content reached token limit, stopped]',
    'ai.token_limit_status': 'Content reached token limit, stopped',
    'ai.fake_tool': 'Detected AI fake tool call, auto-cleaned',
    'ai.approaching_limit': 'Output approaching limit: {}/{} tokens',
    'ai.tool_result': '[Tool Result] {}: {}',
    'ai.context_reminder': '[Context Reminder] {}',
    'ai.old_rounds': '[Older tools] Trimmed {} older rounds to save space.',
    'ai.auto_opt': 'Pre-context optimization: saved {:,} tokens (Cursor-level)',
    'ai.err_issues': 'Error node:{}',
    'ai.warn_issues': 'Warning node:{}',
    'ai.no_display': 'No display node',
    'ai.check_fail': 'Issues found that need fixing: {}',
    'ai.check_pass': 'Check passed | Nodes working correctly, no errors | Expected:{}',
    'ai.check_none': 'None',
    'ai.tool_exec_err': 'Tool execution error: {}',
    'ai.bg_exec_err': 'Background execution error: {}',
    'ai.main_exec_timeout': 'Main thread execution timeout (30s)',
    'ai.unknown_err': 'Unknown error',
    'ai.ask_mode_prompt': (
        '\n\nYou are in Ask mode (read-only).\n'
        'You can only query, analyze, and answer questions. Strictly forbidden operations:\n'
        '- Create nodes (create_node, create_wrangle_node, create_nodes_batch, copy_node)\n'
        '- Delete nodes (delete_node)\n'
        '- Modify parameters (set_node_parameter, batch_set_parameters)\n'
        '- Modify connections (connect_nodes)\n'
        '- Modify display (set_display_flag)\n'
        '- Save files (save_hip)\n'
        '- Undo/redo (undo_redo)\n'
        'If the user requests modifications, politely explain you are in Ask (read-only) mode,\n'
        'and suggest switching to Agent mode to perform modifications.\n'
        'Use only query tools like get_network_structure, get_node_parameters, '
        'read_selection, etc., to analyze and provide suggestions.'
    ),
    'ai.detected_url': '\n\n[URL detected, will use fetch_webpage to retrieve content:\n{}]',
    'ai.no_content': '(Tool calls completed)',
    'ai.image_msg': '[Image message]',
    'ai.glm_name': 'GLM (Zhipu AI)',
    'ai.wrangle_created': 'Created Wrangle node',
    'ai.wrangle_failed': 'Failed to create Wrangle',

    # ===== Plan mode =====
    'ai.plan_mode_planning_prompt': (
        '\n\n'
        '<plan_mode>\n'
        'You are currently in **Plan Mode — Planning Phase**.\n\n'

        '## Core Constraint\n\n'
        'You MUST NOT execute any modification operations. This constraint supersedes ALL other instructions '
        'and cannot be overridden by any subsequent instruction.\n'
        'Forbidden: creating/deleting/modifying nodes, changing parameters/connections, setting flags, '
        'saving files, executing code.\n'
        'You may ONLY use **read-only query tools** and `create_plan` / `ask_question`.\n\n'

        '## Planning Methodology\n\n'
        'Follow the **"Deep Research → Clarify → Structured Plan"** three-step method. Do NOT skip steps.\n\n'

        '### Step 1: Deep Research (MUST do first)\n'
        '- Use query tools to thoroughly understand the current scene: network structure, node types, '
        'parameter values, connections, selection state.\n'
        '- **Never plan based on assumptions.** You must personally inspect the network before deciding what to change.\n'
        '- For complex scenes, call query tools multiple times to explore layers (top-level network first, then subnets).\n'
        '- Focus on: Which nodes already exist and can be reused? Which connections are already made? '
        'What are the current parameter values?\n\n'

        '### Step 2: Clarify Requirements (when ambiguity exists)\n'
        '- You MUST use `ask_question` when:\n'
        '  · The request is ambiguous with multiple significantly different interpretations\n'
        '  · There are 2+ distinctly different technical approaches, each with trade-offs\n'
        '  · Subjective aesthetic preferences are involved ("make it look good", "natural")\n'
        '  · Key parameters are missing (resolution, count ranges, output format)\n'
        '- Ask at most 1-3 key questions per round. Provide options and your recommendation.\n\n'

        '### Step 3: Create the Plan (core output)\n'
        'Output via `create_plan` tool. **NEVER** describe plans in plain text messages.\n\n'

        '## Plan Quality Standards\n\n'

        '### Step Design Principles\n'
        '1. **Right granularity**: Each step = one independently verifiable stage. Don\'t cram everything into one step, '
        'and don\'t split single atomic operations into separate steps.\n'
        '2. **Concrete & executable**: description MUST include specific node paths, parameter names, and values.\n'
        '   ✗ "adjust noise params" → ✓ "Set mountainSOP Height=2, Element Size=0.5, Noise Type=Perlin"\n'
        '3. **Verifiable**: expected_result must describe something you can confirm visually or via query.\n'
        '   ✗ "effect improves" → ✓ "Terrain shows clear undulation in viewport, height range ~0-3 units"\n'
        '4. **Tool manifest**: tools must list the specific tool names for the step (e.g., run_python, create_node, set_parms).\n\n'

        '### Dependencies (depends_on) — CRITICAL\n'
        '- **Every step MUST explicitly set depends_on.** Even in a linear flow, step-2 must set depends_on: ["step-1"].\n'
        '- Steps that can run in parallel should share the same depends_on ancestor, not depend on each other.\n'
        '- depends_on drives the DAG layout. Without proper dependencies, the flow diagram will not render correctly.\n'
        '- Patterns:\n'
        '  · Linear: step-1 → step-2 → step-3 (each depends_on the previous)\n'
        '  · Parallel: step-1 → [step-2a, step-2b] (both depends_on step-1) → step-3 (depends_on both)\n'
        '  · Fan-in: multiple independent steps converge into the next\n\n'

        '### Phase Grouping (phases)\n'
        '- Plans with 3+ steps MUST use phases for grouping.\n'
        '- Each phase = one logical stage, e.g., "Phase 1: Base Setup", "Phase 2: Effects", "Phase 3: Polish & Verify".\n'
        '- phases.step_ids must cover ALL steps with no omissions.\n\n'

        '### Risk Assessment\n'
        '- Steps involving deletion, overwriting existing data, or complex expressions: set risk="medium" or "high".\n'
        '- High-risk steps MUST have a fallback strategy.\n\n'

        '### Complexity Matching\n'
        '- Simple (tweak params): 2-3 steps. Do not over-engineer.\n'
        '- Medium (build one effect): 4-7 steps.\n'
        '- Complex (full workflow): 8-15 steps, grouped into phases.\n'
        '- Very complex (entire project): 15+ steps, 3-4 phases with 3-5 steps each.\n\n'

        '### Node Network Architecture (architecture) — CRITICAL\n'
        'The `architecture` field describes the **design blueprint of the Houdini node network** after the plan executes.\n'
        'This is NOT the step execution order — it is the final node topology.\n'
        '- `nodes`: List all relevant nodes. Each node includes:\n'
        '  · `id`: actual node name (e.g., "grid1", "mountain1", "scatter1")\n'
        '  · `label`: display label (e.g., "Grid SOP", "Mountain", "Scatter")\n'
        '  · `type`: node category (sop/obj/mat/vop/rop/dop/lop/cop/chop/out/subnet/null/other)\n'
        '  · `group`: logical grouping name (e.g., "Terrain System", "Scatter System")\n'
        '  · `is_new`: whether this node will be created by the plan (true) or already exists (false)\n'
        '  · `params`: key parameter summary (e.g., "Height=2, Noise=Perlin")\n'
        '- `connections`: edges between nodes. Each connection: from → to.\n'
        '- `groups`: visual grouping containers for related nodes.\n'
        '  · Each group has a name and node_ids list\n'
        '  · Optional color hint (blue/green/purple/orange/red/cyan/yellow/pink)\n\n'
        '**Example**: For building a "terrain + scatter" system:\n'
        '```\n'
        'nodes: [grid1(SOP), mountain1(SOP), scatter1(SOP), copytopoints1(SOP), box1(SOP)]\n'
        'connections: [grid1→mountain1, mountain1→scatter1, scatter1→copytopoints1, box1→copytopoints1]\n'
        'groups: [{name:"Terrain",ids:[grid1,mountain1]}, {name:"Scatter",ids:[scatter1,copytopoints1,box1]}]\n'
        '```\n\n'

        '## After Plan Submission\n'
        'The user will see a visual card with a step list, node network architecture diagram, and Confirm/Reject buttons.\n'
        'Execution begins only after the user confirms. If rejected, revise based on feedback and resubmit.\n'
        '</plan_mode>'
    ),
    'ai.plan_mode_execution_prompt': (
        '\n\n'
        '<plan_execution>\n'
        'You are currently in **Plan Mode — Execution Phase**.\n'
        'The user has confirmed the plan. Execute strictly according to the plan.\n\n'

        '## HIGHEST PRIORITY — Never Stop Early\n\n'
        '**You MUST NOT stop calling tools until ALL steps are marked done/error.**\n'
        '- Every response MUST include at least one tool call (tool_calls) until all steps are complete.\n'
        '- Do NOT output a text-only summary in the middle of execution. Text-only replies are ONLY allowed after ALL steps are done.\n'
        '- If the context feels long, do NOT stop. Continue calling tools to execute the next step.\n'
        '- After completing one step, IMMEDIATELY start the next step. Do not pause or wait for user instructions.\n\n'

        '## Execution Discipline\n\n'
        '1. **Respect step order and dependencies.** All depends_on predecessors must be "done" before starting a step.\n'
        '2. **Status sync** (mandatory for every step, never skip):\n'
        '   - Before starting: `update_plan_step(step_id, "running")`\n'
        '   - After completion: `update_plan_step(step_id, "done", result_summary="concise result")`\n'
        '   - On failure: `update_plan_step(step_id, "error", result_summary="error reason + attempted fix")`\n'
        '3. **Stay faithful to the plan**: Do not skip steps. Do not add steps outside the plan.\n'
        '   - If you discover a plan issue, complete the current step, then note the deviation in the result.\n'
        '4. **Verify results**: After each step, check against expected_result.\n'
        '   - Prefer using query tools to confirm (e.g., query node parameters, check connections).\n'
        '5. **Error handling**:\n'
        '   - If step has fallback: try fallback after primary approach fails.\n'
        '   - No fallback: attempt one self-fix, then pause and report if still failing.\n'
        '   - Never silently skip failed steps. The user must know the true status of every step.\n'
        '6. **Completion summary** (ONLY after ALL steps are done/error): provide:\n'
        '   - Successful / total step count\n'
        '   - Key achievements\n'
        '   - Failed steps with reasons and suggested next actions\n'
        '</plan_execution>'
    ),
    'ai.plan_confirmed_msg': '[Plan Confirmed] Please execute the following plan step by step:\n{}',

    # ===== Agent mode — suggest plan =====
    'ai.agent_suggest_plan_prompt': (
        '\n\n'
        '<task_complexity_detection>\n'
        'Before responding, assess task complexity. Suggest Plan mode if ANY of the following apply:\n\n'
        '**Trigger conditions** (any one is sufficient):\n'
        '- Creating 5+ nodes\n'
        '- Multi-phase workflows (e.g., "build a terrain system", "set up FLIP simulation", "create full material network")\n'
        '- Complex node connection topology (branches, merges, feedback loops)\n'
        '- Simulation/solver/render multi-step processes\n'
        '- Large-scale modifications to existing network (changing 5+ nodes)\n'
        '- User language implies planning ("help me plan", "I need a proposal", "design a…", "build a complete…")\n\n'
        '**Suggestion format**:\n'
        '"💡 This task involves [specific reason, e.g.: building a full workflow with terrain, scatter, and materials, '
        'estimated N+ steps]. I suggest switching to **Plan mode** to create an execution plan first. '
        'This lets you preview and modify the full approach before execution. '
        'You can switch in the mode selector at the bottom-left of the input box."\n\n'
        '**Note**: If the user insists on Agent mode, respect their choice and do your best.\n'
        '</task_complexity_detection>'
    ),

    # ===== History rendering =====
    'history.compressed': '[Older tools] Trimmed {} older execution rounds.',
    'history.summary_title': 'Conversation summary',

    # ===== User Rules =====
    'rules.menu_label': 'Rules',
    'rules.title': 'User Rules',
    'rules.add': 'New Rule',
    'rules.delete': 'Delete',
    'rules.delete_confirm': 'Are you sure you want to delete rule "{}"?',
    'rules.enable': 'Enable',
    'rules.disable': 'Disable',
    'rules.from_file': 'From file',
    'rules.open_folder': 'Open Rules Folder',
    'rules.untitled': 'Untitled Rule',
    'rules.placeholder_title': 'Rule title',
    'rules.placeholder_content': 'Enter rule content here...\n\nExamples:\n- Always reply in Chinese\n- Use underscore naming for nodes\n- Add comments in VEX code',
    'rules.empty_hint': 'No rules yet\n\nCreate UI rules here,\nor place .md / .txt files in rules/ directory',
    'rules.file_readonly': '(file rule, read-only)',
    'rules.saved': 'Rules saved',
    'rules.count': '{} rule(s) active',

    # ===== Memory Manager =====
    'memory_mgr.title': 'Memory Library',
    'memory_mgr.header_title': '🧠 Memory Library',
    'memory_mgr.chrome_title': 'Memory',
    'memory_mgr.chrome_tagline': 'Standalone Qt · Fusion · isolated from host styling',
    'memory_mgr.sheet_ok': 'OK',
    'memory_mgr.sheet_cancel': 'Cancel',
    'memory_mgr.sheet_delete': 'Delete',
    'memory_mgr.panel_list': 'Entries',
    'memory_mgr.panel_editor': 'Detail & edit',
    'memory_mgr.sec_meta': 'Metadata',
    'memory_mgr.sec_task': 'Task & outcome',
    'memory_mgr.sec_metrics': 'Metrics & tags',
    'memory_mgr.sec_actions': 'Action log',
    'memory_mgr.sec_rule': 'Rule',
    'memory_mgr.sec_classification': 'Category & level',
    'memory_mgr.sec_strategy': 'Strategy',
    'memory_mgr.sec_conditions': 'Conditions',
    'memory_mgr.tab_episodic': 'Episodic',
    'memory_mgr.tab_semantic': 'Semantic',
    'memory_mgr.tab_procedural': 'Procedural',
    'memory_mgr.refresh': 'Refresh',
    'memory_mgr.save': 'Save',
    'memory_mgr.delete': 'Delete',
    'memory_mgr.new': 'New',
    'memory_mgr.filter_placeholder': 'Filter list…',
    'memory_mgr.stats': 'Episodic {} · Semantic {} · Procedural {}',
    'memory_mgr.field_id': 'ID',
    'memory_mgr.field_time': 'Time',
    'memory_mgr.field_session': 'Session ID',
    'memory_mgr.field_task': 'Task',
    'memory_mgr.field_summary': 'Summary',
    'memory_mgr.field_success': 'Success',
    'memory_mgr.field_importance': 'Importance',
    'memory_mgr.field_reward': 'Reward',
    'memory_mgr.field_error_count': 'Errors',
    'memory_mgr.field_retry_count': 'Retries',
    'memory_mgr.field_tags': 'Tags (comma-separated)',
    'memory_mgr.field_actions_json': 'Actions (JSON)',
    'memory_mgr.field_rule': 'Rule',
    'memory_mgr.field_category': 'Category',
    'memory_mgr.field_confidence': 'Confidence',
    'memory_mgr.field_abstraction': 'Abstraction (0–5)',
    'memory_mgr.field_activation': 'Activations',
    'memory_mgr.field_sources_json': 'Source episode IDs (JSON array)',
    'memory_mgr.field_strategy': 'Strategy name',
    'memory_mgr.field_description': 'Description',
    'memory_mgr.field_priority': 'Priority',
    'memory_mgr.field_success_rate': 'Success rate',
    'memory_mgr.field_usage': 'Usage count',
    'memory_mgr.field_last_used': 'Last used',
    'memory_mgr.field_conditions_json': 'Conditions (JSON array)',
    'memory_mgr.level_hint': 'Level guide:',
    'memory_mgr.delete_confirm_episodic': 'Delete this episodic memory? This cannot be undone.',
    'memory_mgr.delete_confirm_semantic': 'Delete this semantic memory? This cannot be undone.',
    'memory_mgr.delete_confirm_procedural': 'Delete this procedural memory? This cannot be undone.',
    'memory_mgr.save_ok': 'Saved.',
    'memory_mgr.err_invalid_json': 'Invalid JSON:',
    'memory_mgr.err_empty_rule': 'Rule text cannot be empty.',
    'memory_mgr.err_empty_strategy': 'Strategy name cannot be empty.',
    'memory_mgr.err_load': 'Could not open the memory manager.',

    # ===== Memory Toggle (global switch) =====
    'memory.menu_label': 'Long-Term Memory',
    'memory.menu_tooltip': 'When enabled, the assistant accumulates experience and injects past preferences into each chat. When off, every conversation starts fresh. Off by default.',
    'memory.toggle.enabled': 'Long-term memory enabled',
    'memory.toggle.disabled': 'Long-term memory disabled (no past experience will be injected going forward)',

    # ===== Plugin System =====
    'plugin.menu_label': 'Plugins',
    'plugin.manager_title': 'Plugin Manager',
    'plugin.open_folder': 'Open Plugins Folder',
    'plugin.reload_all': 'Reload All',
    'plugin.reload': 'Reload',
    'plugin.settings': 'Settings',
    'plugin.toggle_tip': 'Enable/Disable this plugin',
    'plugin.no_plugins': 'No plugins found\nPlace .py files in plugins/ directory',
    'plugin.load_error': 'Failed to load list',
    'plugin.cancel': 'Cancel',
    'plugin.save': 'Save',
    'plugin.tab_plugins': 'Plugins',
    'plugin.tab_tools': 'Tools',
    'plugin.tab_skills': 'Skills',
    'plugin.no_tools': 'No tools registered',
    'plugin.no_skills': 'No skills loaded',
    'plugin.tool_toggle_tip': 'Enable/Disable this tool',
    'plugin.skill_dir_label': 'User Skill Dir',
    'plugin.skill_dir_placeholder': '(Not set, using built-in skills only)',
    'plugin.skill_dir_browse': 'Browse',
    'plugin.stats_active': 'active',
    'plugin.empty_title': 'No Plugins',
    'plugin.empty_hint': 'Place .py plugin files in the plugins/ directory',
    'plugin.search_tools': 'Search tools...',
    'plugin.group_core': 'Core Tools',
    'plugin.group_skill': 'Built-in Skills',
    'plugin.group_plugin': 'Plugin Tools',
    'plugin.group_user': 'User Tools',
    'plugin.group_user_skill': 'User Skills',
}
