# -*- coding: utf-8 -*-
"""
MorfyAI - AI Tab
Agent loop, multi-turn tool calling, streaming UI

Module split structure (migrated step by step):
  ui/header.py          — HeaderMixin: toppartsetbarbuild
  ui/input_area.py      — InputAreaMixin: inputareaandmodeswitch
  ui/chat_view.py       — ChatViewMixin: conversationshowandscrolllogic
  core/agent_runner.py  — AgentRunnerMixin: Agent loopandtooladjustdegree
  core/session_manager.py — SessionManagerMixin: multisessionmanageandcache
"""

import json
import math
import os
import threading
import time
import uuid
import queue
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from morfyai.qt_compat import QtWidgets, QtCore, QtGui, QSettings, invoke_on_main

from .i18n import tr, get_language
from ..utils import debug_log
_dbg = debug_log.log  # route diagnostic prints to in-app Debug Console
from ..utils.ai_client import AIClient, HOUDINI_TOOLS
from ..utils.mcp import HoudiniMCP
from ..utils.token_optimizer import TokenOptimizer, TokenBudget, CompressionStrategy
from ..utils.ultra_optimizer import UltraOptimizer
from .theme_engine import ThemeEngine
from .font_settings_dialog import FontSettingsDialog
from .cursor_widgets import (
    CursorTheme,
    UserMessage,
    AIResponse,
    PlanBlock,
    PlanViewer,
    StreamingPlanCard,
    AskQuestionCard,
    CollapsibleContent,
    StatusLine,
    ChatInput,
    SendButton,
    StopButton,
    TodoList,
    NodeOperationLabel,
    NodeContextBar,
    PythonShellWidget,
    SystemShellWidget,
    ClickableImageLabel,
    ToolStatusBar,
    NodeCompleterPopup,
    StreamingCodePreview,
    UpdateNotificationBanner,
)
import re

# Mixin module (from ai_tab.py splitout submodule) 
from .header import HeaderMixin
from .input_area import InputAreaMixin
from .chat_view import ChatViewMixin
from ..core.agent_runner import AgentRunnerMixin
from ..core.session_manager import SessionManagerMixin

# ★ Brain-inspired long-term memory system
from ..utils.memory_store import get_memory_store
from ..utils.reward_engine import get_reward_engine
from ..utils.reflection import get_reflection_module
from ..utils.growth_tracker import get_growth_tracker, TaskMetric

# ★ Plan mode
from ..utils.plan_manager import get_plan_manager, PLAN_TOOL_CREATE, PLAN_TOOL_UPDATE_STEP, PLAN_TOOL_ASK_QUESTION


