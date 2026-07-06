# -*- coding: utf-8 -*-
"""
Input Area UI — input region and mode switching.

Extracted from ai_tab.py as a Mixin. All methods access AITab instance state via self.
Styling is driven by the global style_template.qss via objectName selectors.
"""

from morfyai.qt_compat import QtWidgets, QtCore
from .i18n import tr

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None
from .cursor_widgets import (
    CursorTheme,
    ChatInput,
    SendButton,
    StopButton,
    UnifiedStatusBar,
    NodeCompleterPopup,
    SlashCommandPopup,
)


class InputAreaMixin:
    """Input area build, mode switching, @-mentions, and confirm mode."""

    def _build_input_area(self) -> QtWidgets.QWidget:
        """Input area — compact modern layout:
        
        ┌─ batch bar (hidden) ──────────────────────────────┐
        │ unified status bar (hidden)                        │
        │ image preview (hidden)                             │
        │ [+] Agent  Cfm           1.1M | $16   61% 122K/200K│  ← toolbar
        │ ┌──────────────────────────────────┐ ┌────┐┌────┐ │
        │ │ input text area                  │ │Stop││Send│ │  ← input row
        │ └──────────────────────────────────┘ └────┘└────┘ │
        └───────────────────────────────────────────────────┘
        """
        container = QtWidgets.QFrame()
        container.setObjectName("inputArea")
        
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(8, 3, 8, 5)
        layout.setSpacing(2)
        
        # -------- Undo All / Keep All batch-operation bar (hidden by default) --------
        self._batch_bar = QtWidgets.QFrame()
        self._batch_bar.setObjectName("batchBar")
        self._batch_bar.setVisible(False)
        batch_layout = QtWidgets.QHBoxLayout(self._batch_bar)
        batch_layout.setContentsMargins(8, 3, 8, 3)
        batch_layout.setSpacing(6)
        
        self._batch_count_label = QtWidgets.QLabel("")
        self._batch_count_label.setObjectName("batchCountLabel")
        batch_layout.addWidget(self._batch_count_label)
        batch_layout.addStretch()
        
        self._btn_undo_all = QtWidgets.QPushButton("Undo All")
        self._btn_undo_all.setObjectName("btnUndoAll")
        self._btn_undo_all.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_undo_all.clicked.connect(self._undo_all_ops)
        batch_layout.addWidget(self._btn_undo_all)
        
        self._btn_keep_all = QtWidgets.QPushButton("Keep All")
        self._btn_keep_all.setObjectName("btnKeepAll")
        self._btn_keep_all.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_keep_all.clicked.connect(self._keep_all_ops)
        batch_layout.addWidget(self._btn_keep_all)
        
        layout.addWidget(self._batch_bar)
        
        # -------- Unified status bar (merges ThinkingBar + ToolStatusBar) --------
        self.thinking_bar = UnifiedStatusBar()
        self.tool_status_bar = self.thinking_bar  # compatibility alias
        layout.addWidget(self.thinking_bar)

        # Image attachment preview area (above the input, hidden by default)
        self._pending_images = []  # List[Tuple[str, str, QPixmap]]
        self.image_preview_container = QtWidgets.QWidget()
        self.image_preview_container.setVisible(False)
        self.image_preview_layout = QtWidgets.QHBoxLayout(self.image_preview_container)
        self.image_preview_layout.setContentsMargins(4, 2, 4, 2)
        self.image_preview_layout.setSpacing(4)
        self.image_preview_layout.addStretch()
        layout.addWidget(self.image_preview_container)
        
        # -------- Toolbar row: + | Agent | Cfm | stretch | token | context --------
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(6)
        toolbar.setContentsMargins(0, 0, 0, 0)
        
        self._agent_mode = True
        self._plan_mode = False
        self._confirm_mode = False
        
        # + Attachment popup menu
        self.btn_attach_menu = QtWidgets.QPushButton("+")
        self.btn_attach_menu.setObjectName("btnAttach")
        self.btn_attach_menu.setFixedSize(18, 18)
        self.btn_attach_menu.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_attach_menu.setToolTip("Attach / Actions")
        self.btn_attach_menu.clicked.connect(self._show_attach_menu)
        toolbar.addWidget(self.btn_attach_menu)

        # Read Selection — promoted out of the + menu to a standalone icon button
        self.btn_selection_toolbar = QtWidgets.QPushButton("▦")
        self.btn_selection_toolbar.setObjectName("btnSelectionToolbar")
        self.btn_selection_toolbar.setFixedSize(18, 18)
        self.btn_selection_toolbar.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_selection_toolbar.setToolTip("Read Selection")
        toolbar.addWidget(self.btn_selection_toolbar)

        # Agent/Ask/Plan mode
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.setObjectName("modeCombo")
        self.mode_combo.addItem("Agent")
        self.mode_combo.addItem("Ask")
        self.mode_combo.addItem("Plan")
        self.mode_combo.setCurrentIndex(0)
        self.mode_combo.setProperty("mode", "agent")
        self.mode_combo.setCursor(QtCore.Qt.PointingHandCursor)
        self.mode_combo.setToolTip(tr('mode.tooltip'))
        self.mode_combo.setFixedWidth(58)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        toolbar.addWidget(self.mode_combo)
        
        # Confirm-mode toggle
        self.chk_confirm_mode = QtWidgets.QCheckBox("Cfm")
        self.chk_confirm_mode.setObjectName("chkConfirm")
        self.chk_confirm_mode.setChecked(False)
        self.chk_confirm_mode.setCursor(QtCore.Qt.PointingHandCursor)
        self.chk_confirm_mode.setToolTip(tr('confirm.tooltip'))
        self.chk_confirm_mode.toggled.connect(self._on_confirm_mode_toggled)
        toolbar.addWidget(self.chk_confirm_mode)
        
        # Plugin button container (HookManager.PluginUIBridge mounts buttons here)
        self._plugin_button_container = QtWidgets.QHBoxLayout()
        self._plugin_button_container.setSpacing(2)
        self._plugin_button_container.setContentsMargins(0, 0, 0, 0)
        toolbar.addLayout(self._plugin_button_container)
        
        toolbar.addStretch()

        # Model selector — moved here from the header (matches the mockup, where
        # model selection lives in the composer toolbar). The widget itself is
        # created in _build_header so all provider/model wiring stays intact.
        if hasattr(self, 'model_combo') and self.model_combo is not None:
            self.model_combo.setObjectName("modelComboComposer")
            toolbar.addWidget(self.model_combo)

        # Token stats
        self.token_stats_btn = QtWidgets.QPushButton("0")
        self.token_stats_btn.setObjectName("tokenStats")
        self.token_stats_btn.setToolTip(tr('header.token_stats.tooltip'))
        self.token_stats_btn.clicked.connect(self._show_token_stats_dialog)
        toolbar.addWidget(self.token_stats_btn)

        # Context usage stats
        self.context_label = QtWidgets.QLabel("0K / 64K")
        self.context_label.setObjectName("contextLabel")
        toolbar.addWidget(self.context_label)

        # -------- Input row: text area + Send/Stop --------
        input_row = QtWidgets.QHBoxLayout()
        input_row.setSpacing(6)
        
        # Text input (auto-resizing)
        self.input_edit = ChatInput()
        self.input_edit.imageDropped.connect(self._on_image_dropped)
        self.input_edit.atTriggered.connect(self._on_at_triggered)
        input_row.addWidget(self.input_edit, 1)
        
        # Node-path completion popup
        self._node_completer = NodeCompleterPopup(parent=self.input_edit)
        self._node_completer.pathSelected.connect(self._on_node_path_selected)
        self.input_edit.set_completer_popup(self._node_completer)

        # Slash-command completion popup
        self._slash_completer = SlashCommandPopup(parent=self.input_edit)
        self._slash_completer.commandSelected.connect(self._on_slash_command_selected)
        self.input_edit.set_slash_popup(self._slash_completer)
        self.input_edit.slashTriggered.connect(self._on_slash_triggered)
        
        # Send / Stop buttons — to the right of the input
        btn_col = QtWidgets.QVBoxLayout()
        btn_col.setSpacing(4)
        btn_col.setContentsMargins(0, 0, 0, 0)
        btn_col.addStretch()
        
        self.btn_stop = StopButton()
        self.btn_stop.setFixedSize(28, 28)
        self.btn_stop.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_stop.setVisible(False)
        btn_col.addWidget(self.btn_stop)

        self.btn_send = SendButton()
        self.btn_send.setFixedSize(28, 28)
        self.btn_send.setCursor(QtCore.Qt.PointingHandCursor)
        btn_col.addWidget(self.btn_send)
        
        input_row.addLayout(btn_col)
        
        layout.addLayout(input_row)

        # Toolbar sits BELOW the input (matches the mockup composer layout)
        layout.addLayout(toolbar)

        # -------- Hidden buttons (preserved as self.btn_xxx for _wire_events compatibility) --------
        self.btn_attach_image = QtWidgets.QPushButton("Img")
        self.btn_attach_image.setVisible(False)
        
        self.btn_network = QtWidgets.QPushButton("Read Network")
        self.btn_network.setVisible(False)
        
        self.btn_selection = QtWidgets.QPushButton("Read Selection")
        self.btn_selection.setVisible(False)
        self.btn_selection_toolbar.clicked.connect(self.btn_selection.click)

        self.btn_export_train = QtWidgets.QPushButton("Train")
        self.btn_export_train.setVisible(False)
        
        return container

    # -------- + Menu popup --------

    def _show_attach_menu(self):
        """Show the attachment / low-frequency actions menu."""
        menu = QtWidgets.QMenu(self)
        menu.addAction("Attach Image", self.btn_attach_image.click)
        menu.addAction("Read Network", self.btn_network.click)
        menu.addAction("Read Selection", self.btn_selection.click)
        menu.addSeparator()
        menu.addAction("Export Train", self.btn_export_train.click)
        menu.exec_(self.btn_attach_menu.mapToGlobal(
            QtCore.QPoint(0, -menu.sizeHint().height())
        ))

    # ---------- Confirm-mode toggle ----------

    def _on_confirm_mode_toggled(self, checked: bool):
        self._confirm_mode = checked

    # ---------- Agent / Ask mode switching (combo box) ----------

    def _on_mode_changed(self, index: int):
        """Mode combo change: 0=Agent, 1=Ask, 2=Plan."""
        _MODE_MAP = {0: "agent", 1: "ask", 2: "plan"}
        mode = _MODE_MAP.get(index, "agent")
        self._agent_mode = (mode == "agent")
        self._plan_mode = (mode == "plan")
        self.mode_combo.setProperty("mode", mode)
        self.mode_combo.style().unpolish(self.mode_combo)
        self.mode_combo.style().polish(self.mode_combo)
        self.btn_send.setProperty("mode", mode)
        self.btn_send.style().unpolish(self.btn_send)
        self.btn_send.style().polish(self.btn_send)

    # ---------- @-mention node autocomplete ----------

    def _on_at_triggered(self, prefix: str, cursor_rect):
        """User typed @ in the input — refresh the node list and show the completion popup."""
        try:
            paths = self._collect_node_paths()
            if not paths:
                self._node_completer.setVisible(False)
                return
            self._node_completer.set_node_paths(paths)
            self._node_completer.show_filtered(prefix, self.input_edit, cursor_rect)
        except Exception:
            self._node_completer.setVisible(False)

    def _on_node_path_selected(self, path: str):
        """User selected a node path from the completion popup."""
        self.input_edit.insert_at_completion(path)
        self._node_completer.setVisible(False)

    def _collect_node_paths(self) -> list:
        """Collect node paths in the current scene (for @ completion)."""
        paths = []
        try:
            import hou  # type: ignore
            for ctx in ['/obj', '/out', '/shop', '/mat', '/stage']:
                try:
                    node = hou.node(ctx)
                    if node:
                        # Include the context root node itself
                        paths.append(ctx)
                        for child in node.allSubChildren():
                            paths.append(child.path())
                except Exception:
                    continue
        except ImportError:
            pass
        # If the scene has no nodes at all, at least surface the context roots
        if not paths:
            paths = ['/obj', '/out', '/shop', '/mat', '/stage']
        return paths

    # ---------- / Slash-command autocomplete ----------

    def _on_slash_triggered(self, prefix: str, cursor_rect):
        """User typed / in the input — show the command list."""
        try:
            self._slash_completer.show_filtered(prefix, self.input_edit, cursor_rect)
        except Exception:
            self._slash_completer.setVisible(False)

    def _on_slash_command_selected(self, command: str):
        """User selected a slash command from the popup."""
        self.input_edit.insert_slash_completion(command)
        self._slash_completer.setVisible(False)
        # Execute the command — delegate to AITab's _execute_slash_command
        try:
            self._execute_slash_command(command)
        except Exception as e:
            _dbg(f"[SlashCommand] Execute /{command} failed: {e}")

    # ---------- Tool execution status (legacy API compatibility) ----------

    def _on_show_tool_status(self, tool_name: str):
        """Show the currently running tool in the input-area status bar."""
        if getattr(self, '_web_headless', False):
            return  # forwarded to the web bridge separately
        if not getattr(self, '_is_running', False):
            return  # Agent has stopped — ignore late signals
        try:
            self.thinking_bar.show_tool(tool_name)
        except RuntimeError:
            pass

    def _on_hide_tool_status(self):
        """Hide the tool status."""
        if getattr(self, '_web_headless', False):
            return
        if not getattr(self, '_is_running', False):
            return  # Agent has stopped — ignore late signals
        try:
            self.thinking_bar.hide_tool()
        except RuntimeError:
            pass

    def _on_show_generating(self):
        """Show the "Generating..." state (waiting for an API request)."""
        if getattr(self, '_web_headless', False):
            return
        if not getattr(self, '_is_running', False):
            return  # Agent has stopped — ignore late signals
        try:
            self.thinking_bar.show_generating()
        except RuntimeError:
            pass

    def _on_show_planning(self, progress: str):
        """Show "Planning..." progress (Plan mode is generating a plan)."""
        if getattr(self, '_web_headless', False):
            return
        if not getattr(self, '_is_running', False):
            return  # Agent has stopped — ignore late signals
        try:
            self.thinking_bar.show_planning(progress)
        except RuntimeError:
            pass

    def _retranslate_input_area(self):
        """Refresh all translated text in the input area after a language change."""
        self.mode_combo.setToolTip(tr('mode.tooltip'))
        self.chk_confirm_mode.setToolTip(tr('confirm.tooltip'))
        self.input_edit.setPlaceholderText(tr('placeholder'))
        self.btn_attach_image.setToolTip(tr('attach_image.tooltip'))
        self.btn_export_train.setToolTip(tr('train.tooltip'))
        self.token_stats_btn.setToolTip(tr('header.token_stats.tooltip'))
