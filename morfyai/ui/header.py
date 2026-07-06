# -*- coding: utf-8 -*-
"""
Header UI — top settings bar (provider/model selection, MCP status, settings entry point).

Extracted from ai_tab.py as a Mixin. All methods access AITab instance state via self.
Styling is driven by the global style_template.qss via objectName selectors.
"""

from pathlib import Path
from morfyai.qt_compat import QtWidgets, QtCore, QtGui
from .i18n import tr

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None


class HeaderMixin:
    """Build logic and interactions for the top settings bar."""

    def _build_header(self) -> QtWidgets.QWidget:
        """Top settings bar — single row: Provider + Model + MCP status chip + ⚙ settings.

        Web/Think toggles and the API-key status label are still created (for
        preference-saving code elsewhere) but no longer shown here — they'll
        surface in the Providers settings page instead.
        """
        header = QtWidgets.QFrame()
        header.setObjectName("headerFrame")
        
        outer = QtWidgets.QVBoxLayout(header)
        outer.setContentsMargins(8, 2, 8, 2)
        outer.setSpacing(0)
        
        # -------- Single top bar: ☰ | session title | — | ● MCP | ⚙ | new-chat --------
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)

        # ── Hamburger — opens the sessions drawer ──
        self.btn_hamburger = QtWidgets.QPushButton("☰")
        self.btn_hamburger.setObjectName("btnHamburger")
        self.btn_hamburger.setFixedSize(28, 28)
        self.btn_hamburger.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_hamburger.setToolTip("Sessions")
        self.btn_hamburger.clicked.connect(self._toggle_session_sidebar)
        row.addWidget(self.btn_hamburger)

        # ── Active session title (click opens the sessions drawer) ──
        self.session_title_label = QtWidgets.QLabel("Chat 1")
        self.session_title_label.setObjectName("sessionTitleLabel")
        self.session_title_label.setCursor(QtCore.Qt.PointingHandCursor)
        self.session_title_label.mousePressEvent = lambda ev: self._toggle_session_sidebar()
        row.addWidget(self.session_title_label)

        # Provider — created here (all wiring kept) but shown in Settings > Providers,
        # not in the top bar. Kept as a live widget so provider-change logic still works.
        self.provider_combo = QtWidgets.QComboBox()
        self.provider_combo.setObjectName("providerCombo")
        self.provider_combo.addItem("Ollama", 'ollama')
        self.provider_combo.addItem("DeepSeek", 'deepseek')
        self.provider_combo.addItem("GLM", 'glm')
        self.provider_combo.addItem("OpenAI", 'openai')
        self.provider_combo.addItem("Duojie", 'duojie')
        self.provider_combo.addItem("OpenRouter", 'openrouter')
        self.provider_combo.addItem("Custom", 'custom')
        self.provider_combo.setMinimumWidth(70)
        self.provider_combo.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self.provider_combo.setVisible(False)

        # Custom config button (only used for the Custom provider; kept, hidden)
        self.btn_custom_config = QtWidgets.QPushButton("⚙")
        self.btn_custom_config.setObjectName("btnCustomConfig")
        self.btn_custom_config.setFixedSize(22, 22)
        self.btn_custom_config.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_custom_config.setToolTip("Configure Custom Model URL, API key, and model names")
        self.btn_custom_config.setVisible(False)
        self.btn_custom_config.clicked.connect(self._open_custom_provider_dialog)

        # Model
        self.model_combo = QtWidgets.QComboBox()
        self.model_combo.setObjectName("modelCombo")
        self._model_map = {
            'ollama': ['qwen2.5:14b', 'qwen2.5:7b', 'llama3:8b', 'mistral:7b'],
            'deepseek': ['deepseek-v4-flash', 'deepseek-v4-pro', 'deepseek-chat', 'deepseek-reasoner'],
            'glm': ['glm-4.7'],
            'openai': ['gpt-5.2', 'gpt-5.3-codex'],
            'duojie': [
                'claude-opus-4-6-gemini',
                'claude-opus-4-6-max',
                'claude-sonnet-4-5',
                'claude-sonnet-4-6',
                'gemini-3-flash',
                'gemini-3.1-pro',
                'glm-5-turbo',
                'glm-5.1',
                'MiniMax-M2.7',
                'MiniMax-M2.7-highspeed',
            ],
            'openrouter': [
                'anthropic/claude-opus-4.8',
                'anthropic/claude-sonnet-4.8',
                'anthropic/claude-sonnet-4.6',
                'anthropic/claude-opus-4.6',
                'anthropic/claude-sonnet-4.5',
                'anthropic/claude-haiku-4.5',
                'openai/gpt-5.2',
                'openai/gpt-5.3-codex',
                'openai/o4-mini',
                'google/gemini-3-flash-preview',
                'google/gemini-2.5-pro',
                'google/gemini-2.5-flash',
                'deepseek/deepseek-v3.2',
                'deepseek/deepseek-r1',
                'x-ai/grok-4.1-fast',
                'meta-llama/llama-4-maverick',
                'qwen/qwen3-235b-a22b',
                'mistralai/mistral-large-2512',
            ],
            'custom': [],  # populated dynamically by the user via the config dialog
        }
        # Runtime configuration for the Custom provider (loaded from persisted config)
        self._custom_provider_config = {
            'api_url': '',
            'api_key': '',
            'models': [],           # user-configured model names
            'context_limit': 128000,
            'supports_vision': False,
            'supports_fc': True,    # whether function calling is supported
        }
        self._load_custom_provider_config()
        self._model_context_limits = {
            'qwen2.5:14b': 32000, 'qwen2.5:7b': 32000, 'llama3:8b': 8000, 'mistral:7b': 32000,
            'deepseek-v4-flash': 128000, 'deepseek-v4-pro': 128000,
            'deepseek-chat': 128000, 'deepseek-reasoner': 128000,
            'glm-4.7': 200000,
            'gpt-5.2': 128000,
            'gpt-5.3-codex': 200000,
            # Duojie models
            'claude-opus-4-6-gemini': 200000,
            'claude-opus-4-6-max': 200000,
            'claude-sonnet-4-5': 200000,
            'claude-sonnet-4-6': 200000,
            'gemini-3-flash': 1048576,
            'gemini-3.1-pro': 1048576,
            'glm-5-turbo': 200000,
            'glm-5.1': 200000,
            'MiniMax-M2.7': 128000,
            'MiniMax-M2.7-highspeed': 128000,
            # OpenRouter models
            'anthropic/claude-opus-4.8': 1000000,
            'anthropic/claude-sonnet-4.8': 1000000,
            'anthropic/claude-sonnet-4.6': 1000000,
            'anthropic/claude-opus-4.6': 1000000,
            'anthropic/claude-sonnet-4.5': 1000000,
            'anthropic/claude-haiku-4.5': 200000,
            'openai/gpt-5.2': 400000,
            'openai/gpt-5.3-codex': 400000,
            'openai/o4-mini': 200000,
            'google/gemini-3-flash-preview': 1048576,
            'google/gemini-2.5-pro': 1048576,
            'google/gemini-2.5-flash': 1048576,
            'deepseek/deepseek-v3.2': 163840,
            'deepseek/deepseek-r1': 64000,
            'x-ai/grok-4.1-fast': 2000000,
            'meta-llama/llama-4-maverick': 1048576,
            'qwen/qwen3-235b-a22b': 131072,
            'mistralai/mistral-large-2512': 262144,
        }
        # Model feature flags
        self._model_features = {
            # Ollama
            'qwen2.5:14b':               {'supports_prompt_caching': True, 'supports_vision': False},
            'qwen2.5:7b':                {'supports_prompt_caching': True, 'supports_vision': False},
            'llama3:8b':                  {'supports_prompt_caching': True, 'supports_vision': False},
            'mistral:7b':                 {'supports_prompt_caching': True, 'supports_vision': False},
            # DeepSeek — the api.deepseek.com chat endpoint rejects image_url content
            # ("unknown variant 'image_url'"), so NONE of these support vision.
            'deepseek-v4-flash':          {'supports_prompt_caching': True, 'supports_vision': False},
            'deepseek-v4-pro':            {'supports_prompt_caching': True, 'supports_vision': False},
            'deepseek-chat':              {'supports_prompt_caching': True, 'supports_vision': False},
            'deepseek-reasoner':          {'supports_prompt_caching': True, 'supports_vision': False},
            # GLM
            'glm-4.7':                    {'supports_prompt_caching': True, 'supports_vision': False},
            # OpenAI
            'gpt-5.2':                    {'supports_prompt_caching': True, 'supports_vision': True},
            'gpt-5.3-codex':              {'supports_prompt_caching': True, 'supports_vision': True},
            # Duojie - Claude
            'claude-opus-4-6-gemini':    {'supports_prompt_caching': True, 'supports_vision': True},
            'claude-opus-4-6-max':        {'supports_prompt_caching': True, 'supports_vision': True},
            'claude-sonnet-4-5':          {'supports_prompt_caching': True, 'supports_vision': True},
            'claude-sonnet-4-6':          {'supports_prompt_caching': True, 'supports_vision': True},
            # Duojie - Gemini
            'gemini-3-flash':             {'supports_prompt_caching': True, 'supports_vision': True},
            'gemini-3.1-pro':             {'supports_prompt_caching': True, 'supports_vision': True},
            # Duojie - GLM (Anthropic protocol)
            'glm-5-turbo':                {'supports_prompt_caching': True, 'supports_vision': False},
            'glm-5.1':                    {'supports_prompt_caching': True, 'supports_vision': False},
            # Duojie - MiniMax
            'MiniMax-M2.7':               {'supports_prompt_caching': True, 'supports_vision': False},
            'MiniMax-M2.7-highspeed':     {'supports_prompt_caching': True, 'supports_vision': False},
            # OpenRouter models
            'anthropic/claude-opus-4.8':          {'supports_prompt_caching': True, 'supports_vision': True},
            'anthropic/claude-sonnet-4.8':        {'supports_prompt_caching': True, 'supports_vision': True},
            'anthropic/claude-sonnet-4.6':        {'supports_prompt_caching': True, 'supports_vision': True},
            'anthropic/claude-opus-4.6':          {'supports_prompt_caching': True, 'supports_vision': True},
            'anthropic/claude-sonnet-4.5':        {'supports_prompt_caching': True, 'supports_vision': True},
            'anthropic/claude-haiku-4.5':         {'supports_prompt_caching': True, 'supports_vision': True},
            'openai/gpt-5.2':                     {'supports_prompt_caching': True, 'supports_vision': True},
            'openai/gpt-5.3-codex':               {'supports_prompt_caching': True, 'supports_vision': True},
            'openai/o4-mini':                     {'supports_prompt_caching': True, 'supports_vision': True},
            'google/gemini-3-flash-preview':      {'supports_prompt_caching': True, 'supports_vision': True},
            'google/gemini-2.5-pro':              {'supports_prompt_caching': True, 'supports_vision': True},
            'google/gemini-2.5-flash':            {'supports_prompt_caching': True, 'supports_vision': True},
            'deepseek/deepseek-v3.2':             {'supports_prompt_caching': True, 'supports_vision': False},
            'deepseek/deepseek-r1':               {'supports_prompt_caching': True, 'supports_vision': False},
            'x-ai/grok-4.1-fast':                 {'supports_prompt_caching': True, 'supports_vision': True},
            'meta-llama/llama-4-maverick':        {'supports_prompt_caching': True, 'supports_vision': True},
            'qwen/qwen3-235b-a22b':               {'supports_prompt_caching': True, 'supports_vision': False},
            'mistralai/mistral-large-2512':       {'supports_prompt_caching': True, 'supports_vision': True},
        }
        self._refresh_models('ollama')
        self.model_combo.setMinimumWidth(100)
        self.model_combo.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self.model_combo.setEditable(False)  # not editable by default; switched to editable in Custom mode
        # Model combo lives in the composer toolbar (added there in _build_input_area),
        # matching the mockup. Created here so all provider/model wiring stays intact.

        # API Key status — moved into Settings > Providers; kept alive (unparented)
        # so existing code that sets its text doesn't break, but no longer shown here.
        self.key_status = QtWidgets.QLabel()
        self.key_status.setObjectName("keyStatus")
        self.key_status.setMaximumWidth(90)
        self.key_status.setMinimumWidth(0)
        from morfyai.qt_compat import QtCore as _qc
        self.key_status.setTextInteractionFlags(_qc.Qt.NoTextInteraction)
        self.key_status.setVisible(False)

        # Web / Think toggles — moved into Settings > Providers (per-model config);
        # kept alive so _wire_events / preference-saving connections still work.
        self.web_check = QtWidgets.QCheckBox("Web")
        self.web_check.setObjectName("chkWeb")
        self.web_check.setChecked(True)
        self.web_check.setVisible(False)

        self.think_check = QtWidgets.QCheckBox("Think")
        self.think_check.setObjectName("chkThink")
        self.think_check.setChecked(True)
        self.think_check.setToolTip(tr('header.think.tooltip'))
        self.think_check.setVisible(False)

        row.addStretch()

        # MCP connection status chip
        self.mcp_status_chip = QtWidgets.QPushButton("● MCP")
        self.mcp_status_chip.setObjectName("mcpStatusChip")
        self.mcp_status_chip.setCursor(QtCore.Qt.PointingHandCursor)
        self.mcp_status_chip.setProperty("connected", False)
        self.mcp_status_chip.setToolTip("MCP disconnected — click to open Connect to Claude")
        self.mcp_status_chip.clicked.connect(self._open_claude_connect)
        row.addWidget(self.mcp_status_chip)

        # ⚙ settings entry point (opens the consolidated Settings dialog)
        self.btn_overflow = QtWidgets.QPushButton("⚙")
        self.btn_overflow.setObjectName("btnOverflow")
        self.btn_overflow.setFixedSize(26, 26)
        self.btn_overflow.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_overflow.setToolTip("Settings")
        self.btn_overflow.clicked.connect(self._open_settings_dialog)
        row.addWidget(self.btn_overflow)

        # ✎ new-chat button
        self.btn_new_chat_header = QtWidgets.QPushButton("✎")
        self.btn_new_chat_header.setObjectName("btnNewChatHeader")
        self.btn_new_chat_header.setFixedSize(26, 26)
        self.btn_new_chat_header.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_new_chat_header.setToolTip("New chat")
        self.btn_new_chat_header.clicked.connect(self._new_session)
        row.addWidget(self.btn_new_chat_header)

        outer.addLayout(row)

        # Hidden stash — keeps functional-but-not-shown widgets parented so they
        # don't become stray top-level windows. The model combo is re-parented
        # into the composer toolbar later (in _build_input_area).
        self._header_stash = QtWidgets.QWidget()
        self._header_stash.setObjectName("headerStash")
        self._header_stash.setVisible(False)
        stash_lay = QtWidgets.QVBoxLayout(self._header_stash)
        stash_lay.setContentsMargins(0, 0, 0, 0)
        stash_lay.setSpacing(0)
        for _w in (self.provider_combo, self.btn_custom_config, self.key_status,
                   self.web_check, self.think_check, self.model_combo):
            stash_lay.addWidget(_w)
        outer.addWidget(self._header_stash)

        # Poll MCP connection state so the chip reflects live status without
        # requiring the user to open the Connect dialog.
        self._mcp_status_timer = QtCore.QTimer(self)
        self._mcp_status_timer.setInterval(3000)
        self._mcp_status_timer.timeout.connect(self._refresh_mcp_status_chip)
        self._mcp_status_timer.start()
        self._refresh_mcp_status_chip()
        
        # -------- Hidden buttons (preserved as self.btn_xxx for _wire_events compatibility) --------
        # These buttons are not added to any layout; they exist only for signal connections.
        self.btn_key = QtWidgets.QPushButton("Key")
        self.btn_key.setObjectName("btnSmall")
        self.btn_key.setVisible(False)
        
        self.btn_clear = QtWidgets.QPushButton("Clear")
        self.btn_clear.setObjectName("btnSmall")
        self.btn_clear.setVisible(False)
        
        self.btn_cache = QtWidgets.QPushButton("Cache")
        self.btn_cache.setObjectName("btnSmall")
        self.btn_cache.setVisible(False)
        
        self.btn_optimize = QtWidgets.QPushButton("Opt")
        self.btn_optimize.setObjectName("btnOptimize")
        self.btn_optimize.setVisible(False)
        
        # btn_update kept as a no-op stub so external _wire_events references don't break
        self.btn_update = QtWidgets.QPushButton("Update")
        self.btn_update.setObjectName("btnUpdate")
        self.btn_update.setVisible(False)
        self.btn_update.setEnabled(False)

        self.btn_font_scale = QtWidgets.QPushButton("Aa")
        self.btn_font_scale.setObjectName("btnFontScale")
        self.btn_font_scale.setVisible(False)

        return header

    @staticmethod
    def _load_logo_pixmap_header(svg_path: str, target_h: int = 26):
        """Load MorfyFX SVG into a crisp QPixmap.

        Uses QSvgRenderer (if available) for sharp scaling — falls back to
        QPixmap direct load (works when Qt SVG plugin is loaded).
        """
        try:
            # Prefer QSvgRenderer for sharp vector rendering at exact target size
            QSvgRenderer = None
            try:
                from PySide6.QtSvg import QSvgRenderer as _R
                QSvgRenderer = _R
            except Exception:
                try:
                    from PySide2.QtSvg import QSvgRenderer as _R
                    QSvgRenderer = _R
                except Exception:
                    pass

            if QSvgRenderer is not None:
                renderer = QSvgRenderer(svg_path)
                if renderer.isValid():
                    default_size = renderer.defaultSize()
                    if default_size.height() > 0:
                        target_w = int(default_size.width() * (target_h / default_size.height()))
                    else:
                        target_w = target_h
                    # Render at 2x density for crisp result on high-DPI displays
                    dpr = 2
                    pix = QtGui.QPixmap(target_w * dpr, target_h * dpr)
                    pix.fill(QtCore.Qt.transparent)
                    painter = QtGui.QPainter(pix)
                    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
                    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
                    renderer.render(painter)
                    painter.end()
                    pix.setDevicePixelRatio(dpr)
                    return pix

            # Fallback: direct QPixmap load
            pix = QtGui.QPixmap(svg_path)
            if not pix.isNull():
                return pix.scaledToHeight(target_h, QtCore.Qt.SmoothTransformation)
            return None
        except Exception:
            return None

    def _open_settings_dialog(self):
        """Open the consolidated Settings window (grouped sidebar nav)."""
        try:
            from .settings_dialog import SettingsDialog
            dlg = SettingsDialog(self, parent=self)
            # Apply the same rendered QSS so the dialog matches the panel theme
            try:
                dlg.setStyleSheet(self._theme.render())
            except Exception:
                pass
            dlg.exec_()
        except Exception as e:
            _dbg(f"[Settings] failed to open, falling back to menu: {e}")
            self._show_overflow_menu()

    def _refresh_mcp_status_chip(self):
        """Reflect the real MCP server/client state on the header chip."""
        try:
            from ..utils import claude_connect as cc
            report = cc.connection_report()
            running = bool(report.get("server_running"))
            connected = bool(report.get("claude_connected"))
        except Exception:
            running = False
            connected = False

        chip = getattr(self, 'mcp_status_chip', None)
        if chip is None:
            return
        chip.setProperty("connected", running)
        chip.style().unpolish(chip)
        chip.style().polish(chip)
        if connected:
            chip.setToolTip("MCP connected — a client is attached")
        elif running:
            chip.setToolTip("MCP server running — waiting for a client")
        else:
            chip.setToolTip("MCP disconnected — click to start the server")

    def _show_overflow_menu(self):
        """Show the overflow menu — collects low-frequency features."""
        menu = QtWidgets.QMenu(self)

        menu.addAction("API Key", self.btn_key.click)
        menu.addAction("Clear Chat", self.btn_clear.click)
        menu.addAction("Cache", self.btn_cache.click)
        menu.addAction("Optimize", self.btn_optimize.click)
        menu.addSeparator()
        menu.addAction("Font (Aa)", self.btn_font_scale.click)
        menu.addSeparator()
        menu.addAction(tr('rules.menu_label'), self._open_rules_editor)
        menu.addAction(tr('plugin.menu_label'), self._open_plugin_manager)

        # Long-term memory global toggle (off by default) — checkable action
        act_memory = menu.addAction(tr('memory.menu_label'))
        act_memory.setCheckable(True)
        act_memory.setChecked(bool(getattr(self, '_memory_enabled', False)))
        act_memory.setToolTip(tr('memory.menu_tooltip'))
        act_memory.toggled.connect(self._on_memory_toggle_from_menu)

        menu.addSeparator()
        menu.addAction("Connect to Claude", self._open_claude_connect)
        menu.addAction("Vision (Eyes) Setup", self._open_vision_setup)
        menu.addSeparator()
        menu.addAction("Debug Console", self._open_debug_console)
        menu.addAction("About MorfyAI", self._open_about_dialog)

        # Popup position: below the overflow button
        menu.exec_(self.btn_overflow.mapToGlobal(
            QtCore.QPoint(0, self.btn_overflow.height())
        ))

    def _open_claude_connect(self):
        """Start the MCP server and show a LIVE connection panel for Claude.

        Shows auto-refreshing server + Claude-client status, step-by-step guidance,
        and copy-paste configs. Fully defensive — never breaks the panel.
        """
        try:
            from ..utils import claude_connect as cc
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Connect to Claude", f"Module unavailable: {e}")
            return
        try:
            cc.start()  # ensure the server is running
            report0 = cc.connection_report()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Connect to Claude", f"Failed to start server: {e}")
            return
        url = report0.get("url", "")

        steps = (
            "Step 1.  Open Houdini + MorfyAI FIRST, then open Claude Code.\n"
            "            (Claude Code attaches MCP servers at startup — order matters.)\n"
            "Step 2.  Claude Code auto-connects via .mcp.json. If not, run the command\n"
            "            below (or paste the config), then reopen Claude Code.\n"
            "Step 3.  Watch the status above — it turns green when Claude connects."
        )
        cfg_text = (
            "-- Claude Code (run once) --------------------------------\n"
            + report0.get("claude_code_command", "") + "\n\n"
            + "or save as .mcp.json in your project:\n" + report0.get("claude_code_json", "") + "\n\n"
            + "-- Claude Desktop (claude_desktop_config.json) ----------\n"
            + report0.get("claude_desktop_json", "")
        )

        try:
            dlg = QtWidgets.QDialog(self)
            dlg.setObjectName("morfyDialog")
            dlg.setWindowTitle("Connect to Claude")
            dlg.resize(660, 560)
            lay = QtWidgets.QVBoxLayout(dlg)
            lay.setContentsMargins(20, 18, 20, 16)

            lbl_server = QtWidgets.QLabel()
            lbl_claude = QtWidgets.QLabel()
            for _L in (lbl_server, lbl_claude):
                _L.setTextFormat(QtCore.Qt.RichText)
                lay.addWidget(_L)

            steps_lbl = QtWidgets.QLabel(steps)
            steps_lbl.setWordWrap(True)
            steps_lbl.setStyleSheet("color:#cbd5e1; padding:6px 0;")
            lay.addWidget(steps_lbl)

            edit = QtWidgets.QPlainTextEdit()
            edit.setReadOnly(True)
            edit.setPlainText(cfg_text)
            lay.addWidget(edit)

            def _fmt(report):
                if report.get("server_running"):
                    lbl_server.setText(f"<b>Server:</b> <span style='color:#22c55e'>&#9679; RUNNING</span> &nbsp;&nbsp;{url}")
                else:
                    lbl_server.setText("<b>Server:</b> <span style='color:#ef4444'>&#9679; not started</span>")
                if report.get("claude_connected"):
                    s = report.get("last_client_activity_sec")
                    ago = f" ({int(s)}s ago)" if isinstance(s, (int, float)) else ""
                    lbl_claude.setText(f"<b>Claude:</b> <span style='color:#22c55e'>&#9679; connected{ago}</span>")
                else:
                    lbl_claude.setText("<b>Claude:</b> <span style='color:#eab308'>&#9675; waiting for Claude to connect...</span>")

            def _refresh():
                try:
                    _fmt(cc.connection_report())
                except Exception:
                    pass

            _fmt(report0)

            btn_row = QtWidgets.QHBoxLayout()
            btn_refresh = QtWidgets.QPushButton("Refresh")
            btn_refresh.clicked.connect(_refresh)
            btn_copy = QtWidgets.QPushButton("Copy Claude Code cmd")
            btn_copy.clicked.connect(
                lambda: QtWidgets.QApplication.clipboard().setText(report0.get("claude_code_command", "")))
            btn_close = QtWidgets.QPushButton("Close")
            btn_close.clicked.connect(dlg.accept)
            btn_row.addWidget(btn_refresh)
            btn_row.addWidget(btn_copy)
            btn_row.addStretch()
            btn_row.addWidget(btn_close)
            lay.addLayout(btn_row)

            # consistent MorfyAI dialog styling (matches About + Vision Setup)
            try:
                from .cursor_widgets import morfy_dialog_qss, style_primary_button, style_secondary_button
                style_secondary_button(btn_refresh)
                style_secondary_button(btn_copy)
                style_primary_button(btn_close)
                dlg.setStyleSheet(morfy_dialog_qss("morfyDialog"))
            except Exception:
                pass

            # auto-refresh the status every 2s while the dialog is open
            timer = QtCore.QTimer(dlg)
            timer.timeout.connect(_refresh)
            timer.start(2000)
            dlg.finished.connect(lambda *_a: timer.stop())

            dlg.exec_()
        except Exception as e:
            QtWidgets.QMessageBox.information(
                self, "Connect to Claude", f"Server running at {url}\n\n{cfg_text[:1200]}")
            _dbg(f"[Header] Claude connect dialog fallback: {e}")

    def _open_about_dialog(self):
        """About dialog — kredit, versi, license."""
        try:
            from .cursor_widgets import AboutDialog
            dlg = AboutDialog(parent=self)
            dlg.exec_()
        except Exception as e:
            _dbg(f"[Header] Failed to open About dialog: {e}")

    def _open_debug_console(self):
        """Open the in-app Debug Console (replaces Houdini Console spam)."""
        try:
            from .cursor_widgets import DebugConsoleDialog
            # Reuse single instance so the buffer stays visible across opens
            if not hasattr(self, "_debug_console_dlg") or self._debug_console_dlg is None:
                self._debug_console_dlg = DebugConsoleDialog(parent=self)
            self._debug_console_dlg.show()
            self._debug_console_dlg.raise_()
            self._debug_console_dlg.activateWindow()
        except Exception as e:
            _dbg(f"[Header] Failed to open Debug Console: {e}")

    def _open_rules_editor(self):
        """Open the user-defined rules editor."""
        try:
            from .cursor_widgets import RulesEditorDialog
            dlg = RulesEditorDialog(parent=self)
            dlg.exec_()
        except Exception as e:
            _dbg(f"[Header] Failed to open rules editor: {e}")

    def _open_plugin_manager(self):
        """Open the plugin manager panel."""
        try:
            from .cursor_widgets import PluginManagerDialog
            dlg = PluginManagerDialog(parent=self)
            dlg.pluginStateChanged.connect(self._on_plugin_state_changed)
            dlg.exec_()
        except Exception as e:
            _dbg(f"[Header] Failed to open plugin manager: {e}")

    def _on_plugin_state_changed(self):
        """Callback after plugin state changes (re-mounts buttons, etc.)."""
        try:
            from ..utils.hooks import get_hook_manager
            bridge = get_hook_manager().get_ui_bridge()
            if bridge:
                bridge.mount_buttons()
        except Exception:
            pass

    def _on_memory_toggle_from_menu(self, checked: bool):
        """Toggle the long-term memory system from the overflow menu."""
        try:
            self.set_memory_enabled(bool(checked))
        except Exception as e:
            _dbg(f"[Header] Memory toggle failed: {e}")

    def _retranslate_header(self):
        """Refresh all translated text in the header after a language change."""
        self.think_check.setToolTip(tr('header.think.tooltip'))
        self.btn_cache.setToolTip(tr('header.cache.tooltip'))
        self.btn_optimize.setToolTip(tr('header.optimize.tooltip'))
        self.btn_update.setToolTip(tr('header.update.tooltip'))
        self.btn_font_scale.setToolTip(tr('header.font.tooltip'))

    # ============================================================
    # Custom Provider configuration
    # ============================================================

    def _load_custom_provider_config(self):
        """Load Custom Provider settings from the persisted config file."""
        try:
            from shared.common_utils import load_config
            cfg, _ = load_config('ai', dcc_type='houdini')
            if cfg:
                self._custom_provider_config['api_url'] = cfg.get('custom_api_url', '')
                self._custom_provider_config['api_key'] = cfg.get('custom_api_key', '')
                models_str = cfg.get('custom_models', '')
                if models_str:
                    self._custom_provider_config['models'] = [m.strip() for m in models_str.split(',') if m.strip()]
                try:
                    self._custom_provider_config['context_limit'] = int(cfg.get('custom_context_limit', '128000'))
                except (ValueError, TypeError):
                    pass
                self._custom_provider_config['supports_vision'] = cfg.get('custom_supports_vision', 'false').lower() == 'true'
                self._custom_provider_config['supports_fc'] = cfg.get('custom_supports_fc', 'true').lower() != 'false'
                # Update the model list
                self._model_map['custom'] = self._custom_provider_config['models']
                # Sync to AIClient if it's already initialised
                self._sync_custom_to_client()
        except Exception as e:
            _dbg(f"[Header] Load custom config failed: {e}")

    def _save_custom_provider_config(self):
        """Persist Custom Provider settings to the config file."""
        try:
            from shared.common_utils import load_config, save_config
            cfg, _ = load_config('ai', dcc_type='houdini')
            cfg = cfg or {}
            cc = self._custom_provider_config
            cfg['custom_api_url'] = cc['api_url']
            cfg['custom_api_key'] = cc['api_key']
            cfg['custom_models'] = ','.join(cc['models'])
            cfg['custom_context_limit'] = str(cc['context_limit'])
            cfg['custom_supports_vision'] = 'true' if cc['supports_vision'] else 'false'
            cfg['custom_supports_fc'] = 'true' if cc['supports_fc'] else 'false'
            save_config('ai', cfg, dcc_type='houdini')
        except Exception as e:
            _dbg(f"[Header] Save custom config failed: {e}")

    def _open_vision_setup(self):
        """Dialog to set the VISION ('eyes') model key used by skill__visual_check.

        This is separate from the main-model dropdown on purpose: the vision model
        is only called internally to LOOK at renders (the main model stays the brain).
        Writes vision_provider / <provider>_api_key / vision_model to the config.
        Fully defensive — never breaks the panel.
        """
        try:
            from shared.common_utils import load_config, save_config
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Vision Setup", f"Config module unavailable: {e}")
            return

        # provider -> (label, config key name, default model, where-to-get URL)
        provs = [
            ("gemini", "Gemini (cheapest, recommended)", "gemini_api_key", "gemini-2.5-flash-lite",
             "aistudio.google.com/apikey"),
            ("openrouter", "OpenRouter", "openrouter_api_key", "google/gemini-2.0-flash-001",
             "openrouter.ai/keys"),
            ("openai", "OpenAI", "openai_api_key", "gpt-4o-mini", "platform.openai.com/api-keys"),
        ]
        try:
            cfg, _ = load_config('ai', dcc_type='houdini')
            cfg = cfg or {}
        except Exception:
            cfg = {}

        # ── Standard dialog, styled to EXACTLY match the About dialog (consistency).
        dlg = QtWidgets.QDialog(self)
        dlg.setObjectName("visionDialog")
        dlg.setWindowTitle("Vision (Eyes) Setup")
        dlg.setMinimumWidth(460)
        dlg.setModal(True)

        def _sep():
            s = QtWidgets.QFrame()
            s.setFrameShape(QtWidgets.QFrame.HLine)
            s.setStyleSheet("background: rgba(255,255,255,18); max-height: 1px; border: none;")
            return s

        root = QtWidgets.QVBoxLayout(dlg)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(10)

        # title (orange, like About's app name)
        title = QtWidgets.QLabel("Vision (Eyes) Setup")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ff8c2a;")
        root.addWidget(title)
        sub = QtWidgets.QLabel("The assistant's eyes — a cheap vision model looks at renders to catch what "
                               "the data can't (upside-down, floating, wrong shape). Your main model stays the brain.")
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #94a3b8; font-size: 12px;")
        root.addWidget(sub)

        root.addWidget(_sep())

        # form rows (About-style label colors)
        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        def _lbl(t):
            l = QtWidgets.QLabel(t)
            l.setStyleSheet("color: #64748b; font-size: 12px;")
            return l

        combo = QtWidgets.QComboBox()
        combo.setCursor(QtCore.Qt.PointingHandCursor)
        for key, label, _k, _m, _u in provs:
            combo.addItem(label, key)
        cur_prov = (cfg.get("vision_provider", "") or "gemini").strip().lower()
        for i, (key, *_rest) in enumerate(provs):
            if key == cur_prov:
                combo.setCurrentIndex(i)
                break
        form.addRow(_lbl("Provider"), combo)

        key_edit = QtWidgets.QLineEdit()
        key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        key_edit.setPlaceholderText("paste API key here")
        form.addRow(_lbl("API Key"), key_edit)

        model_edit = QtWidgets.QLineEdit()
        form.addRow(_lbl("Model"), model_edit)

        geturl = QtWidgets.QLabel()
        geturl.setOpenExternalLinks(True)
        geturl.setTextFormat(QtCore.Qt.RichText)
        form.addRow(_lbl("Get a key"), geturl)
        root.addLayout(form)

        def _refresh(*_a):
            key = combo.currentData()
            for pk, _label, ckey, dmodel, url in provs:
                if pk == key:
                    existing = (cfg.get(ckey, "") or "").strip()
                    key_edit.setText(existing)
                    model_edit.setPlaceholderText(f"default: {dmodel}")
                    cur_model = (cfg.get("vision_model", "") or "").strip()
                    model_edit.setText(cur_model if cur_model else "")
                    geturl.setText(f'<a href="https://{url}" style="color:#ff8c2a;text-decoration:none;">{url}</a>')
                    break
        combo.currentIndexChanged.connect(_refresh)
        _refresh()

        root.addWidget(_sep())
        note = QtWidgets.QLabel("Tip: Gemini has a free tier — usually enough for visual checks. "
                                "Leave Model blank to use the recommended default.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #64748b; font-size: 11px; font-style: italic;")
        root.addWidget(note)

        def _save():
            try:
                prov = combo.currentData()
                ckey = {k: c for k, _l, c, _m, _u in provs}[prov]
                cfg2, _ = load_config('ai', dcc_type='houdini')
                cfg2 = cfg2 or {}
                cfg2['vision_provider'] = prov
                key_val = key_edit.text().strip()
                if key_val:
                    cfg2[ckey] = key_val
                mv = model_edit.text().strip()
                if mv:
                    cfg2['vision_model'] = mv
                save_config('ai', cfg2, dcc_type='houdini')
                dlg.accept()
                QtWidgets.QMessageBox.information(
                    self, "Vision Setup",
                    f"Saved ✓  Vision provider: {prov}. The assistant can now SEE renders via visual_check.")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Vision Setup", f"Save failed: {e}")

        root.addStretch(1)

        # buttons (Save = orange gradient identical to About's Close button)
        brow = QtWidgets.QHBoxLayout()
        brow.addStretch(1)
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.setMinimumWidth(80)
        cancel_btn.setCursor(QtCore.Qt.PointingHandCursor)
        cancel_btn.setStyleSheet(
            "QPushButton { background:#1a1b22; color:#cbd5e1; border:1px solid rgba(255,255,255,20);"
            " border-radius:8px; padding:6px 16px; }"
            "QPushButton:hover { background:#22232c; }")
        cancel_btn.clicked.connect(dlg.reject)
        save_btn = QtWidgets.QPushButton("Save")
        save_btn.setMinimumWidth(90)
        save_btn.setCursor(QtCore.Qt.PointingHandCursor)
        save_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            " stop:0 #fb7a1a, stop:1 #ea580c); color:#ffffff; border:none; border-radius:8px;"
            " padding:6px 18px; font-weight:bold; }"
            "QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            " stop:0 #ff9342, stop:1 #fb7a1a); }")
        save_btn.clicked.connect(_save)
        brow.addWidget(cancel_btn)
        brow.addWidget(save_btn)
        root.addLayout(brow)

        # dialog background + inputs — match About (#0d0e13, subtle border, 10px radius)
        dlg.setStyleSheet(
            "QDialog#visionDialog { background:#0d0e13; border:1px solid rgba(255,255,255,18); border-radius:10px; }"
            "#visionDialog QLineEdit { background:#15161d; color:#e2e8f0; border:1px solid rgba(255,255,255,20);"
            " border-radius:6px; padding:6px 8px; }"
            "#visionDialog QLineEdit:focus { border:1px solid #ff8c2a; }"
            "#visionDialog QComboBox { background:#15161d; color:#e2e8f0; border:1px solid rgba(255,255,255,20);"
            " border-radius:6px; padding:5px 8px; }"
            "#visionDialog QComboBox QAbstractItemView { background:#15161d; color:#e2e8f0;"
            " selection-background-color:#1c1e36; border:1px solid rgba(255,255,255,20); }")

        dlg.exec_()

    def _sync_custom_to_client(self):
        """Sync the Custom configuration over to AIClient."""
        try:
            client = getattr(self, 'client', None)
            if client is None:
                return
            cc = self._custom_provider_config
            if cc['api_url']:
                client.set_custom_provider(
                    api_url=cc['api_url'],
                    api_key=cc['api_key'],
                    supports_fc=cc['supports_fc'],
                )
            if cc['api_key']:
                client._api_keys['custom'] = cc['api_key']
        except Exception as e:
            _dbg(f"[Header] Sync custom config to client failed: {e}")

    def _on_provider_changed_custom_visibility(self):
        """Toggle Custom config button visibility and combo editability when the provider changes."""
        provider = self._current_provider()
        is_custom = (provider == 'custom')
        self.btn_custom_config.setVisible(is_custom)
        # In Custom mode, allow direct model-name entry in model_combo
        self.model_combo.setEditable(is_custom)
        # Only auto-open the legacy Qt config dialog for the OLD Qt panel.
        # In the web panel (_web_headless), provider switches are driven by
        # bridge.setProvider() from JS — this dialog is QDialog.exec_()
        # (modal), which blocks the whole Qt event loop mid-call, hanging
        # the bridge call and desyncing the web UI (surprise popup +
        # composer model list going stale). The web Settings page has its
        # own inline Custom-provider config instead.
        if is_custom and not self._custom_provider_config.get('api_url') and not getattr(self, '_web_headless', False):
            # First time selecting Custom and not yet configured — open the config dialog
            QtCore.QTimer.singleShot(100, self._open_custom_provider_dialog)

    def _open_custom_provider_dialog(self):
        """Open the Custom Provider configuration dialog."""
        dlg = _CustomProviderDialog(self._custom_provider_config, parent=self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            new_cfg = dlg.get_config()
            self._custom_provider_config.update(new_cfg)
            # Update model list
            self._model_map['custom'] = new_cfg['models']
            # Dynamically register model features and context limits
            for m in new_cfg['models']:
                self._model_context_limits[m] = new_cfg['context_limit']
                self._model_features[m] = {
                    'supports_prompt_caching': True,
                    'supports_vision': new_cfg['supports_vision'],
                }
            # Sync to AIClient
            self._sync_custom_to_client()
            # Persist
            self._save_custom_provider_config()
            # Refresh UI
            if self._current_provider() == 'custom':
                self._refresh_models('custom')
                self._update_key_status()


class _CustomProviderDialog(QtWidgets.QDialog):
    """Custom Provider configuration dialog — set API URL, key, model names, etc."""

    def __init__(self, current_config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom Model configuration")
        self.setMinimumWidth(460)
        self.setObjectName("customProviderDialog")
        self._build_ui(current_config)

    def _build_ui(self, cfg: dict):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # Description
        info = QtWidgets.QLabel(
            "Configure any endpoint that's compatible with the OpenAI API.\n"
            "Examples: LM Studio, vLLM, Text Generation WebUI, other relays."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #aaa; font-size: 12px; margin-bottom: 4px;")
        layout.addWidget(info)

        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        # API URL
        self._url_edit = QtWidgets.QLineEdit()
        self._url_edit.setPlaceholderText("https://your-api.example.com/v1/chat/completions")
        self._url_edit.setText(cfg.get('api_url', ''))
        self._url_edit.setMinimumHeight(28)
        form.addRow("API URL:", self._url_edit)

        # API Key
        self._key_edit = QtWidgets.QLineEdit()
        self._key_edit.setPlaceholderText("sk-xxxx (leave blank to omit Authorization header)")
        self._key_edit.setText(cfg.get('api_key', ''))
        self._key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self._key_edit.setMinimumHeight(28)
        # Show/hide key button
        key_row = QtWidgets.QHBoxLayout()
        key_row.setSpacing(4)
        key_row.addWidget(self._key_edit)
        self._btn_show_key = QtWidgets.QPushButton("👁")
        self._btn_show_key.setFixedSize(28, 28)
        self._btn_show_key.setCheckable(True)
        self._btn_show_key.toggled.connect(
            lambda checked: self._key_edit.setEchoMode(
                QtWidgets.QLineEdit.Normal if checked else QtWidgets.QLineEdit.Password
            )
        )
        key_row.addWidget(self._btn_show_key)
        form.addRow("API Key:", key_row)

        # Model names (multiple allowed, comma-separated)
        self._models_edit = QtWidgets.QLineEdit()
        self._models_edit.setPlaceholderText("model-name-1, model-name-2 (comma-separated)")
        self._models_edit.setText(', '.join(cfg.get('models', [])))
        self._models_edit.setMinimumHeight(28)
        form.addRow("Models:", self._models_edit)

        # Context length
        self._ctx_spin = QtWidgets.QSpinBox()
        self._ctx_spin.setRange(1024, 10000000)
        self._ctx_spin.setSingleStep(1024)
        self._ctx_spin.setValue(cfg.get('context_limit', 128000))
        self._ctx_spin.setSuffix(" tokens")
        self._ctx_spin.setMinimumHeight(28)
        form.addRow("Context length:", self._ctx_spin)

        # Feature toggles
        features_row = QtWidgets.QHBoxLayout()
        features_row.setSpacing(12)
        self._chk_vision = QtWidgets.QCheckBox("Vision input")
        self._chk_vision.setChecked(cfg.get('supports_vision', False))
        features_row.addWidget(self._chk_vision)
        self._chk_fc = QtWidgets.QCheckBox("Function calling")
        self._chk_fc.setChecked(cfg.get('supports_fc', True))
        features_row.addWidget(self._chk_fc)
        features_row.addStretch()
        form.addRow("Features:", features_row)

        layout.addLayout(form)

        # Test-connection button
        test_row = QtWidgets.QHBoxLayout()
        test_row.addStretch()
        self._btn_test = QtWidgets.QPushButton("Test connection")
        self._btn_test.setMinimumWidth(100)
        self._btn_test.setMinimumHeight(28)
        self._btn_test.clicked.connect(self._test_connection)
        test_row.addWidget(self._btn_test)
        self._test_status = QtWidgets.QLabel("")
        self._test_status.setStyleSheet("font-size: 12px;")
        test_row.addWidget(self._test_status)
        test_row.addStretch()
        layout.addLayout(test_row)

        # Dialog buttons
        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        # Stylesheet
        self.setStyleSheet("""
            QDialog#customProviderDialog {
                background: #1e1e1e;
                color: #ddd;
            }
            QLabel { color: #ccc; }
            QLineEdit, QSpinBox {
                background: #2a2a2a;
                color: #eee;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QLineEdit:focus, QSpinBox:focus {
                border-color: #6a9eff;
            }
            QCheckBox { color: #ccc; }
            QPushButton {
                background: #333;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 12px;
            }
            QPushButton:hover { background: #444; border-color: #6a9eff; }
        """)

    def _test_connection(self):
        """Test the Custom API connection."""
        url = self._url_edit.text().strip()
        key = self._key_edit.text().strip()
        models = [m.strip() for m in self._models_edit.text().split(',') if m.strip()]
        model = models[0] if models else 'test'

        if not url:
            self._test_status.setText("⚠ Please enter the API URL first")
            self._test_status.setStyleSheet("color: #f5a623; font-size: 12px;")
            return

        self._btn_test.setEnabled(False)
        self._test_status.setText("Connecting…")
        self._test_status.setStyleSheet("color: #aaa; font-size: 12px;")

        try:
            import requests
            headers = {'Content-Type': 'application/json'}
            if key:
                headers['Authorization'] = f'Bearer {key}'
            payload = {
                'model': model,
                'messages': [{'role': 'user', 'content': 'Hi'}],
                'max_tokens': 5,
                'stream': False,
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                recv_model = data.get('model', model)
                self._test_status.setText(f"✅ Connected ({recv_model})")
                self._test_status.setStyleSheet("color: #4caf50; font-size: 12px;")
            else:
                err = resp.text[:120]
                self._test_status.setText(f"❌ HTTP {resp.status_code}: {err}")
                self._test_status.setStyleSheet("color: #f44336; font-size: 12px;")
        except Exception as e:
            self._test_status.setText(f"❌ {str(e)[:100]}")
            self._test_status.setStyleSheet("color: #f44336; font-size: 12px;")
        finally:
            self._btn_test.setEnabled(True)

    def _on_accept(self):
        """Validate required fields before accepting the dialog."""
        url = self._url_edit.text().strip()
        models_text = self._models_edit.text().strip()
        if not url:
            QtWidgets.QMessageBox.warning(self, "Notice", "Please enter the API URL.")
            return
        if not models_text:
            QtWidgets.QMessageBox.warning(self, "Notice", "Please enter at least one model name.")
            return
        self.accept()

    def get_config(self) -> dict:
        """Return the user's configuration as a dict."""
        models = [m.strip() for m in self._models_edit.text().split(',') if m.strip()]
        return {
            'api_url': self._url_edit.text().strip(),
            'api_key': self._key_edit.text().strip(),
            'models': models,
            'context_limit': self._ctx_spin.value(),
            'supports_vision': self._chk_vision.isChecked(),
            'supports_fc': self._chk_fc.isChecked(),
        }