class AITab(
    HeaderMixin,
    InputAreaMixin,
    ChatViewMixin,
    AgentRunnerMixin,
    SessionManagerMixin,
    QtWidgets.QWidget,
):
    """AI assistant — minimal sidebar style (Mixin architecture)."""
    
    # signal (used forthreadsafe  UI update) 
    _appendContent = QtCore.Signal(str)
    _addStatus = QtCore.Signal(str)
    _updateThinkingTime = QtCore.Signal()
    _agentDone = QtCore.Signal(dict)
    _agentError = QtCore.Signal(str)
    _agentStopped = QtCore.Signal()
    _updateTodo = QtCore.Signal(str, str, str)  # (todo_id, text, status)
    _addNodeOperation = QtCore.Signal(str, object)  # (name, result_dict) ★ Pass dict directly to avoid JSON serialize/deserialize overhead
    _addPythonShell = QtCore.Signal(str, str)  # (code, result_json)
    _addSystemShell = QtCore.Signal(str, str)  # (command, result_json)
    _executeToolRequest = QtCore.Signal(str, dict)  # toolexecuterequestsignal (thread-safe)
    _executeToolBatchRequest = QtCore.Signal(list)   # batchtoolexecuterequest: [(tool_name, kwargs), ...]
    _addThinking = QtCore.Signal(str)  # thinkingcontentupdatesignal (thread-safe)
    _finalizeThinkingSignal = QtCore.Signal()  # endthinkingsectionblock (thread-safe)
    _resumeThinkingSignal = QtCore.Signal()    # restorethinkingsectionblock (thread-safe)
    _showToolStatus = QtCore.Signal(str)       # showtoolexecutestate (thread-safe)
    _hideToolStatus = QtCore.Signal()          # hidetoolexecutestate
    _showGenerating = QtCore.Signal()          # show "Generating..." state (thread-safe)
    _autoTitleDone = QtCore.Signal(str, str)   # autotitlegeneratecomplete: (session_id, title)
    _confirmToolRequest = QtCore.Signal()  # confirmmode: requestconfirm (parameterviaattributepassdeliver, avoid QueuedConnection dict issue) 
    _confirmToolResult = QtCore.Signal(bool)        # confirmmode: result (True=execute, False=cancel)
    _toolArgsDelta = QtCore.Signal(str, str, str)   # streaming VEX preview: (tool_name, delta, accumulated)
    _showPlanning = QtCore.Signal(str)              # show "Planning..." progress (progress_text)
    _createStreamingPlan = QtCore.Signal()           # createstreaming Plan previewcard
    _updateStreamingPlan = QtCore.Signal(str)        # updatestreaming Plan previewcardcontent (accumulated_json)
    _renderPlanViewer = QtCore.Signal(dict)          # Plan mode: inmainthreadrender PlanViewer card
    _updatePlanStep = QtCore.Signal(str, str, str)   # Plan mode: updatestepstate (step_id, status, result_summary)
    _askQuestionRequest = QtCore.Signal()             # Plan mode: ask_question request (parameterviaattributepassdeliver) 
    
    def __init__(self, parent=None, workspace_dir: Optional[Path] = None):
        super().__init__(parent)
        
        self.client = AIClient()
        self.mcp = HoudiniMCP()
        self.mcp.set_stop_event(self.client._stop_event)  # sharedstopevent, make shell/python commandcommandcanisinbreak
        self.client.set_tool_executor(self._execute_tool_with_todo)
        self.client.set_batch_tool_executor(self._execute_tools_batch_in_main_thread)
        
        # state
        self._conversation_history: List[Dict[str, Any]] = []
        self._pending_ops: list = []  # tracenotdecideoperation: [(label, op_type, paths, snapshot), ...]
        self._current_response: Optional[AIResponse] = None
        self._is_running = False
        self._thinking_timer: Optional[QtCore.QTimer] = None
        
        # Agent runanchorpoint: recordsendstartrequest  session, guaranteecallbackwritecorrect session
        self._agent_session_id: Optional[str] = None
        self._agent_response: Optional[AIResponse] = None
        self._agent_scroll_area = None  # runin session   scroll_area
        self._agent_history: Optional[List[Dict[str, Any]]] = None
        self._agent_token_stats: Optional[Dict] = None
        self._agent_todo_list = None       # runin session   TodoList
        self._agent_chat_layout = None     # runin session   chat_layout
        
        # contextmanage
        self._max_context_messages = 20
        self._context_summary = ""
        
        # cachemanage
        self._session_id = str(uuid.uuid4())[:8]  # currentsession ID
        self._cache_dir = Path(__file__).parent.parent.parent / "cache" / "conversations"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._auto_save_cache = True  # autosavecache
        self._workspace_dir = workspace_dir  # worksectiondirectory
        
        # multisessionmanage
        self._sessions: Dict[str, dict] = {}   # session_id -> session state
        self._session_counter = 0               # used forgenerate tab label
        # ★ pure Python backup: tab orderorderandlabelname (atexit when Qt widget mayalreadydestroy) 
        self._tabs_backup: list = []  # [(session_id, tab_label), ...]
        self._sessions_saved = False  # _save_all_sessions whetheralreadysucceededexecutepassed
        
        # Static content cache (computed once, saves tokens and compute time)
        self._cached_optimized_system_prompt: Optional[str] = None
        self._cached_optimized_tools: Optional[List[dict]] = None
        self._cached_optimized_tools_no_web: Optional[List[dict]] = None
        
        # Token optimizationization 
        self.token_optimizer = TokenOptimizer()
        self._auto_optimize = True  # autooptimizationization
        self._optimization_strategy = CompressionStrategy.BALANCED
        
        # ★ Plan modestate
        self._plan_phase = 'idle'          # idle | planning | awaiting_confirmation | executing | completed
        self._active_plan_viewer = None    # currentactive  PlanViewer componentreference
        self._streaming_plan_card = None   # streaming Plan previewcard (generateintemporarywhenuse) 
        self._plan_manager = None          # PlanManager instance (latencyinitialization) 
        
        # ★ Brain-inspired long-term memory system (lazy init to avoid blocking the UI)
        self._memory_store = None
        self._reward_engine = None
        self._reflection_module = None
        self._growth_tracker = None
        self._memory_initialized = False
        # Global toggle: off by default; avoids long-term memory locking the agent into one workflow.
        # User can explicitly enable from the Header overflow menu (···); state is persisted to QSettings.
        self._memory_enabled = self._load_memory_enabled_pref()

        # ★ sleepmechanismcountcount 
        self._sleep_msg_counter = 0       # Cumulative user-message count for the current session
        self._sleep_in_progress = False   # preventandsendsleep

        self._init_memory_system()
        
        # thinkinglengthlimit (disabled, allowcompletethinking) 
        self._max_thinking_length = float('inf')  # notlimitthinkinglength
        self._thinking_length_warning = float('inf')  # notwarning
        
        # output Token limit (notlimit) 
        self._max_output_tokens = float('inf')
        self._output_token_warning = float('inf')
        self._current_output_tokens = 0
        
        # <think> labelstreamingparsestate
        self._in_think_block = False
        self._tag_parse_buf = ""
        self._thinking_needs_finalize = False  # markwhetherneeds finalize thinkingsectionblock
        self._think_enabled = True  # currentsessionwhetherenablethinkingshow (by Think togglecontrol) 
        
        # sessionlevelnode pathmapping: name → set[path], used forafterprocessbarenodename → completepath
        self._session_node_map: dict[str, set[str]] = {}
        
        # Token-usage stats (cumulative; aggregated each turn) — aligned with Cursor
        self._token_stats = {
            'input_tokens': 0,      # input token total
            'output_tokens': 0,     # output token total
            'reasoning_tokens': 0,  # inference token (output subset) 
            'cache_read': 0,        # Cache read (commandin) token
            'cache_write': 0,       # Cache write (notcommandin) token
            'total_tokens': 0,      # total token count
            'requests': 0,          # requesttimecount
            'estimated_cost': 0.0,  # pre-estimatecostuse (USD) 
        }
        self._call_records: list = []  # each time API call detailfinerecord (align Cursor) 
        
        # toolexecutethreadsafemechanism (usequeueandlockavoidcompetition) 
        self._tool_result_queue: queue.Queue = queue.Queue()
        self._tool_lock = threading.Lock()  # ensureonceonlyhasonetoolcall
        self._main_thread_busy = False  # ★ mainthreadbusymark (preventtimeoutafterpile upsignaldeadlock) 
        
        # connectsignal
        self._appendContent.connect(self._on_append_content)
        self._addStatus.connect(self._on_add_status)
        self._updateThinkingTime.connect(self._on_update_thinking)
        self._agentDone.connect(self._on_agent_done)
        self._agentError.connect(self._on_agent_error)
        self._agentStopped.connect(self._on_agent_stopped)
        self._updateTodo.connect(self._on_update_todo)
        self._addNodeOperation.connect(self._on_add_node_operation)
        self._addPythonShell.connect(self._on_add_python_shell)
        self._addSystemShell.connect(self._on_add_system_shell)
        self._executeToolRequest.connect(self._on_execute_tool_main_thread, QtCore.Qt.BlockingQueuedConnection)
        self._executeToolBatchRequest.connect(self._on_execute_tool_batch_main_thread, QtCore.Qt.BlockingQueuedConnection)
        self._addThinking.connect(self._on_add_thinking)
        self._finalizeThinkingSignal.connect(self._finalize_thinking_main_thread)
        self._resumeThinkingSignal.connect(self._resume_thinking_main_thread)
        self._showToolStatus.connect(self._on_show_tool_status)
        self._hideToolStatus.connect(self._on_hide_tool_status)
        self._showGenerating.connect(self._on_show_generating)
        self._autoTitleDone.connect(self._on_auto_title_done)
        self._confirmToolRequest.connect(self._on_confirm_tool_request, QtCore.Qt.QueuedConnection)
        self._toolArgsDelta.connect(self._on_tool_args_delta)
        self._showPlanning.connect(self._on_show_planning)
        self._createStreamingPlan.connect(self._on_create_streaming_plan, QtCore.Qt.QueuedConnection)
        self._updateStreamingPlan.connect(self._on_update_streaming_plan)
        self._renderPlanViewer.connect(self._on_render_plan_viewer, QtCore.Qt.QueuedConnection)
        self._updatePlanStep.connect(self._on_update_plan_step, QtCore.Qt.QueuedConnection)
        self._askQuestionRequest.connect(self._on_render_ask_question, QtCore.Qt.QueuedConnection)
        
        # ── streaming VEX previewstate ──
        self._streaming_preview = None          # current  StreamingCodePreview widget
        self._streaming_preview_tool = ""       # positiveinstreamingpreview toolname
        self._streaming_last_code = ""          # ontimeparseout completecode (used forincremental diff) 
        
        # buildandcachesystemhintword (twoversion: hasthinking / nothinking) 
        self._system_prompt_think = self._build_system_prompt(with_thinking=True)
        self._system_prompt_no_think = self._build_system_prompt(with_thinking=False)
        self._cached_prompt_think = self.token_optimizer.optimize_system_prompt(
            self._system_prompt_think, max_length=1800
        )
        self._cached_prompt_no_think = self.token_optimizer.optimize_system_prompt(
            self._system_prompt_no_think, max_length=1500
        )
        # compatible witholdreference
        self._system_prompt = self._system_prompt_think
        self._cached_optimized_system_prompt = self._cached_prompt_think
        self._build_ui()
        self._wire_events()
        self._load_model_preference(restore_provider=True)  # restoreontimeuse raiseforvendorandmodel
        self._update_key_status()
        self._update_context_stats()
        
        # ★ startwhenautorestoreontime session (from sessions_manifest.json) 
        self._restore_all_sessions()
        
        self._destroyed = False

        # Periodic auto-save (every 60s); prevents losing the session on Houdini exit
        self._auto_save_timer = QtCore.QTimer(self)
        self._auto_save_timer.timeout.connect(self._periodic_save_all)
        self._auto_save_timer.start(60_000)  # 60 second
        
        # register atexit callbackand QApplication.aboutToQuit signal
        import atexit
        atexit.register(self._atexit_save)
        app = QtWidgets.QApplication.instance()
        if app:
            app.aboutToQuit.connect(self._save_all_sessions)
        self.destroyed.connect(self._on_destroyed)
        
        # ★ startwhensilentcheckupdate (latency 5 second, notblockinitialization) 
        QtCore.QTimer.singleShot(5000, self._silent_update_check)
        
        # ★ pluginsysteminitialization (latency 3 second, notblock UI) 
        QtCore.QTimer.singleShot(3000, self._init_plugin_system)
        
        # ★ Rebuild system prompt + re-translate UI when the language switches
        from .i18n import language_changed
        language_changed.changed.connect(self._rebuild_system_prompts)
        language_changed.changed.connect(self._retranslateUi)

    def _rebuild_system_prompts(self, _lang: str = ''):
        """languageswitchafterrebuildsystemhintword (containing Ask/Agent modeforcelanguagerule) """
        self._system_prompt_think = self._build_system_prompt(with_thinking=True)
        self._system_prompt_no_think = self._build_system_prompt(with_thinking=False)
        self._cached_prompt_think = self.token_optimizer.optimize_system_prompt(
            self._system_prompt_think, max_length=1800
        )
        self._cached_prompt_no_think = self.token_optimizer.optimize_system_prompt(
            self._system_prompt_no_think, max_length=1800
        )
        self._system_prompt = self._system_prompt_think
        self._cached_optimized_system_prompt = self._cached_prompt_think
        _dbg(f"[i18n] System prompts rebuilt for language: {_lang or get_language()}")

    def _retranslateUi(self, _lang: str = ''):
        """Re-translate all static UI text after a language switch."""
        # Header area
        self._retranslate_header()
        # inputarea
        self._retranslate_input_area()
        # sessionlabelbar
        self._retranslate_session_tabs()
        _dbg(f"[i18n] UI retranslated for language: {_lang or get_language()}")

    # ==========================================================
    # ★ Brain-inspired long-term memory system
    # ==========================================================

    def _init_memory_system(self):
        """initializationlong-termmemorysystem (backgroundthread, notblock UI) 

        Note: initialization always proceeds (low cost; user can toggle anytime).
        butrealboundary inject/reflection/sleeponlyin self._memory_enabled as True whentrigger. 
        """
        def _init():
            try:
                self._memory_store = get_memory_store()
                self._reward_engine = get_reward_engine()
                self._reflection_module = get_reflection_module()
                self._growth_tracker = get_growth_tracker()
                self._memory_initialized = True
                _dbg(f"[Memory] Long-term memory system initialized (enabled={self._memory_enabled}): "
                      f"{self._memory_store.get_stats()}")
            except Exception as e:
                _dbg(f"[Memory] Init failed (non-fatal): {e}")
                self._memory_initialized = False

        thread = threading.Thread(target=_init, daemon=True)
        thread.start()

    # ---------- globaltoggle: memorysystemenable/disable ----------

    @staticmethod
    def _load_memory_enabled_pref() -> bool:
        """from QSettings loadmemorytoggle (default False) . """
        settings = QSettings("MorfyAI", "Settings")
        val = settings.value("memory_enabled", False)
        if isinstance(val, str):
            return val.lower() == 'true'
        return bool(val)

    def _save_memory_enabled_pref(self, enabled: bool):
        settings = QSettings("MorfyAI", "Settings")
        settings.setValue("memory_enabled", bool(enabled))

    def _is_memory_active(self) -> bool:
        """Short-circuit condition for memory-related hooks/stats.

        When True: inject L0 core memory, activate tiered search, reflection, sleep, and
        expose the search_memory tool. When False: fully disabled.
        """
        return bool(self._memory_enabled and self._memory_initialized and self._memory_store)

    def set_memory_enabled(self, enabled: bool):
        """switchmemorysystemglobaltoggleandpersistentization. """
        enabled = bool(enabled)
        if enabled == self._memory_enabled:
            return
        self._memory_enabled = enabled
        self._save_memory_enabled_pref(enabled)
        # statebarhint
        key = 'memory.toggle.enabled' if enabled else 'memory.toggle.disabled'
        try:
            self._addStatus.emit(tr(key))
        except Exception:
            pass

    # ==========================================================
    # ★ pluginsystem (Hook / Plugin System)
    # ==========================================================

    def _init_plugin_system(self):
        """initializationpluginsystem: loadplugin, set UI Bridge, hangloadbutton"""
        try:
            from ..utils.hooks import get_hook_manager, PluginUIBridge, load_all_plugins

            manager = get_hook_manager()

            # Create the UI Bridge and wire it into HookManager
            bridge = PluginUIBridge()
            # setbuttoncontain reference
            if hasattr(self, '_plugin_button_container'):
                bridge.set_button_container(self._plugin_button_container)
            # setchatarealayout (for insert_chat_card use) 
            if hasattr(self, 'chat_layout') and self.chat_layout:
                bridge.set_chat_layout(self.chat_layout)
            bridge.set_ai_tab(self)
            manager.set_ui_bridge(bridge)

            # loadallplugin
            load_all_plugins()

            # hangloadpluginbutton
            bridge.mount_buttons()

            _dbg("[Hook] Plugin system initialized")
        except Exception as e:
            _dbg(f"[Hook] Plugin system init failed (non-fatal): {e}")

    def _fire_session_hook(self, event: str, session_id: str):
        """triggersessionrelated  Hook event"""
        try:
            from ..utils.hooks import get_hook_manager
            get_hook_manager().fire(event, session_id=session_id)
        except Exception:
            pass

    def _activate_long_term_memory(self, user_message: str, scene_context: dict = None) -> str:
        """movestatememoryactivate — partlayer chunk search

        6 layerabstraction levelbodysystem: 
        - L0 (coreidentity): alreadyin sys_prompt inload, hereskip
        - L1 (corepreference): embedding search, top_k=3, threshold=0.15
        - L2 (experiencerule): embedding search, top_k=3, threshold=0.25
        - L3 (workstreammode): embedding search, top_k=2, threshold=0.35
        - L4-L5: notautoinject, onlyvia search_memory toolsearch

        Each tier independently fetches Top-K chunks without crowding the others.
        Each chunk is tagged with a confidence marker and explicitly labelled "for reference only".

        ★ Note: fallback embedding (n-gram hash) cosine similarity is roughly in 0~0.4,
        far lower than sentence-transformers (0~1.0). The threshold is scaled inside search_by_level
        autoscalebysuitmatchdifferentafterend. Episodic / Procedural   score thresholdvaluealsoneedssamelikeprocess. 
        """
        if not self._is_memory_active():
            return ""

        try:
            store = self._memory_store

            # buildquery (usermessage + scenekeyword) 
            query = user_message
            if scene_context:
                selected_types = scene_context.get('selected_types', [])
                if selected_types:
                    query += ' ' + ' '.join(selected_types)

            # ★ Under fallback mode, cosine similarity is small; scale the score threshold
            _is_semantic = store.embedder.is_semantic
            _ep_threshold = 0.3 if _is_semantic else 0.05
            _proc_threshold = 0.25 if _is_semantic else 0.04

            parts = []

            # ── L1: corepreference (top_k=3, threshold=0.15) ──
            l1_results = store.search_by_level(query, level=1, top_k=3, threshold=0.15)
            for rec, score in l1_results:
                parts.append(f"[L1 Preference] (conf={rec.confidence:.2f}) {rec.rule[:120]}")
                store.increment_semantic_activation(rec.id)

            # ── L2: experiencerule (top_k=3, threshold=0.25) ──
            l2_results = store.search_by_level(query, level=2, top_k=3, threshold=0.25)
            for rec, score in l2_results:
                parts.append(f"[L2 Rule] (conf={rec.confidence:.2f}) {rec.rule[:120]}")
                store.increment_semantic_activation(rec.id)

            # ── L3: workstreammode (top_k=2, threshold=0.35) ──
            l3_results = store.search_by_level(query, level=3, top_k=2, threshold=0.35)
            for rec, score in l3_results:
                parts.append(f"[L3 Workflow] (conf={rec.confidence:.2f}) {rec.rule[:120]}")
                store.increment_semantic_activation(rec.id)

            # ── Episodic: related past records (top_k=2) ──
            episodes = store.search_episodic(query, top_k=2, min_importance=0.3)
            for ep, score in episodes:
                if score > _ep_threshold:
                    status = "✅" if ep.success else "❌"
                    parts.append(
                        f"[Past Experience] {status} {ep.task_description[:80]} "
                        f"→ {ep.result_summary[:60]}"
                    )
                    try:
                        new_imp = min(5.0, ep.importance * 1.05)
                        store.update_episodic_importance(ep.id, new_imp)
                    except Exception:
                        pass

            # ── Procedural: suitusestrategy (top_k=2) ──
            strategies = store.search_procedural(query, top_k=2)
            for strat, score in strategies:
                if score > _proc_threshold:
                    parts.append(f"[Strategy] {strat.description[:80]}")

            if not parts:
                return ""

            header = "[Long-Term Memory — historical experience for reference only; combine with the current context before deciding]"
            result = header + "\n" + "\n".join(parts)
            return result

        except Exception as e:
            _dbg(f"[Memory] Activation failed: {e}")
            return ""

    @staticmethod
    def _collect_recent_rounds(history: list, n_rounds: int) -> list:
        """fromconversationhistoryincollectsetrecent N round (by user messageaspartboundary)  message

        Args:
            history: completeconversationhistory
            n_rounds: needcollectset roundcount

        Returns:
            Copy of the last N rounds of messages
        """
        if not history:
            return []

        # by user messageplanpartroundtime
        rounds = []
        current_round = []
        for m in history:
            if m.get('role') == 'user' and current_round:
                rounds.append(current_round)
                current_round = []
            current_round.append(m)
        if current_round:
            rounds.append(current_round)

        # fetchrecent n_rounds round
        recent = rounds[-n_rounds:] if len(rounds) >= n_rounds else rounds
        # Flatten into a message list (deep-copy to avoid mutating the original)
        import copy
        return [copy.copy(m) for rnd in recent for m in rnd]

    def _reflect_after_task(self, result: dict, agent_params: dict):
        """taskcompleteafter reflectionhook — inbackgroundthreadexecute

        from agent result inextractsignal, create episodic memory, 
        compute reward, triggerrule/LLM reflection. 
        """
        if not self._is_memory_active() or not self._reflection_module:
            return

        try:
            # extracttaskinfo
            tool_calls_history = result.get('tool_calls_history', [])
            final_content = result.get('final_content', '') or result.get('content', '')
            new_messages = result.get('new_messages', [])

            # buildtoolcallordercolumn
            tool_calls = []
            error_count = 0
            retry_count = 0
            for tc in tool_calls_history:
                tc_result = tc.get('result', {})
                success = bool(tc_result.get('success', True))
                has_error = bool(tc_result.get('error', ''))
                tool_calls.append({
                    "name": tc.get('tool_name', ''),
                    "success": success and not has_error,
                    "error": tc_result.get('error', ''),
                })
                if has_error or not success:
                    error_count += 1

            # detectretry (consecutivesametoolcall) 
            for i in range(1, len(tool_calls)):
                if (tool_calls[i]["name"] == tool_calls[i-1]["name"]
                        and not tool_calls[i-1]["success"]):
                    retry_count += 1

            # extractuserrequest
            history = self._agent_history if self._agent_history is not None else self._conversation_history
            task_description = ""
            for msg in reversed(history):
                if msg.get('role') == 'user':
                    content = msg.get('content', '')
                    if isinstance(content, list):
                        task_description = ' '.join(
                            p.get('text', '') for p in content if p.get('type') == 'text'
                        )
                    else:
                        task_description = content
                    task_description = task_description[:200]
                    break

            # decidebreaksucceeded / failed
            success = result.get('ok', True) and error_count < len(tool_calls) * 0.5

            # resultsummary
            result_summary = ""
            if final_content:
                # goremove think label
                import re as _re
                clean = _re.sub(r'<think>[\s\S]*?</think>', '', final_content).strip()
                result_summary = clean[:150]

            session_id = self._agent_session_id or self._session_id

            # executereflection
            reflect_result = self._reflection_module.reflect_on_task(
                session_id=session_id,
                task_description=task_description,
                result_summary=result_summary,
                success=success,
                error_count=error_count,
                retry_count=retry_count,
                tool_calls=tool_calls,
                ai_client=self.client,
                model=agent_params.get('model', 'deepseek-v4-flash'),
                provider=agent_params.get('provider', 'deepseek'),
            )

            # update Growth Tracker
            if self._growth_tracker:
                metric = TaskMetric(
                    success=success,
                    error_count=error_count,
                    retry_count=retry_count,
                    tool_call_count=len(tool_calls),
                    reward=reflect_result.get('reward', 0.0),
                    tags=reflect_result.get('tags', []),
                )
                self._growth_tracker.record_task(metric)

                # if LLM reflectionreturnskillcanplaceinfodegreeupdate
                if reflect_result.get('deep_reflected') and 'skill_confidence' in reflect_result:
                    self._growth_tracker.update_skill_confidence_batch(
                        reflect_result.get('skill_confidence', {})
                    )

            if reflect_result.get('reward', 0) > 0:
                _dbg(f"[Memory] Reflection complete: reward={reflect_result['reward']:.2f}, "
                      f"tags={reflect_result.get('tags', [])}, "
                      f"deep_reflected={reflect_result.get('deep_reflected', False)}")

        except Exception as e:
            import traceback
            _dbg(f"[Memory] Reflection hook error: {e}")
            traceback.print_exc()

    def _get_personality_injection(self) -> str:
        """getpropertyinjecttext (attachto system prompt end) """
        if not self._is_memory_active() or not self._growth_tracker:
            return ""
        try:
            return self._growth_tracker.get_personality_description()
        except Exception:
            return ""

    def _get_user_rules_injection(self) -> str:
        """getusercustomruletext (attachto system prompt end) """
        try:
            from ..utils.rules_manager import get_rules_for_prompt
            return get_rules_for_prompt()
        except Exception:
            return ""

    def _get_role_injection(self) -> str:
        """Active-role system block (HDA Architect / VEX Debugger / etc.).

        Fully defensive: any failure returns '' so base behavior is unchanged.
        """
        try:
            from ..utils.roles_manager import get_role_injection
            return get_role_injection()
        except Exception:
            return ""

    def _get_thinking_injection(self) -> str:
        """Thinking-level directive (low/high). Empty for medium or on error."""
        try:
            from ..utils.roles_manager import get_thinking_injection
            return get_thinking_injection()
        except Exception:
            return ""

    def _get_sim_policy_injection(self) -> str:
        """Steer the model to use deterministic builder skills for sims.

        Defensive: returns '' on any error so base behavior is unchanged.
        """
        try:
            from ..utils.roles_manager import get_sim_policy_injection
            return get_sim_policy_injection()
        except Exception:
            return ""

    def _get_procedural_cookbook_injection(self) -> str:
        """Inject the procedural build cookbook (introspect/build/verify protocol +
        hard-won rules) for generic build requests with no dedicated builder skill.

        Defensive: returns '' on any error so base behavior is unchanged.
        """
        try:
            from ..utils.roles_manager import get_procedural_cookbook_injection
            return get_procedural_cookbook_injection()
        except Exception:
            return ""

    def _get_visual_refine_policy_injection(self) -> str:
        """Steer the model to LOOK-then-tweak for iterative refinement requests
        ("make it more X", "lebih ...", "masih siku") instead of guessing a param.

        Defensive: returns '' on any error so base behavior is unchanged.
        """
        try:
            from ..utils.roles_manager import get_visual_refine_policy_injection
            return get_visual_refine_policy_injection()
        except Exception:
            return ""

    def _build_system_prompt(self, with_thinking: bool = True) -> str:
        """buildsystemhint
        
        Args:
            with_thinking: whetherpackagecontaining <think> labelthinkingrefercommand
        """
        # Language enforcement based on UI setting
        if get_language() == 'en':
            lang_rule = "CRITICAL: You MUST reply in English for ALL user-facing text. No exceptions. Even if the user writes in another language, your reply MUST be in English."
        else:
            lang_rule = "CRITICAL: You MUST reply in the SAME language the user uses. If the user writes in Chinese, reply in Chinese. If in English, reply in English. Match the user's language exactly."
        
        base_prompt = f"""You are **MorfyAI — Houdini Assistant**, a Houdini expert specialized in solving problems with nodes and VEX. MorfyAI is part of the MorfyFX ecosystem.

Identity Rule (highest priority — must follow on every relevant reply):
-Your name is **MorfyAI** (full title: "MorfyAI — Houdini Assistant").
-When the user asks who you are, your name, your identity, or what model/AI you are, you MUST introduce yourself as **MorfyAI — Houdini Assistant**, a co-pilot for SideFX Houdini built on top of an LLM. Translate the introduction into the user's language (e.g. Indonesian: "Saya MorfyAI — Houdini Assistant, asisten AI untuk SideFX Houdini.").
-When the user asks who **created / built / made / develops** you, who is **behind** you, or who **owns** you, give the full attribution honestly:
  * MorfyAI is maintained and developed by **gemrra**, as part of the **MorfyFX** ecosystem.
  * It is a fork and continuation of the open-source **Houdini Agent** plugin originally created by **KazamaSuichiku** (released under MIT license). The core agent engine, tool integrations, and underlying functionality come from KazamaSuichiku's work.
  * The MorfyAI rebrand (UI redesign, theme, this Houdini-Assistant identity) was developed by gemrra with iterative assistance from Claude (Anthropic).
  Translate this attribution into the user's language. Keep it concise (2-3 sentences) unless the user asks for more detail.
-Do NOT claim to be GPT, Claude, DeepSeek, Gemini, GLM, or "just an AI". The underlying model is an internal implementation detail and not part of your public identity.
-Do NOT mention your version number unless the user explicitly asks (point them to the About dialog).

{lang_rule}
Never use emoji or icon symbols in replies unless the user explicitly requests them. Use plain text only.
"""
        if with_thinking:
            base_prompt += f"""
Output Format (highest priority rule — violation = failure):
Every single reply (regardless of round number or whether tools were called) MUST begin with a <think>...</think> block. No exceptions.
Even brief confirmations or status updates must start with <think> before the main text.
Omitting the <think> tag is a format violation and is unacceptable.

Deep Thinking Framework (MUST follow inside <think> tags, no steps may be skipped):
1.[Understand] What does the user truly want? Are there implicit needs beyond the literal request? Don't stop at the surface.
2.[Status] What is the current scene state? What did the last tool return? Does the result match expectations? Any anomalies or gaps?
3.[Options] List at least 2 viable approaches and compare pros/cons. If only one exists, explain why there are no alternatives.
4.[Decision] Choose the optimal approach and explicitly state the reasoning.
5.[Plan] List concrete execution steps, tools to call, and their order.
6.[Risk] What could go wrong? How to handle it if it does?

Thinking Principles:
-Do NOT rush to act. First fully understand the existing network structure before deciding how to modify it.
-If unsure about node types, parameter names, or connections, you MUST query with tools first. Never guess.
-After each tool result, evaluate quality: Did it succeed? Is the return value reasonable? If unexpected, analyze why and adjust the plan.
-Better to query one extra time than to redo work due to wrong assumptions.
-After finding the first viable approach, pause and think whether there is a better one.

Collaboration Rules When Encountering Obstacles (critical — never abandon the plan):
-When a step cannot be completed via tools (e.g., user must manually operate the UI, provide files/paths/passwords, install plugins, configure environments, select objects in viewport), you MUST NOT abandon or skip the current plan.
-Correct behavior: Pause execution. Clearly tell the user: current progress, the specific obstacle, and exactly what the user needs to do. Then wait.
-Be specific: Give concrete step-by-step instructions (e.g., "Please install SideFX Labs in Houdini: Shelf area -> Right-click -> Shelves -> SideFX Labs"), not vague "please configure the environment".
-If a step is easier for the user via UI interaction (drag files, click buttons, select objects in viewport), prefer asking the user rather than simulating it with code.
-Before pausing, summarize what you have completed and explain what the user needs to do, so you can resume seamlessly afterward.

Content outside think tags is the formal reply shown to the user — keep it concise, direct, action-oriented. {lang_rule}

Example (deep thinking + plain text reply):
<think>
[Understand] User wants to scatter points on a ground plane and copy small spheres. Implicit need: uniform distribution, appropriate sphere size.
[Status] /obj/geo1 is currently empty, need to build from scratch.
[Options]
A: box -> scatter -> sphere + copytopoints — classic workflow, scatter directly controls count and distribution.
B: grid -> wrangle(VEX rand to manually generate points) + copytopoints — more flexible but more complex, unnecessary for this case.
[Decision] Choose A. Standard workflow, scatter parameters are controllable, no over-engineering needed.
[Plan] 1. create_node box as scatter base 2. create_node scatter connected to box 3. create_node sphere as copy template 4. create_node copytopoints connecting scatter(input1) and sphere(input0) 5. verify_and_summarize
[Risk] copytopoints input order is easy to mix up (0=template, 1=target points). Must verify connections carefully.
</think>
Created box->scatter->copytopoints pipeline, 500 points, sphere radius 0.05.

Example (follow-up reply after tool execution, MUST still have think tag):
<think>
[Status] Previous step created grid node, returned path /obj/geo1/grid1, status normal.
[Plan] Next, add a wrangle node for terrain noise displacement. Code needs @P.y += noise(@P * freq) structure, run_over = Points (operating on point attribute @P).
[Risk] Noise frequency and amplitude need reasonable values. Start with freq=2, amp=0.5 as defaults, user can adjust later.
</think>
"""
        else:
            base_prompt += """
Output format: Concise, direct, action-oriented. MUST reply in the same language the user uses.
"""

        base_prompt += """
Node Path Output Rules (MUST follow when mentioning nodes in replies):
-When mentioning any Houdini node in reply text, you MUST use the full absolute path, e.g. /obj/geo1/box1, NOT just the node name box1
-Path format must start with root category: /obj/..., /out/..., /ch/..., /shop/..., /stage/..., /mat/..., /tasks/...
-Correct: "Created node /obj/geo1/scatter1 and connected to /obj/geo1/box1"
-Wrong: "Created node scatter1 and connected to box1" (missing full path, user cannot click to navigate)
-When listing multiple nodes, each must have full path: "/obj/geo1/box1, /obj/geo1/transform1, /obj/geo1/merge1"
-Node paths are automatically converted to clickable links. Users can click to jump to the corresponding node. Path accuracy is critical.

Fake Tool Call Prevention (highest priority — violation = failure):
-You MUST NEVER write text that looks like tool execution results in your reply
-NEVER include "[ok] web_search:", "[ok] fetch_webpage:", "[Tool Result]" or similar in replies
-If you need to search for information, you MUST actually call the web_search tool via function calling
-If unsure about information, you MUST call a tool to query, never fabricate answers disguised as search results
-Your reply may only contain: think tags, natural language text, code blocks — no simulated tool call formats

Tool Call Parameter Rules (highest priority — MUST check before every tool call):
-Before calling a tool, MUST verify all required parameters are filled. Missing required params will cause failure
-Parameter values must use correct data types (string/number/boolean/array). Don't write numbers as strings, don't omit quotes around paths
-node_path parameter must be a full absolute path (e.g., "/obj/geo1/box1"), never just the node name (e.g., "box1")
-Don't guess parameter names or values from memory. First use query tools (get_node_parameters, get_node_inputs, search_node_types) to confirm
-If a tool call returns "missing parameter" or "parameter error", it means YOUR call parameters were wrong. Fix and retry, don't call check_errors
-When calling the same tool multiple times, always fill all required parameters each time. Don't assume the system remembers previous parameters

Safe Operation Rules:
-When first needing to understand a network, call get_network_structure or list_children, but do NOT re-query a network already queried in this round (system auto-caches within the same round)
-Before setting parameters, MUST call get_node_parameters to see what parameters exist, their names, current values and defaults. Never guess parameter names
-If modifying multiple parameters, first query all with get_node_parameters, then set them one by one with set_node_parameter
-In execute_python, always check for None: node=hou.node(path); if node: ...
-After creating a node, use the returned path. Never guess paths
-Before connecting nodes, confirm both endpoints exist
-No duplicate queries: A network_path only needs one query per round. Results remain valid within the round. If you've already inspected a network's structure, reuse the previous result

Node Creation Failure Recovery (MUST follow strictly):
-If create_node returns an error (e.g., "unrecognized node type"), do NOT retry blindly or give up
-MUST immediately call search_node_types to find the correct node type name
-If search results are unclear, continue with search_local_doc or get_houdini_node_doc for detailed documentation
-Recreate the node using the correct type name found
-If multiple searches still fail, use execute_python to query directly: hou.nodeType(hou.sopNodeTypeCategory(), 'xxx')

Understanding Existing Networks:
-When get_network_structure returns results with [Contains VEX Code] or [Contains Python Code] annotations, you MUST carefully read the embedded code
-Reading wrangle node VEX code reveals the node's specific logic (attribute calculations, conditional filtering, etc.) — this is key to understanding existing network implementations
-To modify an existing wrangle node's code, first use get_node_parameters to read the full snippet parameter, then use set_node_parameter to set new code

Wrangle Node Run Over Mode (critical — MUST consider every time a wrangle is created):
-When creating a wrangle node, you MUST select the correct run_over mode based on what the VEX code actually operates on. Never always use the default Points
-run_over determines VEX execution context: Points (per-point), Primitives (per-primitive), Vertices (per-vertex), Detail (once globally)
-Wrong run_over will cause VEX code to completely malfunction or produce incorrect results
-Selection rules:
  If code operates on @P, @N, @pscale, @Cd etc. point attributes, or uses @ptnum, @numpt -> use Points
  If code operates on @primnum, @numprim, prim() functions, or processes per-primitive -> use Primitives
  If code only needs to run once for global attributes (e.g., @Frame, detail()), or uses addpoint/addprim to manually create geometry -> use Detail
  If code operates on vertex attributes (e.g., UV) or uses @vtxnum -> use Vertices
-Common mistake: Using Points mode with addpoint()/addprim() causes creation to run per input point, producing massive duplicate geometry. Such code MUST use Detail mode
-When unsure which mode to use, prioritize judging by the attributes and functions accessed in VEX code
-Wrangle class parameter value mapping: 0=Detail (only once), 1=Primitives, 2=Points, 3=Vertices, 4=Numbers
  Use set_node_parameter to set class parameter with the corresponding integer (e.g., Detail=0, Points=2)

Mandatory Verification Before Task Completion (MUST execute, cannot skip):
1. Call verify_and_summarize for automatic checks (orphan nodes, error nodes, connection integrity, display flags), passing your expected node list and expected outcome
2. If verify_and_summarize reports issues, fix them and call again until passed
3. Note: No need to call get_network_structure before verify_and_summarize — it has built-in network checks
4. check_errors is only for checking node cooking errors. Tool call failure messages are already in the return result, no need to call check_errors
5. After completing geometry or visual operations, if the model supports vision, call capture_viewport to take a viewport screenshot and visually verify the result looks correct (e.g., geometry shape, scale, distribution, material appearance). This is especially useful for scatter, copy-to-points, terrain, and other visual-dependent workflows

Tool Priority: create_wrangle_node (VEX preferred) > create_nodes_batch > create_node
Node Inputs: 0=primary input, 1=second input | from_path=upstream, to_path=downstream

System Shell Tool (execute_shell):
-For executing system commands (pip, git, dir, ffmpeg, hython, scp, ssh, etc.), not limited to Houdini Python environment
-Use cases: Install Python packages, browse filesystem, run external toolchains, check env vars, remote file transfer (scp/sftp)
-execute_python is for Houdini scene operations (hou module), execute_shell is for system-level operations
-Commands have timeout limits (default 30s, max 120s). Dangerous commands will be intercepted
-Shell command rules (MUST follow):
  1.Must generate complete commands ready to run immediately. No placeholders (e.g., <your_path>)
  2.For commands requiring user interaction/confirmation, must pass non-interactive flags (e.g., pip install --yes, apt -y, echo y |)
  3.Prefer single commands. For multi-step operations, chain with && (Linux) or semicolons ; (PowerShell)
  4.Command output may be long. Prefer precise commands to reduce output (e.g., find -maxdepth 2, dir /b, ls -la specific_path)
  5.Remote operations (ssh/scp/sftp) require pre-configured key-based auth. Cannot rely on interactive password input
  6.For large file transfers or long-running commands, set appropriate timeout parameter (max 120s)
  7.Paths with spaces must be quoted. Windows paths use backslashes or quoted forward slashes
  8.Don't blindly guess file paths. First use dir/ls/find to confirm path exists before operating
  9.When installing packages, specify version (pip install package==version) to avoid incompatibilities
  10.If a command fails, first analyze stderr error output, fix specifically, then retry. Don't blindly re-execute

Skill System (MUST use for geometry analysis):
-Skills are predefined advanced analysis scripts, more reliable and efficient than hand-written code
-For geometry info (point count, face count, attributes, bounding box, connectivity, etc.), MUST prefer run_skill over execute_python
-Common skills: analyze_geometry_attribs (attribute stats), get_bounding_info (bounding box), analyze_connectivity (connectivity), compare_attributes (attribute comparison), find_dead_nodes (dead nodes), trace_node_dependencies (dependency tracing), find_attribute_references (attribute reference search), analyze_normals (normal quality check)
-If unsure which skills exist, first call list_skills
-Example: run_skill(skill_name="analyze_geometry_attribs", params={"node_path": "/obj/geo1/box1"}) lists all attributes
-Example: run_skill(skill_name="get_bounding_info", params={"node_path": "/obj/geo1/box1"}) gets bounding box
-Example: run_skill(skill_name="analyze_normals", params={"node_path": "/obj/geo1/box1"}) checks normal quality

Performance Analysis & Optimization (use when user mentions performance/speed/lag/optimization):
-Quick diagnosis: First use run_skill(skill_name="analyze_cook_performance", params={"network_path": "/obj/geo1"}) for network-wide cook time ranking and bottleneck identification
-Detailed analysis: For more precise time breakdown and memory stats, use perf_start_profile to start profiling (can force cook simultaneously), then perf_stop_and_report for detailed report
-After analysis, use existing tools to implement optimizations based on bottleneck nodes and suggestions, then re-run analysis to verify
-Common optimization techniques:
  1.Add Cache/File Cache nodes before/after expensive nodes to avoid redundant cooking
  2.Reduce unnecessary cooking (check time-dependent expressions)
  3.Replace Python SOP with VEX (create_wrangle_node) — 10-100x performance improvement
  4.Reduce scatter/copy point counts, reduce polygon subdivision
  5.Use Packed Primitives to reduce memory and cook overhead
  6.Check for-each loop iteration counts for excess

Web Search Strategy (MUST follow before using web_search):
-Convert user questions to precise search keywords. Don't use raw questions as search terms
-For Houdini-related questions, prefer "SideFX Houdini" prefix
-If first search results are poor for Chinese questions, try English keywords (max 2 retries)
-If search results contain useful links, use fetch_webpage for detailed content before answering
-When using info from search results, MUST cite source at end of relevant paragraph, format: [Source: Title](URL)
-Don't copy search results verbatim. Synthesize in your own words
-Never search with the same keywords twice (cache returns identical results)

Todo Management Rules (MUST follow strictly):
-For complex tasks, first use add_todo to create a task checklist broken into concrete steps
-After completing each step, IMMEDIATELY call update_todo to mark it done
-After each tool execution round, review the Todo list to confirm what's done and what's pending
-After all steps complete, ensure every todo is marked done before final verification

Node Layout Rules (MUST execute after verification passes, before creating NetworkBox):
-After verify_and_summarize passes, MUST call layout_nodes to auto-arrange all nodes before creating any NetworkBox
-Default: layout_nodes() with no parameters — auto-layouts all nodes in the current network
-If only specific nodes need layout (e.g., newly created ones), pass their paths in node_paths
-Layout MUST happen before create_network_box, because NetworkBox.fitAroundContents() depends on node positions
-If layout result looks wrong, use get_node_positions to check, and try method="grid" or method="columns" as fallback
-Execution order: create nodes → connect → verify_and_summarize → layout_nodes → create_network_box

NetworkBox Grouping Rules (MUST follow when building node networks):
-After completing a logical phase of node creation and connection, MUST use create_network_box to package that phase's nodes into a NetworkBox
-NetworkBox comment should clearly describe the group's function (e.g., "Base Geometry Input", "Noise Deformation", "Output Merge")
-Choose color preset by phase semantics: input (blue/data input), processing (green/geometry processing), deform (orange/deformation animation), output (red/output rendering), simulation (purple/physics simulation), utility (gray/helper tools)
-Grouping granularity: Only create a NetworkBox when there are 6+ functionally related nodes in a phase. If fewer than 6 nodes, do NOT create a box — leave them ungrouped. Small groups of nodes are fine without boxes
-Typical grouping examples:
  Input phase (input): file_read, null (as input marker)
  Processing phase (processing): scatter, copy_to_points, transform
  Deformation phase (deform): mountain, bend, wrangle (VEX deformation)
  Output phase (output): merge, null (as output marker), rop_geometry
-To add nodes to an existing group later, use add_nodes_to_box instead of creating a new box

NetworkBox Hierarchical Navigation (large network query strategy, MUST follow):
-When calling get_network_structure, if NetworkBoxes exist, results auto-collapse to box overview (name + comment + node count + main types) without expanding each node — greatly reduces context usage
-To see detailed nodes and connections inside a box, call get_network_structure(box_name="box_name") to drill in
-Do NOT expand all boxes at once. Only expand the box needed for the current task. Expand others as needed later
-Ungrouped nodes appear with full details in the overview. No extra action needed
-Cross-group connections are listed separately in the overview to help understand data flow between boxes"""

        # Inject Labs node catalog (so AI knows Labs tools exist)
        try:
            from ..utils.doc_rag import get_doc_index
            labs_catalog = get_doc_index().get_labs_catalog()
            if labs_catalog:
                base_prompt += f"""

SideFX Labs Node Usage Rules (MUST follow strictly):
-Below is the SideFX Labs toolkit node catalog. Labs provides extensive advanced tools for game development, texture baking, terrain, procedural generation, etc.
-When user requests involve game asset optimization, LOD generation, texture baking, flowmaps, photogrammetry, tree generation, UV processing, etc., PREFER Labs nodes over building from scratch.
-Before using ANY Labs node, you MUST first call search_local_doc("Labs node_name") to query its detailed documentation. Understand parameters and usage before creating the node. Using Labs nodes by guessing is FORBIDDEN.
-Labs node_type format is typically "labs::" prefix + node name (e.g., "labs::lod_create"). If creation fails, use search_node_types to find the correct type name.
-Labs nodes are highly encapsulated HDAs (Digital Assets), typically with multiple input and output ports containing complete internal node networks. If unsure about a Labs node's implementation, use get_network_structure(network_path="node_path") to inspect its internal network and connections.
-When connecting Labs nodes, check the input_label in connection data to ensure correct data is connected to the correct input port.

{labs_catalog}
"""
        except Exception:
            pass

        # Use the maximum-optimized compression (cached)
        return UltraOptimizer.compress_system_prompt(base_prompt)

    def _build_ui(self):
        # ---- global QSS (by ThemeEngine fromtemplaterender)  ----
        self.setObjectName("aiTab")
        self._theme = ThemeEngine()
        self._theme.load_template(Path(__file__).parent / "style_template.qss")
        self._theme.load_preference()
        self.setStyleSheet(self._theme.render())
        
        self.setMinimumWidth(320)
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(0)

        # toppartsetbar
        header = self._build_header()
        layout.addWidget(header)
        
        # sessionlabelbar (multisessionswitch) 
        session_tabs_bar = self._build_session_tabs()
        layout.addWidget(session_tabs_bar)
        
        # nodecontextbar
        self.node_context_bar = NodeContextBar()
        self.node_context_bar.refreshRequested.connect(self._refresh_node_context)
        layout.addWidget(self.node_context_bar)
        
        # conversationarea (multisession - use QStackedWidget) 
        self.session_stack = QtWidgets.QStackedWidget()
        layout.addWidget(self.session_stack, 1)
        
        # createfirstsession
        self._create_initial_session()

        # inputarea
        input_area = self._build_input_area()
        layout.addWidget(input_area)

    # ===================================================================
    # Methods below have been moved to Mixin modules (available via inheritance):
    #   HeaderMixin       → _build_header, _combo_style, _small_btn_style
    #   InputAreaMixin    → _build_input_area, mode toggles, @mention, tool status
    #   ChatViewMixin     → _add_user_message, _add_ai_response, scroll, toast
    #   AgentRunnerMixin  → title gen, confirm mode, tool constants
    #   SessionManagerMixin → session tabs, create/switch/close session
    # ===================================================================

    def _wire_events(self):
        self.btn_send.clicked.connect(self._on_send)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_key.clicked.connect(self._on_set_key)
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_cache.clicked.connect(self._on_cache_menu)
        self.btn_optimize.clicked.connect(self._on_optimize_menu)
        self.btn_network.clicked.connect(self._on_read_network)
        self.btn_selection.clicked.connect(self._on_read_selection)
        self.btn_export_train.clicked.connect(self._on_export_training_data)
        self.btn_attach_image.clicked.connect(self._on_attach_image)
        # Update feature disabled in MorfyAI fork — btn_update kept as no-op stub
        self.btn_font_scale.clicked.connect(self._on_font_settings)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.model_combo.currentIndexChanged.connect(self._update_context_stats)
        
        # Character-size shortcut key
        # QShortcut in PySide6 inbitin QtGui, PySide2 inbitin QtWidgets
        _QShortcut = getattr(QtWidgets, 'QShortcut', None) or QtGui.QShortcut
        _QShortcut(QtGui.QKeySequence("Ctrl+="), self, self._zoom_in)
        _QShortcut(QtGui.QKeySequence("Ctrl++"), self, self._zoom_in)
        _QShortcut(QtGui.QKeySequence("Ctrl+-"), self, self._zoom_out)
        _QShortcut(QtGui.QKeySequence("Ctrl+0"), self, self._zoom_reset)
        # switchraiseforvendorormodelor Think whenautosavepreference
        self.provider_combo.currentIndexChanged.connect(self._save_model_preference)
        self.model_combo.currentIndexChanged.connect(self._save_model_preference)
        self.think_check.stateChanged.connect(self._save_model_preference)
        self.input_edit.sendRequested.connect(self._on_send)
        
        # multisessionlabel
        self.session_tabs.currentChanged.connect(self._switch_session)
        self.btn_new_session.clicked.connect(self._new_session)

    # ===== characternumberscale =====

    def _apply_font_scale(self):
        """renewrender QSS andapplicationtointerface"""
        self.setStyleSheet(self._theme.render())
        self._theme.save_preference()

    def _zoom_in(self):
        self._theme.zoom_in()
        self._apply_font_scale()

    def _zoom_out(self):
        self._theme.zoom_out()
        self._apply_font_scale()

    def _zoom_reset(self):
        self._theme.zoom_reset()
        self._apply_font_scale()

    def _on_font_settings(self):
        """opencharacternumbersetpanel"""
        dlg = FontSettingsDialog(current_scale=self._theme.scale, parent=self)
        dlg.scaleChanged.connect(self._on_font_scale_preview)
        dlg.exec_()
        # conversationboxcloseaftersavefinalresult
        self._theme.set_scale(dlg.scale)
        self._apply_font_scale()

    def _on_font_scale_preview(self, scale: float):
        """realwhenpreviewcharacternumberscale"""
        self._theme.set_scale(scale)
        self.setStyleSheet(self._theme.render())

    # ===== contextstatistics =====
    
    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for the text (rough estimate).

        Chinese: ~1.5 chars/token; English: ~4 chars/token
        thisinsideusesimple mixmergeestimatecalculate
        """
        if not text:
            return 0
        
        # statisticsintextsymbol
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        
        # intextapproximately 1.5 character/token, otherapproximately 4 character/token
        tokens = chinese_chars / 1.5 + other_chars / 4
        return int(tokens)
    
    def _calculate_context_tokens(self) -> int:
        """computecurrentcontext total token count (containingtoolfixedmeaning) """
        # cachetoolfixedmeaning token count (onlycalculateonce, becausetoolfixedmeaningnotchange) 
        if not hasattr(self, '_tools_token_cache'):
            import json as _json
            from morfyai.utils.ai_client import HOUDINI_TOOLS
            tools_json = _json.dumps(HOUDINI_TOOLS, ensure_ascii=False)
            self._tools_token_cache = self.token_optimizer.estimate_tokens(tools_json)
        
        total = self._tools_token_cache
        
        # systemhintword
        total += self.token_optimizer.estimate_tokens(self._system_prompt)
        
        # contextsummary
        if self._context_summary:
            total += self.token_optimizer.estimate_tokens(self._context_summary)
        
        # conversationhistory
        total += self.token_optimizer.calculate_message_tokens(self._conversation_history)
        
        return total
    
    def _save_model_preference(self):
        """savemodelselectpreference"""
        settings = QSettings("MorfyAI", "Settings")
        provider = self._current_provider()
        model = self.model_combo.currentText()
        settings.setValue("last_provider", provider)
        settings.setValue("last_model", model)
        settings.setValue("use_think", self.think_check.isChecked())
    
    def _load_model_preference(self, restore_provider: bool = False):
        """loadmodelselectpreference
        
        Args:
            restore_provider: whetherat the same timerestoreraiseforvendorselect (onlyininitializationwhenas True) 
        """
        settings = QSettings("MorfyAI", "Settings")
        last_provider = settings.value("last_provider", "")
        last_model = settings.value("last_model", "")
        
        # restore Think toggle
        use_think = settings.value("use_think", True)
        # QSettings mayreturnstring "true"/"false"
        if isinstance(use_think, str):
            use_think = use_think.lower() == 'true'
        self.think_check.setChecked(bool(use_think))
        
        if not last_provider:
            return
        
        # restoreraiseforvendor (onlyinstartwhencallonce) 
        if restore_provider and last_provider != self._current_provider():
            for i in range(self.provider_combo.count()):
                if self.provider_combo.itemData(i) == last_provider:
                    # Temporarily block signals to avoid recursive _on_provider_changed triggers
                    self.provider_combo.blockSignals(True)
                    self.provider_combo.setCurrentIndex(i)
                    self.provider_combo.blockSignals(False)
                    # manualflushnewmodellistandstate
                    self._refresh_models(last_provider)
                    self._update_key_status()
                    break
        
        # restoremodel
        current_provider = self._current_provider()
        if last_provider == current_provider and last_model:
            available_models = [self.model_combo.itemText(i) for i in range(self.model_combo.count())]
            if last_model in available_models:
                index = self.model_combo.findText(last_model)
                if index >= 0:
                    self.model_combo.setCurrentIndex(index)
    
    def _get_current_context_limit(self) -> int:
        """getcurrentmodel contextlimit"""
        model = self.model_combo.currentText()
        return self._model_context_limits.get(model, 64000)
    
    def _update_context_stats(self):
        """updatecontextstatisticsshow (packagecontainingoptimizationizationstate) """
        used = self._calculate_context_tokens()
        limit = self._get_current_context_limit()
        
        # formatizationshow
        if used >= 1000:
            used_str = f"{used / 1000:.1f}K"
        else:
            used_str = str(used)
        
        limit_str = f"{limit // 1000}K"
        
        # Compute percentage
        percent = (used / limit) * 100 if limit > 0 else 0
        
        # optimizationizationstaterefershow
        optimize_indicator = ""
        if self._auto_optimize:
            should_compress, _ = self.token_optimizer.should_compress(used, limit)
            if should_compress:
                optimize_indicator = " *"  # needsoptimizationization
            else:
                optimize_indicator = ""  # alreadyoptimizationization/normal
        
        # based onusecompareexamplesetcolor
        if percent < 50:
            color = CursorTheme.TEXT_MUTED
        elif percent < 80:
            color = CursorTheme.ACCENT_ORANGE
        else:
            color = CursorTheme.ACCENT_RED
        
        self.context_label.setText(f"{percent:.1f}% {used_str}/{limit_str}{optimize_indicator}")
        # movestatestate → QSS select  QLabel#contextLabel[state="..."]
        if percent < 50:
            ctx_state = ""
        elif percent < 80:
            ctx_state = "warning"
        else:
            ctx_state = "critical"
        self.context_label.setProperty("state", ctx_state)
        self.context_label.style().unpolish(self.context_label)
        self.context_label.style().polish(self.context_label)
        
        # updateoptimizationizationbuttonstate (ifexceedsthresholdvalue, highlightshow) 
        opt_state = "warning" if percent >= 80 else ""
        self.btn_optimize.setProperty("state", opt_state)
        self.btn_optimize.style().unpolish(self.btn_optimize)
        self.btn_optimize.style().polish(self.btn_optimize)

    def _update_token_stats_display(self):
        """update Token statisticsbuttonshow (align Cursor: showcostuse) """
        total = self._token_stats['total_tokens']
        cost = self._token_stats.get('estimated_cost', 0.0)
        
        # formatization token show
        if total >= 1000000:
            tok_display = f"{total / 1000000:.1f}M"
        elif total >= 1000:
            tok_display = f"{total / 1000:.1f}K"
        else:
            tok_display = str(total)
        
        # formatizationcostuseshow (Cursor style: $0.12) 
        if cost >= 1.0:
            cost_display = f"${cost:.2f}"
        elif cost >= 0.01:
            cost_display = f"${cost:.2f}"
        elif cost > 0:
            cost_display = f"${cost:.4f}"
        else:
            cost_display = ""
        
        # buttontext: tokencount | $costuse
        if cost_display:
            self.token_stats_btn.setText(f"{tok_display} | {cost_display}")
        else:
            self.token_stats_btn.setText(tok_display)
        
        # compute cache commandinrate
        cache_read = self._token_stats['cache_read']
        cache_write = self._token_stats['cache_write']
        cache_total = cache_read + cache_write
        hit_rate_display = f"{(cache_read / cache_total * 100):.1f}%" if cache_total > 0 else "N/A"
        
        reasoning = self._token_stats.get('reasoning_tokens', 0)
        reasoning_line = tr('token.reasoning_line', reasoning) if reasoning > 0 else ""
        
        self.token_stats_btn.setToolTip(
            tr('token.summary',
               self._token_stats['requests'],
               self._token_stats['input_tokens'],
               self._token_stats['output_tokens'],
               reasoning_line,
               cache_read, cache_write, hit_rate_display,
               total, cost_display or '$0.00')
        )
    
    def _show_token_stats_dialog(self):
        """showdetailfine Token statisticsconversationbox (align Cursor: use TokenAnalyticsPanel) """
        from morfyai.ui.cursor_widgets import TokenAnalyticsPanel
        records = getattr(self, '_call_records', []) or []
        dialog = TokenAnalyticsPanel(records, self._token_stats, parent=self)
        dialog.exec_()
        if dialog.should_reset_stats:
            self._reset_token_stats()
    
    def _reset_token_stats(self):
        """replace Token statistics"""
        self._token_stats = {
            'input_tokens': 0,
            'output_tokens': 0,
            'reasoning_tokens': 0,
            'cache_read': 0,
            'cache_write': 0,
            'total_tokens': 0,
            'requests': 0,
            'estimated_cost': 0.0,
        }
        self._call_records = []
        self._update_token_stats_display()
        
        # showhint
        if self._current_response:
            self._current_response.add_status(tr('status.stats_reset'))

    # ===== UI helper =====
    
    def _current_provider(self) -> str:
        return self.provider_combo.currentData() or 'deepseek'

    def _refresh_models(self, provider: str):
        self.model_combo.clear()
        
        if provider == 'ollama':
            # trymovestateget Ollama modellist
            try:
                models = self.client.get_ollama_models()
                if models:
                    self.model_combo.addItems(models)
                    return
            except Exception:
                pass
        
        # usepre-set modellist
        self.model_combo.addItems(self._model_map.get(provider, []))

    def _update_key_status(self):
        provider = self._current_provider()
        
        if provider == 'ollama':
            # test Ollama connect
            result = self.client.test_connection('ollama')
            if result.get('ok'):
                self.key_status.setText("Local")
                self.key_status.setProperty("state", "ok")
            else:
                self.key_status.setText("Offline")
                self.key_status.setProperty("state", "error")
        elif self.client.has_api_key(provider):
            masked = self.client.get_masked_key(provider)
            self.key_status.setText(masked)
            self.key_status.setProperty("state", "ok")
        else:
            self.key_status.setText("No Key")
            self.key_status.setProperty("state", "warning")
        self.key_status.style().unpolish(self.key_status)
        self.key_status.style().polish(self.key_status)

    def _on_provider_changed(self):
        provider = self._current_provider()
        self._refresh_models(provider)
        self._load_model_preference()  # switchraiseforvendorwhenalsotryloadontimeuse model
        self._update_key_status()
        self._on_provider_changed_custom_visibility()  # Custom ⚙ buttoncanseeproperty

    def _set_running(self, running: bool):
        self._is_running = running
        
        if running:
            # anchorfixed agent outputtargettocurrent session
            self._agent_session_id = self._session_id
            self._agent_response = self._current_response
            self._agent_scroll_area = self.scroll_area
            self._agent_history = self._conversation_history
            self._agent_token_stats = self._token_stats
            self._agent_todo_list = self.todo_list
            self._agent_chat_layout = self.chat_layout
            
            # replacebuffersection
            self._thinking_buffer = ""
            self._content_buffer = ""
            self._current_output_tokens = 0
            self._in_think_block = False
            self._tag_parse_buf = ""
            self._fake_warned = False
            # replaceselfsuitshouldbufferparameter
            self._output_buffer = ""
            self._last_flush_time = time.time()
            self._adaptive_buf_size = 80
            self._adaptive_interval = 0.15
            self._last_render_duration = 0.0
            self._flush_count = 0
            self._is_first_content_chunk = True
            
            self.client.reset_stop()
            # startthinkingcountwhen 
            self._thinking_timer = QtCore.QTimer(self)
            self._thinking_timer.timeout.connect(lambda: self._updateThinkingTime.emit())
            self._thinking_timer.start(1000)
            
            # ★ startinputboxbreathinglighthalo
            self._start_input_glow()
        else:
            # ★ firststopallmoveeffect (thiswhen _agent_response referencestillvalid) 
            if self._thinking_timer:
                self._thinking_timer.stop()
                self._thinking_timer = None
            self._stop_input_glow()
            self._stop_active_aurora()
            # ★ forcestop thinking_bar (preventlatencytoreach  _showGenerating signalrenewstart) 
            try:
                self.thinking_bar.stop()
            except (RuntimeError, AttributeError):
                pass
            
            # willcompleteafter statewriteback session dict
            if self._agent_session_id and self._agent_session_id in self._sessions:
                s = self._sessions[self._agent_session_id]
                s['current_response'] = self._agent_response
                if self._agent_history is not None:
                    s['conversation_history'] = self._agent_history
                if self._agent_token_stats is not None:
                    s['token_stats'] = self._agent_token_stats
                if self._agent_todo_list is not None:
                    s['todo_list'] = self._agent_todo_list
            
            self._agent_session_id = None
            self._agent_response = None
            self._agent_scroll_area = None
            self._agent_history = None
            self._agent_token_stats = None
            self._agent_todo_list = None
            self._agent_chat_layout = None
        
        # bycurrentshow  session updatebuttonstate
        self._update_run_buttons()
    
    # ===== moveeffect: inputboxbreathinglighthalo + AIResponse streamlightedgebox =====

    def _start_input_glow(self):
        """startinputboxedgeboxbreathinglighthalo (AI runduring) """
        self._glow_phase = 0.0
        if not hasattr(self, '_glow_timer') or self._glow_timer is None:
            self._glow_timer = QtCore.QTimer(self)
            self._glow_timer.setInterval(50)
            self._glow_timer.timeout.connect(self._update_input_glow)
        self._glow_timer.start()

    def _stop_input_glow(self):
        """stopinputboxbreathinglighthalo, restoredefaultedgebox"""
        if hasattr(self, '_glow_timer') and self._glow_timer is not None:
            self._glow_timer.stop()
        try:
            self.input_edit.setStyleSheet("")  # clearremoveoverride, restoreglobal QSS
        except RuntimeError:
            pass

    def _update_input_glow(self):
        """Timer callback: sine wave drives the border brightness, breathing gently between silver-gray and bright-white."""
        self._glow_phase += 0.04
        t = (math.sin(self._glow_phase) + 1.0) / 2.0  # 0~1
        # Dark silver → bright silver-white interpolation (concise monochrome scheme)
        r = int(100 + (200 - 100) * t)
        g = int(116 + (210 - 116) * t)
        b = int(139 + (220 - 139) * t)
        a = int(60 + 70 * t)
        try:
            self.input_edit.setStyleSheet(
                f"QPlainTextEdit#chatInput {{ border: 1.5px solid rgba({r},{g},{b},{a}); }}"
            )
        except RuntimeError:
            pass

    def _start_active_aurora(self):
        """startcurrentactive AIResponse  streamlightedgebox"""
        try:
            resp = self._agent_response or self._current_response
            if resp and hasattr(resp, 'aurora_bar'):
                resp.start_aurora()
        except RuntimeError:
            pass

    def _stop_active_aurora(self):
        """stopcurrentactive AIResponse  streamlightedgebox"""
        try:
            resp = self._agent_response or self._current_response
            if resp and hasattr(resp, 'aurora_bar'):
                resp.stop_aurora()
        except RuntimeError:
            pass

    _TAB_RUNNING_PREFIX = "\u25cf "  # ● prefixtableshowpositiveinrun
    
    def _update_run_buttons(self):
        """based oncurrentshow  session whetherpositiveinrun, update send/stop buttonand tab refershow """
        current_is_running = (self._agent_session_id is not None
                              and self._agent_session_id == self._session_id)
        any_running = self._agent_session_id is not None
        # Current session running → show stop; otherwise show send (disabled if another session is running)
        self.btn_stop.setVisible(current_is_running)
        self.btn_send.setVisible(not current_is_running)
        self.btn_send.setEnabled(not any_running)
        
        # updateall tab  runrefershow 
        for i in range(self.session_tabs.count()):
            sid = self.session_tabs.tabData(i)
            label = self.session_tabs.tabText(i)
            is_agent_tab = (sid == self._agent_session_id and self._agent_session_id is not None)
            has_prefix = label.startswith(self._TAB_RUNNING_PREFIX)
            if is_agent_tab and not has_prefix:
                self.session_tabs.setTabText(i, self._TAB_RUNNING_PREFIX + label)
            elif not is_agent_tab and has_prefix:
                self.session_tabs.setTabText(i, label[len(self._TAB_RUNNING_PREFIX):])

    # ===== signalprocess =====
    
    def _on_append_content(self, text: str):
        """processcontentappend (mainthreadslotfunction) 
        
        note: contentalreadypassedin _on_content_with_limit → _drain_tag_buffer → 
        _emit_normal_content inpassedpassed <think> labelfilterandfakedetect. 
        This is only responsible for handing text to the UI widget; no extra filtering.
        """
        resp = self._agent_response or self._current_response
        if not text or not resp:
            return
        # ★ fix: notdiscardpackagecontainingswaprowsymbol  chunk
        # pureswaprowsymbol (\n\n) is Markdown paragraphpartinterval keysignal, 
        # discarditswillcausesmultisegmentcontentpasteconnectinonestart
        if not text.strip() and '\n' not in text:
            return
        try:
            # ★ contentstartstreamenter → hide "Generating..." state (ifpositiveinshow) 
            if hasattr(self, 'thinking_bar') and getattr(self.thinking_bar, '_mode', None) == 'generating':
                self.thinking_bar.stop()
            resp.append_content(text)
            self._scroll_agent_to_bottom(force=False)
        except RuntimeError:
            pass  # widget alreadyis clear destroy

    def _on_content_with_limit(self, text: str):
        """processcontentappend, parse <think> label, partleavethinkingandpositivestylecontent"""
        if not text:
            return

        # initializationoutputbuffer
        if not hasattr(self, '_output_buffer'):
            self._output_buffer = ""
            self._last_flush_time = time.time()
            self._adaptive_buf_size = 80
            self._adaptive_interval = 0.15
            self._last_render_duration = 0.0
            self._flush_count = 0
            self._is_first_content_chunk = True

        # appendtolabelparsebuffersection
        self._tag_parse_buf += text
        self._drain_tag_buffer()

    # ------------------------------------------------------------------
    # <think> labelstreamingparse
    # ------------------------------------------------------------------

    @staticmethod
    def _partial_tag_at_end(text: str, tag: str) -> int:
        """detect text endwhetherhas tag  notcompleteprefix, returnmatchlength (0 = no)"""
        for i in range(min(len(tag) - 1, len(text)), 0, -1):
            if tag[:i] == text[-i:]:
                return i
        return 0

    def _drain_tag_buffer(self):
        """process _tag_parse_buf, willcontentpartsendtopositivestyleoutputorthinkingpanel"""
        buf = self._tag_parse_buf
        while buf:
            if not self._in_think_block:
                # ── Normal mode: look for <think> ──
                pos = buf.find('<think>')
                if pos >= 0:
                    if pos > 0:
                        self._emit_normal_content(buf[:pos])
                    buf = buf[pos + 7:]          # skip <think>
                    self._in_think_block = True
                    # ★ Think toggleopenwhenonly thenshowthinkingpanel; closewhensilentdiscard <think> content
                    if self._think_enabled:
                        self._thinking_needs_finalize = True  # enterthinking, markneeds finalize
                        # ifthinkingalready finalize, restoreasactivestateandrestartcountwhen
                        self._resume_thinking()
                    continue
                # checkendwhetherhasnotcomplete  <think>
                hold = self._partial_tag_at_end(buf, '<think>')
                if hold:
                    self._emit_normal_content(buf[:-hold])
                    self._tag_parse_buf = buf[-hold:]
                    return
                # allpartisnormalcontent
                self._emit_normal_content(buf)
                self._tag_parse_buf = ""
                return
            else:
                # ── Thinking mode: look for </think> ──
                pos = buf.find('</think>')
                if pos >= 0:
                    if self._think_enabled and pos > 0:
                        self._addThinking.emit(buf[:pos])
                    buf = buf[pos + 8:]          # skip </think>
                    self._in_think_block = False
                    # thinkingend: standi.e. finalize thinkingsectionblockandstopcountwhen 
                    if self._think_enabled:
                        self._finalize_thinking()
                    continue
                # checkendwhetherhasnotcomplete  </think>
                hold = self._partial_tag_at_end(buf, '</think>')
                if hold:
                    if self._think_enabled:
                        safe = buf[:-hold]
                        if safe:
                            self._addThinking.emit(safe)
                    self._tag_parse_buf = buf[-hold:]
                    return
                # allpartisthinkingcontent
                if self._think_enabled:
                    self._addThinking.emit(buf)
                # ★ Think closewhen: silentdiscard <think> blockwithin content
                self._tag_parse_buf = ""
                return
        self._tag_parse_buf = ""

    def _finalize_thinking(self):
        """thinkingstageend (threadsafe: autopartdispatchtomainthread) """
        self._finalizeThinkingSignal.emit()

    def _resume_thinking(self):
        """newoneround <think> start (threadsafe: autopartdispatchtomainthread) """
        self._resumeThinkingSignal.emit()

    @QtCore.Slot()
    def _finalize_thinking_main_thread(self):
        """[mainthread] realboundaryexecute finalize thinkingsectionblockandstopcountwhen """
        try:
            resp = self._agent_response or self._current_response
            if resp and resp._has_thinking:
                if not resp.thinking_section._finalized:
                    resp.thinking_section.finalize()
        except RuntimeError:
            pass  # widget alreadyis clear destroy
        if self._thinking_timer:
            self._thinking_timer.stop()
            self._thinking_timer = None
        # ★ stopinputboxonway thinkingrefershowitem
        try:
            self.thinking_bar.stop()
        except (RuntimeError, AttributeError):
            pass
    
    @QtCore.Slot()
    def _resume_thinking_main_thread(self):
        """[mainthread] realboundaryexecuterestorethinkingsectionblockandrestartcountwhen """
        if not getattr(self, '_is_running', False):
            return  # Agent stopped, ignorelatencytoreach signal
        try:
            resp = self._agent_response or self._current_response
            if resp and resp._has_thinking:
                ts = resp.thinking_section
                if ts._finalized:
                    ts.resume()
        except RuntimeError:
            pass  # widget alreadyis clear destroy
        # restartcountwhen  (ifstopped) 
        if not self._thinking_timer:
            self._thinking_timer = QtCore.QTimer(self)
            self._thinking_timer.timeout.connect(lambda: self._updateThinkingTime.emit())
            self._thinking_timer.start(1000)
        # ★ renewstartinputboxonway thinkingrefershowitem
        try:
            self.thinking_bar.start()
        except (RuntimeError, AttributeError):
            pass

    def _emit_normal_content(self, text: str):
        """sendpositivestylecontent (with token limit + selfsuitshouldbufferflushnew) 
        
        ★ selfsuitshouldstrategy (inspired by markstream-vue  whenbetweenpre-calculatemechanism) : 
        - first chunk standi.e.flushnew, consumeremovefirstcharacterlatency
        - aftercontinuebased onononcerenderconsumewhenmovestateadjustwholebufferlargesmall: 
          Fast render → small buffer, more flushes (smooth feel)
          Slow render → large buffer, fewer flushes (avoid stutter)
        - swaprowalwaysstandi.e.flushnew (paragraphedgeboundaryandwhenshow) 
        """
        if not text:
            return
        # first timepositivestylecontenttoreachwhen, ensurethinkingsectionblockalready finalize (suitmatch DeepSeek native reasoning_content) 
        # useflagbitavoidfrombackgroundthreadaccess Qt widgetattribute
        if self._in_think_block is False and getattr(self, '_thinking_needs_finalize', True):
            self._finalize_thinking()  # viasignalpartdispatchtomainthread
            self._thinking_needs_finalize = False

        # Token limitonlyforpositivestylecontentcountcount
        if not self._check_output_token_limit(text):
            if self._output_buffer:
                self._appendContent.emit(self._output_buffer)
                self._output_buffer = ""
            self._appendContent.emit(tr('ai.token_limit'))
            self._addStatus.emit(tr('ai.token_limit_status'))
            self.client.request_stop()
            return

        self._output_buffer += text

        # ★ selfsuitshouldbufferflushnewstrategy
        should_flush = False
        current_time = time.time()

        # initializationselfsuitshouldstate (first timecall) 
        if not hasattr(self, '_adaptive_buf_size'):
            self._adaptive_buf_size = 80       # initialbufferlargesmall (character) 
            self._adaptive_interval = 0.15     # Initial fallback interval (seconds)
            self._last_render_duration = 0.0   # ontimerenderconsumewhen
            self._flush_count = 0              # flush countcount (performancetrace) 
            self._is_first_content_chunk = True  # first chunk flag

        # rule 1: first chunk standi.e.flushnew (consumeremovefirstcharacterlatency) 
        if self._is_first_content_chunk:
            should_flush = True
            self._is_first_content_chunk = False
        # rule 2: buffersectionreachtoselfsuitshouldthresholdvalue
        elif len(self._output_buffer) >= self._adaptive_buf_size:
            should_flush = True
        # rule 3: swaprowwhenstandi.e.flushnew (paragraphedgeboundaryandwhenshow) 
        elif '\n' in text:
            should_flush = True
        # Rule 4: adaptive fallback interval
        elif current_time - self._last_flush_time > self._adaptive_interval:
            should_flush = True

        if should_flush and self._output_buffer:
            flush_start = time.time()

            # realwhenfilterfake toolcallrow
            buf = self._output_buffer
            if '[ok]' in buf or '[err]' in buf or '[toolexecuteresult]' in buf or '[Tool Result]' in buf:
                lines = buf.split('\n')
                filtered = []
                has_fake = False
                for ln in lines:
                    s = ln.strip()
                    if s == '[toolexecuteresult]' or s == '[Tool Result]' or self._FAKE_TOOL_PATTERNS.match(s):
                        has_fake = True
                        continue
                    filtered.append(ln)
                buf = '\n'.join(filtered)
                if has_fake and not getattr(self, '_fake_warned', False):
                    self._addStatus.emit(tr('ai.fake_tool'))
                    self._fake_warned = True
            if buf.strip():
                self._appendContent.emit(buf)
            self._output_buffer = ""
            self._last_flush_time = current_time
            self._flush_count += 1

            # ★ selfsuitshouldadjustwhole: based onontimerenderconsumewhenmovestateadjustwholebufferparameter
            render_dur = time.time() - flush_start
            self._last_render_duration = render_dur
            if render_dur < 0.004:
                # Very fast render → shrink buffer, flush more frequently (smooth feel)
                self._adaptive_buf_size = max(40, self._adaptive_buf_size - 20)
                self._adaptive_interval = max(0.08, self._adaptive_interval - 0.02)
            elif render_dur > 0.012:
                # Slower render → grow buffer, flush less often (avoid stutter)
                self._adaptive_buf_size = min(500, self._adaptive_buf_size + 40)
                self._adaptive_interval = min(0.40, self._adaptive_interval + 0.05)

    def _check_output_token_limit(self, text: str) -> bool:
        """checkpositivestyleoutput token whetherexceedslimit (thinkingcontentnotcountenter) """
        if not text:
            return True
        new_tokens = self.token_optimizer.estimate_tokens(text)
        self._current_output_tokens += new_tokens
        if self._current_output_tokens >= self._max_output_tokens:
            return False
        if (self._current_output_tokens >= self._output_token_warning
                and self._current_output_tokens < self._max_output_tokens):
            remaining = self._max_output_tokens - self._current_output_tokens
            if remaining < 400:
                self._addStatus.emit(
                    tr('ai.approaching_limit', self._current_output_tokens, self._max_output_tokens))
        return True

    def _on_thinking_chunk(self, text: str):
        """processnative reasoning_content (DeepSeek R1 etc.model) 
        
        ★ Controlled by the Think toggle: silently discarded when off
        """
        if text and self._think_enabled:
            self._addThinking.emit(text)
    
    @QtCore.Slot(str)
    def _on_add_thinking(self, text: str):
        """inmainthreadupdatethinkingcontent (slotfunction) """
        if not getattr(self, '_is_running', False):
            return  # Agent stopped, ignorelatencytoreach signal
        try:
            resp = self._agent_response or self._current_response
            if resp:
                resp.add_thinking(text)
                # ★ first timethinkingcontent → startinputboxonwaythinkingrefershowitem
                if hasattr(self, 'thinking_bar') and not self.thinking_bar.isVisible():
                    self.thinking_bar.start()
            self._scroll_agent_to_bottom(force=False)
        except RuntimeError:
            pass  # widget alreadyis clear destroy

    def _on_add_status(self, text: str):
        try:
            resp = self._agent_response or self._current_response
            if resp:
                resp.add_status(text)
                self._scroll_agent_to_bottom(force=False)
        except RuntimeError:
            pass  # widget alreadyis clear destroy

    def _on_update_thinking(self):
        try:
            resp = self._agent_response or self._current_response
            if resp:
                resp.update_thinking_time()
                # ★ syncupdateinputboxonwaythinkingrefershowitem whenbetween
                if hasattr(self, 'thinking_bar') and self.thinking_bar.isVisible():
                    if resp._has_thinking:
                        self.thinking_bar.set_elapsed(resp.thinking_section._total_elapsed())
        except RuntimeError:
            pass  # widgetmayalreadydestroy

    def _cook_displayed_nodes_if_manual(self):
        """★ in Manual protectmodebelow, forcurrentworksection  display nodedoneedleforproperty cook
        
        v1.4.4 fix: Agent runduringplacein Manual modewhen, modifytoolnottrigger cook, 
        causesreadtool (get_network_structure, check_errors etc.) return stale data, 
        AI may incorrectly assume the operation had no effect.
        
        strategy: only cook current /obj beloweach geo contain inset Display Flag  node. 
        This is a minimal-range cook that refreshes only the data the AI cares about, without triggering a full scene cook.
        """
        if getattr(self, '_pre_agent_update_mode', None) is None:
            return  # notin Agent cook protectmodebelow, noneedsprocess
        try:
            import hou  # type: ignore
            if hou.updateModeSetting() != hou.updateMode.Manual:
                return  # currentno Manual mode, noneedsprocess
            
            # collectsetallneeds cook   display node
            cooked = 0
            for child in hou.node('/obj').children():
                # onlyprocess geo typecontain  (SOP network) 
                if child.type().name() not in ('geo', 'subnet'):
                    continue
                try:
                    display_node = child.displayNode()
                    if display_node is not None:
                        display_node.cook(force=True)
                        cooked += 1
                except Exception:
                    pass  # singlenode cook failednotshadowrespondother
            if cooked:
                _dbg(f"[Cook Guard] Manual-mode targeted cook: {cooked} display node(s)")
        except Exception as e:
            _dbg(f"[Cook Guard] Targeted cook failed: {e}")

    def _restore_update_mode(self):
        """★ restore Houdini updatemode (Agent end/error/stopwhencall) 
        
        v1.4.3 Cook protectstrategy: 
        Agent runduring, modifytoolwillwill Houdini switchas Manual modebyprevent
        cook blockmainthread. Agent endafterinthisstatsonerestoreuseroriginal updatemode, 
        thiswhen Houdini willautotriggeronce cook expandshowfinalresult. 
        """
        _user_mode = getattr(self, '_pre_agent_update_mode', None)
        if _user_mode is not None:
            try:
                import hou  # type: ignore
                hou.setUpdateMode(_user_mode)
            except Exception:
                pass
            self._pre_agent_update_mode = None
    
    def _on_agent_done(self, result: dict):
        # ★ Hook: on_session_end
        self._fire_session_hook('on_session_end', self._agent_session_id or self._session_id)
        
        # ★ restore Houdini updatemode & clearremovemainthreadbusymark
        self._main_thread_busy = False
        self._restore_update_mode()
        
        # ★ stopthinkingrefershowitem
        try:
            self.thinking_bar.stop()
        except (RuntimeError, AttributeError):
            pass

        # Use the agent-anchored reference (the session may have switched away)
        resp = self._agent_response or self._current_response
        history = self._agent_history if self._agent_history is not None else self._conversation_history
        stats = self._agent_token_stats or self._token_stats
        
        # flushnewlabelparsebuffersectionresidualremainingcontent
        if self._tag_parse_buf:
            if self._in_think_block:
                if self._think_enabled:
                    self._addThinking.emit(self._tag_parse_buf)
                # Think closewhensilentdiscardresidualremainingthinkingcontent
            else:
                self._emit_normal_content(self._tag_parse_buf)
            self._tag_parse_buf = ""
            self._in_think_block = False

        # Flush the output buffer (ensures the last content isn't lost)
        if hasattr(self, '_output_buffer') and self._output_buffer:
            self._on_append_content(self._output_buffer)
            self._output_buffer = ""
        
        try:
            if resp:
                # ★ Post-process: auto-resolve bare node names to full paths (prevents the AI from forgetting path conventions in long context)
                if resp._content:
                    resp._content = self._resolve_bare_node_names(resp._content)
                resp.finalize()
        except RuntimeError:
            resp = None  # widget alreadyis clear destroy, skip UI operation
        
        # ================================================================
        # Cursor style: savenativemessagechaintoconversationhistory
        # ================================================================
        # format: assistant(tool_calls) → tool → ... → assistant(reply)
        # completekeeptoolcallchainand AI reply, notdoanycompress
        # onlyhassystemlevelcontextmanage (_manage_context / _progressive_trim) only theninexceedlimitwhencompress
        
        tool_calls_history = result.get('tool_calls_history', [])
        new_messages = result.get('new_messages', [])
        
        # 1. addtoolsubmitmutualchain (native OpenAI format) 
        # new_messages packagecontaining: assistant(tool_calls) + tool(results) + ...
        # ★ onlyaddinbetweenroundtime (with tool_calls   assistant and tool reply) , 
        #   final puretext assistant replybybelowfacestep 2 statsonebuild, avoidduplicate
        if new_messages:
            for nm in new_messages:
                clean = nm.copy()
                clean.pop('reasoning_content', None)  # inferencemodeldedicateduse, notneedspersistentization
                # skiplastoneitempuretext assistant message (nothas tool_calls  ) , 
                # itwillinstep 2 inas final_msg add
                if nm is new_messages[-1] and nm.get('role') == 'assistant' and not nm.get('tool_calls'):
                    continue
                history.append(clean)
        
        # 2. extractandaddfinal AI reply
        # preferreduse final_content (lastoneround puretext) , itstimefrom new_messages extract
        final_content = result.get('final_content', '')
        if not final_content or not final_content.strip():
            # final_content asempty → tryfrom new_messages inextractlastonehas content   assistant message
            for nm in reversed(new_messages):
                if nm.get('role') == 'assistant' and nm.get('content'):
                    c = nm['content']
                    # godrop think labelafterstillhascontent? 
                    stripped = re.sub(r'<think>[\s\S]*?</think>', '', c).strip()
                    if stripped:
                        final_content = c
                        break
            # stillthenasempty → fall backto full_content
            if not final_content or not final_content.strip():
                final_content = result.get('content', '')
        
        thinking_text = ""
        clean_content = ""
        if final_content:
            thinking_parts = re.findall(r'<think>([\s\S]*?)</think>', final_content)
            thinking_text = '\n'.join(thinking_parts).strip() if thinking_parts else ''
            clean_content = re.sub(r'<think>[\s\S]*?</think>', '', final_content).strip()
            clean_content = self._strip_fake_tool_results(clean_content)
        # Native thinking protocol (no <think> tags): fetch the already-collected thinking from the UI widget
        if not thinking_text and resp and resp._has_thinking:
            try:
                ui_thinking = resp.thinking_section._thinking_text.strip()
                if ui_thinking:
                    thinking_text = ui_thinking
            except (AttributeError, RuntimeError):
                pass
        
        # Ensure history ends with an assistant message (maintains user↔assistant alternation)
        # onlyneedhascontentorhastoolsubmitmutual, allneedsoneitemfinal assistant message
        need_final = bool(clean_content) or bool(new_messages) or not history or history[-1].get('role') != 'assistant'
        if need_final:
            final_msg = {'role': 'assistant', 'content': clean_content or tr('ai.no_content')}
            if thinking_text:
                final_msg['thinking'] = thinking_text
            # extract shell executerecord, forhistoryrestorewhenrebuild Shell collapsepanel
            py_shells = []
            sys_shells = []
            for tc in tool_calls_history:
                tn = tc.get('tool_name', '')
                ta = tc.get('arguments', {})
                tc_result = tc.get('result', {})
                if tn == 'execute_python' and ta.get('code'):
                    py_shells.append({
                        'code': ta['code'],
                        'output': tc_result.get('result', ''),
                        'error': tc_result.get('error', ''),
                        'success': bool(tc_result.get('success')),
                    })
                elif tn == 'execute_shell' and ta.get('command'):
                    sys_shells.append({
                        'command': ta['command'],
                        'output': tc_result.get('result', ''),
                        'error': tc_result.get('error', ''),
                        'success': bool(tc_result.get('success')),
                        'cwd': ta.get('cwd', ''),
                    })
            if py_shells:
                final_msg['python_shells'] = py_shells
            if sys_shells:
                final_msg['system_shells'] = sys_shells
            history.append(final_msg)
        
        # managecontext
        self._manage_context()
        
        # Update token stats (accumulate into the agent's owning session stats) — aligned with Cursor
        usage = result.get('usage', {})
        new_call_records = result.get('call_records', [])
        if usage:
            stats['input_tokens'] += usage.get('prompt_tokens', 0)
            stats['output_tokens'] += usage.get('completion_tokens', 0)
            stats['reasoning_tokens'] = stats.get('reasoning_tokens', 0) + usage.get('reasoning_tokens', 0)
            stats['cache_read'] += usage.get('cache_hit_tokens', 0)
            stats['cache_write'] += usage.get('cache_miss_tokens', 0)
            stats['total_tokens'] += usage.get('total_tokens', 0)
            stats['requests'] += 1
            
            # computethistimecostuseandaccumulate
            from morfyai.utils.token_optimizer import calculate_cost
            model_name = self.model_combo.currentText()
            this_cost = calculate_cost(
                model=model_name,
                input_tokens=usage.get('prompt_tokens', 0),
                output_tokens=usage.get('completion_tokens', 0),
                cache_hit=usage.get('cache_hit_tokens', 0),
                cache_miss=usage.get('cache_miss_tokens', 0),
                reasoning_tokens=usage.get('reasoning_tokens', 0),
            )
            stats['estimated_cost'] = stats.get('estimated_cost', 0.0) + this_cost
        
        # merge call_records
        if new_call_records:
            if not hasattr(self, '_call_records'):
                self._call_records = []
            self._call_records.extend(new_call_records)
        
        # ifcurrentshow justis agent session, update UI
        if usage:
            if not self._agent_session_id or self._agent_session_id == self._session_id:
                self._update_token_stats_display()
            
            cache_hit = usage.get('cache_hit_tokens', 0)
            cache_miss = usage.get('cache_miss_tokens', 0)
            cache_rate = usage.get('cache_hit_rate', 0)
            
            if cache_hit > 0 or cache_miss > 0:
                rate_percent = cache_rate * 100
                self._addStatus.emit(f"Cache: {cache_hit}/{cache_hit+cache_miss} ({rate_percent:.0f}%)")
        
        # ★ reflectionhook: taskcompleteaftertriggerlong-termmemoryreflection (backgroundthread, notblock UI) 
        if self._is_memory_active() and tool_calls_history:
            # get agent_params (fromrecent  _run_agent callinsave) 
            _reflect_params = getattr(self, '_last_agent_params', {})
            def _do_reflect():
                self._reflect_after_task(result, _reflect_params)
            reflect_thread = threading.Thread(target=_do_reflect, daemon=True)
            reflect_thread.start()
        
        # autosavecache (mustin _set_running(False) before, becausethiswhen agent referencestillvalid) 
        agent_sid = self._agent_session_id
        if self._auto_save_cache and len(history) > 0 and agent_sid:
            # temporarywhenwill history syncto sessions dict, againsave
            if agent_sid in self._sessions:
                self._sessions[agent_sid]['conversation_history'] = history
                self._sessions[agent_sid]['token_stats'] = stats
            # If the currently displayed session is exactly the agent's session, save directly
            if agent_sid == self._session_id:
                self._save_cache()
            else:
                # notincurrent session on, write session dicti.e.can (belowtimeswitchbackcomewhenagainsave) 
                pass
        
        self._set_running(False)
        
        # hidetoolstate
        self._hideToolStatus.emit()
        
        # updatecontextstatistics
        self._update_context_stats()
        
        # ★ Async-generate the session title (only on the first agent completion)
        self._maybe_generate_title(agent_sid, history)

    def _on_agent_error(self, error: str):
        # ★ restore Houdini updatemode & clearremovemainthreadbusymark
        self._main_thread_busy = False
        self._restore_update_mode()
        # stopthinkingrefershowitem
        try:
            self.thinking_bar.stop()
        except (RuntimeError, AttributeError):
            pass
        # flushnewoutputbuffersection
        if hasattr(self, '_output_buffer') and self._output_buffer:
            self._on_append_content(self._output_buffer)
            self._output_buffer = ""
        
        resp = self._agent_response or self._current_response
        try:
            if resp:
                resp.finalize()
                resp.add_status(f"Error: {error}")
        except RuntimeError:
            pass  # widget alreadyis clear destroy
        
        # ★ Ensure history ends with assistant (prevents consecutive user messages breaking structure)
        self._ensure_history_ends_with_assistant(f"[Error] {error}")
        
        self._set_running(False)

    def _on_agent_stopped(self):
        # ★ restore Houdini updatemode & clearremovemainthreadbusymark
        self._main_thread_busy = False
        self._restore_update_mode()
        # stopthinkingrefershowitem
        try:
            self.thinking_bar.stop()
        except (RuntimeError, AttributeError):
            pass
        # flushnewoutputbuffersection
        if hasattr(self, '_output_buffer') and self._output_buffer:
            self._on_append_content(self._output_buffer)
            self._output_buffer = ""
        
        resp = self._agent_response or self._current_response
        try:
            if resp:
                resp.finalize()
                resp.add_status("Stopped")
        except RuntimeError:
            pass  # widget alreadyis clear destroy
        
        # ★ Ensure history ends with assistant (prevents consecutive user messages breaking structure)
        self._ensure_history_ends_with_assistant("[Stopped by user]")
        
        self._set_running(False)
        self._hideToolStatus.emit()
    
    def _ensure_history_ends_with_assistant(self, fallback_content: str):
        """ensure conversation_history by assistant messageend
        
        when agent outwrongorisinbreakwhen, usermessagealreadyappendbutnothasforshould  assistant reply, 
        This would break the user↔assistant alternation and cause the next API call to fail.
        """
        history = self._agent_history if self._agent_history is not None else self._conversation_history
        if history and history[-1].get('role') == 'user':
            history.append({'role': 'assistant', 'content': fallback_content})

    # ---------- toolexecutestate ----------

    def _on_update_todo(self, todo_id: str, text: str, status: str):
        """update Todo list (followconversationstreamwithinassociateshow) 
        
        use agent anchorfixed  todo_list / chat_layout, preventswitchsessionafter
        writeerror window. 
        """
        try:
            # Prefer the agent-anchored target (session A running is not affected by session B)
            todo = self._agent_todo_list or self.todo_list
            layout = self._agent_chat_layout or self.chat_layout
            if not todo:
                return
            # ensure todo_list alreadyinforshould chat_layout in
            self._ensure_todo_in_chat(todo, layout)
        except RuntimeError:
            return  # widget alreadyis clear destroy
        if text:
            todo.add_todo(todo_id, text, status)
        else:
            todo.update_todo(todo_id, status)

    def _execute_tool_with_todo(self, tool_name: str, **kwargs) -> dict:
        """executetool, packagecontaining Todo related tool
        
        note: thismethodinbackgroundthreadcall, Houdini operationmustviasignaladjustdegreetomainthreadexecute. 
        notdepend on hou module tool (execute_shell etc.) directlyinbackgroundthreadexecute, avoidblock UI. 
        """
        # ★ Stop detection: return immediately when the user requests stop; don't queue new tools
        if self.client.is_stop_requested():
            return {"success": False, "error": "User requested stop"}
        
        # ★ mainthreadbusyprotect: ifononetooltimeoutandmainthreadstillin cook, 
        #   notagainpile upnew BlockingQueuedConnection signal (avoiddeadlock) 
        if getattr(self, '_main_thread_busy', False):
            if tool_name not in self._BG_SAFE_TOOLS:
                return {
                    "success": False,
                    "error": "Main thread is busy (likely a long-running computation). "
                            "Please retry once it finishes, or press Stop to interrupt."
                }
        
        # ★ Ask-mode safety guard: intercept any tool not on the whitelist
        if not self._agent_mode and not self._plan_mode and tool_name not in self._ASK_MODE_TOOLS:
            # extracheck ToolRegistry (plugin/Skill toolmayregister ask mode) 
            _ask_allowed = False
            try:
                from ..utils.tool_registry import get_tool_registry
                _meta = get_tool_registry()._tools.get(tool_name)
                if _meta and _meta.enabled and "ask" in _meta.modes:
                    _ask_allowed = True
            except Exception:
                pass
            if not _ask_allowed:
                return {
                    "success": False,
                    "error": tr('ask.restricted', tool_name)
                }
        
        # ★ Plan-mode planning-stage safety guard
        if self._plan_mode and self._plan_phase == 'planning':
            allowed = self._PLAN_PLANNING_TOOLS | {'create_plan'}
            if tool_name not in allowed:
                # extracheck ToolRegistry (plugin/Skill toolmayregister plan_planning mode) 
                _plan_allowed = False
                try:
                    from ..utils.tool_registry import get_tool_registry
                    _meta = get_tool_registry()._tools.get(tool_name)
                    if _meta and _meta.enabled and "plan_planning" in _meta.modes:
                        _plan_allowed = True
                except Exception:
                    pass
                if not _plan_allowed:
                    return {
                        "success": False,
                        "error": f"Plan planning phase does not allow {tool_name}. Only query tools and create_plan are permitted."
                    }
        
        # ★ confirmmode: forkeynodeoperationpopupoutpreviewconfirm
        if self._confirm_mode and tool_name in self._CONFIRM_TOOLS:
            confirmed = self._request_tool_confirmation(tool_name, kwargs)
            if not confirmed:
                return {
                    "success": False,
                    "error": tr('ask.user_cancel', tool_name)
                }
        
        # ★ showtoolexecutestate
        self._showToolStatus.emit(tool_name)
        
        try:
            # ★ Plan modededicatedusetoolprocess
            if tool_name == "create_plan":
                return self._handle_create_plan(kwargs)
            
            elif tool_name == "update_plan_step":
                return self._handle_update_plan_step(kwargs)
            
            elif tool_name == "ask_question":
                return self._handle_ask_question(kwargs)
            
            # process Todo relatedtool (pure Python operation, threadsafe) 
            if tool_name == "add_todo":
                todo_id = kwargs.get("todo_id", "")
                text = kwargs.get("text", "")
                status = kwargs.get("status", "pending")
                self._updateTodo.emit(todo_id, text, status)
                return {"success": True, "result": f"Added todo: {text}"}
            
            elif tool_name == "update_todo":
                todo_id = kwargs.get("todo_id", "")
                status = kwargs.get("status", "done")
                self._updateTodo.emit(todo_id, "", status)
                return {"success": True, "result": f"Updated todo {todo_id} to {status}"}
            
            elif tool_name == "verify_and_summarize":
                # needsinmainthreadexecute Houdini operation
                return self._execute_tool_in_main_thread(tool_name, kwargs)
            
            # notdepend on hou  tool → directlyinbackgroundthreadexecute (avoidblock UI) 
            if tool_name in self._BG_SAFE_TOOLS:
                return self._execute_tool_in_bg(tool_name, kwargs)
            
            # othertoolneedsinmainthreadexecute (Houdini hou moduleoperation) 
            return self._execute_tool_in_main_thread(tool_name, kwargs)
        finally:
            self._hideToolStatus.emit()
    
    def _execute_tool_in_bg(self, tool_name: str, kwargs: dict) -> dict:
        """inbackgroundthreaddirectlyexecutetool (notblock UI mainthread) 
        
        onlyused fornotdepend on hou module tool, such as execute_shell, search_local_doc etc.. 
        """
        try:
            return self.mcp.execute_tool(tool_name, kwargs)
        except Exception as e:
            import traceback
            return {"success": False, "error": tr('ai.bg_exec_err', f"{e}\n{traceback.format_exc()[:300]}")}
    
    # mainthreadtoolexecutetimeout (second) 
    # Modify operations can trigger a Houdini cook; needs enough timeout
    _TOOL_MAIN_THREAD_TIMEOUT = 120.0

    def _execute_tool_in_main_thread(self, tool_name: str, kwargs: dict) -> dict:
        """inmainthreadexecutetool (thread-safe)
        
        use BlockingQueuedConnection + Queue ensure: 
        1. Houdini operations run on the main thread (the hou module is not thread-safe; macOS is especially strict)
        2. multitoolcallnotwillcompetition
        3. resultsafepassdelivercallbackusethread
        
        ★ macOS crash-fix note:
        Houdini embed Qt when, macOS   Cocoa eventloopcompare Windows morestrict. 
        all hou API callmustinmainthreadexecute, otherwisewillcausessegmenterroror EXC_BAD_ACCESS. 
        BlockingQueuedConnection guaranteesignalintargetthread (mainthread)  eventloopinexecute, 
        and emit willblockcallthreaddirecttoslotfunctionreturn, realnowthreadsafe synccall. 
        
        ★ Deadlock-prevention mechanism (v1.4.3):
        when Houdini cook consumewhencausestimeoutafter, mark _main_thread_busy, 
        blockaftercontinuetoolcallpile up BlockingQueuedConnection signal (avoiddeadlock) . 
        mainthreadslotfunctionexecutefinishfinishafterautoclearremovemark. 
        """
        # uselockensureonceonlyhasonetoolcall (avoidandsendcompetition) 
        with self._tool_lock:
            # clearemptyqueue (preventresidualkeepdata) 
            while not self._tool_result_queue.empty():
                try:
                    self._tool_result_queue.get_nowait()
                except queue.Empty:
                    break
            
            # sendsignaltomainthreadexecute
            # BlockingQueuedConnection willblockdirecttoslotfunctionexecutecomplete
            self._executeToolRequest.emit(tool_name, kwargs)
            
            # fromqueuegetresult (hastimeoutprotect) 
            # ★ timeoutsetas 120s, becausesome Houdini operation (such ascreatecomplexnode, cook highfacecountmodel) 
            #   May need significant time. After timeout, mark the main thread busy to prevent signal pile-up.
            try:
                result = self._tool_result_queue.get(timeout=self._TOOL_MAIN_THREAD_TIMEOUT)
                # mainthreadnormalreturn → clearremovebusymark
                self._main_thread_busy = False
                return result
            except queue.Empty:
                # ★ timeout: mainthreadmaystillinexecute cook, markasbusy
                self._main_thread_busy = True
                _dbg(f"[⚠️ TIMEOUT] Tool {tool_name} main-thread exec timed out "
                      f"({self._TOOL_MAIN_THREAD_TIMEOUT}s). "
                      f"Houdini may be running a long computation. Subsequent tool calls will be paused.")
                return {
                    "success": False,
                    "error": f"Operation timed out ({int(self._TOOL_MAIN_THREAD_TIMEOUT)}s): Houdini main thread is likely busy (e.g. cook/render). "
                             f"Tool {tool_name} is still running in the background — wait for it to finish or press Stop to interrupt."
                }

    def _execute_tools_batch_in_main_thread(self, batch: list) -> list:
        """Batch-execute read-only tools on the main thread (reduce N signal round-trips to 1).

        Args:
            batch: [(tool_name, kwargs), ...]

        Returns:
            [result_dict, ...] (with batch orderorderconsistent) 
        """
        with self._tool_lock:
            while not self._tool_result_queue.empty():
                try:
                    self._tool_result_queue.get_nowait()
                except queue.Empty:
                    break

            self._executeToolBatchRequest.emit(batch)

            try:
                results = self._tool_result_queue.get(timeout=60.0)
                return results if isinstance(results, list) else [results]
            except queue.Empty:
                return [{"success": False, "error": tr('ai.main_exec_timeout')}] * len(batch)

    def _on_execute_tool_batch_main_thread(self, batch: list):
        """inmainthreadbatchexecuteread-onlytool slotfunction

        All tools run on the main thread in order (they are fast read-only queries),
        thenafterwillresultlistoncepropertyputenterqueuereturngivecallthread. 
        """
        # ★ Pre-read cook (v1.4.4): batch reads also need to ensure data freshness
        needs_cook = any(tn in self._COOK_BEFORE_READ_TOOLS for tn, _ in batch)
        if needs_cook:
            self._cook_displayed_nodes_if_manual()
        
        results = []
        for tool_name, kwargs in batch:
            try:
                result = self.mcp.execute_tool(tool_name, kwargs)
            except Exception as e:
                result = {"success": False, "error": str(e)}
            results.append(result)
        self._tool_result_queue.put(results)
    
    # ------------------------------------------------------------------
    # Plan modetoolprocess
    # ------------------------------------------------------------------

    def _handle_create_plan(self, kwargs: dict) -> dict:
        """process create_plan toolcall (backgroundthread) """
        try:
            if self._plan_manager is None:
                self._plan_manager = get_plan_manager()
            plan_data = self._plan_manager.create_plan(self._session_id, kwargs)
            self._plan_phase = 'awaiting_confirmation'
            # switchstate: Planning → Generating (Plan completedbuild) 
            self._showGenerating.emit()
            # viasignalinmainthreadrender PlanViewer card
            self._renderPlanViewer.emit(plan_data)
            return {
                "success": True,
                "result": f"Plan '{plan_data.get('title', '')}' created with {len(plan_data.get('steps', []))} steps. Waiting for user confirmation."
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create plan: {e}"}

    def _handle_update_plan_step(self, kwargs: dict) -> dict:
        """process update_plan_step toolcall (backgroundthread) """
        try:
            if self._plan_manager is None:
                self._plan_manager = get_plan_manager()
            step_id = kwargs.get('step_id', '')
            status = kwargs.get('status', 'done')
            result_summary = kwargs.get('result_summary', '')
            plan = self._plan_manager.update_step(
                self._session_id, step_id, status, result_summary
            )
            if not plan:
                return {"success": False, "error": f"No active plan found for session {self._session_id}"}
            # viasignalinmainthreadupdate PlanViewer stepstate
            self._updatePlanStep.emit(step_id, status, result_summary or '')
            # checkwhetherallpartcomplete
            all_steps = plan.get('steps', [])
            done_count = sum(1 for s in all_steps if s.get('status') == 'done')
            error_count = sum(1 for s in all_steps if s.get('status') == 'error')
            total = len(all_steps)
            
            if plan.get('status') == 'completed':
                self._plan_phase = 'completed'
                return {
                    "success": True,
                    "result": f"Step {step_id} updated to '{status}'. Plan complete! ({done_count}/{total} done, {error_count} errors)"
                }
            
            # Return progress info so the AI knows how many steps remain
            pending_steps = [s for s in all_steps if s.get('status') == 'pending']
            next_step_info = ""
            if pending_steps:
                ns = pending_steps[0]
                next_step_info = f" Next: {ns['id']} \"{ns.get('title', ns.get('description', ns['id']))}\""
            
            return {
                "success": True,
                "result": f"Step {step_id} updated to '{status}'. Progress: {done_count}/{total} done.{next_step_info}"
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to update plan step: {e}"}

    def _handle_ask_question(self, kwargs: dict) -> dict:
        """process ask_question toolcall (backgroundthread) 
        
        recoveruse _request_tool_confirmation  blockmode: 
        1. Set pending attribute → emit signal → main thread renders AskQuestionCard
        2. backgroundthreadin queue onblocketc.pendinguseranswer
        3. userraisesubmitafter queue.put(answers) → backgroundthreadresume
        """
        questions = kwargs.get('questions', [])
        if not questions:
            return {"success": False, "error": "No questions provided"}

        self._ask_question_result_queue = queue.Queue()
        self._pending_ask_questions = questions
        self._askQuestionRequest.emit()

        try:
            result = self._ask_question_result_queue.get(timeout=300.0)  # 5-minute timeout
            if result is None:
                return {"success": True, "result": "User skipped the questions."}
            # Format the answer as human-readable text
            answer_lines = []
            for q_id, selections in result.items():
                readable = []
                for sel in selections:
                    if sel.startswith("__free_text__:"):
                        readable.append(sel.replace("__free_text__:", ""))
                    else:
                        readable.append(sel)
                answer_lines.append(f"{q_id}: {', '.join(readable)}")
            return {
                "success": True,
                "result": f"User answered:\n" + "\n".join(answer_lines)
            }
        except queue.Empty:
            return {"success": True, "result": "User did not answer within the time limit."}

    @QtCore.Slot()
    def _on_render_ask_question(self):
        """mainthread: inchatstreamininsert AskQuestionCard"""
        q = getattr(self, '_ask_question_result_queue', None)
        questions = getattr(self, '_pending_ask_questions', [])

        if not q:
            _dbg("[AskQuestion] ⚠ _ask_question_result_queue missing")
            return

        try:
            card = AskQuestionCard(questions, parent=self.chat_container)
        except Exception as e:
            _dbg(f"[AskQuestion] ✖ AskQuestionCard creation failed: {e}")
            q.put(None)
            return

        def _on_answered(answers: dict):
            q.put(answers)

        def _on_cancelled():
            q.put(None)

        card.answered.connect(_on_answered)
        card.cancelled.connect(_on_cancelled)

        # inserttoconversationstream
        try:
            self.chat_layout.insertWidget(self.chat_layout.count() - 1, card)
        except Exception as e:
            _dbg(f"[AskQuestion] ⚠ Insert failed: {e}")
            q.put(None)
            return

        card.setVisible(True)
        try:
            self._scroll_to_bottom(force=True)
        except Exception:
            pass

    @QtCore.Slot(dict)
    def _show_plan_generation_progress(self, accumulated: str):
        """from create_plan  streamingparameterinextractprogressinfoandshow Planning... state"""
        import re as _re
        # statisticsalreadyoutnow  step id
        step_ids = _re.findall(r'"id"\s*:\s*"(step-\d+)"', accumulated)
        # tryextract title
        title_match = _re.search(r'"title"\s*:\s*"([^"]{1,30})', accumulated)
        title_part = title_match.group(1) if title_match else ""

        # checkwhetheralreadyenter architecture partpart
        has_arch = '"architecture"' in accumulated
        arch_nodes = _re.findall(r'"id"\s*:\s*"(?!step-)([^"]+)"', accumulated)

        if has_arch and arch_nodes:
            progress = f"architecture ({len(arch_nodes)} nodes)"
        elif step_ids:
            progress = f"step {len(step_ids)}"
            if title_part:
                progress = f"{title_part!r} {progress}"
        elif title_part:
            progress = f"{title_part!r}"
        else:
            progress = ""

        self._showPlanning.emit(progress)

    @QtCore.Slot()
    def _on_create_streaming_plan(self):
        """mainthread: createstreaming Plan previewcardandinsertchatstream"""
        try:
            # ifalreadyhasoldstreamingcardthenfirstremove
            if self._streaming_plan_card is not None:
                self._streaming_plan_card.setParent(None)
                self._streaming_plan_card.deleteLater()

            card = StreamingPlanCard(parent=self.chat_container)
            self._streaming_plan_card = card
            self.chat_layout.insertWidget(self.chat_layout.count() - 1, card)
            self._scroll_to_bottom(force=True)
        except Exception as e:
            _dbg(f"[Plan] Create streaming card error: {e}")

    @QtCore.Slot(str)
    def _on_update_streaming_plan(self, accumulated: str):
        """Main thread: incrementally render streaming JSON fragments into the streaming Plan card.

        usesimple sectionstreamstrategy: cachelatestdata, via singleShot latencyprocess, 
        avoideach token alltriggerpositivethenparseand UI update. 
        """
        self._streaming_plan_acc = accumulated
        if not getattr(self, '_streaming_plan_timer_active', False):
            self._streaming_plan_timer_active = True
            QtCore.QTimer.singleShot(150, self._flush_streaming_plan)

    def _flush_streaming_plan(self):
        """realboundaryexecutestreaming Plan cardupdate"""
        self._streaming_plan_timer_active = False
        if self._streaming_plan_card is None:
            return
        acc = getattr(self, '_streaming_plan_acc', '')
        if not acc:
            return
        try:
            old_count = self._streaming_plan_card._rendered_step_count
            self._streaming_plan_card.update_from_accumulated(acc)
            new_count = self._streaming_plan_card._rendered_step_count
            if new_count > old_count:
                self._scroll_to_bottom()
        except Exception as e:
            _dbg(f"[Plan] Update streaming card error: {e}")

    def _on_render_plan_viewer(self, plan_data: dict):
        """mainthread: willstreaming Plan cardoriginalplaceupgradeascompletesubmitmutualcard. 

        ifstreamingcardalreadysavein → finalize_with_data originalplacesupplementfillcompletedata. 
        If it does not exist (edge case) → create a new card.
        """
        try:
            if self._streaming_plan_card is not None:
                # ★ Upgrade in place: fill DAG + buttons onto the streaming skeleton
                card = self._streaming_plan_card
                card.finalize_with_data(plan_data)
                card.planConfirmed.connect(self._on_plan_confirmed)
                card.planRejected.connect(self._on_plan_rejected)
                self._active_plan_viewer = card
                self._streaming_plan_card = None  # notagaintraceasstreamingcard
            else:
                # Edge case: no streaming card present — create PlanViewer directly
                viewer = PlanViewer(plan_data, parent=self.chat_container)
                viewer.planConfirmed.connect(self._on_plan_confirmed)
                viewer.planRejected.connect(self._on_plan_rejected)
                self._active_plan_viewer = viewer
                self.chat_layout.insertWidget(self.chat_layout.count() - 1, viewer)
            self._scroll_to_bottom(force=True)
        except Exception as e:
            _dbg(f"[Plan] Render PlanViewer error: {e}")

    @QtCore.Slot(str, str, str)
    def _on_update_plan_step(self, step_id: str, status: str, result_summary: str):
        """mainthread: update PlanViewer cardin stepstate"""
        if self._active_plan_viewer:
            try:
                self._active_plan_viewer.update_step_status(step_id, status, result_summary)
            except Exception as e:
                _dbg(f"[Plan] Update step UI error: {e}")

    def _on_plan_confirmed(self, plan_data: dict):
        """userclick Confirm button → startexecutestage"""
        self._plan_phase = 'executing'
        # disable PlanViewer button (preventduplicateclick) 
        if self._active_plan_viewer:
            self._active_plan_viewer.set_confirmed()
        
        # constructexecutehintmessage
        exec_msg = tr('ai.plan_confirmed_msg', plan_data.get('title', 'Plan'))
        self._conversation_history.append({
            'role': 'user', 'content': exec_msg
        })
        
        # createnew AI replyblock
        self._set_running(True)
        self._add_ai_response()
        self._agent_response = self._current_response
        self._start_active_aurora()
        
        # construct agent_params (recoveruseontime  provider/model set) 
        agent_params = getattr(self, '_last_agent_params', {}).copy()
        agent_params['use_agent'] = True          # executestageusecompletetool
        agent_params['plan_mode'] = True
        agent_params['plan_executing'] = True     # markas Plan executestage
        agent_params['plan_data'] = plan_data
        
        # backgroundthreadexecute
        thread = threading.Thread(
            target=self._run_agent, args=(agent_params,), daemon=True
        )
        thread.start()

    def _on_plan_rejected(self):
        """userclick Reject button → discard Plan"""
        self._plan_phase = 'idle'
        try:
            if self._plan_manager is None:
                self._plan_manager = get_plan_manager()
            self._plan_manager.delete_plan(self._session_id)
        except Exception:
            pass
        if self._active_plan_viewer:
            self._active_plan_viewer.set_rejected()
        self._active_plan_viewer = None

    # Self-tracking checkpoint tool (handled in a dedicated branch inside _on_add_node_operation)
    _SELF_TRACKING_TOOLS = frozenset({
        'create_node', 'create_nodes_batch', 'create_wrangle_node',
        'delete_node', 'set_node_parameter',
    })

    @staticmethod
    def _snapshot_network_children() -> dict:
        """snapshotcurrentnetwork subnodelist {path: {name, type, path}}"""
        try:
            import hou  # type: ignore
            network = None
            try:
                editor = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.NetworkEditor)
                if editor:
                    network = editor.pwd()
            except Exception:
                pass
            if not network:
                network = hou.node('/obj/geo1') or hou.node('/obj')
            if not network:
                return {}
            return {
                node.path(): {
                    'name': node.name(),
                    'type': node.type().name(),
                    'path': node.path(),
                }
                for node in network.children()
            }
        except Exception:
            return {}

    # ------------------------------------------------------------------
    #  afterprocess: autowill AI replyin barenodenameparseascompletepath
    # ------------------------------------------------------------------

    _NODE_PATH_RE = re.compile(r'/(?:obj|out|shop|stage|tasks|ch|mat|img)/[\w/]+')

    def _collect_node_paths_from_tool(self, result: dict, arguments: dict = None):
        """fromtoolexecute resultandparameterinextract Houdini node path, accumulateto _session_node_map. """
        import re
        paths: set[str] = set()

        # from result and arguments inusepositivethenextractallshapesuch as /obj/geo1/box1  path
        for source in (result, arguments):
            if not source:
                continue
            raw = json.dumps(source, default=str) if isinstance(source, dict) else str(source)
            paths.update(self._NODE_PATH_RE.findall(raw))

        # from _node_changes inextract
        node_changes = result.get('_node_changes') if isinstance(result, dict) else None
        if node_changes:
            for n in node_changes.get('created', []):
                if n.get('path'):
                    paths.add(n['path'])
            for n in node_changes.get('deleted', []):
                if n.get('path'):
                    paths.add(n['path'])

        # write _session_node_map: name → set[path]
        for p in paths:
            name = p.rsplit('/', 1)[-1]
            if name:
                self._session_node_map.setdefault(name, set()).add(p)

    def _resolve_bare_node_names(self, text: str) -> str:
        """will AI replyin barenodename (such as box1) autoreplaceswapascompletepath (such as /obj/geo1/box1) . 

        datacomesource: currentsessionin AI toolcallinvolveand node path (_session_node_map) . 
        saferule:
        - Only replace names that map to exactly **one and only one** path in the session (avoid cross-subnet ambiguity).
        - onlyprocessbycountcharacterend name (box1, scatter2) , avoiderrormatchregularEnglish word. 
        - skipcodeblock (```...``` and `...`) in content. 
        - skipalreadypassediscompletepathonepartpart name (previousfacehas /) . 
        - longnamepreferredreplaceswap, avoidsubstringconflict. 
        """
        if not text or not self._session_node_map:
            return text

        import re

        # Build name → path map (only short-suffix + unique-path names)
        name_to_path: dict[str, str] = {}
        for name, path_set in self._session_node_map.items():
            if len(path_set) == 1 and name and name[-1].isdigit():
                name_to_path[name] = next(iter(path_set))
        if not name_to_path:
            return text

        # bynamelengthlowerorderarrangecolumn (longnamepreferred, avoid "box1" errormatch "networkbox1"  substring) 
        sorted_names = sorted(name_to_path.keys(), key=len, reverse=True)

        # willtextsplitas codeblock / notcodeblock
        code_pattern = re.compile(r'(```[\s\S]*?```|`[^`\n]+`)')
        parts = code_pattern.split(text)

        for i, part in enumerate(parts):
            # skipcodeblocksnippet
            if part.startswith('`'):
                continue
            for name in sorted_names:
                full_path = name_to_path[name]
                # Negative lookbehind: must not be preceded by / or \w (already in a path or part of a longer name)
                # Negative lookahead: must not be followed by \w (part of a longer name)
                pat = r'(?<![/\w])' + re.escape(name) + r'(?!\w)'
                parts[i] = re.sub(pat, full_path, parts[i])

        return ''.join(parts)

    @staticmethod
    def _diff_network_children(before: dict, after: dict):
        """forcomparepreviousaftersubnodesnapshot, return {created: [...], deleted: [...]} or None"""
        before_paths = set(before.keys())
        after_paths = set(after.keys())
        created = [after[p] for p in sorted(after_paths - before_paths)]
        deleted = [before[p] for p in sorted(before_paths - after_paths)]
        if not created and not deleted:
            return None
        return {'created': created, 'deleted': deleted}

    # ★ willtrigger Houdini cook  toolset
    # thissometoolexecutewhenmaycausesconsumewhen scenecompute, needsspecialprotect
    _COOK_TRIGGERING_TOOLS = frozenset({
        'create_node', 'create_nodes_batch', 'create_wrangle_node',
        'connect_nodes', 'set_display_flag', 'set_node_parameter',
        'batch_set_parameters', 'execute_python', 'run_skill',
    })

    # ★ needsin Manual protectmodebelowdoneedleforproperty cook  readtool
    # thissometoolneedsreadnodelatestcomputeresult (geometry, errorstateetc.) , 
    # ifnot cook, AI willseeto stale datafromanderrordecideoperationresult
    _COOK_BEFORE_READ_TOOLS = frozenset({
        'get_network_structure', 'get_node_parameters', 'list_children',
        'check_errors', 'verify_and_summarize',
        'capture_viewport',  # screenshotpreviousneedsensuregeometryalready cook
    })

    @QtCore.Slot(str, dict)
    def _on_execute_tool_main_thread(self, tool_name: str, kwargs: dict):
        """inmainthreadexecutetool (slotfunction) 
        
        note: thismethodinmainthreadinexecute, directlyoperation Houdini API issafe . 
        allmodifyoperationpackagewrapin undo group in, supportonekeyundowhole Agent operation. 
        ★ forinnotselfwith checkpoint  modifytool, willinexecutepreviousaftersnapshotnetworksubnodebydetectchange. 
        
        ★ macOS threadsafedescription: 
        Houdini   hou modulenothreadsafe . macOS on Cocoa/AppKit needrequest UI and
        sceneoperationmustinmainthreadexecute, otherwisewillcauses EXC_BAD_ACCESS. 
        thismethodvia BlockingQueuedConnection signalfrombackgroundthreadtrigger, guaranteeinmainthreadexecute. 
        
        ★ Cook protect (v1.4.3) : 
        formaytrigger cook  modifytool, inexecuteprevioustemporarywhenswitchasmanualupdatemode, 
        executefinishfinishafterrestoreoriginalmode. thislike setDisplayFlag/connect etc.operationnotwill
        standi.e.triggerconsumewhen scene cook, avoidblockmainthreadcausesdeadlock. 
        """
        # ★ Main-thread assertion (debug helper: warns if executed off the main thread)
        _app = QtWidgets.QApplication.instance()
        if _app and _app.thread() != QtCore.QThread.currentThread():
            _dbg(f"[⚠️ THREAD SAFETY] _on_execute_tool_main_thread not running on main thread! "
                  f"tool={tool_name}, current_thread={QtCore.QThread.currentThread()}")
        
        result = {"success": False, "error": tr('ai.unknown_err')}
        
        # decidebreakwhetherasmodifyoperation (needs undo group) 
        _MUTATING_TOOLS = {
            "create_node", "create_nodes_batch", "create_wrangle_node",
            "delete_node", "set_node_parameter", "connect_nodes",
            "copy_node", "batch_set_parameters", "set_display_flag",
            "execute_python", "save_hip", "run_skill",
        }
        use_undo_group = tool_name in _MUTATING_TOOLS
        
        # ★ Cook protect (v1.4.3) : formaytrigger cook  tool, 
        # in Agent runduringkeep Manual mode, prevent cook blockmainthread
        # moderestorein Agent endwhenstatsoneprocess (_restore_update_mode) 
        if tool_name in self._COOK_TRIGGERING_TOOLS:
            try:
                import hou  # type: ignore
                if hou.updateModeSetting() != hou.updateMode.Manual:
                    hou.setUpdateMode(hou.updateMode.Manual)
            except Exception:
                pass
        
        # ★ readprevious Cook (v1.4.4) : when Agent placein Manual protectmodebelow, 
        # readtoolexecutepreviousfirstforcurrentshownodedoonceneedleforproperty cook, 
        # ensure AI canseetomodifyafter latestresult (andnot stale data) 
        if tool_name in self._COOK_BEFORE_READ_TOOLS:
            self._cook_displayed_nodes_if_manual()
        
        # ★ fornotselfwith checkpoint trace modifytool, do before/after snapshot
        should_snapshot = (
            tool_name in _MUTATING_TOOLS
            and tool_name not in self._SELF_TRACKING_TOOLS
            and tool_name != 'save_hip'  # save noneedssnapshot
        )
        before_children = self._snapshot_network_children() if should_snapshot else {}
        
        try:
            # formodifyoperationopenstart undo group
            if use_undo_group:
                try:
                    import hou  # type: ignore
                    hou.undos.beginGroup(f"AI Agent: {tool_name}")
                except Exception:
                    use_undo_group = False  # hou unavailablethenskip
            
            if tool_name == "verify_and_summarize":
                check_items = kwargs.get("check_items", [])
                expected = kwargs.get("expected_result", "")
                
                # ensure check_items islisttype (prevent unhashable type: 'slice' error) 
                if not isinstance(check_items, list):
                    if isinstance(check_items, str):
                        check_items = [check_items]
                    elif hasattr(check_items, '__iter__') and not isinstance(check_items, (dict, str)):
                        check_items = list(check_items)
                    else:
                        check_items = []
                
                # getcurrentnetworkstructureenterrowverify
                ok, structure_data = self.mcp.get_network_structure()
                
                # autodetectissue
                issues = []
                if ok and isinstance(structure_data, dict):
                    nodes = structure_data.get('nodes', [])
                    connections = structure_data.get('connections', [])
                    
                    # collectsetallalreadyconnect node
                    connected_nodes = set()
                    for conn in connections:
                        from_path = conn.get('from', '')
                        to_path = conn.get('to', '')
                        if from_path:
                            connected_nodes.add(from_path.split('/')[-1])
                        if to_path:
                            connected_nodes.add(to_path.split('/')[-1])
                    
                    # detectissue
                    for node in nodes:
                        node_name = node.get('name', '')
                        # detecterrornode
                        if node.get('has_errors'):
                            issues.append(tr('ai.err_issues', node_name))
                        # Detect orphan nodes (no output node and unconnected)
                        if node_name not in connected_nodes:
                            node_type = node.get('type', '').lower()
                            # Exclude output nodes and root nodes
                            if not any(x in node_type for x in ['output', 'null', 'out', 'merge']):
                                if not any(x in node_name.lower() for x in ['out', 'output', 'result']):
                                    issues.append(f"orphan:{node_name}")
                    
                    # checkwhetherhasshow outputnode
                    has_displayed = any(node.get('is_displayed') for node in nodes)
                    if not has_displayed and nodes:
                        issues.append(tr('ai.no_display'))
                
                # generateverifyresult
                if issues:
                    issues_str = ' | '.join(issues[:5])  # at mostshow5issue
                    result = {
                        "success": True,
                        "result": tr('ai.check_fail', issues_str)
                    }
                else:
                    check_items_str = ', '.join(str(item) for item in check_items[:3]) if check_items else tr('ai.check_none')
                    result = {
                        "success": True,
                        "result": tr('ai.check_pass', expected[:30] if expected else 'done')
                    }
            else:
                # othertoolsubmitgive MCP process
                result = self.mcp.execute_tool(tool_name, kwargs)
        except Exception as e:
            result = {"success": False, "error": tr('ai.tool_exec_err', str(e))}
        finally:
            # ★ executeaftersnapshot & diff, detectnodechange
            if should_snapshot and result.get("success"):
                try:
                    after_children = self._snapshot_network_children()
                    changes = self._diff_network_children(before_children, after_children)
                    if changes:
                        result['_node_changes'] = changes
                except Exception:
                    pass  # snapshotfailednotshadowrespondtoolresult

            # close undo group
            if use_undo_group:
                try:
                    import hou  # type: ignore
                    hou.undos.endGroup()
                except Exception:
                    pass

            # ★ Cook protectrestore: notinsingletool finally inrestoreupdatemode
            # andisin Agent endwhenstatsonerestore (_restore_update_mode) , 
            # avoidinbetweentoolrestoreaftertriggerconsumewhen cook blockmainthread

            # ★ clearremovemainthreadbusymark
            # Regardless of tool success/failure, the main thread is now idle
            self._main_thread_busy = False

            # ★ macOS crash fix: do NOT call processEvents() here
            # ─────────────────────────────────────────────────────
            # oldcode: QtWidgets.QApplication.processEvents()
            #
            # Why was it removed?
            # 1. thisslotfunctionvia BlockingQueuedConnection frombackgroundthreadtrigger, 
            #    in emit returnpreviousmainthreadeventloopnotwillprocessnewevent——thisissetcountintentdiagram. 
            # 2. processEvents() willinslotfunctionwithinpartrecursiveprocesseventqueue, maycauses: 
            #    a) recursivetriggeranother _executeToolRequest signal (deadlockorreenter) 
            #    b) trigger Houdini sceneevent, rendercallbacketc. (withcurrent hou operationcompetition) 
            #    c) macOS Cocoa runloop reentry causes EXC_BAD_ACCESS crash
            # 3. BlockingQueuedConnection returnafter, mainthreadeventloopselfthenwillresume
            #    process the event queue — no manual processEvents needed.
            # ─────────────────────────────────────────────────────

            # willresultputenterqueue (thread-safe)
            self._tool_result_queue.put(result)

    # ------------------------------------------------------------------
    # faketoolcalldetect
    # ------------------------------------------------------------------
    # allregister toolname (used fordetectfake) 
    _ALL_TOOL_NAMES = (
        'create_wrangle_node|get_network_structure'
        '|get_node_parameters|set_node_parameter|create_node|create_nodes_batch'
        '|connect_nodes|delete_node|search_node_types|semantic_search_nodes'
        '|list_children|read_selection|set_display_flag'
        '|copy_node|batch_set_parameters|find_nodes_by_param|save_hip|undo_redo'
        '|web_search|fetch_webpage|search_local_doc|get_houdini_node_doc'
        '|execute_python|execute_shell|check_errors|get_node_inputs|add_todo|update_todo'
        '|verify_and_summarize|run_skill|list_skills'
        '|layout_nodes|get_node_positions'
        '|perf_start_profile|perf_stop_and_report'
    )
    _FAKE_TOOL_PATTERNS = re.compile(
        r'^\[(?:ok|err)\]\s*(?:' + _ALL_TOOL_NAMES + r')\s*[:\uff1a]',
        re.MULTILINE | re.IGNORECASE,
    )

    @staticmethod
    def _split_and_compress_assistant(content: str, max_reply: int = 1500) -> str:
        """Split tool summaries from AI replies, plus smart compression.
        
        used foroldformat assistant message (nothas _reply_content field) , 
        trywill [toolexecuteresult] paragraphandaftercontinue AI replypartopen, 
        compresstoolpartpart, keepreplypartpart. 
        """
        # lookuptoolresultparagraphend
        if '[toolexecuteresult]' not in content and '[toolresult]' not in content and '[Tool Result]' not in content:
            # nothastoolsummary, directlycutbreak
            return content[:max_reply] + ('...' if len(content) > max_reply else '')
        
        # findtolastonerow [ok] or [err]
        last_tool_line = max(content.rfind('\n[ok]'), content.rfind('\n[err]'))
        if last_tool_line <= 0:
            return content[:max_reply] + ('...' if len(content) > max_reply else '')
        
        # findtothisrowendposition
        next_nl = content.find('\n', last_tool_line + 1)
        if next_nl <= 0 or next_nl >= len(content) - 5:
            return content[:max_reply] + ('...' if len(content) > max_reply else '')
        
        tool_text = content[:next_nl]
        reply_text = content[next_nl:].strip()
        
        # compresstoolpartpart
        tool_lines = tool_text.strip().split('\n')
        if len(tool_lines) > 6:
            tool_text = '\n'.join(tool_lines[:1] + tool_lines[-4:]) + f'\n... {len(tool_lines)-1} calls'
        elif len(tool_text) > 500:
            tool_text = tool_text[:500] + '...'
        
        # keepreplypartpart
        if reply_text:
            reply_text = reply_text[:max_reply] + ('...' if len(reply_text) > max_reply else '')
        
        return tool_text + '\n\n' + reply_text if reply_text else tool_text

    @staticmethod
    def _fix_message_alternation(messages: list) -> list:
        """fixmessagesubmitreplaceissue: mergeconsecutive sameanglecolormessage
        
        Cursor stylemessageformatsupport: 
        - user → assistant(tool_calls) → tool → assistant → user (normalformat) 
        - onlymergeconsecutive  user orconsecutive  assistant (no tool_calls  ) 
        - notmergewith tool_calls   assistant message (itsneedsforshould  tool result) 
        - Tool messages do not participate in merging
        """
        if not messages:
            return messages
        
        fixed = [messages[0]]
        for msg in messages[1:]:
            role = msg.get('role', '')
            prev_role = fixed[-1].get('role', '')
            
            # Tool messages are never merged (linked to assistant via tool_call_id)
            if role == 'tool' or prev_role == 'tool':
                fixed.append(msg)
                continue
            
            # with tool_calls   assistant messagenotmerge (API formatneedrequestindependentstand) 
            if role == 'assistant' and msg.get('tool_calls'):
                fixed.append(msg)
                continue
            if prev_role == 'assistant' and fixed[-1].get('tool_calls'):
                fixed.append(msg)
                continue
            
            if role == prev_role and role in ('user', 'assistant'):
                # mergeconsecutive sameanglecolormessage
                prev_content = fixed[-1].get('content')
                curr_content = msg.get('content')
                
                # ★ Multimodal messages (content is list) cannot be string-concatenated with +
                # Strategy: if any content is a list, extract text parts then merge
                prev_text = prev_content
                curr_text = curr_content
                if isinstance(prev_content, list):
                    prev_text = '\n'.join(
                        p.get('text', '') for p in prev_content
                        if isinstance(p, dict) and p.get('type') == 'text'
                    ) or ''
                if isinstance(curr_content, list):
                    curr_text = '\n'.join(
                        p.get('text', '') for p in curr_content
                        if isinstance(p, dict) and p.get('type') == 'text'
                    ) or ''
                
                prev_text = prev_text or ''
                curr_text = curr_text or ''
                
                fixed[-1] = fixed[-1].copy()
                
                # If both sides are pure text, just concatenate
                # If either side is a multimodal list, keep the last image part + merge text
                if isinstance(prev_content, list) or isinstance(curr_content, list):
                    # mergeasmultimodalformat: keepall text and image_url
                    merged_parts = []
                    combined_text = (prev_text + '\n\n' + curr_text).strip()
                    if combined_text:
                        merged_parts.append({'type': 'text', 'text': combined_text})
                    # collectsetallimagepartpart
                    for src in (prev_content, curr_content):
                        if isinstance(src, list):
                            for part in src:
                                if isinstance(part, dict) and part.get('type') == 'image_url':
                                    merged_parts.append(part)
                    fixed[-1]['content'] = merged_parts if merged_parts else combined_text
                else:
                    fixed[-1]['content'] = prev_text + '\n\n' + curr_text
                
                if 'thinking' in msg and msg['thinking']:
                    prev_thinking = fixed[-1].get('thinking', '')
                    fixed[-1]['thinking'] = (prev_thinking + '\n' + msg['thinking']).strip()
            else:
                fixed.append(msg)
        
        return fixed

    @staticmethod
    def _format_tool_args_brief(tool_name: str, args: dict) -> str:
        """formatizationtoolparametersummary, keepkeyparameterletmodelcanreferenceononeroundcall
        
        forcompare ChatGPT/Cursor: itskeepcompleteparameter, butIsneedscontrol token. 
        Compromise: keep only the most important parameters; limit total length.
        """
        if not args:
            return ""
        
        # differenttool keyparameter (byreneedpropertysort) 
        _KEY_PARAMS = {
            'create_node': ['node_type', 'parent_path', 'node_name'],
            'create_wrangle_node': ['wrangle_type', 'node_name', 'run_over'],
            'create_nodes_batch': ['nodes'],
            'connect_nodes': ['from_path', 'to_path', 'input_index'],
            'set_node_parameter': ['node_path', 'param_name', 'value'],
            'get_node_parameters': ['node_path'],
            'get_network_structure': ['network_path'],
            'set_display_flag': ['node_path', 'display', 'render'],
            'execute_python': ['code'],
            'execute_shell': ['command'],
            'search_node_types': ['keyword'],
            'web_search': ['query'],
            'fetch_webpage': ['url'],
            'check_errors': ['node_path'],
            'run_skill': ['skill_name'],
        }
        
        key_params = _KEY_PARAMS.get(tool_name, list(args.keys())[:3])
        parts = []
        for k in key_params:
            if k in args:
                v = args[k]
                v_str = str(v)
                # codeclassparameteronlyfetchprevious 60 character
                if k in ('code', 'vex_code', 'command') and len(v_str) > 60:
                    v_str = v_str[:60] + '...'
                elif len(v_str) > 80:
                    v_str = v_str[:80] + '...'
                parts.append(f'{k}={v_str}')
        
        brief = ', '.join(parts)
        return brief[:200] if len(brief) > 200 else brief  # totallengthlimit

    def _strip_fake_tool_results(self, text: str) -> str:
        """detectandremove AI fake toolcallresulttext. 
        
        The AI sometimes fakes a tool call inside the reply, producing output like:
          [ok] web_search: search xxx
          [ok] fetch_webpage: netpagebody text xxx
        thissomenotruepositive toolcall, needsclearremove. 
        """
        if not text:
            return text
        
        # detect [toolexecuteresult] headpart (thisissystemautogeneratedformat, AI notshouldoutput) 
        if text.lstrip().startswith('[toolexecuteresult]') or text.lstrip().startswith('[Tool Result]'):
            # wholesegmentjustisfake toolsummary, removeheadpartand [ok]/[err] row
            lines = text.split('\n')
            real_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped in ('[toolexecuteresult]', '[Tool Result]'):
                    continue
                if self._FAKE_TOOL_PATTERNS.match(stripped):
                    continue
                real_lines.append(line)
            text = '\n'.join(real_lines).strip()
        
        # detectscatterinbody textin fakerow
        lines = text.split('\n')
        cleaned = []
        for line in lines:
            if self._FAKE_TOOL_PATTERNS.match(line.strip()):
                continue
            cleaned.append(line)
        
        return '\n'.join(cleaned).strip()

    def _manage_context(self):
        """managecontextlength — Cursor styleroundtimetrim
        
        coreoriginalthen (with _progressive_trim consistent) : 
        - **Never truncate user / assistant messages**
        - onlycompress tool result (role='tool'   content) 
        - by"roundtime" (by user messageaspartboundary) trim, protectrecent N round
        - If compressing tools alone isn't enough, drop the earliest rounds entirely
        - Preserve the native assistant(tool_calls) ↔ tool chain
        """
        # ★ use agent anchorfixed  history (avoidcompresserror session) 
        history = self._agent_history if self._agent_history is not None else self._conversation_history
        if len(history) < 6:
            return  # too few to manage
        
        current_tokens = self.token_optimizer.calculate_message_tokens(history)
        context_limit = self._get_current_context_limit()
        
        # updatepre-calculate
        self.token_optimizer.budget.max_tokens = context_limit
        should_compress, reason = self.token_optimizer.should_compress(current_tokens, context_limit)
        
        if not (should_compress and self._auto_optimize):
            if reason and ('warning' in reason or 'warning' in reason.lower()):
                self._addStatus.emit(f"Note: {reason}")
            return
        
        # ★ depthsleep: _manage_context compresspreviouswholemanageallpartcontextaslong-termmemory
        if self._is_memory_active() and self._reflection_module and not self._sleep_in_progress:
            _params = getattr(self, '_last_agent_params', {})
            if _params:
                self._addStatus.emit("😴 depthsleep: positiveinwholemanageallpartcontextaslong-termmemory...")
                try:
                    self._sleep_in_progress = True
                    deep_result = self._reflection_module.deep_sleep(
                        session_id=self._session_id,
                        all_messages=list(history),
                        ai_client=self.client,
                        model=_params.get('model', 'deepseek-v4-flash'),
                        provider=_params.get('provider', 'deepseek'),
                    )
                    if deep_result.get("success"):
                        n_rules = len(deep_result.get("new_rules", []))
                        n_strats = len(deep_result.get("new_strategies", []))
                        self._addStatus.emit(
                            f"😴 depthsleepcomplete: {n_rules} itemexperience + {n_strats} itemstrategyalreadywritelong-termmemory"
                        )
                except Exception as e:
                    _dbg(f"[Sleep] _manage_context deep-sleep error: {e}")
                finally:
                    self._sleep_in_progress = False
        
        old_tokens = current_tokens
        
        # --- by user messageplanpartroundtime ---
        rounds = []       # [[msg, msg, ...], ...]
        current_round = []
        for m in history:
            if m.get('role') == 'user' and current_round:
                rounds.append(current_round)
                current_round = []
            current_round.append(m)
        if current_round:
            rounds.append(current_round)
        
        if len(rounds) <= 2:
            return  # onlyhas 1-2 round, nottrim
        
        # --- firstall: compressoldroundtime  tool result (keeprecent 60%) ---
        n_rounds = len(rounds)
        protect_n = max(2, int(n_rounds * 0.6))
        for r_idx in range(n_rounds - protect_n):
            for m in rounds[r_idx]:
                if m.get('role') == 'tool':
                    c = m.get('content') or ''
                    if len(c) > 200:
                        m['content'] = self.client._summarize_tool_content(c, 200) if hasattr(self.client, '_summarize_tool_content') else c[:200] + '...[summary]'
        
        # renewcompute
        compressed = [m for rnd in rounds for m in rnd]
        new_tokens = self.token_optimizer.calculate_message_tokens(compressed)
        
        if new_tokens < context_limit * self.token_optimizer.budget.compression_threshold:
            # Compressing tools alone is enough
            history.clear()
            history.extend(compressed)
            saved = old_tokens - new_tokens
            if saved > 0:
                pct = saved / old_tokens * 100 if old_tokens else 0
                self._addStatus.emit(tr('opt.auto_status', saved))
            return
        
        # --- secondall: deletemostearly completeroundtime, directtolowinthresholdvalue ---
        target = int(context_limit * 0.65)  # targetlowerto 65%
        while len(rounds) > 2:
            # deletemostearly roundtime
            removed = rounds.pop(0)
            compressed = [m for rnd in rounds for m in rnd]
            new_tokens = self.token_optimizer.calculate_message_tokens(compressed)
            if new_tokens <= target:
                break
        
        # inheadpartinsertsummaryhint
        summary_note = {
            'role': 'system',
            'content': tr('ai.old_rounds', n_rounds - len(rounds))
        }
        
        history.clear()
        history.append(summary_note)
        history.extend([m for rnd in rounds for m in rnd])
        
        saved = old_tokens - self.token_optimizer.calculate_message_tokens(history)
        if saved > 0:
            self._addStatus.emit(tr('opt.auto_status', saved))
            self._render_conversation_history()
    
    def _compress_context(self):
        """Compress context — smart summarization that keeps key info.

        improvedstrategy:
        1. byroundtime (user→assistant for) extractinfo, andnotsimplecutfetch
        2. extractuserintentdiagram, tooloperation, keyresult, node path
        3. Recognize errors and corrective actions
        4. generatestructureizationsummary
        """
        if len(self._conversation_history) <= 4:
            return  # too short — no compression needed

        # willoldconversationcompressbecomesummary
        old_messages = self._conversation_history[:-4]  # keeprecent 4 item
        recent_messages = self._conversation_history[-4:]

        # byroundtimegroup
        rounds_info = []
        current_round = {"user": "", "assistant": "", "tools": [], "errors": []}

        for msg in old_messages:
            role = msg.get('role', '')
            content = msg.get('content', '')

            if isinstance(content, list):
                # multimodalcontent → extracttext
                content = ' '.join(
                    p.get('text', '') for p in content if isinstance(p, dict) and p.get('type') == 'text'
                )

            if role == 'user':
                if current_round["user"]:
                    rounds_info.append(current_round)
                    current_round = {"user": "", "assistant": "", "tools": [], "errors": []}
                current_round["user"] = content[:120].replace('\n', ' ').strip()
            elif role == 'assistant' and content:
                # goremove think label
                clean = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
                if clean:
                    # Extract key sentences (the last two lines are usually conclusions)
                    lines = [l.strip() for l in clean.split('\n') if l.strip()]
                    summary_lines = lines[-2:] if len(lines) > 2 else lines
                    current_round["assistant"] = ' '.join(summary_lines)[:100]
                # extracttoolcall
                tool_calls = msg.get('tool_calls', [])
                if tool_calls:
                    for tc in tool_calls:
                        fn = tc.get('function', {})
                        current_round["tools"].append(fn.get('name', ''))
            elif role == 'tool':
                tool_content = content or ''
                if 'error' in tool_content.lower() or 'fail' in tool_content.lower():
                    current_round["errors"].append(tool_content[:60])

        if current_round["user"]:
            rounds_info.append(current_round)

        # generatestructureizationsummary
        summary_parts = []
        for i, rnd in enumerate(rounds_info[-5:], 1):  # keep at mostrecent 5 round
            parts = []
            if rnd["user"]:
                parts.append(f"Q: {rnd['user'][:60]}")
            if rnd["assistant"]:
                parts.append(f"A: {rnd['assistant'][:60]}")
            if rnd["tools"]:
                unique_tools = list(dict.fromkeys(rnd["tools"]))[:3]
                parts.append(f"Tools: {','.join(unique_tools)}")
            if rnd["errors"]:
                parts.append(f"⚠ {rnd['errors'][0][:40]}")
            if parts:
                summary_parts.append(f"R{i}: " + " | ".join(parts))

        # extractraiseto node path
        all_text = ' '.join(msg.get('content', '') for msg in old_messages if isinstance(msg.get('content'), str))
        node_paths = list(set(re.findall(r'/obj/[a-zA-Z0-9_/]+', all_text)))
        if node_paths:
            summary_parts.append(f"Nodes: {', '.join(node_paths[:5])}")

        # generatecontextsummary
        if summary_parts:
            self._context_summary = "\n".join(summary_parts)
        else:
            self._context_summary = ""

        # updatehistory (onlykeeprecent ) 
        self._conversation_history = recent_messages

        _dbg(f"[Context] Compressed: kept {len(recent_messages)} message(s), "
              f"summary {len(self._context_summary)} character ({len(rounds_info)} roundextract)")
    
    def _get_context_reminder(self) -> str:
        """Generate a context reminder (very concise; emphasizes reuse)."""
        parts = []
        
        # Add compressed history summary (very concise)
        if self._context_summary:
            parts.append(f"[Context Cache] {self._context_summary}")
        
        # Add current Todo state (very concise)
        todo_summary = self._get_todo_summary_safe()
        if todo_summary:
            # onlykeepnotcomplete  todo
            if "0/" in todo_summary or "pending" in todo_summary.lower():
                parts.append(f"[TODO] {todo_summary.split(':', 1)[-1] if ':' in todo_summary else todo_summary}")
        
        # Remind to reuse context (very concise)
        if len(self._conversation_history) > 2:
            parts.append(f"[{len(self._conversation_history)} messages in context, reuse prior info]")
        
        return " | ".join(parts) if parts else ""

    def _auto_rag_retrieve(self, user_text: str,
                           scene_context: dict = None,
                           conversation_len: int = 0) -> str:
        """auto RAG: fromusermessage + Houdini scenecontextsearchdocumentandinject

        inbackgroundthreadcall, notinvolveand Qt widget. 
        
        Args:
            user_text: userlatestmessagetext
            scene_context: mainthreadcollectset scenecontext (network_path, selected_types, selected_names)
            conversation_len: currentconversationhistoryitemcount (used formovestateadjustwholeinjectquantity) 
        """
        try:
            from ..utils.doc_rag import get_doc_index
            index = get_doc_index()
            
            # ★ Dynamic-adjust RAG injection volume: the longer the conversation, the more we trim — avoid wasting tokens
            if conversation_len > 20:
                max_chars = 400   # longconversation: simplifyinject
            elif conversation_len > 10:
                max_chars = 800   # inetc.conversation
            else:
                max_chars = 1200  # short conversation: inject in full
            
            # ★ Strengthen scene context: also add the selected node type to the search query
            enriched_query = user_text
            if scene_context:
                selected_types = scene_context.get('selected_types', [])
                if selected_types:
                    # Add the selected node type to the query so RAG can find related docs
                    enriched_query += ' ' + ' '.join(selected_types)
            
            return index.auto_retrieve(enriched_query, max_chars=max_chars)
        except Exception:
            return ""

    def _get_todo_summary_safe(self) -> str:
        """threadsafeplaceget Todo summary (preferreduse agent anchorfixed  TodoList) """
        todo = self._agent_todo_list or self.todo_list
        try:
            return todo.get_todos_summary() if todo else ""
        except Exception:
            return ""

    @QtCore.Slot(result=str)
    def _invoke_get_todo_summary(self) -> str:
        todo = self._agent_todo_list or self.todo_list
        return todo.get_todos_summary() if todo else ""

    # ===== URL recognize =====
    
    def _extract_urls(self, text: str) -> list:
        """fromtextinextract URL"""
        # URL positivethentableexpression
        url_pattern = r'https?://[^\s<>"\'`\]\)]+[^\s<>"\'`\]\)\.,;:!?]'
        urls = re.findall(url_pattern, text)
        return urls
    
    def _process_urls_in_text(self, text: str) -> str:
        """processtextin  URL, addhintlet AI getnetpagecontent"""
        urls = self._extract_urls(text)
        
        if not urls:
            return text
        
        # ifpackagecontaining URL, addhint
        url_list = "\n".join(f"  - {url}" for url in urls)
        hint = tr('ai.detected_url', url_list)
        
        return text + hint

    # ===== eventprocess =====
    
    def _on_send(self):
        text = self.input_edit.toPlainText().strip()
        # Any session with an agent running blocks send (AIClient is shared, no parallelism supported)
        if not text or self._agent_session_id is not None:
            return

        provider = self._current_provider()
        if not self.client.has_api_key(provider):
            self._on_set_key()
            return

        # ★ Hook: on_session_start
        self._fire_session_hook('on_session_start', self._session_id)

        # collectsetpendingsend image (in clear before) 
        has_images = bool(self._pending_images) and self._current_model_supports_vision()
        pending_imgs = [img for img in self._pending_images if img is not None] if has_images else []

        # showusermessage (containingimagethumbnaildiagram) 
        self._add_user_message(text, images=pending_imgs)
        self.input_edit.clear()
        self._clear_pending_images()
        
        # autorecommandnamelabel (firstitemmessagewhen) 
        self._auto_rename_tab(text)
        
        # detect URL andaddhint
        processed_text = self._process_urls_in_text(text)
        
        # buildmessagecontent (textormultimodal) 
        if pending_imgs:
            msg_content = self._build_multimodal_content(processed_text, pending_imgs)
            self._conversation_history.append({'role': 'user', 'content': msg_content})
        else:
            self._conversation_history.append({'role': 'user', 'content': processed_text})
        
        # updatecontextstatistics
        self._update_context_stats()
        
        # startrun (firstsetstate, againcreatereplyblock) 
        self._set_running(True)
        
        # create AI replyblock (mustin _set_running after, otherwisewillisclearremove) 
        self._add_ai_response()
        # Sync the agent anchor to the just-created response widget
        self._agent_response = self._current_response
        # ★ startstreamlightedgeboxmovedraw
        self._start_active_aurora()
        
        # ★ recordusercurrent  Houdini updatemode (Agent endafterrestore) 
        try:
            import hou  # type: ignore
            self._pre_agent_update_mode = hou.updateModeSetting()
        except Exception:
            self._pre_agent_update_mode = None
        
        # ⚠️ inmainthreadingetall Qt widget value (backgroundthreadcannotdirectlyaccess) 
        agent_params = {
            'provider': self._current_provider(),
            'model': self.model_combo.currentText(),
            'use_web': self.web_check.isChecked(),
            'use_agent': self._agent_mode,  # True=Agent(full), False=Ask(read-only)
            'use_think': self.think_check.isChecked(),
            'context_limit': self._get_current_context_limit(),  # alsoinmainthreadget
            'scene_context': self._collect_scene_context(),  # ★ mainthreadcollectset Houdini scenecontext
            'supports_vision': self._current_model_supports_vision(),  # modelwhethersupportimage
            'plan_mode': self._plan_mode,  # ★ Plan modemark
        }
        
        # savemodelselect
        self._save_model_preference()
        
        # backgroundexecute (passdeliverparameterandnodirectlyaccesswidget) 
        thread = threading.Thread(target=self._run_agent, args=(agent_params,), daemon=True)
        thread.start()

    def _run_agent(self, agent_params: dict):
        """backgroundrun Agent
        
        Args:
            agent_params: frommainthreadget parameter (avoidinbackgroundthreadaccess Qt widget) 
                - provider: AI raiseforvendor
                - model: modelname
                - use_web: whetherenablenetpagesearch
                - use_agent: whetherenable Agent mode
                - use_think: whetherenablethinkingmode
                - context_limit: contextlimit
        """
        # ⚠️ fromparametergetvalue, notdirectlyaccess Qt widget (thread-safe)
        provider = agent_params['provider']
        model = agent_params['model']
        use_web = agent_params['use_web']
        use_agent = agent_params['use_agent']
        use_think = agent_params.get('use_think', True)
        context_limit = agent_params['context_limit']
        scene_context = agent_params.get('scene_context', {})
        supports_vision = agent_params.get('supports_vision', True)
        plan_mode = agent_params.get('plan_mode', False)
        plan_executing = agent_params.get('plan_executing', False)
        
        # ★ save agent_params forreflectionhookuse
        self._last_agent_params = agent_params
        
        # ★ savestore Think togglestate, for _drain_tag_buffer / _on_thinking_chunk use
        self._think_enabled = use_think
        
        try:
            # ========================================
            # 🔥 Cache optimization: keep the message prefix stable
            # ========================================
            # messagestructure: [systemhint] + [historymessage] + [contextremind+currentrequest]
            # Prefix (system prompt + history messages) stays stable to raise the cache-hit rate
            
            # 1. systemhintword (based onthinkingmodeselectversion) 
            sys_prompt = self._cached_prompt_think if use_think else self._cached_prompt_no_think
            
            # ★ Ask mode: appendread-onlyconstraint
            if not use_agent and not plan_mode:
                sys_prompt = sys_prompt + tr('ai.ask_mode_prompt')
            
            # ★ Plan mode: appendruleplanorexecutestagehintword
            if plan_mode:
                if plan_executing:
                    sys_prompt = sys_prompt + tr('ai.plan_mode_execution_prompt')
                else:
                    self._plan_phase = 'planning'
                    sys_prompt = sys_prompt + tr('ai.plan_mode_planning_prompt')
            
            # ★ Agent mode: appendcomplextasksuggestionswitch Plan  hint
            if use_agent and not plan_mode:
                sys_prompt = sys_prompt + tr('ai.agent_suggest_plan_prompt')
            
            # ★ Identity injection: append growth-system-shaped identity traits to the end of the system prompt
            personality_text = self._get_personality_injection()
            if personality_text:
                sys_prompt = sys_prompt + "\n\n" + personality_text

            # ★ Simulation builder policy — only when build skills are available
            #   (Agent / Plan modes, NOT read-only Ask) AND the request is actually
            #   about a simulation. This keeps procedural requests (modeling, VEX,
            #   node networks) lean and un-biased toward sim builders.
            if use_agent or plan_mode:
                _last_user = ""
                try:
                    for _m in reversed(self._conversation_history):
                        if _m.get('role') == 'user':
                            _c = _m.get('content', '')
                            _last_user = _c if isinstance(_c, str) else str(_c)
                            break
                except Exception:
                    pass
                _want_sim = True
                try:
                    from ..utils.roles_manager import is_sim_request
                    _want_sim = is_sim_request(_last_user)
                except Exception:
                    _want_sim = True
                if _want_sim:
                    sim_policy = self._get_sim_policy_injection()
                    if sim_policy:
                        sys_prompt = sys_prompt + "\n\n" + sim_policy
                else:
                    # ★ Procedural Build Competence — for generic build/modeling requests
                    #   with no dedicated builder skill. Mutually exclusive with the sim
                    #   policy above so we never bloat both into one prompt.
                    try:
                        from ..utils.roles_manager import is_build_request
                        _want_build = is_build_request(_last_user)
                    except Exception:
                        _want_build = False
                    if _want_build:
                        cookbook = self._get_procedural_cookbook_injection()
                        if cookbook:
                            sys_prompt = sys_prompt + "\n\n" + cookbook

                # ★ Visual Refinement Loop — additive (not exclusive): fires when the
                #   user is tweaking the LOOK of an existing result ("make it more X",
                #   "lebih ...", "masih siku"), which is neither a fresh sim nor build.
                try:
                    from ..utils.roles_manager import is_refine_request
                    _want_refine = is_refine_request(_last_user)
                except Exception:
                    _want_refine = False
                if _want_refine:
                    refine_policy = self._get_visual_refine_policy_injection()
                    if refine_policy:
                        sys_prompt = sys_prompt + "\n\n" + refine_policy

            # ★ Role injection (HDA Architect / VEX Debugger / Technical Writer / FX Artist).
            #   Defensive: returns '' for the default 'generalist' role or on any error.
            role_text = self._get_role_injection()
            if role_text:
                sys_prompt = sys_prompt + "\n\n" + role_text

            # ★ Thinking-level directive (only when thinking is on; empty for medium / on error)
            if use_think:
                think_text = self._get_thinking_injection()
                if think_text:
                    sys_prompt = sys_prompt + "\n\n" + think_text

            # ★ L0 corememoryload: allpartloadto sys_prompt (onlimit 5 item, by confidence TopK) 
            if self._is_memory_active():
                try:
                    core_mems = self._memory_store.get_core_memories(max_count=5)
                    if core_mems:
                        core_lines = [f"- {m.rule}" for m in core_mems]
                        sys_prompt = sys_prompt + (
                            "\n\n[Core Memory — the following is core memory; for reference only — judge based on current context]\n"
                            + "\n".join(core_lines)
                        )
                except Exception as e:
                    _dbg(f"[Memory] L0 core memory load failed: {e}")
            
            # ★ usercustomruleinject (classsimilar Cursor Rules) 
            rules_text = self._get_user_rules_injection()
            if rules_text:
                sys_prompt = sys_prompt + "\n\n" + rules_text
            
            messages = [{'role': 'system', 'content': sys_prompt}]
            
            # ================================================================
            # 2. Cursor stylehistorymessage: nativeformatdirectthrough, notpre-compress
            # ================================================================
            # coreoriginalthen: 
            # - assistant messagecompletekeep (packageinclude content and tool_calls) 
            # - tool messagecompletekeep (packageinclude tool_call_id and content) 
            # - user messagecompletekeep
            # - onlycleanupwithinpartmetadatadatafield (thinking, python_shells etc.) 
            # - compressonlyinexceedlimitwhenby _progressive_trim / auto_optimize process
            
            # withinpartmetadatadatafieldlist (notsendgive API) 
            _INTERNAL_FIELDS = frozenset({
                '_reply_content', '_tool_summary', 'thinking',
                'python_shells', 'system_shells',
            })
            
            # ★ Cursor style: onlykeepcurrentroundtime (lastoneitem user message)  image
            # Strip image_url in older rounds to plain text — avoid base64 bloating the context
            _last_user_idx = None
            for _i in range(len(self._conversation_history) - 1, -1, -1):
                if self._conversation_history[_i].get('role') == 'user':
                    _last_user_idx = _i
                    break
            
            history_to_send = []
            for msg_idx, msg in enumerate(self._conversation_history):
                role = msg.get('role', '')
                
                if role == 'tool':
                    # ★ newformat (Cursor style) : keepnative tool message ★
                    # musthas tool_call_id only thencansendgive API
                    if msg.get('tool_call_id'):
                        clean = {k: v for k, v in msg.items() if k not in _INTERNAL_FIELDS}
                        history_to_send.append(clean)
                    else:
                        # oldformat tool message (no tool_call_id) → convertas assistant text
                        tool_name = msg.get('name', 'unknown')
                        content = msg.get('content', '')
                        history_to_send.append({
                            'role': 'assistant',
                            'content': tr('ai.tool_result', tool_name, content[:500])
                        })
                
                elif role == 'assistant':
                    # ★ completekeep assistant message ★
                    clean = {}
                    for k, v in msg.items():
                        if k in _INTERNAL_FIELDS:
                            continue
                        clean[k] = v
                    # ifisoldformat  [toolexecuteresult] text, alsooriginallikekeep
                    # content completepassdeliver, notdoanycutbreak
                    # Also keep tool_calls (if any — new format)
                    history_to_send.append(clean)
                
                elif role == 'user':
                    # ★ Cursor styleimageprocess: 
                    # - currentroundtime (lastoneitem user) + visualmodel → keepimage
                    # - oldroundtime or notvisualmodel → strip image_url, onlykeeptext
                    content = msg.get('content')
                    is_current_round = (msg_idx == _last_user_idx)
                    
                    if isinstance(content, list):
                        if is_current_round and supports_vision:
                            # currentround + visualmodel: completekeepimage
                            history_to_send.append(msg)
                        else:
                            # oldroundtime or notvisualmodel: stripimage, onlykeeptext
                            text_parts = []
                            for part in content:
                                if isinstance(part, dict) and part.get('type') == 'text':
                                    text_parts.append(part.get('text', ''))
                            text_only = '\n'.join(t for t in text_parts if t)
                            history_to_send.append({
                                'role': 'user',
                                'content': text_only or tr('ai.image_msg')
                            })
                    else:
                        # puretextmessage: originallikekeep
                        history_to_send.append(msg)
                
                elif role == 'system':
                    # systemmessage (such ashistorysummary) keep
                    history_to_send.append(msg)
            
            # fix user/assistant submitreplace (onlyprocessconsecutive sameanglecolor, notshadowrespond tool message) 
            history_to_send = self._fix_message_alternation(history_to_send)
            
            messages.extend(history_to_send)
            
            # 3. auto RAG inject (fromuserlatestmessageinextractkeyword, searchrelateddocument) 
            user_last_msg = ""
            if self._conversation_history:
                for msg in reversed(self._conversation_history):
                    if msg.get('role') == 'user':
                        raw_content = msg.get('content', '')
                        # multimodalcontent (list) inextracttextpartpart
                        if isinstance(raw_content, list):
                            user_last_msg = ' '.join(
                                p.get('text', '') for p in raw_content if p.get('type') == 'text'
                            )
                        else:
                            user_last_msg = raw_content
                        break
            if user_last_msg:
                rag_context = self._auto_rag_retrieve(
                    user_last_msg,
                    scene_context=scene_context,
                    conversation_len=len(self._conversation_history),
                )
                if rag_context:
                    messages.append({'role': 'system', 'content': rag_context})
            
            # 4. ★ Long-term memory activation ("I'm awake" mechanism)
            # in RAG documentafter, contextremindbeforeinject
            if user_last_msg:
                memory_context = self._activate_long_term_memory(
                    user_last_msg, scene_context=scene_context
                )
                if memory_context:
                    messages.append({'role': 'system', 'content': memory_context})
            
            # 5. ★ Plan contextinject (onlyin Plan executestage + current session matchwhen) 
            if plan_mode and plan_executing:
                try:
                    if self._plan_manager is None:
                        self._plan_manager = get_plan_manager()
                    plan_ctx = self._plan_manager.get_plan_for_context(self._session_id)
                    if plan_ctx:
                        messages.append({'role': 'system', 'content': plan_ctx})
                except Exception as e:
                    _dbg(f"[Plan] Context injection error: {e}")
            
            # 6. Context reminder (placed last to not break the cache prefix)
            # ⚠️ Cache optimization: place dynamic content at the end to keep the prefix stable
            context_reminder = self._get_context_reminder()
            if context_reminder:
                # willcontextremindassystemmessageaddtoend
                messages.append({'role': 'system', 'content': f"[Context] {context_reminder}"})
            
            # ================================================================
            # ★ sleepmechanism: shallowsleep (each N rounduserasktrigger) 
            # ================================================================
            if self._is_memory_active() and self._reflection_module:
                self._sleep_msg_counter += 1
                from ..utils.reflection import LIGHT_SLEEP_INTERVAL
                if self._sleep_msg_counter % LIGHT_SLEEP_INTERVAL == 0 and not self._sleep_in_progress:
                    # collectsetrecent N round messageused forshallowsleepsummary
                    _sleep_messages = self._collect_recent_rounds(
                        self._conversation_history, LIGHT_SLEEP_INTERVAL
                    )
                    if _sleep_messages:
                        _sleep_sid = self._session_id
                        _sleep_model = model
                        _sleep_provider = provider
                        _sleep_client = self.client
                        _sleep_reflection = self._reflection_module
                        def _do_light_sleep():
                            self._sleep_in_progress = True
                            try:
                                result = _sleep_reflection.light_sleep(
                                    session_id=_sleep_sid,
                                    recent_messages=_sleep_messages,
                                    ai_client=_sleep_client,
                                    model=_sleep_model,
                                    provider=_sleep_provider,
                                )
                                if result.get("success"):
                                    self._addStatus.emit("💤 shallowsleepcomplete, experiencealreadywritelong-termmemory")
                            finally:
                                self._sleep_in_progress = False
                        sleep_thread = threading.Thread(target=_do_light_sleep, daemon=True)
                        sleep_thread.start()
            
            # Cursor stylepre-sendcompress: onlycompress tool result, keep user/assistant complete
            if self._auto_optimize:
                current_tokens = self.token_optimizer.calculate_message_tokens(messages)
                should_compress, _ = self.token_optimizer.should_compress(current_tokens, context_limit)
                
                if should_compress:
                    # ★ depthsleep: compresspreviouswillcompletecontextwritelong-termmemory
                    if self._is_memory_active() and self._reflection_module and not self._sleep_in_progress:
                        self._addStatus.emit("😴 depthsleep: positiveinwholemanageallpartcontextaslong-termmemory...")
                        try:
                            self._sleep_in_progress = True
                            deep_result = self._reflection_module.deep_sleep(
                                session_id=self._session_id,
                                all_messages=self._conversation_history,
                                ai_client=self.client,
                                model=model,
                                provider=provider,
                            )
                            if deep_result.get("success"):
                                n_rules = len(deep_result.get("new_rules", []))
                                n_strats = len(deep_result.get("new_strategies", []))
                                self._addStatus.emit(
                                    f"😴 depthsleepcomplete: {n_rules} itemexperience + {n_strats} itemstrategyalreadywritelong-termmemory"
                                )
                        except Exception as e:
                            _dbg(f"[Sleep] Deep-sleep error: {e}")
                        finally:
                            self._sleep_in_progress = False
                    
                    old_tokens = current_tokens
                    # partleavesystemhintandcontextremind
                    first_system = messages[0] if messages and messages[0].get('role') == 'system' else None
                    last_context = messages[-1] if messages and ('[context]' in messages[-1].get('content', '') or '[Context]' in messages[-1].get('content', '')) else None
                    start_idx = 1 if first_system else 0
                    end_idx = -1 if last_context else len(messages)
                    body = messages[start_idx:end_idx] if end_idx != len(messages) else messages[start_idx:]
                    
                    # by user messageplanpartroundtime
                    rounds = []
                    cur_rnd = []
                    for m in body:
                        if m.get('role') == 'user' and cur_rnd:
                            rounds.append(cur_rnd)
                            cur_rnd = []
                        cur_rnd.append(m)
                    if cur_rnd:
                        rounds.append(cur_rnd)
                    
                    # firstall: compressoldroundtime tool result
                    n_rounds = len(rounds)
                    protect_n = max(2, int(n_rounds * 0.6))
                    for r_idx in range(n_rounds - protect_n):
                        for m in rounds[r_idx]:
                            if m.get('role') == 'tool':
                                c = m.get('content') or ''
                                if len(c) > 200:
                                    m['content'] = self.client._summarize_tool_content(c, 200) if hasattr(self.client, '_summarize_tool_content') else c[:200] + '...[summary]'
                    
                    compressed_body = [m for rnd in rounds for m in rnd]
                    
                    # ifstillexceedlimit, deletemostearlyroundtime
                    target = int(context_limit * 0.7)
                    while len(rounds) > 2:
                        test_body = [m for rnd in rounds for m in rnd]
                        test_msgs = ([first_system] if first_system else []) + test_body + ([last_context] if last_context else [])
                        if self.token_optimizer.calculate_message_tokens(test_msgs) <= target:
                            break
                        rounds.pop(0)
                    
                    compressed_body = [m for rnd in rounds for m in rnd]
                    
                    # regroup
                    messages = []
                    if first_system:
                        messages.append(first_system)
                    if n_rounds - len(rounds) > 0:
                        messages.append({
                            'role': 'system',
                            'content': tr('ai.old_rounds', n_rounds - len(rounds))
                        })
                    messages.extend(compressed_body)
                    if last_context:
                        messages.append(last_context)
                    
                    new_tokens = self.token_optimizer.calculate_message_tokens(messages)
                    saved = old_tokens - new_tokens
                    if saved > 0:
                        self._addStatus.emit(tr('opt.auto_status', saved))
            
            # ⚠️ usefrommainthreadpassenter parameter (notdirectlyaccess Qt widget) 
            # provider, model, use_web, use_agent alreadyinmethodstartfrom agent_params get
            
            # debug: showpositiveinrequest
            self._addStatus.emit(f"Requesting {provider}/{model}...")
            
            # inferencemodelcompatible with: cleanupmessageformat
            is_reasoning_model = AIClient.is_reasoning_model(model)
            cleaned_messages = []
            for msg in messages:
                role = msg.get('role', 'user')
                content = msg.get('content')
                has_tool_calls = 'tool_calls' in msg
                
                clean_msg = {'role': role}
                
                # ★ Cursor style: assistant has tool_calls when content canas None ★
                # Claude/Anthropic generationmanagereject content="" + tool_calls sharedsave
                if role == 'assistant' and has_tool_calls:
                    clean_msg['content'] = content  # keep None (notconvertasemptystring) 
                else:
                    clean_msg['content'] = content if content is not None else ''
                
                # inferencemodel: assistant messageneeds reasoning_content field
                if is_reasoning_model and role == 'assistant':
                    clean_msg['reasoning_content'] = msg.get('reasoning_content', '')
                # keep tool_calls field
                if has_tool_calls:
                    clean_msg['tool_calls'] = msg['tool_calls']
                # keep tool_call_id field
                if 'tool_call_id' in msg:
                    clean_msg['tool_call_id'] = msg['tool_call_id']
                # keep name field (used for tool message) 
                if 'name' in msg:
                    clean_msg['name'] = msg['name']
                
                # ★ cleanup assistant content in  <think> label ★
                # No need to send history thinking back to the API (wastes tokens)
                if role == 'assistant' and clean_msg.get('content'):
                    c = clean_msg['content']
                    if '<think>' in c:
                        c = re.sub(r'<think>[\s\S]*?</think>', '', c).strip()
                        clean_msg['content'] = c or None
                
                cleaned_messages.append(clean_msg)
            messages = cleaned_messages
            
            # usecache optimizationizationaftertoolfixedmeaning (onlycomputeonce) 
            if plan_mode and not plan_executing:
                # ★ Plan ruleplanstage: read-onlytool + create_plan + ask_question
                plan_filtered = [t for t in HOUDINI_TOOLS
                                 if t['function']['name'] in self._PLAN_PLANNING_TOOLS]
                plan_filtered.append(PLAN_TOOL_CREATE)
                plan_filtered.append(PLAN_TOOL_ASK_QUESTION)
                if not use_web:
                    plan_filtered = [t for t in plan_filtered
                                     if t['function']['name'] not in ('web_search', 'fetch_webpage')]
                tools = UltraOptimizer.optimize_tool_definitions(plan_filtered)
            elif plan_mode and plan_executing:
                # ★ Plan executestage: completetool + update_plan_step
                exec_tools = list(HOUDINI_TOOLS) + [PLAN_TOOL_UPDATE_STEP]
                if not use_web:
                    exec_tools = [t for t in exec_tools
                                  if t['function']['name'] not in ('web_search', 'fetch_webpage')]
                tools = UltraOptimizer.optimize_tool_definitions(exec_tools)
            elif not use_agent:
                # ★ Ask mode: onlykeepread-only/querytool
                ask_filtered = [t for t in HOUDINI_TOOLS
                                if t['function']['name'] in self._ASK_MODE_TOOLS]
                if not use_web:
                    ask_filtered = [t for t in ask_filtered
                                    if t['function']['name'] not in ('web_search', 'fetch_webpage')]
                tools = UltraOptimizer.optimize_tool_definitions(ask_filtered)
            else:
                # ★ Agent mode: useallquantitytool
                # note: notdointentdiagramfilter. Agent needsmultirounditerate, mayfirstqueryagaincreateagainverify, 
                # intentdiagramfilterwillcausesaftercontinueiteratemissingmustneedtool (such as capture_viewport, create_node etc.) . 
                if use_web:
                    if self._cached_optimized_tools is None:
                        self._cached_optimized_tools = UltraOptimizer.optimize_tool_definitions(HOUDINI_TOOLS)
                    tools = self._cached_optimized_tools
                else:
                    if self._cached_optimized_tools_no_web is None:
                        filtered = [t for t in HOUDINI_TOOLS if t['function']['name'] not in ('web_search', 'fetch_webpage')]
                        self._cached_optimized_tools_no_web = UltraOptimizer.optimize_tool_definitions(filtered)
                    tools = self._cached_optimized_tools_no_web
            
            # ★ mergeexternaltool (HookManager plugintool + ToolRegistry Skill tool) 
            try:
                from ..utils.hooks import get_hook_manager as _ghm_tools
                _ext = _ghm_tools().get_external_tools()
                if _ext:
                    tools = list(tools) + _ext
            except Exception:
                pass
            try:
                from ..utils.tool_registry import get_tool_registry
                _reg = get_tool_registry()
                # get ToolRegistry in source=skill  tool (avoidwithonfaceduplicate) 
                _existing_names = {t.get('function', {}).get('name', '') for t in tools}
                for meta in _reg._tools.values():
                    if meta.source == "skill" and meta.enabled and meta.name not in _existing_names:
                        tools = list(tools) if not isinstance(tools, list) else tools
                        tools.append(meta.schema)
            except Exception:
                pass

            # ★ When the memory toggle is off, strip search_memory from the tool schema
            #   so the LLM cannot call it (which would read polluted experience while memory is disabled).
            if not self._is_memory_active():
                tools = [t for t in tools
                         if t.get('function', {}).get('name') != 'search_memory']

            # ★ notvisualmodel: capture_viewport downgradeasonlysavefile (notinjectimage) 
            # notagainremovetool——AI stillcanscreenshotsaveletuserselfrowview
            if not supports_vision:
                _degraded_tools = []
                for _t in tools:
                    if _t.get('function', {}).get('name') == 'capture_viewport':
                        import copy
                        _t_copy = copy.deepcopy(_t)
                        _t_copy['function']['description'] = (
                            "cutfetchcurrent Houdini 3D viewportsnapshotandsavetofile. "
                            "currentmodelnot supportedimageanalyze, screenshotwillsaveto output_path specified pathforuserview. "
                            "mustspecified output_path parameter. "
                        )
                        _degraded_tools.append(_t_copy)
                    else:
                        _degraded_tools.append(_t)
                tools = _degraded_tools
            
            # ★ Plan mode silenttoolset (notin UI inshow tool) 
            _silent = self._SILENT_TOOLS | self._PLAN_SILENT_TOOLS if plan_mode else self._SILENT_TOOLS
            
            # ★ throughusecallback: eachround API iteratestartwhenshow "Generating..." state
            # the1roundalsoshow, fillsupplement Send → firstcharacterofbetween emptywhite
            _on_iter = lambda i: self._showGenerating.emit()
            
            if plan_mode:
                # ★ Plan mode: use the agent loop (both planning and execution stages go through this branch)
                _max_iter = 999 if plan_executing else 20
                
                # ★ Plan continueconnectcallback: detect AI raisepreviousabortbut Plan notcomplete case
                _plan_resume_callback = None
                _plan_resume_count = 0       # preventnolimitcontinueconnect
                _MAX_PLAN_RESUMES = 5        # at mostcontinueconnect 5 time
                if plan_executing:
                    def _check_plan_incomplete():
                        nonlocal _plan_resume_count
                        if _plan_resume_count >= _MAX_PLAN_RESUMES:
                            _dbg(f"[AI Client] Plan resume limit reached ({_MAX_PLAN_RESUMES}), stopping")
                            return None
                        try:
                            if self._plan_manager is None:
                                from ..utils.plan_manager import get_plan_manager
                                self._plan_manager = get_plan_manager()
                            plan = self._plan_manager.load_plan(self._session_id)
                            if not plan:
                                return None
                            steps = plan.get('steps', [])
                            if not steps:
                                return None
                            done_count = sum(1 for s in steps if s.get('status') == 'done')
                            total = len(steps)
                            if done_count >= total:
                                return None  # allpartcomplete, normalend
                            
                            # findtonotcomplete step
                            pending_steps = [s for s in steps if s.get('status') in ('pending', 'running')]
                            if not pending_steps:
                                return None
                            
                            _plan_resume_count += 1
                            # constructremindmessage
                            pending_names = ', '.join(
                                f'"{s.get("title", s.get("description", s["id"]))}"'
                                for s in pending_steps[:5]
                            )
                            # getlatest  Plan context
                            plan_ctx = self._plan_manager.get_plan_for_context(self._session_id)
                            resume_msg = (
                                f"[Plan Incomplete] countplanstillnotcomplete! completed {done_count}/{total} step. \n"
                                f"notcompletestep: {pending_names}\n"
                                f"pleasestandi.e.resumeexecutebelowonenotcomplete step. don'tstop, don'tsummary, resumecalltoolexecute. \n"
                            )
                            if plan_ctx:
                                resume_msg += f"\n{plan_ctx}"
                            return resume_msg
                        except Exception as e:
                            _dbg(f"[Plan] Incomplete check error: {e}")
                            return None
                    _plan_resume_callback = _check_plan_incomplete
                
                result = self.client.agent_loop_auto(
                    messages=messages,
                    model=model,
                    provider=provider,
                    max_iterations=_max_iter,
                    max_tokens=None,
                    enable_thinking=use_think,
                    supports_vision=supports_vision,
                    tools_override=tools,
                    context_limit=context_limit,
                    on_content=lambda c: self._on_content_with_limit(c),
                    on_thinking=lambda t: self._on_thinking_chunk(t),
                    on_tool_call=lambda n, a: (
                        None  # create_plan alreadyin on_tool_args_delta inprocess
                        if n == 'create_plan' else
                        (self._addStatus.emit(f"[tool]{n}"), self._showToolStatus.emit(n))
                        if n not in _silent else None
                    ),
                    on_tool_result=lambda n, a, r: (
                        (self._add_tool_result(n, r, a), self._hideToolStatus.emit())
                        if n not in _silent else None
                    ),
                    on_tool_args_delta=lambda name, delta, acc: (
                        self._toolArgsDelta.emit(name, delta, acc)
                    ),
                    on_iteration_start=_on_iter,
                    on_plan_incomplete=_plan_resume_callback,
                )
            elif use_agent:
                # ★ Agent mode: complete agent loop, cancreate/modify/deletenode
                result = self.client.agent_loop_auto(
                    messages=messages,
                    model=model,
                    provider=provider,
                    max_iterations=999,  # notlimititeratetimecount
                    max_tokens=None,  # notlimitoutputlength
                    enable_thinking=use_think,
                    supports_vision=supports_vision,
                    tools_override=tools,
                    context_limit=context_limit,
                    on_content=lambda c: self._on_content_with_limit(c),
                    on_thinking=lambda t: self._on_thinking_chunk(t),
                    on_tool_call=lambda n, a: (
                        (self._addStatus.emit(f"[tool]{n}"), self._showToolStatus.emit(n))
                        if n not in self._SILENT_TOOLS else None
                    ),
                    on_tool_result=lambda n, a, r: (
                        (self._add_tool_result(n, r, a), self._hideToolStatus.emit())
                        if n not in self._SILENT_TOOLS else None
                    ),
                    on_tool_args_delta=lambda name, delta, acc: (
                        self._toolArgsDelta.emit(name, delta, acc)
                    ),
                    on_iteration_start=_on_iter,
                )
            elif tools:
                # ★ Ask mode: stilluse agent loop butonlyraiseforread-onlytool
                result = self.client.agent_loop_auto(
                    messages=messages,
                    model=model,
                    provider=provider,
                    max_iterations=15,  # Ask modelimititerate (mainneedisquery) 
                    max_tokens=None,
                    enable_thinking=use_think,
                    supports_vision=supports_vision,
                    tools_override=tools,  # ★ onlypassenterread-onlytool
                    context_limit=context_limit,
                    on_content=lambda c: self._on_content_with_limit(c),
                    on_thinking=lambda t: self._on_thinking_chunk(t),
                    on_tool_call=lambda n, a: (
                        (self._addStatus.emit(f"[tool]{n}"), self._showToolStatus.emit(n))
                        if n not in self._SILENT_TOOLS else None
                    ),
                    on_tool_result=lambda n, a, r: (
                        (self._add_tool_result(n, r, a), self._hideToolStatus.emit())
                        if n not in self._SILENT_TOOLS else None
                    ),
                    on_iteration_start=_on_iter,
                )
            else:
                # notool pureconversationmode (fallback) 
                self._showGenerating.emit()  # ★ show "Generating..." etc.pendingfirstcharacter
                result = {'ok': True, 'content': '', 'tool_calls_history': [], 'iterations': 1, 'usage': {}}
                for chunk in self.client.chat_stream(
                    messages=messages, 
                    model=model, 
                    provider=provider, 
                    tools=None,
                    max_tokens=None,
                ):
                    if self.client.is_stop_requested():
                        self._agentStopped.emit()
                        return
                    
                    ctype = chunk.get('type')
                    if ctype == 'content':
                        content = chunk.get('content', '')
                        result['content'] += content
                        # All goes through _on_content_with_limit (which handles <think> parsing internally)
                        self._on_content_with_limit(content)
                    elif ctype == 'thinking':
                        # native reasoning_content
                        self._on_thinking_chunk(chunk.get('content', ''))
                    elif ctype == 'done':
                        # collectset usage statistics
                        usage = chunk.get('usage', {})
                        if usage:
                            result['usage'] = usage
                    elif ctype == 'stopped':
                        self._agentStopped.emit()
                        return
                    elif ctype == 'error':
                        result = {'ok': False, 'error': chunk.get('error')}
                        break
            
            if self.client.is_stop_requested():
                self._agentStopped.emit()
                return
            
            if result.get('ok'):
                self._agentDone.emit(result)
            else:
                error_msg = result.get('error', 'Unknown error')
                # showmoredetailfine error
                self._agentError.emit(f"API Error: {error_msg}")
                
        except Exception as e:
            import traceback
            if self.client.is_stop_requested():
                self._agentStopped.emit()
            else:
                # showcompleteerrorinfo
                error_detail = f"{type(e).__name__}: {str(e)}"
                _dbg(f"[AI Tab Error] {traceback.format_exc()}")  # Console output
                self._agentError.emit(error_detail)

    def _add_tool_result(self, name: str, result: dict, arguments: dict = None):
        """addtoolresulttoexecuteflow (autocompresslongresult) """
        result_text = str(result.get('result', result.get('error', '')))
        success = result.get('success', True)
        
        # ★ fromtoolresultandparameterinextractnode path, used forafterprocessbarenodename
        self._collect_node_paths_from_tool(result, arguments)
        
        # Compress tool results to save tokens (if the result is very long)
        if self._auto_optimize and len(result_text) > 300:
            compressed_summary = self.token_optimizer.compress_tool_result(result, max_length=200)
            # inhistoryinusecompressversion, but UI inshowcompleteversion
            # note: thisinsideonlyshadowrespondshow, realboundarysavetohistorywhenwillusecompressversion
        
        # === execute_python dedicateduseexpandshow ===
        if name == 'execute_python' and arguments:
            code = arguments.get('code', '')
            if code:
                shell_data = {
                    'code': code,
                    'output': result.get('result', ''),
                    'error': result.get('error', ''),
                    'success': success,
                }
                self._addPythonShell.emit(code, json.dumps(shell_data))
                # at the same timeset ToolCallItem result
                short = f"[ok] Python ({len(code.splitlines())} lines)" if success else f"[err] {result_text[:50]}"
                invoke_on_main(self, "_add_tool_result_ui", name, short)
                # ★ if execute_python causesnodechange, extragenerate checkpoint
                if result.get('_node_changes'):
                    self._addNodeOperation.emit(name, result)
                return
        
        # === execute_shell dedicateduseexpandshow ===
        if name == 'execute_shell' and arguments:
            command = arguments.get('command', '')
            if command:
                shell_data = {
                    'command': command,
                    'output': result.get('result', ''),
                    'error': result.get('error', ''),
                    'success': success,
                    'cwd': arguments.get('cwd', ''),
                }
                self._addSystemShell.emit(command, json.dumps(shell_data))
                short = f"[ok] $ {command[:40]}" if success else f"[err] {result_text[:50]}"
                invoke_on_main(self, "_add_tool_result_ui", name, short)
                return
        
        # ★ throughusenodechangedetect: anytoolifvia before/after snapshotdetecttonodechange, generate checkpoint
        if result.get('_node_changes') and result.get('success'):
            self._addNodeOperation.emit(name, result)
        
        # checkwhetherisnodeoperation, needshighlightshow
        # butifisfailed operation, alsoneedshowerrorinfo
        if name in ('create_node', 'create_nodes_batch', 'create_wrangle_node', 'delete_node', 'set_node_parameter'):
            if result.get('success'):
                # On success, fire the node-operation signal (pass dict directly to avoid JSON serialization overhead)
                self._addNodeOperation.emit(name, result)
                # at the same timeset ToolCallItem result (collapsestyle, canexpandviewcompletecontent) 
                invoke_on_main(self, "_add_tool_result_ui", name, f"[ok] {result_text}")
                return
            else:
                # failedwhenalsoendstreamingpreview
                if name in self._VEX_TOOLS:
                    self._finalize_streaming_preview()
                # failedwhenshowerrorinfo (resumebelowface logic) 
                pass
        
        # addtoexecuteflow (CollapsibleSection style, clickexpandviewcompleteresult) 
        if self._agent_response or self._current_response:
            prefix = "[err]" if not success else "[ok]"
            invoke_on_main(self, "_add_tool_result_ui", name, f"{prefix} {result_text}")
    
    @QtCore.Slot(str, str)
    def _add_tool_result_ui(self, name: str, result: str):
        """in UI threadinaddtoolresult"""
        try:
            resp = self._agent_response or self._current_response
            if resp:
                resp.add_tool_result(name, result)
        except RuntimeError:
            pass  # widget alreadyis clear destroy

    @QtCore.Slot(str, str)
    def _add_collapsible_result(self, name: str, result: str):
        resp = self._agent_response or self._current_response
        if resp:
            resp.add_collapsible(f"Result: {name}", result)

    @staticmethod
    def _extract_node_paths(text: str, tool_name: str = '') -> list:
        """fromtoolreturn resulttextinextract **realboundaryoperation**  node path
        
        onlyextracttruepositiveiscreate/delete node path, ignorecontextinfo
        (parent network, input/output connections, etc. — supplementary paths).
        
        eachtool returnformat:
        - create_node:      "✓/obj/geo1/scatter1 (parentnetwork: /obj/geo1, ...)"
        - create_nodes_batch:"alreadycreate 3 node: /obj/geo1/a, /obj/geo1/b, /obj/geo1/c"
        - create_wrangle_node:"alreadycreate Wrangle node: /obj/geo1/attribwrangle1"
        - delete_node:      "alreadydeletenode: /obj/geo1/scatter1 (parentnetwork: ...)"
        """
        import re
        _PATH_RE = r'(/(?:obj|out|ch|shop|stage|mat|tasks)[/\w]*)'
        
        if tool_name == 'create_node':
            # format: "✓/obj/geo1/scatter1 (parentnetwork: /obj/geo1, ...)"
            # onlyfetch ✓ afterface firstpath
            m = re.match(r'[✓\s]*' + _PATH_RE, text)
            return [m.group(1)] if m else []
        
        if tool_name == 'delete_node':
            # format: "alreadydeletenode: /obj/geo1/scatter1 (parentnetwork: ...)"
            # onlyfetch "alreadydeletenode:" afterface firstpath
            m = re.search(r'alreadydeletenode:\s*' + _PATH_RE, text)
            if m:
                return [m.group(1)]
            # fallback: fetchtextinfirstpath
            m = re.search(_PATH_RE, text)
            return [m.group(1)] if m else []
        
        if tool_name == 'create_nodes_batch':
            # format: "alreadycreate 3 node: /obj/geo1/a, /obj/geo1/b, /obj/geo1/c\nnote: ..."
            # Only parse comma-separated paths on the same line after "node:"
            m = re.search(r'node:\s*(.*)', text)
            if m:
                first_line = m.group(1).split('\n')[0]
                return re.findall(_PATH_RE, first_line)
            # fallback: extractallpath (batchcreateformatnotmatchwhen) 
            return re.findall(_PATH_RE, text)
        
        if tool_name == 'create_wrangle_node':
            # format: "alreadycreate Wrangle node: /obj/geo1/attribwrangle1"
            m = re.search(r'node:\s*' + _PATH_RE, text)
            return [m.group(1)] if m else []
        
        # Unknown tool → conservative strategy: only fetch the first path
        m = re.search(_PATH_RE, text)
        return [m.group(1)] if m else []
    
    # ── streaming VEX preview ─────────────────────────────────────
    # VEX related toolname (onlyhasthissomeonly thenneedsstreamingpreview) 
    _VEX_TOOLS = frozenset({'create_wrangle_node', 'set_node_parameter'})

    # common  VEX/codeparametername (set_node_parameter onlyhasinsetthissomeparameterwhenonly thendostreamingpreview) 
    _VEX_PARAM_NAMES = frozenset({
        'snippet', 'vex_code', 'code', 'script', 'python',
        'sopoutput', 'command', 'expr', 'expression',
    })

    @QtCore.Slot(str, str, str)
    def _on_tool_args_delta(self, tool_name: str, delta: str, accumulated: str):
        """mainthread slot: process tool_call parameterincremental, streamingpreview VEX code / Plan generateprogress"""
        try:
            # ★ Plan mode: create_plan parameterstreaming → create/updatestreamingcard
            if tool_name == 'create_plan':
                # first timecollectto create_plan parameter → standi.e.createstreamingcard
                if self._streaming_plan_card is None:
                    self._on_create_streaming_plan()
                self._show_plan_generation_progress(accumulated)
                self._updateStreamingPlan.emit(accumulated)
                return

            if tool_name not in self._VEX_TOOLS:
                return

            # set_node_parameter onlyfor VEX/codeparameterdostreamingpreview
            if tool_name == 'set_node_parameter':
                # tryfromalreadyaccumulate  JSON inextract param_name
                import re as _re
                m = _re.search(r'"param_name"\s*:\s*"([^"]*)"', accumulated)
                if m:
                    param_name = m.group(1).lower()
                    if param_name not in self._VEX_PARAM_NAMES:
                        return
                # If param_name hasn't shown up yet, don't create the preview (wait until we can confirm it's a VEX parameter)

            # nevercomplete  JSON inincrementalextract VEX code
            code = self._extract_vex_from_partial_json(tool_name, accumulated)
            if not code:
                return
            
            # forin set_node_parameter, onlyhascodeexceedsonefixedlengthonly thenshowpreview (avoidas "1.5" thiskindvaluecreatepreview) 
            if tool_name == 'set_node_parameter' and len(code) < 10 and '\n' not in code:
                return

            # ifstillnothas StreamingCodePreview, thencreate
            if self._streaming_preview is None or self._streaming_preview_tool != tool_name:
                resp = self._agent_response or self._current_response
                if not resp:
                    return
                self._streaming_preview = StreamingCodePreview(tool_name, parent=resp)
                self._streaming_preview_tool = tool_name
                self._streaming_last_code = ""
                resp.details_layout.addWidget(self._streaming_preview)
                self._scroll_agent_to_bottom()

            # updatepreview (StreamingCodePreview withinpartdoincrementalappend) 
            self._streaming_preview.update_code(code)
            self._streaming_last_code = code
        except RuntimeError:
            pass  # widget alreadyisdestroy

    def _extract_vex_from_partial_json(self, tool_name: str, accumulated: str) -> str:
        """nevercomplete  JSON stringinincrementalextract VEX codefield
        
        create_wrangle_node → extract "vex_code" field
        set_node_parameter  → extract "value" field
        """
        import re as _re
        # certainfixedneedextract fieldname
        if tool_name == 'create_wrangle_node':
            field_pattern = r'"vex_code"\s*:\s*"'
        else:
            field_pattern = r'"value"\s*:\s*"'

        m = _re.search(field_pattern, accumulated)
        if not m:
            return ""
        start = m.end()

        # from start start, parse JSON stringcontent (processconvertmeaningcharacter) 
        result_chars = []
        i = start
        while i < len(accumulated):
            ch = accumulated[i]
            if ch == '\\' and i + 1 < len(accumulated):
                next_ch = accumulated[i + 1]
                if next_ch == 'n':
                    result_chars.append('\n')
                elif next_ch == 't':
                    result_chars.append('\t')
                elif next_ch == '"':
                    result_chars.append('"')
                elif next_ch == '\\':
                    result_chars.append('\\')
                elif next_ch == '/':
                    result_chars.append('/')
                elif next_ch == 'r':
                    result_chars.append('\r')
                else:
                    result_chars.append(next_ch)
                i += 2
            elif ch == '"':
                break  # stringcharacterfacequantityend
            else:
                result_chars.append(ch)
                i += 1
        return ''.join(result_chars)

    def _finalize_streaming_preview(self):
        """streamingpreviewend: removepreview widget (ParamDiffWidget willconnectreplaceexpandshowpositivestyle diff) """
        if self._streaming_preview is not None:
            try:
                self._streaming_preview.setVisible(False)
                self._streaming_preview.deleteLater()
            except RuntimeError:
                pass
            self._streaming_preview = None
            self._streaming_preview_tool = ""
            self._streaming_last_code = ""

    @QtCore.Slot(str, str)
    def _on_add_node_operation(self, name: str, result: dict):
        """processnodeoperationhighlightshow"""
        try:
            # ★ toolexecutefinishfinish → endstreamingpreview
            if name in self._VEX_TOOLS:
                self._finalize_streaming_preview()
            
            resp = self._agent_response or self._current_response
            if not resp:
                return
            
            if not isinstance(result, dict):
                result = {}
            
            label = None
            result_text = str(result.get('result', ''))
            undo_snapshot = result.get('_undo_snapshot')  # only delete_node whenwillhas
            
            # ---- collectsetpath & operationtype ----
            op_type = 'create'
            paths: list = []
            
            if name == 'create_node':
                paths = self._extract_node_paths(result_text, 'create_node') or ([result_text] if result_text else [])
                label = NodeOperationLabel('create', 1, paths) if paths else None
            
            elif name in ('create_nodes_batch', 'create_wrangle_node'):
                paths = self._extract_node_paths(result_text, name) or ([result_text] if result_text else [])
                label = NodeOperationLabel('create', len(paths) or 1, paths) if paths else None
            
            elif name == 'delete_node':
                op_type = 'delete'
                paths = self._extract_node_paths(result_text, 'delete_node') or ([result_text] if result_text else [])
                label = NodeOperationLabel('delete', 1, paths) if paths else None
            
            elif name == 'set_node_parameter':
                op_type = 'modify'
                # undo_snapshot packagecontaining node_path, param_name, old_value, new_value
                # ★ No snapshot = parameter value did not change → don't show checkpoint (avoid user confusion)
                if undo_snapshot:
                    node_path = undo_snapshot.get("node_path", "")
                    param_name = undo_snapshot.get("param_name", "")
                    old_val = undo_snapshot.get("old_value", "")
                    new_val = undo_snapshot.get("new_value", "")
                    paths = [node_path] if node_path else []
                    # pass param_diff give NodeOperationLabel, expandshowredgreen diff
                    param_diff = {
                        "param_name": param_name,
                        "old_value": old_val,
                        "new_value": new_val,
                    }
                    label = NodeOperationLabel('modify', 1, paths, param_diff=param_diff) if paths else None
            
            # ★ throughusechangedetect (execute_python, run_skill, copy_node etc.via before/after snapshotdetectto change) 
            node_changes = result.get('_node_changes')
            if node_changes and label is None:
                created = node_changes.get('created', [])
                deleted = node_changes.get('deleted', [])
                labels_to_add = []
                
                if created:
                    c_paths = [n['path'] for n in created]
                    op_type = 'create'
                    paths = c_paths
                    labels_to_add.append(
                        ('create', len(created), c_paths, None)
                    )
                if deleted:
                    d_paths = [n['path'] for n in deleted]
                    if not created:
                        op_type = 'delete'
                        paths = d_paths
                    labels_to_add.append(
                        ('delete', len(deleted), d_paths, None)
                    )
                
                # aseachkindoperationtypegenerateindependentstand  checkpoint label
                for l_op, l_count, l_paths, _ in labels_to_add:
                    l_label = NodeOperationLabel(l_op, l_count, l_paths)
                    l_label.nodeClicked.connect(self._navigate_to_node)
                    l_label.undoRequested.connect(
                        lambda _op=l_op, _paths=list(l_paths), _snap=None:
                            self._undo_node_operation(_op, _paths, _snap)
                    )
                    resp.details_layout.addWidget(l_label)
                    entry = (l_label, l_op, list(l_paths), None)
                    self._pending_ops.append(entry)
                    l_label.decided.connect(self._update_batch_bar)
                
                if labels_to_add:
                    self._update_batch_bar()
                    self._scroll_agent_to_bottom()
                    return  # alreadyprocess, skipbelowface throughuselogic
            
            if label:
                label.nodeClicked.connect(self._navigate_to_node)
                # Use a lambda to capture the current operation context so undo targets exactly this operation
                label.undoRequested.connect(
                    lambda _op=op_type, _paths=list(paths), _snap=undo_snapshot:
                        self._undo_node_operation(_op, _paths, _snap)
                )
                resp.details_layout.addWidget(label)
                
                # ★ tracenotdecideoperation → Undo All / Keep All buttoncansee
                entry = (label, op_type, list(paths), undo_snapshot)
                self._pending_ops.append(entry)
                label.decided.connect(self._update_batch_bar)
                self._update_batch_bar()
            
            self._scroll_agent_to_bottom()
        except RuntimeError:
            pass  # widget alreadyis clear destroy
    
    def _navigate_to_node(self, node_path: str):
        """clicknodelabelwhen, jumptothisnodeandselected"""
        try:
            import hou
            node = hou.node(node_path)
            if node is None:
                self._show_toast(tr('toast.node_not_exist', node_path))
                return
            
            # selectednode
            node.setSelected(True, clear_all_selected=True)
            
            # innetworkedit injumptothisnode
            try:
                editor = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.NetworkEditor)
                if editor:
                    # firstswitchtonode parentnetwork
                    parent = node.parent()
                    if parent:
                        editor.cd(parent.path())
                    editor.homeToSelection()
            except Exception:
                pass
            
            # updatenodecontextbar
            self._refresh_node_context()
            
        except ImportError:
            self._show_toast(tr('toast.houdini_unavailable'))
        except Exception as e:
            self._show_toast(tr('toast.jump_failed', e))
    
    # ----------------------------------------------------------------
    # ★ recursiverestorenodetree (used for undo delete operation) 
    # ----------------------------------------------------------------
    def _restore_node_from_snapshot(self, hou, snapshot: dict, _parent_override=None):
        """Recursively rebuild a node and its full subtree from a snapshot.
        
        Args:
            hou: Houdini modulereference
            snapshot: _snapshot_node generatedsnapshotdict
            _parent_override: if not None, create under this node (used for recursively rebuilding subnodes)
        
        Returns:
            create  hou.Node, or None (failedwhen) 
        """
        if not snapshot:
            return None
        
        parent_path = snapshot.get("parent_path", "")
        node_type = snapshot.get("node_type", "")
        node_name = snapshot.get("node_name", "")
        has_children_snapshot = bool(snapshot.get("children"))
        
        parent = _parent_override or hou.node(parent_path)
        if parent is None:
            return None
        
        # 1) createnode
        # ★ ifsnapshotinhassubnodedata, mustdisallowautocreatedefaultsubnode
        #   otherwise geo etc.contain nodewillautogenerate file1 etc.defaultsubnode, 
        #   withIsrecursiverestore originalsubnodeconflict (nameconflict/multiremainingnode) 
        try:
            if has_children_snapshot:
                new_node = parent.createNode(
                    node_type, node_name,
                    run_init_scripts=False,
                    load_contents=False,
                )
            else:
                new_node = parent.createNode(node_type, node_name)
        except Exception:
            return None
        
        # 2) restoreposition
        pos = snapshot.get("position")
        if pos and len(pos) == 2:
            try:
                new_node.setPosition(hou.Vector2(pos[0], pos[1]))
            except Exception:
                pass
        
        # 3) restoreparameter
        for parm_name, val in snapshot.get("params", {}).items():
            try:
                parm = new_node.parm(parm_name)
                if parm is None:
                    continue
                if isinstance(val, dict) and "expr" in val:
                    lang_str = val.get("lang", "Hscript")
                    lang = (hou.exprLanguage.Python
                            if "python" in lang_str.lower()
                            else hou.exprLanguage.Hscript)
                    parm.setExpression(val["expr"], lang)
                else:
                    parm.set(val)
            except Exception:
                continue
        
        # 4) ★ Clear any leftover default subnodes (defensive — ensure a clean restore)
        if has_children_snapshot:
            try:
                for default_child in list(new_node.children()):
                    try:
                        default_child.destroy()
                    except Exception:
                        pass
            except Exception:
                pass
        
        # 5) ★ recursiverebuildsubnode
        children_map: dict = {}  # name → hou.Node — used later to restore internal connections
        for child_snap in snapshot.get("children", []):
            child_node = self._restore_node_from_snapshot(hou, child_snap, _parent_override=new_node)
            if child_node:
                children_map[child_node.name()] = child_node
        
        # 6) ★ restoresubnodebetween withinpartconnect
        for iconn in snapshot.get("internal_connections", []):
            try:
                src_node = children_map.get(iconn["src_name"])
                dest_node = children_map.get(iconn["dest_name"])
                if src_node and dest_node:
                    dest_node.setInput(iconn["dest_input"], src_node)
            except Exception:
                continue
        
        # 7) restoreexternalinputconnect (onlytoplayernode — subnode externalconnectbyparentlevelcallprocess) 
        if _parent_override is None:
            for conn in snapshot.get("input_connections", []):
                try:
                    src = hou.node(conn["source_path"])
                    if src:
                        new_node.setInput(conn["input_index"], src)
                except Exception:
                    continue
        
        # 8) restoreexternaloutputconnect (onlytoplayernode) 
        if _parent_override is None:
            for conn in snapshot.get("output_connections", []):
                try:
                    dest = hou.node(conn["dest_path"])
                    if dest:
                        dest.setInput(conn["dest_input_index"], new_node, conn.get("output_index", 0))
                except Exception:
                    continue
        
        # 9) restoreflagbit
        try:
            if snapshot.get("display_flag") and hasattr(new_node, 'setDisplayFlag'):
                new_node.setDisplayFlag(True)
            if snapshot.get("render_flag") and hasattr(new_node, 'setRenderFlag'):
                new_node.setRenderFlag(True)
        except Exception:
            pass
        
        return new_node

    def _undo_node_operation(self, op_type: str = 'create',
                              node_paths: list = None,
                              undo_snapshot: dict = None):
        """finecertainundosingletimenodeoperation
        
        - create operation → deletethisnode (by path) 
        - delete operation → fromsnapshotrecursiverebuildthisnodeandallsubnode
        - modify operation → restoreparameteroldvalue
        """
        try:
            import hou
        except ImportError:
            self._show_toast(tr('toast.houdini_unavailable'))
            return
        
        try:
            if op_type == 'modify' and undo_snapshot:
                # ---- undoparametermodify = restoreoldvalue ----
                node_path = undo_snapshot.get("node_path", "")
                param_name = undo_snapshot.get("param_name", "")
                old_value = undo_snapshot.get("old_value")
                is_tuple = undo_snapshot.get("is_tuple", False)
                
                node = hou.node(node_path)
                if node is None:
                    self._show_toast(tr('toast.node_not_found', node_path))
                    return
                
                if is_tuple:
                    parm_tuple = node.parmTuple(param_name)
                    if parm_tuple is None:
                        self._show_toast(tr('toast.param_not_found', param_name))
                        return
                    parm_tuple.set(old_value)
                else:
                    parm = node.parm(param_name)
                    if parm is None:
                        self._show_toast(tr('toast.param_not_found', param_name))
                        return
                    if isinstance(old_value, dict) and "expr" in old_value:
                        lang_str = old_value.get("lang", "Hscript")
                        lang = (hou.exprLanguage.Python
                                if "python" in lang_str.lower()
                                else hou.exprLanguage.Hscript)
                        parm.setExpression(old_value["expr"], lang)
                    else:
                        parm.set(old_value)
                
                self._show_toast(tr('toast.param_restored', param_name))
            
            elif op_type == 'create':
                # ---- undocreate = deletenode ----
                if not node_paths:
                    self._show_toast(tr('toast.missing_path'))
                    return
                deleted = 0
                for p in node_paths:
                    node = hou.node(p)
                    if node is not None:
                        node.destroy()
                        deleted += 1
                if deleted:
                    self._show_toast(tr('toast.undo_create', deleted))
                else:
                    self._show_toast(tr('toast.node_gone'))
            
            elif op_type == 'delete' and undo_snapshot:
                # ---- Undo-delete = recursively rebuild the entire node tree from the snapshot ----
                new_node = self._restore_node_from_snapshot(hou, undo_snapshot)
                if new_node:
                    self._show_toast(tr('toast.node_restored', new_node.path()))
                else:
                    self._show_toast(tr('toast.undo_failed', 'snapshot restore returned None'))
            
            else:
                # fall back: use Houdini native undo
                hou.undos.performUndo()
                self._show_toast(tr('toast.undone'))
            
            self._refresh_node_context()
        
        except Exception as e:
            self._show_toast(tr('toast.undo_failed', e))

    # ---------- Undo All / Keep All batchoperation ----------

    def _update_batch_bar(self):
        """based onnotdecideoperationcountshow/hidebatchoperationbar"""
        # cleanupalreadydecide itemitem (label._decided == True) 
        self._pending_ops = [
            entry for entry in self._pending_ops
            if entry[0] and not entry[0]._decided
        ]
        count = len(self._pending_ops)
        if count > 0:
            self._batch_count_label.setText(f"{count} pending operations")
            self._batch_bar.setVisible(True)
        else:
            self._batch_bar.setVisible(False)

    def _undo_all_ops(self):
        """Undo all pending operations (reverse order — undo latest-created first)."""
        # cleanupalreadydecideitemitem
        self._pending_ops = [
            entry for entry in self._pending_ops
            if entry[0] and not entry[0]._decided
        ]
        if not self._pending_ops:
            self._batch_bar.setVisible(False)
            return
        
        count = 0
        # Reverse order: undo latest-created first (avoids dependency conflicts)
        for label, op_type, paths, snapshot in reversed(self._pending_ops):
            if label._decided:
                continue
            # ★ directlyexecuteundologic, notvia label._on_undo()  signal
            #   because label._on_undo() will emit undoRequested signal, 
            #   and this signal is already connected to _undo_node_operation — would cause double execution.
            #   thisinsideonlyupdate label   UI state, thenaftermanualexecuteonceundo. 
            label._decided = True
            label._undo_btn.setVisible(False)
            label._keep_btn.setVisible(False)
            label._status_label.setText(tr('status.undone'))
            label._status_label.setProperty("state", "undone")
            label._status_label.style().unpolish(label._status_label)
            label._status_label.style().polish(label._status_label)
            label._status_label.setVisible(True)
            self._undo_node_operation(op_type, paths, snapshot)
            count += 1
        
        self._pending_ops.clear()
        self._batch_bar.setVisible(False)
        if count:
            self._show_toast(f"Undid all {count} operations")

    def _keep_all_ops(self):
        """keepallnotdecideoperation"""
        self._pending_ops = [
            entry for entry in self._pending_ops
            if entry[0] and not entry[0]._decided
        ]
        if not self._pending_ops:
            self._batch_bar.setVisible(False)
            return
        
        count = 0
        for label, op_type, paths, snapshot in self._pending_ops:
            if label._decided:
                continue
            label._on_keep()
            label.collapse_diff()  # ★ autocollapse diff expandshowsection
            count += 1
        
        self._pending_ops.clear()
        self._batch_bar.setVisible(False)
        if count:
            self._show_toast(f"Kept all {count} operations")

    @QtCore.Slot(str, str)
    def _on_add_python_shell(self, code: str, result_json: str):
        """process execute_python  dedicateduse UI expandshow"""
        try:
            resp = self._agent_response or self._current_response
            if not resp:
                return
            
            try:
                data = json.loads(result_json)
            except Exception:
                data = {}
            
            raw_output = data.get('output', '')
            error = data.get('error', '')
            success = data.get('success', True)
            
            # fromformatization outputinextractexecutewhenbetweenandcleanupcontent
            # format: "output:\n...\nreturnvalue: ...\nexecutewhenbetween: 0.123s"
            exec_time = 0.0
            clean_parts = []
            
            for line in raw_output.split('\n'):
                time_match = re.match(r'^executewhenbetween:\s*([\d.]+)s$', line.strip())
                if time_match:
                    exec_time = float(time_match.group(1))
                    continue
                # godrop "output:" prefix
                if line.strip() == 'output:':
                    continue
                clean_parts.append(line)
            
            clean_output = '\n'.join(clean_parts).strip()
            
            widget = PythonShellWidget(
                code=code,
                output=clean_output,
                error=error,
                exec_time=exec_time,
                success=success,
                parent=resp
            )
            # putenter Python Shell collapsesectionblock (andnot details_layout) 
            resp.add_shell_widget(widget)
            self._scroll_agent_to_bottom()
        except RuntimeError:
            pass  # widget alreadyis clear destroy

    @QtCore.Slot(str, str)
    def _on_add_system_shell(self, command: str, result_json: str):
        """process execute_shell  dedicateduse UI expandshow"""
        try:
            resp = self._agent_response or self._current_response
            if not resp:
                return

            try:
                data = json.loads(result_json)
            except Exception:
                data = {}

            raw_output = data.get('output', '')
            error = data.get('error', '')
            success = data.get('success', True)
            cwd = data.get('cwd', '')

            # fromoutputinextractexecutewhenbetweenandexitcode
            exec_time = 0.0
            exit_code = 0
            stdout_parts = []

            for line in raw_output.split('\n'):
                # match "exitcode: 0, consumewhen: 0.123s" or "⛔ commandcommandexecution failed: exitcode: 1, consumewhen: ..."
                time_match = re.search(r'consumewhen:\s*([\d.]+)s', line)
                code_match = re.search(r'exitcode:\s*(\d+)', line)
                if time_match:
                    exec_time = float(time_match.group(1))
                if code_match:
                    exit_code = int(code_match.group(1))
                if time_match or code_match:
                    continue
                # partleave stdout / stderr
                if line.strip() == '--- stdout ---':
                    continue
                if line.strip() == '--- stderr ---':
                    continue
                stdout_parts.append(line)

            clean_output = '\n'.join(stdout_parts).strip()

            widget = SystemShellWidget(
                command=command,
                output=clean_output,
                error=error,
                exit_code=exit_code,
                exec_time=exec_time,
                success=success,
                cwd=cwd,
                parent=resp
            )
            resp.add_sys_shell_widget(widget)
            self._scroll_agent_to_bottom()
        except RuntimeError:
            pass  # widget alreadyis clear destroy

    def _on_stop(self):
        self.client.request_stop()

    def _on_set_key(self):
        provider = self._current_provider()
        # Custom provider usededicateduseconfigconversationbox
        if provider == 'custom':
            self._open_custom_provider_dialog()
            return
        names = {'openai': 'OpenAI', 'deepseek': 'DeepSeek', 'glm': 'GLM (Zhipu AI)', 'ollama': 'Ollama', 'openrouter': 'OpenRouter'}

        try:
            from .cursor_widgets import MorfyInputDialog
            key, ok = MorfyInputDialog.get_text(
                self, f"Set {names.get(provider, provider)} API Key",
                "Enter API Key:", password=True)
        except Exception:
            key, ok = QtWidgets.QInputDialog.getText(
                self, f"Set {names.get(provider, provider)} API Key",
                "Enter API Key:", QtWidgets.QLineEdit.Password)

        if ok and key.strip():
            self.client.set_api_key(key.strip(), persist=True, provider=provider)
            self._update_key_status()

    def _on_clear(self):
        # ── ifcurrent session positiveinrun agent, firststop ──
        if self._agent_session_id == self._session_id and self._agent_session_id is not None:
            # 1) requestafterendthreadstop
            self.client.request_stop()
            # 2) disconnect agent foralreadydelete widget  reference (preventcallbackaccessalreadydestroywidget) 
            self._agent_response = None
            self._agent_todo_list = None
            self._agent_chat_layout = None
            self._agent_scroll_area = None
            # 3) replacerunstateandbutton
            self._set_running(False)
        
        self._conversation_history.clear()
        self._context_summary = ""
        self._current_response = None
        self._token_stats = {
            'input_tokens': 0, 'output_tokens': 0,
            'reasoning_tokens': 0,
            'cache_read': 0, 'cache_write': 0,
            'total_tokens': 0, 'requests': 0,
            'estimated_cost': 0.0,
        }
        self._call_records = []
        
        # ── cleanuppendingconfirmoperationlistandbatchoperationbar ──
        self._pending_ops.clear()
        self._batch_bar.setVisible(False)
        self._session_node_map.clear()
        
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # old todo_list alreadyis deleteLater, createnew
        self.todo_list = self._create_todo_list(self.chat_container)
        if self._session_id in self._sessions:
            self._sessions[self._session_id]['todo_list'] = self.todo_list
        
        # syncto sessions dict
        self._save_current_session_state()
        
        # ★ clearemptyafterdeletediskon old session file (preventresidualkeepdatainrestartafterisrestore) 
        try:
            old_session_file = self._cache_dir / f"session_{self._session_id}.json"
            if old_session_file.exists():
                old_session_file.unlink()
        except Exception:
            pass
        # ★ standi.e.update manifest (removealreadyclearempty sessionitemitem) 
        try:
            self._update_manifest()
        except Exception:
            pass
        
        # replacelabelname
        for i in range(self.session_tabs.count()):
            if self.session_tabs.tabData(i) == self._session_id:
                self.session_tabs.setTabText(i, f"Chat {self._session_counter}")
                break
        
        # updatestatisticsshow
        self._update_token_stats_display()
        self._update_context_stats()

    # ============================================================
    # ★ slashcommandcommandexecute
    # ============================================================

    def _execute_slash_command(self, command: str):
        """executeslashcommandcommand — by InputAreaMixin._on_slash_command_selected call"""
        handler = getattr(self, f'_slash_{command}', None)
        if handler:
            handler()
        else:
            _dbg(f"[SlashCommand] Unknown command: /{command}")

    def _slash_clear(self):
        """/ clear — clearemptycurrentconversation"""
        self._on_clear()

    def _slash_new(self):
        """/new — createsession"""
        self._new_session()

    def _slash_memory(self):
        """/memory — showmemorysystemstate"""
        from ..utils.memory_store import get_memory_store, ABSTRACTION_LEVELS, MEMORY_CATEGORIES
        try:
            store = get_memory_store()
            stats = store.get_stats()
            core_mems = store.get_core_memories(max_count=10)

            lines = ["📊 **long-termmemorysystemstate**\n"]
            lines.append(f"- Episodic memory: {stats.get('episodic_count', 0)} items")
            lines.append(f"- semanticmemory (Semantic): {stats.get('semantic_count', 0)} item")
            lines.append(f"- strategic memory (Procedural): {stats.get('procedural_count', 0)} item")
            lines.append(f"- embedafterend: {stats.get('backend', 'unknown')}")
            lines.append(f"- Embedding dimension: {stats.get('embedding_dim', 0)}")

            if core_mems:
                lines.append(f"\n🧠 **corememory (L0)** — {len(core_mems)} item:")
                for i, mem in enumerate(core_mems, 1):
                    conf = f"(conf={mem.confidence:.2f})" if hasattr(mem, 'confidence') else ""
                    lines.append(f"  {i}. [{mem.category}] {mem.rule} {conf}")
            else:
                lines.append("\n🧠 Core memory (L0): none yet")

            # showgrowthrefermarker
            if self._memory_initialized and self._growth_tracker:
                try:
                    gm = self._growth_tracker.get_growth_metrics()
                    lines.append(f"\n📈 **growthrefermarker:**")
                    lines.append(f"  - succeededrate: {gm.get('success_rate', 0):.1%}")
                    lines.append(f"  - errorrate: {gm.get('error_rate', 0):.1%}")
                    lines.append(f"  - growthpart: {gm.get('growth_score', 0):.2f}")
                    lines.append(f"  - taskcount: {gm.get('total_tasks', 0)}")
                except Exception:
                    pass

            content = "\n".join(lines)
            self._add_user_message("[/memory]")
            resp = self._add_ai_response()
            resp.set_content(content)
            resp.finalize()
        except Exception as e:
            self._add_user_message("[/memory]")
            resp = self._add_ai_response()
            resp.set_content(f"❌ Memory system not ready: {e}")
            resp.finalize()

    def _slash_remember(self):
        """/remember — popupoutconversationboxletuserinputneedremember content"""
        from ..utils.memory_store import get_memory_store, SemanticRecord

        text, ok = QtWidgets.QInputDialog.getText(
            self, "📌 Remember preference", "Enter content to remember permanently (saved as L0 core memory):"
        )
        if not ok or not text.strip():
            return

        try:
            store = get_memory_store()
            record = SemanticRecord(
                rule=text.strip(),
                confidence=1.0,
                category="preference",
                abstraction_level=0,
            )
            rid = store.add_semantic(record)
            self._add_user_message(f"[/remember] {text.strip()}")
            resp = self._add_ai_response()
            resp.set_content(f"✅ alreadywritecorememory (L0): {text.strip()}\nID: `{rid}`")
            resp.finalize()
        except Exception as e:
            self._add_user_message(f"[/remember]")
            resp = self._add_ai_response()
            resp.set_content(f"❌ writememoryfailed: {e}")
            resp.finalize()

    def _slash_forget(self):
        """/forget — searchanddeletememory"""
        from ..utils.memory_store import get_memory_store

        keyword, ok = QtWidgets.QInputDialog.getText(
            self, "🧹 clearremovememory", "inputkeywordsearchneeddelete memory:"
        )
        if not ok or not keyword.strip():
            return

        try:
            store = get_memory_store()
            results = store.search_all_levels(
                query=keyword.strip(), top_k=5, min_confidence=0.0
            )
            if not results:
                self._add_user_message(f"[/forget] {keyword.strip()}")
                resp = self._add_ai_response()
                resp.set_content("notfindtomatch memory. ")
                resp.finalize()
                return

            # showfindto memory, letuserselectdelete
            items = []
            for rec, score in results:
                display = f"[L{rec.abstraction_level}][{rec.category}] {rec.rule[:60]} (conf={rec.confidence:.2f})"
                items.append((rec.id, display))

            choices = [d for _, d in items]
            choice, ok2 = QtWidgets.QInputDialog.getItem(
                self, "selectneeddelete memory", "findtoor lessmatchmemory:", choices, 0, False
            )
            if not ok2:
                return

            idx = choices.index(choice)
            del_id = items[idx][0]
            store.delete_semantic(del_id)

            self._add_user_message(f"[/forget] {keyword.strip()}")
            resp = self._add_ai_response()
            resp.set_content(f"🗑 alreadydeletememory: {choice}")
            resp.finalize()
        except Exception as e:
            self._add_user_message(f"[/forget]")
            resp = self._add_ai_response()
            resp.set_content(f"❌ operationfailed: {e}")
            resp.finalize()

    def _slash_search_mem(self):
        """/search_mem — searchlong-termmemory"""
        from ..utils.memory_store import get_memory_store, ABSTRACTION_LEVELS

        keyword, ok = QtWidgets.QInputDialog.getText(
            self, "🔍 searchmemory", "inputsearchkeyword:"
        )
        if not ok or not keyword.strip():
            return

        try:
            store = get_memory_store()
            results = store.search_all_levels(
                query=keyword.strip(), top_k=10, min_confidence=0.0
            )

            self._add_user_message(f"[/search_mem] {keyword.strip()}")
            resp = self._add_ai_response()

            if not results:
                resp.set_content("notfindtorelatedmemory. ")
            else:
                lines = [f"🔍 **searchresult** — keyword: `{keyword.strip()}`  ({len(results)} item)\n"]
                for i, (rec, score) in enumerate(results, 1):
                    level_name = ABSTRACTION_LEVELS.get(rec.abstraction_level, "unknown")
                    lines.append(
                        f"{i}. **[L{rec.abstraction_level} {level_name}]** [{rec.category}] "
                        f"conf={rec.confidence:.2f}  rel={score:.3f}\n"
                        f"   {rec.rule}"
                    )
                resp.set_content("\n".join(lines))
            resp.finalize()
        except Exception as e:
            self._add_user_message(f"[/search_mem]")
            resp = self._add_ai_response()
            resp.set_content(f"❌ searchfailed: {e}")
            resp.finalize()

    def _slash_memories(self):
        """/memories — open the memory library manager window (CRUD on episodic / semantic / strategy)."""
        try:
            from .memory_manager_dialog import MemoryManagerDialog
            # Call exec_ directly to avoid depending on the exec_centered staticmethod (older or hot-reloaded modules may lack it and raise)
            MemoryManagerDialog(self).exec_()
        except Exception as e:
            # Don't re-import MemoryMgrSheet here: stale modules / hot-reload residue could re-trigger ImportError
            QtWidgets.QMessageBox.critical(
                None,
                tr('memory_mgr.title'),
                f"{tr('memory_mgr.err_load')}\n{e}",
            )

    def _slash_network(self):
        """/network — readnetworkstructure"""
        self._on_read_network()

    def _slash_selection(self):
        """/selection — readselectednode"""
        self._on_read_selection()

    def _slash_skills(self):
        """/skills — columnoutallskillcan"""
        result = self.mcp._tool_list_skills({})
        self._add_user_message("[/skills]")
        resp = self._add_ai_response()
        if result.get('success'):
            resp.set_content(result.get('result', 'nocanuse Skill'))
        else:
            resp.set_content(f"❌ {result.get('error', 'notknowerror')}")
        resp.finalize()

    def _slash_status(self):
        """/status — showsystemcomprehensivemergestate"""
        lines = ["📊 **System state overview**\n"]

        # contextstatistics
        token_stats = self._token_stats
        lines.append("**Token statistics:**")
        lines.append(f"  - input: {token_stats.get('input_tokens', 0):,}")
        lines.append(f"  - output: {token_stats.get('output_tokens', 0):,}")
        lines.append(f"  - total: {token_stats.get('total_tokens', 0):,}")
        lines.append(f"  - requesttimecount: {token_stats.get('requests', 0)}")
        cost = token_stats.get('estimated_cost', 0.0)
        if cost > 0:
            lines.append(f"  - pre-estimatecostuse: ${cost:.4f}")
        lines.append(f"  - conversationroundcount: {len(self._conversation_history)}")

        # memorystatistics
        if self._memory_initialized and self._memory_store:
            try:
                stats = self._memory_store.get_stats()
                lines.append(f"\n**memorysystem:**")
                lines.append(f"  - Episodic: {stats.get('episodic_count', 0)}")
                lines.append(f"  - semantic: {stats.get('semantic_count', 0)}")
                lines.append(f"  - strategy: {stats.get('procedural_count', 0)}")
            except Exception:
                pass

        # growthrefermarker
        if self._memory_initialized and self._growth_tracker:
            try:
                gm = self._growth_tracker.get_growth_metrics()
                lines.append(f"\n**growthrefermarker:**")
                lines.append(f"  - succeededrate: {gm.get('success_rate', 0):.1%}")
                lines.append(f"  - growthpart: {gm.get('growth_score', 0):.2f}")
                lines.append(f"  - Cumulative tasks: {gm.get('total_tasks', 0)}")
            except Exception:
                pass

        self._add_user_message("[/status]")
        resp = self._add_ai_response()
        resp.set_content("\n".join(lines))
        resp.finalize()

    def _slash_export(self):
        """/export — importouttrainingdata"""
        self._on_export_training_data()

    def _slash_image(self):
        """/image — attachimage"""
        self._on_attach_image()

    def _slash_help(self):
        """/help — showallslashcommandcommand"""
        from .cursor_widgets import SLASH_COMMANDS
        from .i18n import get_language

        is_zh = (get_language() == 'zh')
        lines = ["❓ **canuseslashcommandcommand**\n"]
        for cmd, icon, lbl_zh, lbl_en, desc_zh, desc_en, cat in SLASH_COMMANDS:
            label = lbl_zh if is_zh else lbl_en
            desc = desc_zh if is_zh else desc_en
            lines.append(f"  {icon} `/{cmd}` — {label}: {desc}")

        self._add_user_message("[/help]")
        resp = self._add_ai_response()
        resp.set_content("\n".join(lines))
        resp.finalize()

    def _on_read_network(self):
        """Stage the current network path as an @mention — does NOT auto-send.

        User can append their own question and press Send.
        """
        try:
            import hou  # type: ignore
            editors = [p for p in hou.ui.paneTabs()
                       if p.type() == hou.paneTabType.NetworkEditor]
            if not editors:
                self._show_toast("No active network editor")
                return
            pwd = editors[0].pwd()
            if pwd is None:
                self._show_toast("Could not determine current network")
                return
            net_path = pwd.path()
        except Exception as e:
            self._show_toast(f"Read network failed: {e}")
            return

        prefix = f"@{net_path} "
        current = self.input_edit.toPlainText()
        new_text = prefix + current
        self.input_edit.setPlainText(new_text)

        cursor = self.input_edit.textCursor()
        cursor.setPosition(len(prefix))
        self.input_edit.setTextCursor(cursor)
        self.input_edit.setFocus()

        self._refresh_node_context()
        self._show_toast(f"Added {net_path} — type your question and press Send")

    # ============================================================
    # imageinputsupport
    # ============================================================
    
    def _current_model_supports_vision(self) -> bool:
        """checkcurrentselected modelwhethersupportimageinput"""
        model = self.model_combo.currentText()
        features = self._model_features.get(model, {})
        return features.get('supports_vision', False)
    
    def _on_attach_image(self):
        """Open file dialog to attach an image"""
        if not self._current_model_supports_vision():
            model = self.model_combo.currentText()
            self._show_toast(
                f"Model {model} does not support image input. "
                f"Switch to a vision-capable model (Claude, GPT-5.2, etc.)."
            )
            return
        
        file_paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "selectimage", "",
            "Images (*.png *.jpg *.jpeg *.gif *.webp *.bmp);;All Files (*)"
        )
        for fp in file_paths:
            self._add_image_from_path(fp)
    
    def _add_image_from_path(self, file_path: str):
        """fromfile pathloadimageandaddtopendingsendlist (autoscalepassedlargeimage) """
        import base64
        try:
            # ★ Load via QImage, route through the unified scaling logic
            qimg = QtGui.QImage(file_path)
            if qimg.isNull():
                _dbg(f"[AI Tab] Cannot load image: {file_path}")
                return
            qimg = self._resize_image_if_needed(qimg, self._MAX_IMAGE_DIMENSION)
            
            ext = os.path.splitext(file_path)[1].lower()
            # preferredkeeporiginalformat; BMP/GIF etc.notsuitmergedirectlysend API, statsoneconvert PNG
            if ext in ('.jpg', '.jpeg'):
                fmt, media_type = 'JPEG', 'image/jpeg'
            elif ext == '.webp':
                fmt, media_type = 'WEBP', 'image/webp'
            else:
                fmt, media_type = 'PNG', 'image/png'
            
            buf = QtCore.QBuffer()
            buf.open(QtCore.QIODevice.WriteOnly)
            quality = 90 if fmt == 'JPEG' else -1
            qimg.save(buf, fmt, quality)
            raw_bytes = buf.data().data()
            buf.close()
            
            # ★ passedlargewhendowngradeas JPEG compress
            if len(raw_bytes) > self._MAX_IMAGE_BYTES and fmt != 'JPEG':
                buf2 = QtCore.QBuffer()
                buf2.open(QtCore.QIODevice.WriteOnly)
                qimg.save(buf2, 'JPEG', 85)
                raw_bytes = buf2.data().data()
                buf2.close()
                media_type = 'image/jpeg'
                _dbg(f"[AI Tab] Image too large, converted to JPEG ({len(raw_bytes)//1024}KB)")
            
            b64 = base64.b64encode(raw_bytes).decode('utf-8')
            self._add_pending_image(b64, media_type)
        except Exception as e:
            _dbg(f"[AI Tab] Load image failed: {e}")
    
    # ★ Image-size limit: images over this resolution are auto-scaled (prevents base64 too-large API 400 errors)
    _MAX_IMAGE_DIMENSION = 2048  # mostlongedgenotexceeds 2048px
    _MAX_IMAGE_BYTES = 5 * 1024 * 1024  # Pre-base64 raw byte cap ~5MB (post-encode ~6.7MB)

    @staticmethod
    def _resize_image_if_needed(image: 'QtGui.QImage', max_dim: int = 2048) -> 'QtGui.QImage':
        """ifimageexceeds max_dim, etc.comparescale. returnscaleafter  QImage. """
        w, h = image.width(), image.height()
        if w <= max_dim and h <= max_dim:
            return image
        if w > h:
            new_w = max_dim
            new_h = int(h * max_dim / w)
        else:
            new_h = max_dim
            new_w = int(w * max_dim / h)
        _dbg(f"[AI Tab] Image too large ({w}x{h}), auto-resized to {new_w}x{new_h}")
        return image.scaled(new_w, new_h, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)

    def _on_image_dropped(self, image: 'QtGui.QImage'):
        """ChatInput dragorpasteimage callback"""
        if not self._current_model_supports_vision():
            return
        import base64
        # ★ autoscalepassedlargeimage
        image = self._resize_image_if_needed(image, self._MAX_IMAGE_DIMENSION)
        buf = QtCore.QBuffer()
        buf.open(QtCore.QIODevice.WriteOnly)
        image.save(buf, "PNG")
        raw_bytes = buf.data().data()
        buf.close()
        # ★ if PNG stillthenpassedlarge, changeuse JPEG compress
        if len(raw_bytes) > self._MAX_IMAGE_BYTES:
            buf2 = QtCore.QBuffer()
            buf2.open(QtCore.QIODevice.WriteOnly)
            image.save(buf2, "JPEG", 85)
            raw_bytes = buf2.data().data()
            buf2.close()
            media_type = 'image/jpeg'
            _dbg(f"[AI Tab] PNG too large, converted to JPEG (quality=85, {len(raw_bytes)//1024}KB)")
        else:
            media_type = 'image/png'
        b64 = base64.b64encode(raw_bytes).decode('utf-8')
        self._add_pending_image(b64, media_type)
    
    def _add_pending_image(self, b64_data: str, media_type: str):
        """addimagetopendingsendlistandinpreviewsectionshowthumbnaildiagram (clickcanzoom in) """
        # createthumbnaildiagramandcomplete pixmap
        img_bytes = __import__('base64').b64decode(b64_data)
        full_pixmap = QtGui.QPixmap()
        full_pixmap.loadFromData(img_bytes)
        thumb = full_pixmap.scaled(60, 60, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        
        # savestore
        idx = len(self._pending_images)
        self._pending_images.append((b64_data, media_type, thumb))
        
        # createpreview widget
        img_widget = QtWidgets.QWidget()
        img_layout = QtWidgets.QVBoxLayout(img_widget)
        img_layout.setContentsMargins(2, 2, 2, 2)
        img_layout.setSpacing(1)
        
        lbl = ClickableImageLabel(thumb, full_pixmap)
        lbl.setObjectName("imgThumb")
        img_layout.addWidget(lbl)
        
        # deletebutton
        rm_btn = QtWidgets.QPushButton("x")
        rm_btn.setFixedSize(16, 16)
        rm_btn.setObjectName("imgRemoveBtn")
        rm_btn.clicked.connect(lambda checked=False, i=idx: self._remove_pending_image(i))
        img_layout.addWidget(rm_btn, alignment=QtCore.Qt.AlignCenter)
        
        # insertto stretch before
        count = self.image_preview_layout.count()
        self.image_preview_layout.insertWidget(count - 1, img_widget)
        self.image_preview_container.setVisible(True)
    
    def _remove_pending_image(self, index: int):
        """removependingsendimage"""
        if 0 <= index < len(self._pending_images):
            self._pending_images[index] = None  # markasalreadydelete
            self._rebuild_image_preview()  # filter None afterrebuildwholepreviewsection
    
    def _rebuild_image_preview(self):
        """renewbuildimagepreviewsection"""
        # clearremoveall widget (keep stretch) 
        while self.image_preview_layout.count() > 1:
            item = self.image_preview_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # renewfilterandadd
        new_images = [(b64, mt, th) for entry in self._pending_images 
                      if entry is not None for b64, mt, th in [entry]]
        self._pending_images = list(new_images)
        
        if not self._pending_images:
            self.image_preview_container.setVisible(False)
            return
        
        for i, (b64, mt, thumb) in enumerate(self._pending_images):
            img_widget = QtWidgets.QWidget()
            img_layout = QtWidgets.QVBoxLayout(img_widget)
            img_layout.setContentsMargins(2, 2, 2, 2)
            img_layout.setSpacing(1)
            
            # from base64 stilloriginalcomplete pixmap used forzoom inpreview
            full_pixmap = QtGui.QPixmap()
            full_pixmap.loadFromData(__import__('base64').b64decode(b64))
            lbl = ClickableImageLabel(thumb, full_pixmap)
            lbl.setObjectName("imgThumb")
            img_layout.addWidget(lbl)
            
            rm_btn = QtWidgets.QPushButton("x")
            rm_btn.setFixedSize(16, 16)
            rm_btn.setObjectName("imgRemoveBtn")
            rm_btn.clicked.connect(lambda checked=False, idx=i: self._remove_pending_image(idx))
            img_layout.addWidget(rm_btn, alignment=QtCore.Qt.AlignCenter)
            
            count = self.image_preview_layout.count()
            self.image_preview_layout.insertWidget(count - 1, img_widget)
    
    def _clear_pending_images(self):
        """clearemptyallpendingsendimage"""
        self._pending_images.clear()
        while self.image_preview_layout.count() > 1:
            item = self.image_preview_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.image_preview_container.setVisible(False)
    
    def _build_multimodal_content(self, text: str, images: list) -> list:
        """buildpackagecontainingtextandimage multimodalmessagecontent (OpenAI Vision API format) 
        
        Args:
            text: usertextmessage
            images: List of (base64_data, media_type, thumbnail) tuples
            
        Returns:
            list: content countgroup, packagecontaining text and image_url item
        """
        # ★ API support  media type whitenamesingle (BMP etc.needsfirstconvertswap) 
        _SUPPORTED_MEDIA = {'image/png', 'image/jpeg', 'image/gif', 'image/webp'}
        
        content_parts = []
        # ★ Always add a text part (even if empty, as a placeholder — some APIs require at least one text block)
        content_parts.append({"type": "text", "text": text or " "})
        # addimage
        for b64_data, media_type, _thumb in images:
            if not b64_data:
                continue  # skipemptydata
            # ★ not supported  media type downgradeas image/png
            if media_type not in _SUPPORTED_MEDIA:
                media_type = 'image/png'
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{media_type};base64,{b64_data}"
                }
            })
        return content_parts
    
    def _on_read_selection(self):
        """Stage the selected nodes as @mentions in the chat input — does NOT auto-send.

        User can then add their own question (e.g. "What does this do?") and press Send.
        The @mentions are recognized by the AI as node context (already supported in
        the @-completer flow).
        """
        try:
            import hou  # type: ignore
            selected = hou.selectedNodes()
        except Exception as e:
            self._show_toast(f"Read selection failed: {e}")
            return

        if not selected:
            self._show_toast("No nodes selected in Houdini")
            return

        # Build "@/obj/geo1/nodeA @/obj/geo1/nodeB " prefix
        prefix = " ".join(f"@{n.path()}" for n in selected) + " "

        # Insert prefix at the start of the input box, keep any existing text after
        current = self.input_edit.toPlainText()
        new_text = prefix + current
        self.input_edit.setPlainText(new_text)

        # Place cursor right after the prefix so the user can keep typing
        cursor = self.input_edit.textCursor()
        cursor.setPosition(len(prefix))
        self.input_edit.setTextCursor(cursor)
        self.input_edit.setFocus()

        # Refresh node context bar (header indicator)
        self._refresh_node_context()
        self._show_toast(f"Added {len(selected)} node(s) — type your question and press Send")

    def _refresh_node_context(self):
        """flushnewnodecontextbar (showcurrentnetwork pathandselectednode) """
        try:
            import hou
            # getcurrentnetworkedit  workpath
            path = "/obj"
            editors = [p for p in hou.ui.paneTabs()
                       if p.type() == hou.paneTabType.NetworkEditor]
            if editors:
                pwd = editors[0].pwd()
                if pwd:
                    path = pwd.path()
            # getselectednode
            selected = [n.path() for n in hou.selectedNodes()]
            self.node_context_bar.update_context(path, selected)
        except Exception:
            self.node_context_bar.update_context("/obj")

    def _collect_scene_context(self) -> dict:
        """[mainthread] collectset Houdini scenecontextused forauto RAG addstrong
        
        returnscenecontext dict, passgivebackgroundthread  _auto_rag_retrieve use. 
        packagecontaining: currentnetwork path, selectednodetype, selectednodename. 
        """
        ctx = {'network_path': '', 'selected_types': [], 'selected_names': []}
        try:
            import hou  # type: ignore
            # currentnetwork path
            editors = [p for p in hou.ui.paneTabs()
                       if p.type() == hou.paneTabType.NetworkEditor]
            if editors:
                pwd = editors[0].pwd()
                if pwd:
                    ctx['network_path'] = pwd.path()
            # selectednode typeandname
            for n in hou.selectedNodes()[:5]:  # at most 5 , avoidpassedmulti
                ctx['selected_types'].append(n.type().name())
                ctx['selected_names'].append(n.name())
        except Exception:
            pass
        return ctx

    def _on_create_wrangle(self, vex_code: str):
        """fromcodeblockonekeycreate Wrangle node"""
        result = self.mcp.execute_tool("create_wrangle_node", {"vex_code": vex_code})
        if result.get("success"):
            resp = self._add_ai_response()
            resp.set_content(f"{result.get('result', 'alreadycreate Wrangle node')}")
            resp.finalize()
            self._refresh_node_context()
        else:
            resp = self._add_ai_response()
            resp.set_content(f"error: {result.get('error', 'create Wrangle failed')}")
            resp.finalize()

    def _on_export_training_data(self):
        """importoutcurrentconversationastrainingdata"""
        if not self._conversation_history:
            QtWidgets.QMessageBox.warning(self, "Export failed", "No conversation history to export")
            return

        # statisticsconversationinfo
        user_count = sum(1 for m in self._conversation_history if m.get('role') == 'user')
        assistant_count = sum(1 for m in self._conversation_history if m.get('role') == 'assistant')

        if user_count == 0:
            QtWidgets.QMessageBox.warning(self, "Export failed", "No user messages in conversation")
            return

        # askimportoutselectitem
        msg_box = QtWidgets.QMessageBox(self)
        msg_box.setWindowTitle("Export Training Data")
        msg_box.setText(f"Conversation has {user_count} user messages and {assistant_count} AI replies.\n\nChoose export mode:")
        msg_box.setInformativeText(
            "• Split mode: one training sample per turn (recommended, more samples)\n"
            "• Full mode: the whole conversation as a single sample"
        )

        split_btn = msg_box.addButton("Split mode", QtWidgets.QMessageBox.ActionRole)
        full_btn = msg_box.addButton("Full mode", QtWidgets.QMessageBox.ActionRole)
        cancel_btn = msg_box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
        
        msg_box.exec_()
        
        clicked = msg_box.clickedButton()
        if clicked == cancel_btn:
            return
        
        split_by_user = (clicked == split_btn)
        
        # importout
        try:
            from ..utils.training_data_exporter import ChatTrainingExporter
            
            exporter = ChatTrainingExporter()
            filepath = exporter.export_conversation(
                self._conversation_history,
                system_prompt=self._system_prompt,
                split_by_user=split_by_user
            )
            
            # showsucceededmessage
            response = self._add_ai_response()
            response.add_status("Training data exported")
            
            # readgeneratedlikethiscount
            sample_count = 0
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    sample_count = sum(1 for _ in f)
            except:
                pass
            
            response.set_content(
                f"Training data exported!\n\n"
                f"File: {filepath}\n"
                f"Samples: {sample_count}\n"
                f"Turns: {user_count}\n"
                f"Mode: {'Split' if split_by_user else 'Full'}\n\n"
                f"Note: file is JSONL — ready for OpenAI/DeepSeek fine-tuning."
            )
            response.finalize()
            
            # Ask whether to open the containing folder
            reply = QtWidgets.QMessageBox.question(
                self,
                "Export complete",
                f"Generated {sample_count} training samples.\n\nOpen the folder?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )
            
            if reply == QtWidgets.QMessageBox.Yes:
                import os
                import subprocess
                folder = os.path.dirname(filepath)
                if os.name == 'nt':  # Windows
                    os.startfile(folder)
                else:  # macOS/Linux
                    subprocess.run(['open' if 'darwin' in __import__('sys').platform else 'xdg-open', folder])
        
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Export error", f"Error exporting training data: {str(e)}")

    # ===== cachemanage =====
    
    def _on_cache_menu(self):
        """showcachemenusingle"""
        menu = QtWidgets.QMenu(self)
        
        # Save the archive (standalone file)
        archive_action = menu.addAction("Archive current conversation")
        archive_action.triggered.connect(self._archive_cache)
        
        # loadconversation
        load_action = menu.addAction("Load conversation…")
        load_action.triggered.connect(self._load_cache_dialog)
        
        menu.addSeparator()
        
        # compressassummary (reduce token) 
        compress_action = menu.addAction("Compress old conversation into summary")
        compress_action.triggered.connect(self._compress_to_summary)
        
        # columnoutallcache
        list_action = menu.addAction("View all caches")
        list_action.triggered.connect(self._list_caches)
        
        menu.addSeparator()
        
        # autosavetoggle
        auto_save_action = menu.addAction("[on] Auto-save" if self._auto_save_cache else "Auto-save")
        auto_save_action.setCheckable(True)
        auto_save_action.setChecked(self._auto_save_cache)
        auto_save_action.triggered.connect(lambda: setattr(self, '_auto_save_cache', not self._auto_save_cache))
        
        # showmenusingle
        # btn_cache may be hidden (triggered via overflow ···) — fall back to cursor pos
        if self.btn_cache.isVisible():
            menu.exec_(self.btn_cache.mapToGlobal(QtCore.QPoint(0, self.btn_cache.height())))
        else:
            menu.exec_(QtGui.QCursor.pos())
    
    @staticmethod
    def _strip_images_for_cache(history: list) -> list:
        """strip conversation_history in  base64 imagedata, 
        Replace with placeholder text to dramatically shrink the cache file size.
        Returns a deep copy; does not modify the original history.
        """
        import copy
        stripped = []
        for msg in history:
            content = msg.get('content')
            if isinstance(content, list):
                # multimodalmessage: content is [{type:text,...}, {type:image_url,...}, ...]
                new_parts = []
                for part in content:
                    if part.get('type') == 'image_url':
                        url = part.get('image_url', {}).get('url', '')
                        if url.startswith('data:'):
                            # replaceswap base64 asoccupybitsymbol, keep media type info
                            media_type = url.split(';')[0].replace('data:', '')
                            new_parts.append({
                                'type': 'text',
                                'text': f'[Image: {media_type}]',
                            })
                        else:
                            new_parts.append(copy.copy(part))
                    else:
                        new_parts.append(copy.copy(part))
                new_msg = msg.copy()
                new_msg['content'] = new_parts
                stripped.append(new_msg)
            else:
                stripped.append(msg)  # notmultimodalmessagedirectlyreference (str/None notcanchange) 
        return stripped
    
    def _build_cache_data(self) -> dict:
        """buildcachedatadict"""
        todo_data = []
        if hasattr(self, 'todo_list') and self.todo_list:
            todo_data = self.todo_list.get_todos_data()
        return {
            'version': '1.0',
            'session_id': self._session_id,
            'created_at': datetime.now().isoformat(),
            'message_count': len(self._conversation_history),
            'estimated_tokens': self._calculate_context_tokens(),
            'conversation_history': self._conversation_history,
            'context_summary': self._context_summary,
            'todo_summary': self.todo_list.get_todos_summary() if hasattr(self, 'todo_list') else "",
            'todo_data': todo_data,
            'token_stats': self._token_stats.copy(),
        }

    def _on_destroyed(self):
        """Widget isdestroywhenmark, preventoldinstance  atexit/aboutToQuit callbackoverridenewdata"""
        self._destroyed = True
        try:
            app = QtWidgets.QApplication.instance()
            if app:
                try:
                    app.aboutToQuit.disconnect(self._save_all_sessions)
                except (TypeError, RuntimeError):
                    pass
        except Exception:
            pass

    def _periodic_save_all(self):
        """fixedperiodsaveallsession (QTimer trigger + aboutToQuit trigger) """
        try:
            if not self._sessions:
                return
            # onlyhassaveinconversationwhenonly thensave
            has_any = False
            for sid, sdata in self._sessions.items():
                if sdata.get('conversation_history'):
                    has_any = True
                    break
            if not has_any:
                return
            self._save_all_sessions()
        except Exception as e:
            _dbg(f"[Cache] Periodic save failed: {e}")
    
    def _atexit_save(self):
        """Last-save opportunity on Python exit (atexit callback).
        
        ★ thiswhen Qt widget mayalreadyisdestroy, becausethis: 
        - use _tabs_backup (pure Python list) generationreplacetraverse QTabBar
        - use try/except packagewrap todo_list access
        - if aboutToQuit alreadysucceededsavepassed, thenskip (avoidusenotcompletedataoverride) 
        - If the widget is already destroyed (old instance), skip to avoid overwriting the new instance's data
        """
        try:
            if getattr(self, '_destroyed', False):
                return
            if getattr(self, '_sessions_saved', False):
                return
            if not hasattr(self, '_sessions') or not self._sessions:
                return
            _dbg(f"[Cache] atexit: starting save (sessions={len(self._sessions)}, backup={len(getattr(self, '_tabs_backup', []))})")
            try:
                self._save_current_session_state()
            except (RuntimeError, AttributeError):
                pass
            
            tabs_info = getattr(self, '_tabs_backup', [])
            if not tabs_info:
                tabs_info = [(sid, f"Chat") for sid in self._sessions]
            
            manifest_tabs = []
            for sid, tab_label in tabs_info:
                if not sid or sid not in self._sessions:
                    continue
                sdata = self._sessions[sid]
                history = sdata.get('conversation_history', [])
                if not history:
                    manifest_tabs.append({
                        'session_id': sid,
                        'tab_label': tab_label,
                        'file': '',
                        'empty': True,
                    })
                    continue
                todo_data = []
                try:
                    todo_list_obj = sdata.get('todo_list')
                    todo_data = todo_list_obj.get_todos_data() if todo_list_obj else []
                except (RuntimeError, AttributeError, Exception):
                    pass
                cache_data = {
                    'version': '1.0',
                    'session_id': sid,
                    'message_count': len(history),
                    'conversation_history': self._strip_images_for_cache(history),
                    'context_summary': sdata.get('context_summary', ''),
                    'todo_data': todo_data,
                    'token_stats': sdata.get('token_stats', {}),
                }
                session_file = self._cache_dir / f"session_{sid}.json"
                with open(session_file, 'w', encoding='utf-8') as f:
                    json.dump(cache_data, f, ensure_ascii=False)
                manifest_tabs.append({
                    'session_id': sid,
                    'tab_label': tab_label,
                    'file': f"session_{sid}.json",
                })
            if not manifest_tabs:
                return
            # Prevent fewer-tab data from overwriting an already-complete manifest
            manifest_file = self._cache_dir / "sessions_manifest.json"
            try:
                if manifest_file.exists():
                    import json as _json
                    with open(manifest_file, 'r', encoding='utf-8') as f:
                        existing = _json.load(f)
                    existing_count = len(existing.get('tabs', []))
                    if existing_count > len(manifest_tabs):
                        return
            except Exception:
                pass
            manifest = {
                'version': '1.0',
                'active_session_id': self._session_id,
                'tabs': manifest_tabs,
            }
            with open(manifest_file, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, ensure_ascii=False)
        except Exception:
            pass

    def _save_cache(self) -> bool:
        """autosave: coverwritesame session file + manifest"""
        if not self._conversation_history:
            return False
        try:
            # synccurrentsessionstateto _sessions
            self._save_current_session_state()
            # ★ sync tab backup
            self._sync_tabs_backup()
            
            cache_data = self._build_cache_data()
            # ★ strip base64 imagebysubtractsmallcachefilelargesmall
            cache_data['conversation_history'] = self._strip_images_for_cache(
                cache_data.get('conversation_history', [])
            )

            # 1. coverwritefixfixed  session file (one session onlyhasonefile) 
            session_file = self._cache_dir / f"session_{self._session_id}.json"
            with open(session_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)

            # 2. syncupdate sessions_manifest.json (ensureall tab infoallislatest ) 
            # ★ notagainwrite cache_latest.json — restoreby sessions_manifest + session_*.json manage
            self._update_manifest()

            if self._workspace_dir:
                self._update_workspace_cache_info()
            return True
        except Exception as e:
            _dbg(f"[Cache] Auto-save failed: {e}")
            return False
    
    def _update_manifest(self):
        """Update sessions_manifest.json to reflect the current state of all tabs."""
        try:
            manifest_tabs = []
            for i in range(self.session_tabs.count()):
                sid = self.session_tabs.tabData(i)
                if not sid:
                    continue
                tab_label = self.session_tabs.tabText(i)
                session_file = self._cache_dir / f"session_{sid}.json"
                if session_file.exists():
                    manifest_tabs.append({
                        'session_id': sid,
                        'tab_label': tab_label,
                        'file': f"session_{sid}.json",
                    })
                else:
                    sdata = self._sessions.get(sid, {})
                    history = sdata.get('conversation_history', [])
                    if history:
                        manifest_tabs.append({
                            'session_id': sid,
                            'tab_label': tab_label,
                            'file': f"session_{sid}.json",
                        })
                    else:
                        manifest_tabs.append({
                            'session_id': sid,
                            'tab_label': tab_label,
                            'file': '',
                            'empty': True,
                        })
            if manifest_tabs:
                manifest = {
                    'version': '1.0',
                    'active_session_id': self._session_id,
                    'tabs': manifest_tabs,
                }
                manifest_file = self._cache_dir / "sessions_manifest.json"
                with open(manifest_file, 'w', encoding='utf-8') as f:
                    json.dump(manifest, f, ensure_ascii=False, indent=2)
        except Exception as e:
            _dbg(f"[Cache] Update manifest failed: {e}")

    def _save_all_sessions(self) -> bool:
        """saveallopen sessiontodisk (closesoftwarewhencall) """
        if getattr(self, '_destroyed', False):
            return False
        try:
            # firstsavecurrentactivesession stateto _sessions dict
            try:
                self._save_current_session_state()
            except (RuntimeError, AttributeError):
                pass
            # ★ sync tab backup (ensure atexit whenalsocanuse) 
            try:
                self._sync_tabs_backup()
            except (RuntimeError, AttributeError):
                pass

            manifest_tabs = []
            active_session_id = self._session_id

            # from QTabBar get tab list; if Qt widget alreadydestroythenfall backtopure Python backup
            tabs_list = []
            try:
                for i in range(self.session_tabs.count()):
                    sid = self.session_tabs.tabData(i)
                    tab_label = self.session_tabs.tabText(i)
                    if sid:
                        tabs_list.append((sid, tab_label))
            except (RuntimeError, AttributeError):
                tabs_list = getattr(self, '_tabs_backup', [])

            for sid, tab_label in tabs_list:
                if not sid or sid not in self._sessions:
                    continue

                sdata = self._sessions[sid]
                history = sdata.get('conversation_history', [])
                if not history:
                    # emptysession: cleanupdiskresidualkeep, butstillrecordto manifest bykeeplabellayout
                    try:
                        old_file = self._cache_dir / f"session_{sid}.json"
                        if old_file.exists():
                            old_file.unlink()
                    except Exception:
                        pass
                    manifest_tabs.append({
                        'session_id': sid,
                        'tab_label': tab_label,
                        'file': '',
                        'empty': True,
                    })
                    continue

                # collectset todo data (defensive widget alreadydestroy case) 
                todo_data = []
                try:
                    todo_list_obj = sdata.get('todo_list')
                    todo_data = todo_list_obj.get_todos_data() if todo_list_obj else []
                except (RuntimeError, AttributeError):
                    pass

                # write session file (★ strip base64 imagebysubtractsmallfilelargesmall) 
                cache_data = {
                    'version': '1.0',
                    'session_id': sid,
                    'created_at': datetime.now().isoformat(),
                    'message_count': len(history),
                    'conversation_history': self._strip_images_for_cache(history),
                    'context_summary': sdata.get('context_summary', ''),
                    'todo_data': todo_data,
                    'token_stats': sdata.get('token_stats', {}),
                }
                session_file = self._cache_dir / f"session_{sid}.json"
                with open(session_file, 'w', encoding='utf-8') as f:
                    json.dump(cache_data, f, ensure_ascii=False, indent=2)

                manifest_tabs.append({
                    'session_id': sid,
                    'tab_label': tab_label,
                    'file': f"session_{sid}.json",
                })

            if not manifest_tabs:
                return False

            manifest = {
                'version': '1.0',
                'active_session_id': active_session_id,
                'tabs': manifest_tabs,
            }
            manifest_file = self._cache_dir / "sessions_manifest.json"
            with open(manifest_file, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)

            self._sessions_saved = True
            _dbg(f"[Cache] Saved {len(manifest_tabs)} session tab(s) (tabs_list={len(tabs_list)}, sessions={len(self._sessions)})")
            return True
        except Exception as e:
            _dbg(f"[Cache] Failed to save all sessions: {e}")
            import traceback; traceback.print_exc()
            return False

    def _restore_all_sessions(self) -> bool:
        """Restore all session tabs from sessions_manifest.json (called on startup, idempotent)."""
        # ★ Idempotency guard: prevent __init__ and the main_window delayed callback from double-restoring
        if getattr(self, '_sessions_restored', False):
            return True
        try:
            manifest_file = self._cache_dir / "sessions_manifest.json"
            if not manifest_file.exists():
                return False

            with open(manifest_file, 'r', encoding='utf-8') as f:
                manifest = json.load(f)

            tabs_info = manifest.get('tabs', [])
            if not tabs_info:
                return False

            active_sid = manifest.get('active_session_id', '')
            active_tab_index = 0
            first_tab = True

            for tab_info in tabs_info:
                sid = tab_info.get('session_id', '')
                tab_label = tab_info.get('tab_label', 'Chat')
                is_empty = tab_info.get('empty', False)

                history = []
                context_summary = ''
                todo_data = []
                saved_token_stats = {
                    'input_tokens': 0, 'output_tokens': 0,
                    'reasoning_tokens': 0,
                    'cache_read': 0, 'cache_write': 0,
                    'total_tokens': 0, 'requests': 0,
                    'estimated_cost': 0.0,
                }

                if not is_empty:
                    file_name = tab_info.get('file', '')
                    if not file_name:
                        continue
                    session_file = self._cache_dir / file_name
                    if not session_file.exists():
                        continue
                    with open(session_file, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                    history = cache_data.get('conversation_history', [])
                    if not history:
                        is_empty = True
                    else:
                        context_summary = cache_data.get('context_summary', '')
                        todo_data = cache_data.get('todo_data', [])
                        saved_token_stats = cache_data.get('token_stats', saved_token_stats)

                if first_tab:
                    # first tab: loadtoalreadyhas initialsessionin
                    first_tab = False
                    old_id = self._session_id

                    self._session_id = sid
                    self._conversation_history = history
                    self._context_summary = context_summary
                    self._token_stats = saved_token_stats

                    if old_id in self._sessions:
                        sdata = self._sessions.pop(old_id)
                        sdata['conversation_history'] = history
                        sdata['context_summary'] = context_summary
                        sdata['token_stats'] = saved_token_stats
                        self._sessions[sid] = sdata
                    elif sid not in self._sessions:
                        self._sessions[sid] = {
                            'scroll_area': self.scroll_area,
                            'chat_container': self.chat_container,
                            'chat_layout': self.chat_layout,
                            'todo_list': self.todo_list,
                            'conversation_history': history,
                            'context_summary': context_summary,
                            'current_response': None,
                            'token_stats': saved_token_stats,
                        }

                    if todo_data and hasattr(self, 'todo_list') and self.todo_list:
                        self.todo_list.restore_todos(todo_data)
                        self._ensure_todo_in_chat(self.todo_list, self.chat_layout)

                    for i in range(self.session_tabs.count()):
                        if self.session_tabs.tabData(i) == old_id:
                            self.session_tabs.setTabData(i, sid)
                            self.session_tabs.setTabText(i, tab_label)
                            if sid == active_sid:
                                active_tab_index = i
                            break

                    if not is_empty:
                        self._render_conversation_history()
                else:
                    # aftercontinue tab: createnewlabel
                    self._save_current_session_state()
                    self._session_counter += 1

                    scroll_area, chat_container, chat_layout = self._create_session_widgets()
                    self.session_stack.addWidget(scroll_area)

                    tab_index = self.session_tabs.addTab(tab_label)
                    self.session_tabs.setTabData(tab_index, sid)

                    todo = self._create_todo_list(chat_container)
                    if todo_data:
                        todo.restore_todos(todo_data)
                        self._ensure_todo_in_chat(todo, chat_layout)

                    self._sessions[sid] = {
                        'scroll_area': scroll_area,
                        'chat_container': chat_container,
                        'chat_layout': chat_layout,
                        'todo_list': todo,
                        'conversation_history': history,
                        'context_summary': context_summary,
                        'current_response': None,
                        'token_stats': saved_token_stats,
                    }

                    if not is_empty:
                        # temporarywhenswitchtothislabelbyrenderhistory
                        old_scroll = self.scroll_area
                        old_chat_container = self.chat_container
                        old_chat_layout = self.chat_layout
                        old_todo = self.todo_list
                        old_history = self._conversation_history
                        old_summary = self._context_summary
                        old_stats = self._token_stats
                        old_sid = self._session_id

                        self._session_id = sid
                        self._conversation_history = history
                        self._context_summary = context_summary
                        self._token_stats = saved_token_stats
                        self.scroll_area = scroll_area
                        self.chat_container = chat_container
                        self.chat_layout = chat_layout
                        self.todo_list = todo

                        self._render_conversation_history()

                        self._session_id = old_sid
                        self._conversation_history = old_history
                        self._context_summary = old_summary
                        self._token_stats = old_stats
                        self.scroll_area = old_scroll
                        self.chat_container = old_chat_container
                        self.chat_layout = old_chat_layout
                        self.todo_list = old_todo

                    if sid == active_sid:
                        active_tab_index = tab_index

            # switchtobeforeactive label
            if self.session_tabs.count() > 0:
                self.session_tabs.blockSignals(True)
                self.session_tabs.setCurrentIndex(active_tab_index)
                self.session_tabs.blockSignals(False)

                target_sid = self.session_tabs.tabData(active_tab_index)
                if target_sid and target_sid in self._sessions:
                    self._load_session_state(target_sid)
                    self.session_stack.setCurrentWidget(
                        self._sessions[target_sid]['scroll_area']
                    )

            # ★ restorecompleteaftersync tab backupandupdate UI show
            self._sync_tabs_backup()
            self._update_token_stats_display()
            self._update_context_stats()
            self._sessions_restored = True  # markalreadyrestore, preventduplicate
            _dbg(f"[Cache] Restored {self.session_tabs.count()} session tab(s)")
            return True

        except Exception as e:
            _dbg(f"[Cache] Failed to restore multi-session: {e}")
            import traceback; traceback.print_exc()
            return False

    def _archive_cache(self) -> bool:
        """Manual archive: create a timestamped standalone file (won't be overwritten)."""
        if not self._conversation_history:
            QtWidgets.QMessageBox.information(self, "Info", "No conversation history to archive")
            return False
        try:
            cache_data = self._build_cache_data()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"archive_{self._session_id}_{timestamp}.json"
            archive_file = self._cache_dir / filename
            with open(archive_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            est = cache_data['estimated_tokens']
            self._addStatus.emit(f"Archived: {filename} (~{est} tokens)")
            return True
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Archive failed: {str(e)}")
            return False
    
    def _update_workspace_cache_info(self):
        """updateworksectionin cacheinfo (formainwindowsaveworksectionwhenuse) """
        # thismethodwillismainwindowcall, used forupdateworksectionconfig
        # realboundarysavebymainwindow  _save_workspace complete
        pass
    
    def _load_cache(self, cache_file: Path, silent: bool = False) -> bool:
        """fromcachefileloadconversationhistory (innewlabelpageinopen) 
        
        Args:
            cache_file: cachefile path
            silent: whethersilentload (notshowconfirmconversationbox, used forworksectionautorestore) 
        """
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # verifydataformat
            if 'conversation_history' not in cache_data:
                if not silent:
                    QtWidgets.QMessageBox.warning(self, "Error", "Invalid cache file format")
                return False
            
            # confirmload (silentmodebelowskip) 
            if not silent:
                msg_count = len(cache_data.get('conversation_history', []))
                reply = QtWidgets.QMessageBox.question(
                    self, "Confirm load",
                    f"Will load {msg_count} messages in a new tab.\nContinue?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
                )
                
                if reply != QtWidgets.QMessageBox.Yes:
                    return False
            
            history = cache_data.get('conversation_history', [])
            context_summary = cache_data.get('context_summary', '')
            todo_data = cache_data.get('todo_data', [])
            cached_session_id = cache_data.get('session_id', str(uuid.uuid4())[:8])
            # ★ restore token usestatistics
            saved_token_stats = cache_data.get('token_stats', {
                'input_tokens': 0, 'output_tokens': 0,
                'reasoning_tokens': 0,
                'cache_read': 0, 'cache_write': 0,
                'total_tokens': 0, 'requests': 0,
                'estimated_cost': 0.0,
            })
            
            if silent and not self._conversation_history:
                # silentrestore: currentsessionasemptywhendirectlyloadtocurrentlabel
                self._conversation_history = history
                self._context_summary = context_summary
                self._session_id = cached_session_id
                self._token_stats = saved_token_stats
                # restore todo data
                if todo_data and hasattr(self, 'todo_list') and self.todo_list:
                    self.todo_list.restore_todos(todo_data)
                    self._ensure_todo_in_chat(self.todo_list, self.chat_layout)
                # update sessions dict
                if self._session_id in self._sessions:
                    self._sessions[self._session_id]['conversation_history'] = self._conversation_history
                    self._sessions[self._session_id]['context_summary'] = self._context_summary
                    self._sessions[self._session_id]['token_stats'] = saved_token_stats
                elif self._sessions:
                    # old session_id alreadypassedchange, needsrenewmapping
                    old_id = list(self._sessions.keys())[0]
                    sdata = self._sessions.pop(old_id)
                    sdata['conversation_history'] = self._conversation_history
                    sdata['context_summary'] = self._context_summary
                    sdata['token_stats'] = saved_token_stats
                    self._sessions[self._session_id] = sdata
                    # updatelabeldata
                    for i in range(self.session_tabs.count()):
                        if self.session_tabs.tabData(i) == old_id:
                            self.session_tabs.setTabData(i, self._session_id)
                            break
                self._render_conversation_history()
                self._update_token_stats_display()
                self._update_context_stats()
                # autorecommandnamelabel
                if history:
                    for msg in history:
                        if msg.get('role') == 'user' and msg.get('content'):
                            self._auto_rename_tab(msg['content'])
                            break
                _dbg(f"[Workspace] Auto-restored context: {len(self._conversation_history)} message(s)")
                return True
            
            # notsilentorcurrentsessionnotempty: innewlabelpageinopen
            self._save_current_session_state()
            
            # createnewlabel
            self._session_counter += 1
            scroll_area, chat_container, chat_layout = self._create_session_widgets()
            self.session_stack.addWidget(scroll_area)
            
            # usecachefilenameorfirstitemusermessageaslabelname
            label = f"Chat {self._session_counter}"
            for msg in history:
                if msg.get('role') == 'user' and msg.get('content'):
                    short = msg['content'][:18].replace('\n', ' ').strip()
                    if len(msg['content']) > 18:
                        short += "..."
                    label = short
                    break
            
            tab_index = self.session_tabs.addTab(label)
            self.session_tabs.setTabData(tab_index, cached_session_id)
            
            todo = self._create_todo_list(chat_container)
            if todo_data:
                todo.restore_todos(todo_data)
                self._ensure_todo_in_chat(todo, chat_layout)
            
            self._sessions[cached_session_id] = {
                'scroll_area': scroll_area,
                'chat_container': chat_container,
                'chat_layout': chat_layout,
                'todo_list': todo,
                'conversation_history': history,
                'context_summary': context_summary,
                'current_response': None,
                'token_stats': saved_token_stats,
            }
            
            # switchtonewlabel
            self._session_id = cached_session_id
            self._conversation_history = history
            self._context_summary = context_summary
            self._current_response = None
            self._token_stats = saved_token_stats
            self.scroll_area = scroll_area
            self.chat_container = chat_container
            self.chat_layout = chat_layout
            self.todo_list = todo
            
            self.session_tabs.blockSignals(True)
            self.session_tabs.setCurrentIndex(tab_index)
            self.session_tabs.blockSignals(False)
            self.session_stack.setCurrentWidget(scroll_area)
            
            self._render_conversation_history()
            self._update_token_stats_display()
            self._update_context_stats()
            
            if not silent:
                self._addStatus.emit(f"Cache loaded: {cache_file.name}")
            
            return True
            
        except Exception as e:
            if not silent:
                QtWidgets.QMessageBox.warning(self, "Error", f"Failed to load cache: {str(e)}")
            else:
                _dbg(f"[Workspace] Cache load failed: {str(e)}")
            return False
    
    def _load_cache_silent(self, cache_file: Path) -> bool:
        """silentloadcache (used forworksectionautorestore) """
        return self._load_cache(cache_file, silent=True)
    
    def _load_cache_dialog(self):
        """showloadcacheconversationbox"""
        cache_files = sorted(
            set(self._cache_dir.glob("session_*.json"))
            | set(self._cache_dir.glob("archive_*.json"))
            | set(self._cache_dir.glob("cache_*.json")),
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        
        if not cache_files:
            QtWidgets.QMessageBox.information(self, "Info", "No cache files found")
            return

        # createselectconversationbox
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Select cache file")
        dialog.setMinimumWidth(500)
        
        layout = QtWidgets.QVBoxLayout(dialog)
        
        # filelist
        list_widget = QtWidgets.QListWidget()
        for cache_file in cache_files:
            # readfileinfo
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    msg_count = len(data.get('conversation_history', []))
                    estimated_tokens = data.get('estimated_tokens', 0)
                    created_at = data.get('created_at', '')
                    if created_at:
                        try:
                            dt = datetime.fromisoformat(created_at)
                            created_at = dt.strftime("%Y-%m-%d %H:%M:%S")
                        except:
                            pass
                    token_info = f" | ~{estimated_tokens:,} tokens" if estimated_tokens else ""
                    item_text = f"{cache_file.name}\n  {msg_count} messages{token_info} | {created_at}"
            except:
                item_text = cache_file.name
            
            item = QtWidgets.QListWidgetItem(item_text)
            item.setData(QtCore.Qt.UserRole, cache_file)
            list_widget.addItem(item)
        
        layout.addWidget(QtWidgets.QLabel("Select a cache file to load:"))
        layout.addWidget(list_widget)

        # button
        btn_layout = QtWidgets.QHBoxLayout()
        btn_load = QtWidgets.QPushButton("Load")
        btn_cancel = QtWidgets.QPushButton("Cancel")
        btn_layout.addWidget(btn_load)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
        def on_load():
            current = list_widget.currentItem()
            if current:
                cache_file = current.data(QtCore.Qt.UserRole)
                if self._load_cache(cache_file):
                    dialog.accept()
        
        btn_load.clicked.connect(on_load)
        btn_cancel.clicked.connect(dialog.reject)
        
        dialog.exec_()
    
    def _list_caches(self):
        """columnoutallcachefile"""
        cache_files = sorted(
            set(self._cache_dir.glob("session_*.json"))
            | set(self._cache_dir.glob("archive_*.json"))
            | set(self._cache_dir.glob("cache_*.json")),
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        
        if not cache_files:
            QtWidgets.QMessageBox.information(self, "Info", "No cache files found")
            return

        # createinfoconversationbox
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Cache files")
        dialog.setMinimumSize(600, 400)
        
        layout = QtWidgets.QVBoxLayout(dialog)
        
        # textshow
        text_edit = QtWidgets.QTextEdit()
        text_edit.setReadOnly(True)
        
        lines = ["Cache files:\n"]
        for cache_file in cache_files:
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    msg_count = len(data.get('conversation_history', []))
                    created_at = data.get('created_at', '')
                    session_id = data.get('session_id', '')
                    estimated_tokens = data.get('estimated_tokens', 0)
                    
                    if created_at:
                        try:
                            dt = datetime.fromisoformat(created_at)
                            created_at = dt.strftime("%Y-%m-%d %H:%M:%S")
                        except:
                            pass
                    
                    size_kb = cache_file.stat().st_size / 1024
                    lines.append(f"  {cache_file.name}")
                    lines.append(f"   Session ID: {session_id}")
                    lines.append(f"   Messages: {msg_count}")
                    if estimated_tokens:
                        lines.append(f"   Est. tokens: ~{estimated_tokens:,}")
                    lines.append(f"   Created: {created_at}")
                    lines.append(f"   Size: {size_kb:.1f} KB")
                    lines.append("")
            except Exception as e:
                lines.append(f"[err] {cache_file.name} (read failed: {str(e)})")
                lines.append("")
        
        text_edit.setPlainText("\n".join(lines))
        layout.addWidget(text_edit)
        
        btn_close = QtWidgets.QPushButton("Close")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)
        
        dialog.exec_()
    
    def _compress_to_summary(self):
        """willoldconversationcompressassummary, reduce token consumeconsume"""
        if len(self._conversation_history) <= 4:
            QtWidgets.QMessageBox.information(self, "Info", "Conversation too short — nothing to compress")
            return

        # confirmoperation
        reply = QtWidgets.QMessageBox.question(
            self, "Confirm compression",
            f"Will compress the first {len(self._conversation_history) - 4} messages into a summary, "
            f"keeping the most recent 4 messages intact.\n\n"
            f"This significantly reduces token usage. Continue?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply != QtWidgets.QMessageBox.Yes:
            return
        
        # executecompress
        old_messages = self._conversation_history[:-4]
        recent_messages = self._conversation_history[-4:]
        
        # generatedetailfinesummary
        summary_parts = ["[historyconversationsummary - alreadycompressbysectionsave token]"]
        
        user_requests = []
        ai_results = []
        
        for msg in old_messages:
            role = msg.get('role', '')
            content = msg.get('content', '')
            
            if role == 'user':
                # extractuserrequest core (previous200character) 
                user_request = content[:200].replace('\n', ' ')
                if len(content) > 200:
                    user_request += "..."
                user_requests.append(user_request)
            
            elif role == 'assistant' and content:
                # extract AI reply keyinfo
                lines = [l.strip() for l in content.split('\n') if l.strip()]
                if lines:
                    # fetchlastoneroworprevious150character
                    result_summary = lines[-1][:150].replace('\n', ' ')
                    if len(lines[-1]) > 150:
                        result_summary += "..."
                    ai_results.append(result_summary)
        
        # mergesummary
        if user_requests:
            summary_parts.append(f"\nuserrequest ({len(user_requests)} item):")
            for i, req in enumerate(user_requests[:10], 1):  # at mostshow10item
                summary_parts.append(f"  {i}. {req}")
            if len(user_requests) > 10:
                summary_parts.append(f"  ... stillhas {len(user_requests) - 10} itemrequest")
        
        if ai_results:
            summary_parts.append(f"\nAI complete task ({len(ai_results)} item):")
            for i, res in enumerate(ai_results[:10], 1):  # at mostshow10item
                summary_parts.append(f"  {i}. {res}")
            if len(ai_results) > 10:
                summary_parts.append(f"  ... stillhas {len(ai_results) - 10} itemresult")
        
        summary_text = "\n".join(summary_parts)
        
        # updatehistory: usesummaryreplaceswapoldconversation
        self._conversation_history = [
            {'role': 'system', 'content': summary_text}
        ] + recent_messages
        
        # updatecontextsummary
        self._context_summary = summary_text
        
        # renewrender
        self._render_conversation_history()
        
        # updatestatistics
        self._update_context_stats()
        
        # computesectionsave  token
        old_tokens = sum(self._estimate_tokens(json.dumps(msg)) for msg in old_messages)
        new_tokens = self._estimate_tokens(summary_text)
        saved_tokens = old_tokens - new_tokens
        
        QtWidgets.QMessageBox.information(
            self, "compresscomplete",
            f"conversationalreadycompress! \n\n"
            f"original: ~{old_tokens} tokens\n"
            f"compressafter: ~{new_tokens} tokens\n"
            f"sectionsave: ~{saved_tokens} tokens ({saved_tokens/old_tokens*100:.1f}%)"
        )
    
    # ---------- historyrenderhelper ----------
    _CONTEXT_HEADERS = ('[Network structure]', '[Selected nodes]',
                        '[networkstructure]', '[selectednode]')

    # ★ partbatchrenderconstant (inspired by markstream-vue  batchtimestrategy) 
    _BATCH_INITIAL = 30      # firstbatchrenderlast N itemmessage (userrecentseeto ) 
    _BATCH_SIZE = 15          # aftercontinueeachbatchrender N item
    _BATCH_BUDGET_MS = 8      # Per-batch time budget (ms)

    def _render_conversation_history(self):
        """renewrenderconversationhistoryto UI

        ★ partbatchrenderstrategy (inspired by markstream-vue) : 
        1. firstbatchrenderlast _BATCH_INITIAL itemmessage (userrecentseeto ) 
        2. use QTimer.singleShot(0) simulation idle callback, one by onebatchrenderremaining
        3. eachbatchsetwhenbetweenpre-calculate, exceedoutthenpauseletoutmainthread

        Handle three data formats:
        1. role="user" inembed [Network structure] / [Selected nodes] etc.context
           → usertextnormalshow, contextdataputentercancollapsearea
        2. role="assistant" by [toolexecuteresult] start
           → parseeachoneitem [ok]/[err]/✅/❌ row, createcollapsestyle ToolCallItem
        3. role="tool" (oldcacheformat) 
           → first add_tool_call again set_tool_result (collapsestyle) 
        """
        # clearemptycurrentshow (keepend stretch) 
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # cancelbefore partbatchrenderfixedwhen 
        if hasattr(self, '_batch_render_timer') and self._batch_render_timer is not None:
            self._batch_render_timer.stop()
            self._batch_render_timer = None

        messages = self._conversation_history
        if not messages:
            return

        # ★ pre-scan: willmessagegroupaslogic"roundtime" (eachround = onegrouprelatedmessage) 
        groups = self._group_messages_into_turns(messages)
        total_groups = len(groups)

        if total_groups <= self._BATCH_INITIAL:
            # messagequantitysmall, oncepropertyrender
            self._render_message_groups(groups, 0, total_groups)
        else:
            # ★ partbatchrender: firstrenderlast _BATCH_INITIAL group (userrecentseeto ) 
            # earlymessageuseoccupybitsymbol
            early_count = total_groups - self._BATCH_INITIAL

            # insertoccupybitsymbol
            self._batch_placeholder = QtWidgets.QLabel(
                f"⏳ loadhistorymessage ({early_count} round)..."
            )
            self._batch_placeholder.setObjectName("batchPlaceholder")
            self._batch_placeholder.setStyleSheet(
                "color: #64748b; padding: 8px 12px; font-size: 12px; "
                "font-style: italic; background: transparent;"
            )
            self._batch_placeholder.setAlignment(QtCore.Qt.AlignCenter)
            # insertto stretch before
            self.chat_layout.insertWidget(self.chat_layout.count() - 1,
                                         self._batch_placeholder)

            # renderlast _BATCH_INITIAL group
            self._render_message_groups(groups, early_count, total_groups)

            # use QTimer partbatchrenderearlymessage
            self._batch_groups = groups
            self._batch_cursor = early_count  # from early_count toward 0 fall back
            self._batch_insert_pos = 0  # earlymessageinserttolayoutheadpart
            self._batch_render_timer = QtCore.QTimer(self)
            self._batch_render_timer.setSingleShot(True)
            self._batch_render_timer.timeout.connect(self._render_next_batch)
            self._batch_render_timer.start(0)  # belowoneframestart

    def _group_messages_into_turns(self, messages: list) -> list:
        """willmessagelistgroupaslogicroundtime
        
        return: list of (start_idx, end_idx) tuple
        """
        groups: list = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg.get('role', '')

            if role == 'user':
                groups.append((i, i + 1))
                i += 1
            elif role == 'assistant':
                if msg.get('tool_calls'):
                    # collectsettoolsubmitmutualroundtime
                    j = i + 1
                    while j < len(messages):
                        m = messages[j]
                        r = m.get('role', '')
                        if r == 'tool':
                            j += 1
                        elif r == 'assistant':
                            j += 1
                            if not m.get('tool_calls'):
                                break
                        else:
                            break
                    groups.append((i, j))
                    i = j
                else:
                    # regular assistant + aftercontinue tool message
                    j = i + 1
                    while j < len(messages) and messages[j].get('role') == 'tool':
                        j += 1
                    groups.append((i, j))
                    i = j
            elif role == 'system':
                groups.append((i, i + 1))
                i += 1
            else:
                groups.append((i, i + 1))
                i += 1
        return groups

    def _render_message_groups(self, groups: list, start: int, end: int):
        """render [start, end) rangewithin messagegroup"""
        messages = self._conversation_history
        for gi in range(start, end):
            si, ei = groups[gi]
            try:
                self._render_single_group(messages, si, ei)
            except Exception:
                import traceback
                traceback.print_exc()

    def _render_single_group(self, messages: list, si: int, ei: int):
        """renderonemessagegroup"""
        msg = messages[si]
        role = msg.get('role', '')
        raw_content = msg.get('content', '') or ''
        if isinstance(raw_content, list):
            content = '\n'.join(
                part.get('text', '') for part in raw_content
                if isinstance(part, dict) and part.get('type') == 'text'
            )
        else:
            content = raw_content

        if role == 'user':
            self._render_user_history(content)

        elif role == 'assistant':
            if msg.get('tool_calls'):
                turn_msgs = messages[si:ei]
                self._render_native_tool_turn(turn_msgs)
            else:
                tool_msgs = [messages[j] for j in range(si + 1, ei)
                             if messages[j].get('role') == 'tool']

                if content.lstrip().startswith('[toolexecuteresult]'):
                    self._render_tool_summary_history(content, msg)
                else:
                    response = self._add_ai_response()
                    thinking = msg.get('thinking', '')
                    if thinking:
                        response.add_thinking(thinking)
                        response.thinking_section.finalize()
                    self._render_old_tool_msgs(response, tool_msgs)
                    self._restore_shell_widgets(response, msg)
                    response.set_content(content)
                    response.status_label.setText("History")
                    response.finalize()
                    parts = []
                    if thinking:
                        parts.append("thinking")
                    if tool_msgs:
                        parts.append(f"{len(tool_msgs)} calls")
                    label = f"History | {', '.join(parts)}" if parts else "History"
                    response.status_label.setText(label)

        elif role == 'system' and '[historyconversationsummary' in content:
            response = self._add_ai_response()
            response.add_collapsible("Conversation history summary", content)
            response.status_label.setText("History summary")
            response.finalize()
            response.status_label.setText("History summary")

    def _render_next_batch(self):
        """partbatchrendercallback — renderbelowonebatchearlymessage (fromaftertowardprevious, inserttolayoutheadpart) """
        if not hasattr(self, '_batch_groups') or not self._batch_groups:
            return
        if self._batch_cursor <= 0:
            # allpartrenderfinishfinish, removeoccupybitsymbol
            self._finish_batch_render()
            return

        batch_start = max(0, self._batch_cursor - self._BATCH_SIZE)
        batch_end = self._batch_cursor
        start_time = time.time()

        # ★ earlymessageneedsinserttooccupybitsymbolbefore (i.e.layout the 0 positionstart) 
        # Isfrom batch_start to batch_end byorderorderrender, each widget insertto
        # occupybitsymbolpositionbefore (insert_pos deliveradd) 
        messages = self._conversation_history
        insert_pos = self._batch_insert_pos  # inthispositionbeforeinsert
        rendered_count = 0

        for gi in range(batch_start, batch_end):
            si, ei = self._batch_groups[gi]
            try:
                widgets_before = self.chat_layout.count()
                self._render_single_group(messages, si, ei)
                widgets_after = self.chat_layout.count()
                added = widgets_after - widgets_before

                # willnewadd  widget movemovetocorrectposition (occupybitsymbolbefore) 
                if added > 0:
                    for _ in range(added):
                        # fetchoutlastadd  widget (in stretch before) 
                        from_idx = self.chat_layout.count() - 2  # -1 is stretch, -2 isnew widget
                        item = self.chat_layout.takeAt(from_idx)
                        if item and item.widget():
                            self.chat_layout.insertWidget(insert_pos, item.widget())
                            insert_pos += 1
                    rendered_count += added
            except Exception:
                import traceback
                traceback.print_exc()

            # whenbetweenpre-calculatecheck
            elapsed_ms = (time.time() - start_time) * 1000
            if elapsed_ms > self._BATCH_BUDGET_MS and gi < batch_end - 1:
                self._batch_cursor = gi + 1
                self._batch_insert_pos = insert_pos
                remaining = gi + 1
                if hasattr(self, '_batch_placeholder') and self._batch_placeholder:
                    try:
                        self._batch_placeholder.setText(
                            f"⏳ Loading history ({remaining} turns)…"
                        )
                    except RuntimeError:
                        pass
                self._batch_render_timer.start(0)
                return

        self._batch_cursor = batch_start
        self._batch_insert_pos = insert_pos

        if self._batch_cursor > 0:
            if hasattr(self, '_batch_placeholder') and self._batch_placeholder:
                try:
                    self._batch_placeholder.setText(
                        f"⏳ Loading history ({self._batch_cursor} turns)…"
                    )
                except RuntimeError:
                    pass
            self._batch_render_timer.start(0)
        else:
            self._finish_batch_render()

    def _finish_batch_render(self):
        """completepartbatchrender, cleanupoccupybitsymbol"""
        if hasattr(self, '_batch_placeholder') and self._batch_placeholder:
            try:
                self._batch_placeholder.setVisible(False)
                self._batch_placeholder.deleteLater()
            except RuntimeError:
                pass
            self._batch_placeholder = None
        self._batch_groups = None
        self._batch_render_timer = None

    # ------------------------------------------------------------------
    def _replay_todo_from_tool_call(self, tool_name: str, arguments_str: str):
        """fromhistorytoolcallinrestore todo item (notshowin UI executelistin) 
        
        note: todo datanowinvia todo_data fieldincacheinsave/restore, 
        thismethodonlyascompatible witholdcache afterbackupapproach. 
        """
        try:
            if isinstance(arguments_str, str) and arguments_str:
                args = json.loads(arguments_str)
            elif isinstance(arguments_str, dict):
                args = arguments_str
            else:
                return
            if tool_name == 'add_todo':
                tid = args.get('todo_id', '')
                text = args.get('text', '')
                status = args.get('status', 'pending')
                if tid and text and hasattr(self, 'todo_list') and self.todo_list:
                    self.todo_list.add_todo(tid, text, status)
                    self._ensure_todo_in_chat(self.todo_list, self.chat_layout)
            elif tool_name == 'update_todo':
                tid = args.get('todo_id', '')
                status = args.get('status', 'done')
                if tid and hasattr(self, 'todo_list') and self.todo_list:
                    self.todo_list.update_todo(tid, status)
        except Exception:
            pass  # parse failedignore

    # ------------------------------------------------------------------
    def _render_native_tool_turn(self, turn_msgs: list):
        """render Cursor stylenativetoolcallroundtime
        
        turn_msgs format: 
          assistant(tool_calls) → tool → [assistant(tool_calls) → tool →] ... → assistant(reply)
        silenttool (add_todo/update_todo) notshowinexecutelistin, butwillrestore todo data. 
        """
        response = self._add_ai_response()
        tool_count = 0
        final_content = ''
        thinking = ''
        final_msg = {}
        
        for m in turn_msgs:
            r = m.get('role', '')
            if r == 'assistant':
                tc_list = m.get('tool_calls', [])
                if tc_list:
                    # toolcall assistant message: registereachtoolcall
                    for tc in tc_list:
                        fn = tc.get('function', {})
                        name = fn.get('name', 'unknown')
                        # silenttool: restore todo butnotshowinexecutelist
                        if name in self._SILENT_TOOLS:
                            self._replay_todo_from_tool_call(name, fn.get('arguments', ''))
                            continue
                        response.add_status(f"[tool]{name}")
                        tool_count += 1
                else:
                    # finalreply assistant message
                    final_content = m.get('content', '') or ''
                    thinking = m.get('thinking', '')
                    final_msg = m
            elif r == 'tool':
                tc_id = m.get('tool_call_id', '')
                t_content = m.get('content', '') or ''
                # from tool_call_id lookupforshould toolname
                t_name = self._find_tool_name_by_id(turn_msgs, tc_id) or 'tool'
                # silenttool resultalsonotshow
                if t_name in self._SILENT_TOOLS:
                    continue
                success = not t_content.lstrip().startswith('[err]') and 'error' not in t_content[:50].lower()
                prefix = "[ok] " if success else "[err] "
                response.add_tool_result(t_name, f"{prefix}{t_content}")
        
        # restore thinking
        if thinking:
            response.add_thinking(thinking)
            response.thinking_section.finalize()
        
        # restore Shell collapsepanel
        self._restore_shell_widgets(response, final_msg)
        
        # AI replycontent
        if final_content:
            response.set_content(final_content)
        
        # statelabel
        parts = []
        if thinking:
            parts.append("thinking")
        if tool_count > 0:
            parts.append(f"{tool_count} calls")
        label = f"History | {', '.join(parts)}" if parts else "History"
        response.status_label.setText(label)
        response.finalize()
        response.status_label.setText(label)

    @staticmethod
    def _find_tool_name_by_id(messages: list, tool_call_id: str) -> str:
        """frommessagelistinbased on tool_call_id lookupforshould toolname"""
        if not tool_call_id:
            return ''
        for m in messages:
            if m.get('role') == 'assistant':
                for tc in m.get('tool_calls', []):
                    if tc.get('id') == tool_call_id:
                        return tc.get('function', {}).get('name', '')
        return ''

    # ------------------------------------------------------------------
    def _render_user_history(self, content: str):
        """renderuserhistorymessage, longcontextautocollapse"""
        # checkwhetherpackagecontaining [Network structure] etc.contextinject
        split_pos = -1
        header_tag = ''
        for tag in self._CONTEXT_HEADERS:
            pos = content.find(tag)
            if pos != -1:
                split_pos = pos
                header_tag = tag
                break

        if split_pos > 0 and len(content) > 300:
            # userrealboundaryinput + contextinject
            user_text = content[:split_pos].strip()
            context_data = content[split_pos:]
            # showuserrealboundarytext
            if user_text:
                self._add_user_message(user_text)
            # contextputentercollapsearea
            resp = self._add_ai_response()
            resp.add_collapsible(header_tag.strip('[]'), context_data)
            resp.status_label.setText("Context")
            resp.finalize()
            resp.status_label.setText("Context")
        elif split_pos == 0 and len(content) > 300:
            # purecontext (nousertext) , wholeblockcollapse
            resp = self._add_ai_response()
            resp.add_collapsible(header_tag.strip('[]'), content)
            resp.status_label.setText("Context")
            resp.finalize()
            resp.status_label.setText("Context")
        else:
            self._add_user_message(content)

    # ------------------------------------------------------------------
    _TOOL_LINE_PREFIXES = ('[ok] ', '[err] ', '\u2705 ', '\u274c ')

    def _render_tool_summary_history(self, content: str, msg: dict = None):
        """render [toolexecuteresult] format  assistant message

        formatexample: 
          [toolexecuteresult]
          [ok] get_network_structure: ## networkstructure: /obj
          networktype: obj          ← ononeitem continuerow
          nodecount: 0            ← ononeitem continuerow
          [ok] create_node: /obj/geo1
        """
        if msg is None:
            msg = {}
        response = self._add_ai_response()

        # firstbyrowgroup: by [ok]/[err]/✅/❌ start rowstartnewitemitem, 
        # Other lines belong to the previous item — continue that line
        entries = []  # [(first_line, [continuation_lines])]
        for line in content.split('\n'):
            stripped = line.strip()
            if not stripped or stripped == '[toolexecuteresult]':
                # emptyrowortitle→ifhasononeitemitem, addemptyrowtocontinuerow (keepformat) 
                if entries:
                    entries[-1][1].append('')
                continue
            is_new_entry = any(stripped.startswith(p) for p in self._TOOL_LINE_PREFIXES)
            if is_new_entry:
                entries.append((stripped, []))
            elif entries:
                entries[-1][1].append(stripped)
            # else: no preceding item — stray line, ignore

        tool_count = 0
        for first_line, cont_lines in entries:
            t_name = 'unknown'
            success = True
            # parseprefix
            rest = first_line
            for prefix in self._TOOL_LINE_PREFIXES:
                if first_line.startswith(prefix):
                    if 'err' in prefix or '\u274c' in prefix:
                        success = False
                    rest = first_line[len(prefix):]
                    break
            # parse tool_name: result
            if ':' in rest:
                parts = rest.split(':', 1)
                t_name = parts[0].strip()
                first_result = parts[1].strip() if len(parts) > 1 else ''
            else:
                first_result = rest

            # mergecontinuerow
            all_parts = [first_result] + cont_lines
            t_result = '\n'.join(all_parts).strip()

            # silenttoolnotshowinexecutelist
            if t_name in self._SILENT_TOOLS:
                continue
            # registertool + setresult
            response.add_status(f"[tool]{t_name}")
            tool_count += 1
            result_prefix = "[ok] " if success else "[err] "
            response.add_tool_result(t_name, f"{result_prefix}{t_result}")

        # restore Shell collapsepanel
        self._restore_shell_widgets(response, msg)

        # restore thinking
        thinking = msg.get('thinking', '')
        if thinking:
            response.add_thinking(thinking)
            response.thinking_section.finalize()

        # restorebody text ([toolexecuteresult]aftermaystillhas AI positivestylereply) 
        # findtotoolsummaryafter body textpartpart
        text_after_tools = ''
        parts = content.split('\n\n')
        for idx_p, part in enumerate(parts):
            if not part.strip().startswith('[toolexecuteresult]') and not any(
                part.strip().startswith(p) for p in self._TOOL_LINE_PREFIXES
            ):
                # checkwhetherwholesegmentallistoolresultrow
                is_tool_block = all(
                    any(line.strip().startswith(p) for p in self._TOOL_LINE_PREFIXES)
                    or not line.strip()
                    or line.strip() == '[toolexecuteresult]'
                    for line in part.split('\n')
                )
                if not is_tool_block and part.strip():
                    text_after_tools = '\n\n'.join(parts[idx_p:])
                    break
        if text_after_tools:
            response.set_content(text_after_tools)

        label_parts = []
        if thinking:
            label_parts.append("thinking")
        label_parts.append(f"{tool_count} calls")
        response.status_label.setText(f"History | {', '.join(label_parts)}")
        response.finalize()
        response.status_label.setText(f"History | {', '.join(label_parts)}")

    # ------------------------------------------------------------------
    def _restore_shell_widgets(self, response, msg: dict):
        """fromhistorymessageinrestore Python Shell / System Shell collapsepanel"""
        # restore Python Shell
        for ps in msg.get('python_shells', []):
            code = ps.get('code', '')
            raw_output = ps.get('output', '')
            error = ps.get('error', '')
            success = ps.get('success', True)
            # extractexecutewhenbetween (and _on_add_python_shell samelogic) 
            exec_time = 0.0
            clean_parts = []
            for line in raw_output.split('\n'):
                time_match = re.match(r'^executewhenbetween:\s*([\d.]+)s$', line.strip())
                if time_match:
                    exec_time = float(time_match.group(1))
                    continue
                if line.strip() == 'output:':
                    continue
                clean_parts.append(line)
            clean_output = '\n'.join(clean_parts).strip()
            widget = PythonShellWidget(
                code=code, output=clean_output, error=error,
                exec_time=exec_time, success=success, parent=response
            )
            response.add_shell_widget(widget)

        # restore System Shell
        for ss in msg.get('system_shells', []):
            command = ss.get('command', '')
            raw_output = ss.get('output', '')
            error = ss.get('error', '')
            success = ss.get('success', True)
            cwd = ss.get('cwd', '')
            exec_time = 0.0
            exit_code = 0
            stdout_parts = []
            for line in raw_output.split('\n'):
                tm = re.search(r'consumewhen:\s*([\d.]+)s', line)
                cm = re.search(r'exitcode:\s*(\d+)', line)
                if tm:
                    exec_time = float(tm.group(1))
                if cm:
                    exit_code = int(cm.group(1))
                if tm or cm:
                    continue
                if line.strip() in ('--- stdout ---', '--- stderr ---'):
                    continue
                stdout_parts.append(line)
            clean_output = '\n'.join(stdout_parts).strip()
            widget = SystemShellWidget(
                command=command, output=clean_output, error=error,
                exit_code=exit_code, exec_time=exec_time,
                success=success, cwd=cwd, parent=response
            )
            response.add_sys_shell_widget(widget)

    # ------------------------------------------------------------------
    def _render_old_tool_msgs(self, response, tool_msgs: list):
        """renderoldformat role=tool messageto AIResponse"""
        for tm in tool_msgs:
            t_name = tm.get('name', 'unknown')
            t_content = tm.get('content', '')
            # parse tool_name:result_text
            if ':' in t_content:
                parts = t_content.split(':', 1)
                t_name = parts[0].strip() or t_name
                t_result = parts[1].strip() if len(parts) > 1 else t_content
            else:
                t_result = t_content
            # silenttoolnotshowinexecutelist
            if t_name in self._SILENT_TOOLS:
                continue
            success = not t_result.startswith('[err]') and not t_result.startswith('\u274c')
            # firstregistertoolcall
            response.add_status(f"[tool]{t_name}")
            result_prefix = "[ok] " if success else "[err] "

            response.add_tool_result(t_name, f"{result_prefix}{t_result}")

    # ===== Token optimizationizationmanage =====
    
    def _on_optimize_menu(self):
        """show Token optimizationizationmenusingle"""
        menu = QtWidgets.QMenu(self)
        
        # standi.e.optimizationization
        optimize_now_action = menu.addAction("Compress conversation now")
        optimize_now_action.triggered.connect(self._optimize_now)

        menu.addSeparator()

        # autooptimizationizationtoggle
        auto_label = "Auto-compress [on]" if self._auto_optimize else "Auto-compress"
        auto_opt_action = menu.addAction(auto_label)
        auto_opt_action.setCheckable(True)
        auto_opt_action.setChecked(self._auto_optimize)
        auto_opt_action.triggered.connect(lambda: setattr(self, '_auto_optimize', not self._auto_optimize))

        menu.addSeparator()

        # compressstrategy
        strategy_menu = menu.addMenu("Compression strategy")
        for label, strat in [
            ("Aggressive (max savings)", CompressionStrategy.AGGRESSIVE),
            ("Balanced (recommended)", CompressionStrategy.BALANCED),
            ("Conservative (preserve detail)", CompressionStrategy.CONSERVATIVE),
        ]:
            action = strategy_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self._optimization_strategy == strat)
            action.triggered.connect(lambda _, s=strat: setattr(self, '_optimization_strategy', s))
        
        # showmenusingle: anchor ke cursor (btn_optimize may hidden, via overflow trigger)
        if self.btn_optimize.isVisible():
            menu.exec_(self.btn_optimize.mapToGlobal(QtCore.QPoint(0, self.btn_optimize.height())))
        else:
            menu.exec_(QtGui.QCursor.pos())

    def _optimize_now(self):
        """standi.e.optimizationizationcurrentconversation"""
        if len(self._conversation_history) <= 4:
            self._show_toast("Conversation too short — nothing to optimize")
            return

        # computeoptimizationizationprevious
        before_tokens = self._calculate_context_tokens()

        # executeoptimizationization
        compressed_messages, stats = self.token_optimizer.compress_messages(
            self._conversation_history,
            strategy=self._optimization_strategy
        )

        if stats['saved_tokens'] > 0:
            self._conversation_history = compressed_messages
            self._context_summary = compressed_messages[0].get('content', '') if compressed_messages and compressed_messages[0].get('role') == 'system' else self._context_summary

            # renewrender
            self._render_conversation_history()

            # updatestatistics
            self._update_context_stats()

            # showresult
            saved_percent = stats.get('saved_percent', 0)
            self._show_toast(
                f"Optimized: ~{stats['saved_tokens']:,} tokens saved "
                f"({saved_percent:.1f}%) • {stats['compressed']} compressed, {stats['kept']} kept"
            )
        else:
            self._show_toast("Already concise — no optimization needed")

    # ============================================================
    # autoupdate
    # ============================================================

    _updateCheckDone = QtCore.Signal(dict)   # checkresult
    _updateApplyDone = QtCore.Signal(dict)   # applicationresult
    _updateProgress = QtCore.Signal(str, int)  # (stage, percent)

    def _silent_update_check(self):
        """[Disabled in MorfyAI fork] Auto-update check disabled by design."""
        return

    @QtCore.Slot(dict)
    def _on_silent_check_result(self, result: dict):
        """[mainthread] silentcheckresult → ifhasupdate, highlightbutton + shownotifybanner"""
        # disconnectsilentcallback, preventandmanualclickconflict
        try:
            self._updateCheckDone.disconnect(self._on_silent_check_result)
        except RuntimeError:
            pass
        
        if result.get('has_update') and result.get('remote_version'):
            remote_ver = result['remote_version']
            local_ver = result.get('local_version', '?')
            release_name = result.get('release_name', '')
            
            # 1) Use a noticeable style for the marker button
            self.btn_update.setText(tr('update.new_ver', remote_ver))
            self.btn_update.setToolTip(tr('update.new_ver_tip', remote_ver))
            self.btn_update.setProperty("state", "available")
            self.btn_update.style().unpolish(self.btn_update)
            self.btn_update.style().polish(self.btn_update)
            
            # 2) savecheckresult, formanualclickwhendirectlyuse
            self._cached_update_result = result
            
            # 3) ★ ininputareaonwayshowupdatenotifybanner (containingupdatesummary) 
            try:
                if hasattr(self, '_update_banner') and self._update_banner:
                    self._update_banner.setVisible(True)
                else:
                    release_notes = result.get('release_notes', '').strip()
                    self._update_banner = UpdateNotificationBanner(
                        remote_version=remote_ver,
                        release_name=release_name,
                        local_version=local_ver,
                        release_notes=release_notes,
                    )
                    self._update_banner.updateClicked.connect(self._on_banner_update)
                    # inserttoinputarealayout mosttoppart (batch_bar before) 
                    input_layout = self._batch_bar.parent().layout()
                    if input_layout:
                        input_layout.insertWidget(0, self._update_banner)
                    self._update_banner.setVisible(True)
            except Exception:
                pass  # bannercreatefailednotshadowrespondmainflow
    
    def _on_banner_update(self):
        """notifybanner "standi.e.update"buttonisclick"""
        # hidebanner
        if hasattr(self, '_update_banner') and self._update_banner:
            self._update_banner.setVisible(False)
        # triggerupdateflow
        cached = getattr(self, '_cached_update_result', None)
        if cached and cached.get('has_update'):
            self._on_update_check_result(cached)
            self._cached_update_result = None
        else:
            self._on_check_update()

    def _on_check_update(self):
        """click Update button → backgroundcheckupdate (ifhascacheresultdirectlyuse) """
        # ifstartwhenalreadydetecttonewversion, directlyshowresult
        cached = getattr(self, '_cached_update_result', None)
        if cached and cached.get('has_update'):
            self._on_update_check_result(cached)
            self._cached_update_result = None  # usefinishclearremove
            return
        
        self.btn_update.setEnabled(False)
        self.btn_update.setText("Checking…")
        
        # connectsignal (onlyconnectonce, use UniqueConnection preventduplicate) 
        try:
            self._updateCheckDone.connect(self._on_update_check_result, QtCore.Qt.UniqueConnection)
        except RuntimeError:
            pass
        
        threading.Thread(target=self._bg_check_update, daemon=True).start()

    def _bg_check_update(self):
        """[backgroundthread] call updater.check_update"""
        try:
            from ..utils.updater import check_update
            result = check_update()
        except Exception as e:
            result = {'has_update': False, 'error': str(e), 'local_version': '?', 'remote_version': ''}
        self._updateCheckDone.emit(result)

    @QtCore.Slot(dict)
    def _on_update_check_result(self, result: dict):
        """[mainthread] processcheckresult"""
        self.btn_update.setEnabled(True)
        self.btn_update.setText("Update")
        self.btn_update.setProperty("state", "")  # restoredefaultstyle
        self.btn_update.style().unpolish(self.btn_update)
        self.btn_update.style().polish(self.btn_update)
        
        if result.get('error'):
            QtWidgets.QMessageBox.warning(self, "Check for updates", f"Update check failed:\n{result['error']}")
            return
        
        local_ver = result.get('local_version', '?')
        remote_ver = result.get('remote_version', '?')
        release_name = result.get('release_name', '')
        release_notes = result.get('release_notes', '')
        
        if not result.get('has_update'):
            QtWidgets.QMessageBox.information(
                self, "Check for updates",
                f"You're on the latest version ✓\n\n"
                f"Local version: v{local_ver}\n"
                f"Latest release: v{remote_ver}"
            )
            return

        # ---- hasnewversion, popupoutconfirmconversationbox ----
        detail = f"Local version: v{local_ver}\nLatest release: v{remote_ver}"
        if release_name:
            detail += f"\nRelease name: {release_name}"
        if release_notes:
            detail += f"\nRelease notes: {release_notes}"
        detail += "\n\n⚠️ The plugin window will restart automatically after updating.\n(config, cache, trainData directories are preserved)"

        reply = QtWidgets.QMessageBox.question(
            self, "Update available",
            f"New version v{remote_ver} is available. Update now?\n\n{detail}",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Cancel,
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            self._start_update()

    # Rotating update-progress messages (used during download stage when there's no percentage)
    _UPDATE_FUNNY_MESSAGES = [
        "Files are on their way…",
        "Data is crossing the Internet…",
        "Server is rummaging for your bytes…",
        "Syncing with the backend…",
        "Aligning with related services…",
        "The progress bar is hard at work…",
        "Yanking data down from the cloud…",
        "Server is trying to remember where it put the file…",
        "Composing best practices for this request…",
        "Data has left the station — almost here…",
    ]

    def _start_update(self):
        """startbelowloadandapplicationupdate"""
        # Create the progress dialog — initially uses the first quirky message + indeterminate progress bar (animated)
        first_msg = self._UPDATE_FUNNY_MESSAGES[0]
        self._update_progress_dlg = QtWidgets.QProgressDialog(
            first_msg, "Cancel", 0, 100, self
        )
        self._update_progress_dlg.setWindowTitle("Update MorfyAI")
        self._update_progress_dlg.setWindowModality(QtCore.Qt.WindowModal)
        self._update_progress_dlg.setAutoClose(False)
        self._update_progress_dlg.setAutoReset(False)
        self._update_progress_dlg.setMinimumDuration(0)
        self._update_progress_dlg.setValue(0)
        # When there's no Content-Length, hide the percentage: use indeterminate progress bar
        self._update_progress_dlg.setRange(0, 0)
        # Message-rotation timer (started in _on_update_progress when it sees downloading at 0)
        self._update_msg_index = 0
        self._update_msg_timer = None
        self._update_fade_anim = None
        # QProgressDialog / QProgressBar stylebyglobal QSS control
        
        # connectsignal
        try:
            self._updateProgress.connect(self._on_update_progress, QtCore.Qt.UniqueConnection)
            self._updateApplyDone.connect(self._on_update_apply_result, QtCore.Qt.UniqueConnection)
        except RuntimeError:
            pass
        
        threading.Thread(target=self._bg_download_and_apply, daemon=True).start()

    def _bg_download_and_apply(self):
        """[backgroundthread] belowloadandapplicationupdate"""
        try:
            from ..utils.updater import download_and_apply
            result = download_and_apply(progress_callback=self._update_progress_cb)
        except Exception as e:
            result = {'success': False, 'error': str(e), 'updated_files': 0}
        self._updateApplyDone.emit(result)

    def _update_progress_cb(self, stage: str, percent: int):
        """progresscallback (frombackgroundthreadcall → viasignaltomainthread) """
        self._updateProgress.emit(stage, percent)

    def _stop_update_msg_timer(self):
        """Stop the update-message rotation timer."""
        if getattr(self, '_update_msg_timer', None) is not None:
            self._update_msg_timer.stop()
            self._update_msg_timer.deleteLater()
            self._update_msg_timer = None
        if getattr(self, '_update_fade_anim', None) is not None:
            try:
                self._update_fade_anim.stop()
            except Exception:
                pass
            self._update_fade_anim = None

    def _rotate_update_message(self):
        """Rotate the quirky message and run a slight transition animation."""
        if not hasattr(self, '_update_progress_dlg') or self._update_progress_dlg is None:
            return
        msgs = self._UPDATE_FUNNY_MESSAGES
        if not msgs:
            return
        self._update_msg_index = (self._update_msg_index + 1) % len(msgs)
        new_text = msgs[self._update_msg_index]
        self._update_progress_dlg.setLabelText(new_text)
        # lightentermoveeffect: findtoconversationboxinside  QLabel, use QGraphicsOpacityEffect + QPropertyAnimation
        label = self._update_progress_dlg.findChild(QtWidgets.QLabel)
        if label is not None:
            effect = label.graphicsEffect()
            if effect is None:
                effect = QtWidgets.QGraphicsOpacityEffect(label)
                label.setGraphicsEffect(effect)
            effect.setOpacity(0.28)
            if getattr(self, '_update_fade_anim', None) is not None:
                try:
                    self._update_fade_anim.stop()
                except Exception:
                    pass
            anim = QtCore.QPropertyAnimation(effect, b"opacity")
            anim.setDuration(380)
            anim.setStartValue(0.28)
            anim.setEndValue(1.0)
            anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
            self._update_fade_anim = anim

    @QtCore.Slot(str, int)
    def _on_update_progress(self, stage: str, percent: int):
        """[Main thread] Update the progress bar (indeterminate when no Content-Length + rotating quirky messages)."""
        if not hasattr(self, '_update_progress_dlg') or self._update_progress_dlg is None:
            return
        
        if stage == 'downloading':
            if percent == 0:
                self._update_progress_dlg.setRange(0, 0)
                self._update_progress_dlg.setLabelText(self._UPDATE_FUNNY_MESSAGES[0])
                self._update_msg_index = 0
                if getattr(self, '_update_msg_timer', None) is None:
                    self._update_msg_timer = QtCore.QTimer(self)
                    self._update_msg_timer.timeout.connect(self._rotate_update_message)
                    self._update_msg_timer.start(2200)
            elif 1 <= percent <= 99:
                self._stop_update_msg_timer()
                self._update_progress_dlg.setRange(0, 100)
                self._update_progress_dlg.setValue(percent)
                self._update_progress_dlg.setLabelText(f"positiveinbelowload… {percent}%")
            else:
                self._stop_update_msg_timer()
                self._update_progress_dlg.setRange(0, 100)
                self._update_progress_dlg.setValue(100)
                self._update_progress_dlg.setLabelText("belowloadcomplete")
        elif stage == 'extracting':
            self._stop_update_msg_timer()
            self._update_progress_dlg.setRange(0, 0)
            self._update_progress_dlg.setLabelText("Decompressing…")
            self._update_progress_dlg.setValue(0)
        elif stage == 'applying':
            self._update_progress_dlg.setRange(0, 0)
            self._update_progress_dlg.setLabelText("positiveinupdatefile…")
        elif stage == 'done':
            self._stop_update_msg_timer()
            self._update_progress_dlg.setRange(0, 100)
            self._update_progress_dlg.setValue(100)
            self._update_progress_dlg.setLabelText("updatecomplete! ")
        else:
            self._update_progress_dlg.setValue(percent)
            self._update_progress_dlg.setLabelText(f"{stage} ({percent}%)")

    @QtCore.Slot(dict)
    def _on_update_apply_result(self, result: dict):
        """[mainthread] updatecompleteafter process"""
        self._stop_update_msg_timer()
        # closeprogressitem
        if hasattr(self, '_update_progress_dlg') and self._update_progress_dlg:
            self._update_progress_dlg.close()
            self._update_progress_dlg = None
        
        if not result.get('success'):
            QtWidgets.QMessageBox.critical(
                self, "updatefailed",
                f"updateprocessinoutnowerror:\n{result.get('error', 'notknowerror')}"
            )
            return
        
        updated = result.get('updated_files', 0)
        
        # updatesucceeded → hintandrestart
        reply = QtWidgets.QMessageBox.information(
            self, "updatesucceeded",
            f"alreadysucceededupdate {updated} file! \n\nclick OK standi.e.restartplugin. ",
            QtWidgets.QMessageBox.Ok,
        )
        
        # latencyrestart (letconversationboxcloseafteragainexecute) 
        QtCore.QTimer.singleShot(200, self._do_restart)

    def _do_restart(self):
        """executepluginrestart"""
        try:
            # firstsavecurrentworksection
            main_win = self.window()
            if hasattr(main_win, '_save_workspace'):
                main_win._save_workspace()
            
            # closecurrentwindow
            main_win.force_quit = True
            main_win.close()
            
            # latencyrenewopen (letwindowfinishallcloseafteragainrebuild) 
            # Note: use the absolute-import function reference to avoid cross-import failures after the module is wiped
            from morfyai.utils.updater import restart_plugin as _restart_fn
            QtCore.QTimer.singleShot(500, _restart_fn)
        except Exception as e:
            _dbg(f"[Updater] Restart error: {e}")
            QtWidgets.QMessageBox.warning(
                self, "restartfailed",
                f"autorestartfailed, pleasemanualcloseandrenewopenplugin. \n\nerror: {e}"
            )
    
