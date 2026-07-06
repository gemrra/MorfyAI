# -*- coding: utf-8 -*-
"""
Settings Dialog — consolidated settings surface.

Replaces the flat 12-item overflow menu with a single grouped window:
sidebar navigation on the left, a stacked content pane on the right.

Simple settings (General, Providers, Context & Cache, MCP Server) are edited
inline here. Complex editors (Rules, Plugins, Memory, Debug Console, About)
reuse their existing dialogs via the owning AITab's handlers.
"""

from morfyai.qt_compat import QtWidgets, QtCore, QtGui

try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None


# ============================================================
# Custom pill toggle switch (Qt has no native one)
# ============================================================
class ToggleSwitch(QtWidgets.QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFixedSize(36, 20)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        on = self.isChecked()
        # Track
        track = QtGui.QColor("#fb7a1a") if on else QtGui.QColor(255, 255, 255, 26)
        if on:
            track.setAlpha(90)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(0, 0, self.width(), self.height(), self.height() / 2, self.height() / 2)
        # Knob
        knob = QtGui.QColor("#fb7a1a") if on else QtGui.QColor("#5f616b")
        p.setBrush(knob)
        d = self.height() - 6
        x = self.width() - d - 3 if on else 3
        p.drawEllipse(int(x), 3, d, d)
        p.end()


class SettingsDialog(QtWidgets.QDialog):
    """Grouped settings window. `owner` is the AITab instance."""

    # (group_label, [(page_key, label)])
    NAV = [
        ("Session", [("context", "Context & Cache")]),
        ("Configure", [
            ("general", "General"),
            ("providers", "Providers"),
            ("rules", "Rules"),
            ("plugins", "Plugins & Skills"),
            ("memory", "Memory"),
        ]),
        ("Connections", [("mcp", "MCP Server")]),
        ("Help", [
            ("debug", "Debug Console"),
            ("about", "About"),
        ]),
    ]

    def __init__(self, owner, parent=None):
        super().__init__(parent or owner)
        self.owner = owner
        self.setObjectName("settingsDialog")
        self.setWindowTitle("MorfyAI Settings")
        self.resize(820, 560)
        self.setMinimumSize(680, 460)

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Sidebar ----
        sidebar = QtWidgets.QWidget()
        sidebar.setObjectName("settingsSidebar")
        sidebar.setFixedWidth(200)
        sb_lay = QtWidgets.QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(8, 14, 8, 14)
        sb_lay.setSpacing(2)

        self._nav_buttons = {}
        self._pages = {}
        self.stack = QtWidgets.QStackedWidget()
        self.stack.setObjectName("settingsStack")

        for group_label, items in self.NAV:
            lbl = QtWidgets.QLabel(group_label.upper())
            lbl.setObjectName("settingsNavGroup")
            sb_lay.addWidget(lbl)
            for key, label in items:
                btn = QtWidgets.QPushButton(label)
                btn.setObjectName("settingsNavItem")
                btn.setCheckable(True)
                btn.setCursor(QtCore.Qt.PointingHandCursor)
                btn.clicked.connect(lambda checked=False, k=key: self._show_page(k))
                sb_lay.addWidget(btn)
                self._nav_buttons[key] = btn
                page = self._build_page(key)
                self._pages[key] = page
                self.stack.addWidget(page)
        sb_lay.addStretch()

        root.addWidget(sidebar)

        # ---- Content ----
        content_wrap = QtWidgets.QWidget()
        content_wrap.setObjectName("settingsContent")
        cw = QtWidgets.QVBoxLayout(content_wrap)
        cw.setContentsMargins(0, 0, 0, 0)
        cw.setSpacing(0)
        cw.addWidget(self.stack, 1)
        root.addWidget(content_wrap, 1)

        self._show_page("general")

    # ---------- navigation ----------
    def _show_page(self, key):
        page = self._pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        for k, btn in self._nav_buttons.items():
            btn.setChecked(k == key)

    # ---------- page scaffolding ----------
    def _page(self, title, subtitle=None):
        page = QtWidgets.QScrollArea()
        page.setWidgetResizable(True)
        page.setObjectName("settingsPage")
        page.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        page.setFrameShape(QtWidgets.QFrame.NoFrame)
        inner = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(inner)
        lay.setContentsMargins(30, 26, 30, 30)
        lay.setSpacing(12)
        h = QtWidgets.QLabel(title)
        h.setObjectName("settingsH1")
        lay.addWidget(h)
        if subtitle:
            s = QtWidgets.QLabel(subtitle)
            s.setObjectName("settingsSub")
            s.setWordWrap(True)
            lay.addWidget(s)
        page.setWidget(inner)
        page._lay = lay  # stash for builders
        return page

    def _card(self):
        card = QtWidgets.QFrame()
        card.setObjectName("settingsCard")
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(12)
        card._lay = lay
        return card

    def _section_title(self, text):
        lbl = QtWidgets.QLabel(text.upper())
        lbl.setObjectName("settingsSectionTitle")
        return lbl

    def _toggle_row(self, label, hint, checked, on_toggle):
        row = QtWidgets.QHBoxLayout()
        col = QtWidgets.QVBoxLayout()
        col.setSpacing(2)
        t = QtWidgets.QLabel(label)
        t.setObjectName("settingsToggleLabel")
        col.addWidget(t)
        if hint:
            hh = QtWidgets.QLabel(hint)
            hh.setObjectName("settingsHint")
            col.addWidget(hh)
        row.addLayout(col)
        row.addStretch()
        sw = ToggleSwitch()
        sw.setChecked(bool(checked))
        if on_toggle:
            sw.toggled.connect(on_toggle)
        row.addWidget(sw)
        return row, sw

    def _launch_card(self, desc, btn_label, handler):
        card = self._card()
        d = QtWidgets.QLabel(desc)
        d.setObjectName("settingsHint")
        d.setWordWrap(True)
        card._lay.addWidget(d)
        brow = QtWidgets.QHBoxLayout()
        brow.addStretch()
        btn = QtWidgets.QPushButton(btn_label)
        btn.setObjectName("settingsBtnPrimary")
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self._safe(handler))
        brow.addWidget(btn)
        card._lay.addLayout(brow)
        return card

    def _safe(self, fn):
        try:
            fn()
        except Exception as e:
            _dbg(f"[Settings] action failed: {e}")

    # ---------- pages ----------
    def _build_page(self, key):
        return getattr(self, f"_page_{key}", self._page_placeholder)(key) \
            if hasattr(self, f"_page_{key}") else self._page_placeholder(key)

    def _page_placeholder(self, key):
        p = self._page(key.title())
        return p

    def _page_general(self, key):
        p = self._page("General", "Panel-wide preferences and session actions.")
        lay = p._lay

        # Appearance
        lay.addWidget(self._section_title("Appearance"))
        card = self._card()
        fr = QtWidgets.QHBoxLayout()
        fr_lbl = QtWidgets.QLabel("Font scale")
        fr_lbl.setObjectName("settingsToggleLabel")
        fr.addWidget(fr_lbl)
        fr.addStretch()
        self._font_pct = QtWidgets.QLabel("100%")
        self._font_pct.setObjectName("settingsHint")
        fr.addWidget(self._font_pct)
        card._lay.addLayout(fr)
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setMinimum(70)
        slider.setMaximum(150)
        slider.setSingleStep(5)
        try:
            slider.setValue(int(round(self.owner._theme.scale * 100)))
            self._font_pct.setText(f"{int(round(self.owner._theme.scale * 100))}%")
        except Exception:
            slider.setValue(100)
        slider.valueChanged.connect(self._on_font_slider)
        card._lay.addWidget(slider)
        lay.addWidget(card)

        # Session
        lay.addWidget(self._section_title("Session"))
        card2 = self._card()
        info = QtWidgets.QLabel("Clear this session's conversation history, token stats and pending change ledger. This cannot be undone.")
        info.setObjectName("settingsHint")
        info.setWordWrap(True)
        card2._lay.addWidget(info)
        brow = QtWidgets.QHBoxLayout()
        brow.addStretch()
        clr = QtWidgets.QPushButton("Clear Chat")
        clr.setObjectName("settingsBtnDanger")
        clr.setCursor(QtCore.Qt.PointingHandCursor)
        clr.clicked.connect(lambda: self._safe(self.owner._on_clear))
        brow.addWidget(clr)
        card2._lay.addLayout(brow)
        lay.addWidget(card2)

        lay.addStretch()
        return p

    def _on_font_slider(self, value):
        try:
            self._font_pct.setText(f"{value}%")
            self.owner._theme.set_scale(value / 100.0)
            self.owner._apply_font_scale()
        except Exception as e:
            _dbg(f"[Settings] font scale failed: {e}")

    def _page_providers(self, key):
        p = self._page("Providers", "API keys and per-model options. Chat model is picked from the composer toolbar.")
        lay = p._lay

        card = self._card()
        card._lay.addWidget(self._section_title("API key"))
        prow = QtWidgets.QHBoxLayout()
        plbl = QtWidgets.QLabel("Provider")
        plbl.setObjectName("settingsToggleLabel")
        prow.addWidget(plbl)
        prow.addStretch()
        self._prov_combo = QtWidgets.QComboBox()
        self._prov_combo.setObjectName("settingsCombo")
        for i in range(self.owner.provider_combo.count()):
            self._prov_combo.addItem(self.owner.provider_combo.itemText(i),
                                     self.owner.provider_combo.itemData(i))
        self._prov_combo.setCurrentIndex(self.owner.provider_combo.currentIndex())
        self._prov_combo.currentIndexChanged.connect(self._on_settings_provider_changed)
        prow.addWidget(self._prov_combo)
        card._lay.addLayout(prow)

        self._key_edit = QtWidgets.QLineEdit()
        self._key_edit.setObjectName("settingsInput")
        self._key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self._key_edit.setPlaceholderText("paste API key here")
        card._lay.addWidget(self._key_edit)

        krow = QtWidgets.QHBoxLayout()
        self._key_state = QtWidgets.QLabel("")
        self._key_state.setObjectName("settingsHint")
        krow.addWidget(self._key_state)
        krow.addStretch()
        cfg_btn = QtWidgets.QPushButton("Custom endpoint…")
        cfg_btn.setObjectName("settingsBtn")
        cfg_btn.setCursor(QtCore.Qt.PointingHandCursor)
        cfg_btn.clicked.connect(lambda: self._safe(self.owner._open_custom_provider_dialog))
        krow.addWidget(cfg_btn)
        save_btn = QtWidgets.QPushButton("Save key")
        save_btn.setObjectName("settingsBtnPrimary")
        save_btn.setCursor(QtCore.Qt.PointingHandCursor)
        save_btn.clicked.connect(self._on_save_key)
        krow.addWidget(save_btn)
        card._lay.addLayout(krow)
        lay.addWidget(card)

        # Per-request options (Web / Think)
        lay.addWidget(self._section_title("Request options"))
        card2 = self._card()
        r1, self._web_sw = self._toggle_row(
            "Web search", "Let the model search the web when it helps",
            self.owner.web_check.isChecked(),
            lambda on: self.owner.web_check.setChecked(on))
        card2._lay.addLayout(r1)
        r2, self._think_sw = self._toggle_row(
            "Extended thinking", "Allow the model to reason longer before answering",
            self.owner.think_check.isChecked(),
            lambda on: self.owner.think_check.setChecked(on))
        card2._lay.addLayout(r2)
        lay.addWidget(card2)

        # Vision model (separate lightweight model)
        lay.addWidget(self._section_title("Vision model"))
        lay.addWidget(self._launch_card(
            "A separate, lighter model used only to visually inspect renders "
            "(e.g. visual_check) — kept independent from the chat model.",
            "Open vision setup…", self.owner._open_vision_setup))

        lay.addStretch()
        self._refresh_key_state()
        return p

    def _on_settings_provider_changed(self, idx):
        # Mirror to the real provider combo so downstream logic runs
        try:
            self.owner.provider_combo.setCurrentIndex(idx)
        except Exception:
            pass
        self._refresh_key_state()

    def _refresh_key_state(self):
        try:
            provider = self._prov_combo.currentData()
            if provider == 'ollama':
                self._key_state.setText("Local — no key needed")
            elif self.owner.client.has_api_key(provider):
                self._key_state.setText(f"Key set: {self.owner.client.get_masked_key(provider)}")
            else:
                self._key_state.setText("No key set")
        except Exception:
            self._key_state.setText("")

    def _on_save_key(self):
        try:
            provider = self._prov_combo.currentData()
            key = self._key_edit.text().strip()
            if key:
                self.owner.client.set_api_key(key, persist=True, provider=provider)
                self._key_edit.clear()
                self.owner._update_key_status()
            self._refresh_key_state()
        except Exception as e:
            _dbg(f"[Settings] save key failed: {e}")

    def _page_context(self, key):
        p = self._page("Context & Cache", "Manage saved conversation snapshots and keep the active context under the model's window.")
        lay = p._lay
        card = self._card()
        card._lay.addWidget(self._section_title("Cache"))
        b1 = QtWidgets.QPushButton("Cache actions…")
        b1.setObjectName("settingsBtn")
        b1.setCursor(QtCore.Qt.PointingHandCursor)
        b1.clicked.connect(lambda: self._safe(self.owner._on_cache_menu))
        card._lay.addWidget(b1)
        lay.addWidget(card)

        card2 = self._card()
        card2._lay.addWidget(self._section_title("Optimize"))
        b2 = QtWidgets.QPushButton("Optimize / compress…")
        b2.setObjectName("settingsBtn")
        b2.setCursor(QtCore.Qt.PointingHandCursor)
        b2.clicked.connect(lambda: self._safe(self.owner._on_optimize_menu))
        card2._lay.addWidget(b2)
        lay.addWidget(card2)
        lay.addStretch()
        return p

    def _page_mcp(self, key):
        p = self._page("MCP Server", "MorfyAI runs its own MCP server so any compatible client can drive Houdini directly — not just Claude.")
        lay = p._lay

        card = self._card()
        status = QtWidgets.QLabel("Checking…")
        status.setObjectName("settingsHint")
        card._lay.addWidget(status)
        try:
            from ..utils import claude_connect as cc
            report = cc.connection_report()
            running = report.get("server_running")
            url = report.get("url", "")
            status.setText(("● Server RUNNING  " + url) if running else "○ Server not started")
        except Exception:
            url = "http://127.0.0.1:9000/mcp"
            status.setText("○ Server status unavailable")
        brow = QtWidgets.QHBoxLayout()
        brow.addStretch()
        guide = QtWidgets.QPushButton("Open connection guide…")
        guide.setObjectName("settingsBtn")
        guide.setCursor(QtCore.Qt.PointingHandCursor)
        guide.clicked.connect(lambda: self._safe(self.owner._open_claude_connect))
        brow.addWidget(guide)
        card._lay.addLayout(brow)
        lay.addWidget(card)

        lay.addWidget(self._section_title("Connect a client"))
        info = QtWidgets.QLabel("Works with Claude Code, Claude Desktop, OpenCode, Codex CLI, Cursor, and any other MCP-compatible client.")
        info.setObjectName("settingsHint")
        info.setWordWrap(True)
        lay.addWidget(info)

        prompt_lbl = QtWidgets.QLabel("Setup prompt — copy and paste into whichever app you use:")
        prompt_lbl.setObjectName("settingsHint")
        lay.addWidget(prompt_lbl)

        prompt = (f'Add an MCP server named "morfyai-houdini" using the '
                  f'streamable-http transport at {url}')
        edit = QtWidgets.QPlainTextEdit()
        edit.setObjectName("settingsCode")
        edit.setReadOnly(True)
        edit.setPlainText(prompt)
        edit.setFixedHeight(64)
        lay.addWidget(edit)

        crow = QtWidgets.QHBoxLayout()
        crow.addStretch()
        copy = QtWidgets.QPushButton("Copy setup prompt")
        copy.setObjectName("settingsBtnPrimary")
        copy.setCursor(QtCore.Qt.PointingHandCursor)
        copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(prompt))
        crow.addWidget(copy)
        lay.addLayout(crow)
        lay.addStretch()
        return p

    def _page_memory(self, key):
        p = self._page("Memory", "Three-tier brain-inspired store — episodic, semantic, procedural.")
        lay = p._lay
        card = self._card()
        r, self._mem_sw = self._toggle_row(
            "Long-term memory",
            "When off, MorfyAI won't read or write any memory tier",
            bool(getattr(self.owner, '_memory_enabled', False)),
            lambda on: self._safe(lambda: self.owner.set_memory_enabled(on)))
        card._lay.addLayout(r)
        lay.addWidget(card)
        lay.addWidget(self._launch_card(
            "Browse and edit stored episodic, semantic and procedural memories.",
            "Open memory manager…", self.owner._slash_memories))
        lay.addStretch()
        return p

    def _page_rules(self, key):
        p = self._page("Rules", "Persistent, Cursor-style context injected into every request.")
        p._lay.addWidget(self._launch_card(
            "Add, edit and toggle the rules that are auto-injected into every prompt.",
            "Open rules editor…", self.owner._open_rules_editor))
        p._lay.addStretch()
        return p

    def _page_plugins(self, key):
        p = self._page("Plugins & Skills", "Community plugins, built-in tools, and analysis skills.")
        p._lay.addWidget(self._launch_card(
            "Enable/disable plugins, browse tools, and configure the skills folder.",
            "Open plugin manager…", self.owner._open_plugin_manager))
        p._lay.addStretch()
        return p

    def _page_debug(self, key):
        p = self._page("Debug Console", "Live diagnostic log from the panel.")
        p._lay.addWidget(self._launch_card(
            "View the in-app diagnostic log, copy it, or clear it.",
            "Open debug console…", self.owner._open_debug_console))
        p._lay.addStretch()
        return p

    def _page_about(self, key):
        p = self._page("About MorfyAI")
        p._lay.addWidget(self._launch_card(
            "Version, credits, license and feedback.",
            "Open about…", self.owner._open_about_dialog))
        p._lay.addStretch()
        return p
