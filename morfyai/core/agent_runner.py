# -*- coding: utf-8 -*-
"""
Agent Runner — agent-loop helpers: title generation, confirm mode, tool dispatch constants.

Extracted from ai_tab.py as a Mixin. Responsibilities:
- Auto AI title generation
- Confirm-mode interception
- Tool classification constants (Ask-mode whitelist, background-safe tools, silent tools)
"""

import threading
import queue
from morfyai.qt_compat import QtWidgets, QtCore
from ..ui.i18n import tr
from ..ui.cursor_widgets import VEXPreviewInline

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None


class AgentRunnerMixin:
    """Agent-loop helpers and tool dispatch constants."""

    # Tools that require user confirmation (in Confirm mode)
    _CONFIRM_TOOLS = frozenset({
        # Create
        'create_wrangle_node',
        'create_node',
        'create_nodes_batch',
        # Delete / modify
        'delete_node',
        'set_node_parameter',
        'batch_set_parameters',
        'connect_nodes',
        'copy_node',
        'set_display_flag',
        # Code execution
        'execute_python',
        'execute_shell',
        # Save
        'save_hip',
        # NetworkBox (modifies the scene)
        'create_network_box',
        'add_nodes_to_box',
        # Node layout (moves node positions)
        'layout_nodes',
    })

    # Tools that don't need the Houdini main thread (pure Python / system ops; safe on background threads)
    _BG_SAFE_TOOLS = frozenset({
        'execute_shell',       # subprocess.run, no hou dependency
        'search_local_doc',    # pure-Python text search
        'list_skills',         # pure-Python list
        'search_memory',       # pure-Python memory-store search
    })

    # Silent tools: not surfaced in the execution-list UI (AI invokes them internally)
    _SILENT_TOOLS = frozenset({
        'add_todo',
        'update_todo',
    })

    # ★ Plan-mode planning-phase whitelist: read-only tools + create_plan
    _PLAN_PLANNING_TOOLS = frozenset({
        # Query & inspect (reused from Ask mode)
        'get_network_structure',
        'get_node_parameters',
        'list_children',
        'read_selection',
        'search_node_types',
        'semantic_search_nodes',
        'find_nodes_by_param',
        'get_node_inputs',
        'check_errors',
        'verify_and_summarize',
        # Documentation & search
        'web_search',
        'fetch_webpage',
        'search_local_doc',
        'get_houdini_node_doc',
        # Skills
        'list_skills',
        # Task management
        'add_todo',
        'update_todo',
        # Read-only queries
        'get_node_positions',
        'list_network_boxes',
        'perf_start_profile',
        'perf_stop_and_report',
        # Memory search (read-only)
        'search_memory',
        # Viewport capture (read-only)
        'capture_viewport',
        # ★ Plan-specific
        'create_plan',
        'ask_question',
    })

    # ★ Plan-mode execution-phase extra tools
    _PLAN_EXECUTION_EXTRA_TOOLS = frozenset({
        'update_plan_step',
    })

    # ★ Plan-mode silent tools (not surfaced in the execution-list UI)
    _PLAN_SILENT_TOOLS = frozenset({
        'create_plan',
        'update_plan_step',
        'ask_question',
    })

    # ★ Ask-mode whitelist: read-only / query / analysis tools (no scene-modifying ops)
    _ASK_MODE_TOOLS = frozenset({
        # Query & inspect
        'get_network_structure',
        'get_node_parameters',
        'list_children',
        'read_selection',
        'search_node_types',
        'semantic_search_nodes',
        'find_nodes_by_param',
        'get_node_inputs',
        'check_errors',
        'verify_and_summarize',
        # Documentation & search
        'web_search',
        'fetch_webpage',
        'search_local_doc',
        'get_houdini_node_doc',
        # Skills (read-only inspection)
        'list_skills',
        # Task management
        'add_todo',
        'update_todo',
        # Node layout (read-only queries)
        'get_node_positions',
        # NetworkBox (read-only inspection)
        'list_network_boxes',
        # PerfMon profiling (read-only)
        'perf_start_profile',
        'perf_stop_and_report',
        # Memory search (read-only)
        'search_memory',
        # Viewport capture (read-only)
        'capture_viewport',
    })

    # ---------- Auto AI title generation ----------

    def _maybe_generate_title(self, session_id: str, history: list):
        """Asynchronously generate a session title once the agent finishes (first run only)."""
        if not session_id:
            return
        # Check whether this session already has an AI-generated title
        sdata = self._sessions.get(session_id)
        if not sdata:
            return
        if sdata.get('_ai_title_generated'):
            return

        # Only generate when there's enough context (at least one user + one assistant)
        user_msgs = [m for m in history if m.get('role') == 'user']
        if not user_msgs:
            return

        # Use the first user message and first assistant reply as title-generation input
        first_user = ''
        first_assistant = ''
        for m in history:
            if m.get('role') == 'user' and not first_user:
                c = m.get('content', '')
                first_user = c if isinstance(c, str) else str(c)
            elif m.get('role') == 'assistant' and not first_assistant:
                c = m.get('content', '')
                first_assistant = c if isinstance(c, str) else str(c)
            if first_user and first_assistant:
                break

        sdata['_ai_title_generated'] = True  # marker to prevent duplicate generation

        # Generate the title asynchronously on a background thread
        def _gen():
            try:
                title = self._generate_short_title(first_user, first_assistant)
                if title:
                    self._autoTitleDone.emit(session_id, title)
            except Exception:
                pass

        t = threading.Thread(target=_gen, daemon=True)
        t.start()

    def _generate_short_title(self, user_msg: str, assistant_msg: str) -> str:
        """Call the LLM to generate a conversation title (≤10 characters)."""
        # Use the first 200 characters as context
        ctx = tr('title_gen.ctx', user_msg[:200], assistant_msg[:200])
        messages = [
            {'role': 'system', 'content': tr('title_gen.system_en')},
            {'role': 'user', 'content': ctx}
        ]
        try:
            result = ''
            for chunk in self.client.chat_stream(messages):
                delta = chunk.get('content', '')
                if delta:
                    result += delta
            title = result.strip().strip('"\'""''。，.').strip()
            if title and len(title) <= 20:
                return title
            return title[:10] if title else ''
        except Exception:
            return ''

    @QtCore.Slot(str, str)
    def _on_auto_title_done(self, session_id: str, title: str):
        """AI title generation finished — update the tab label."""
        if not title:
            return
        for i in range(self.session_tabs.count()):
            if self.session_tabs.tabData(i) == session_id:
                self.session_tabs.setTabText(i, title)
                break

    # ---------- Confirm mode — inline preview confirmation ----------

    @QtCore.Slot()
    def _on_confirm_tool_request(self):
        """Main thread: insert an inline preview card into the chat flow; the user's
        confirm/cancel decision is written to _confirm_result_queue.

        Args are passed via self._pending_confirm_* attributes (works around
        PySide6 QueuedConnection dict-serialization issues).
        """
        q = getattr(self, '_confirm_result_queue', None)
        tool_name = getattr(self, '_pending_confirm_tool', 'unknown')
        args = getattr(self, '_pending_confirm_args', {})

        if not q:
            _dbg(f"[ConfirmMode] ⚠ _confirm_result_queue missing")
            return

        # Make sure args is a dict
        if not isinstance(args, dict):
            args = {"raw": str(args)}

        try:
            preview = VEXPreviewInline(tool_name, args, parent=self)
        except Exception as e:
            _dbg(f"[ConfirmMode] ✖ VEXPreviewInline creation failed: {e}")
            q.put(False)
            return

        def _accept():
            q.put(True)

        def _reject():
            q.put(False)

        preview.confirmed.connect(_accept)
        preview.cancelled.connect(_reject)

        # Insert into the chat flow
        resp = getattr(self, '_agent_response', None) or getattr(self, '_current_response', None)
        inserted = False
        if resp and hasattr(resp, 'details_layout'):
            try:
                resp.details_layout.addWidget(preview)
                inserted = True
            except Exception as e:
                _dbg(f"[ConfirmMode] ⚠ details_layout insert failed: {e}")

        if not inserted:
            try:
                self.chat_layout.insertWidget(self.chat_layout.count() - 1, preview)
                inserted = True
            except Exception as e:
                _dbg(f"[ConfirmMode] ⚠ chat_layout insert failed: {e}")

        if not inserted:
            # Final fallback: render as a standalone dialog
            _dbg("[ConfirmMode] ⚠ All layout inserts failed, using standalone dialog")
            preview.setParent(None)
            preview.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.WindowStaysOnTopHint)
            preview.resize(400, 120)
            preview.show()

        preview.setVisible(True)
        try:
            self._scroll_to_bottom(force=True)
        except Exception:
            pass

    def _request_tool_confirmation(self, tool_name: str, kwargs: dict) -> bool:
        """In Confirm mode, insert an inline preview into the chat for the user to confirm or cancel.

        Called from a background thread; the preview widget is created on the
        main thread via a QueuedConnection signal. The background thread blocks
        on the queue waiting for the user's decision.
        ★ Args are passed via attributes; the signal carries no payload
        (works around PySide6 dict-serialization issues).
        """
        self._confirm_result_queue = queue.Queue()
        self._pending_confirm_tool = tool_name
        self._pending_confirm_args = dict(kwargs) if kwargs else {}
        self._confirmToolRequest.emit()
        try:
            return self._confirm_result_queue.get(timeout=120.0)
        except queue.Empty:
            return False
