# -*- coding: utf-8 -*-
"""
Session Manager — multi-session management and caching.

Extracted from ai_tab.py as a Mixin. Responsibilities:
- Create / switch / close multiple sessions
- Session tab bar
- Save / restore session state
"""

import uuid
from pathlib import Path
from morfyai.qt_compat import QtWidgets, QtCore, QtGui

from ..ui.i18n import tr
from ..ui.cursor_widgets import TodoList
from ..ui.chat_view import attach_scroll_to_bottom_button


# ============================================================
# Custom QTabBar with orange × close buttons on every tab
# ============================================================
class _ChromeTabBar(QtWidgets.QTabBar):
    """QTabBar that auto-installs an orange × close button on every new tab.

    Qt's default ::close-button image is barely visible in dark themes and
    occasionally missing entirely; this overrides each tab's right-side
    widget with a styled QPushButton showing a clear orange "✕".
    """

    _CLOSE_BTN_QSS = (
        "QPushButton {"
        " color: #fb7a1a;"
        " background: transparent;"
        " border: none;"
        " padding: 0;"
        " font-size: 13px;"
        " font-weight: 400;"
        " font-family: 'Segoe UI', 'Inter', sans-serif;"
        " min-width: 14px; max-width: 14px;"
        " min-height: 14px; max-height: 14px;"
        " border-radius: 4px;"
        "}"
        "QPushButton:hover {"
        " background: rgba(239,68,68,160);"
        " color: #ffffff;"
        "}"
    )

    def tabInserted(self, index: int):
        super().tabInserted(index)
        # Skip if our custom close button is already attached
        existing = self.tabButton(index, QtWidgets.QTabBar.RightSide)
        if existing is not None and existing.property("morfyClose") == True:
            return

        # Use thin "×" multiplication sign (U+00D7), not heavy "✕" (U+2715)
        btn = QtWidgets.QPushButton("×", self)
        btn.setObjectName("tabCloseBtn")
        btn.setProperty("morfyClose", True)
        btn.setFlat(True)
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        btn.setStyleSheet(self._CLOSE_BTN_QSS)
        btn.clicked.connect(lambda checked=False, b=btn: self._emit_close_for(b))

        self.setTabButton(index, QtWidgets.QTabBar.RightSide, btn)

    # Colors mirror the QSS selectors for QTabBar#sessionTabs::tab
    _TEXT_COLOR_SELECTED = QtGui.QColor("#f1f5f9")
    _TEXT_COLOR_UNSELECTED = QtGui.QColor("#94a3b8")

    def paintEvent(self, event):
        """Override paint to draw tab text left-aligned (Qt centers it by default)."""
        painter = QtWidgets.QStylePainter(self)
        opt = QtWidgets.QStyleOptionTab()

        for i in range(self.count()):
            self.initStyleOption(opt, i)
            # Draw tab shape (background + border) only — skip default centered label
            painter.drawControl(QtWidgets.QStyle.CE_TabBarTabShape, opt)

            # Custom-draw the text, left-aligned
            tab_rect = self.tabRect(i)
            # Reserve space on right for close button (≈ 20px), left padding 10px
            text_rect = tab_rect.adjusted(10, 0, -20, 0)

            # Elide the title if it would overflow
            fm = QtGui.QFontMetrics(painter.font())
            elided = fm.elidedText(self.tabText(i), QtCore.Qt.ElideRight, text_rect.width())

            # Pick text color matching the QSS state
            selected = bool(opt.state & QtWidgets.QStyle.State_Selected)
            painter.setPen(self._TEXT_COLOR_SELECTED if selected else self._TEXT_COLOR_UNSELECTED)
            painter.drawText(text_rect, int(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter), elided)

    def _emit_close_for(self, btn: QtWidgets.QPushButton):
        for i in range(self.count()):
            if self.tabButton(i, QtWidgets.QTabBar.RightSide) is btn:
                self.tabCloseRequested.emit(i)
                return


class SessionManagerMixin:
    """Multi-session management."""

    def _build_session_tabs(self) -> QtWidgets.QWidget:
        """Session tab bar — supports multiple conversation windows."""
        container = QtWidgets.QFrame()
        container.setObjectName("sessionBar")

        hl = QtWidgets.QHBoxLayout(container)
        hl.setContentsMargins(8, 0, 6, 0)
        hl.setSpacing(4)

        self.session_tabs = _ChromeTabBar()
        self.session_tabs.setObjectName("sessionTabs")
        self.session_tabs.setTabsClosable(True)
        self.session_tabs.tabCloseRequested.connect(self._close_session_tab)
        self.session_tabs.setMovable(True)
        self.session_tabs.setExpanding(False)
        self.session_tabs.setDrawBase(False)
        self.session_tabs.setUsesScrollButtons(True)
        self.session_tabs.setElideMode(QtCore.Qt.ElideRight)
        self.session_tabs.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.session_tabs.customContextMenuRequested.connect(self._on_tab_context_menu)
        self.session_tabs.tabBarDoubleClicked.connect(self._rename_session_tab)
        # Tabs take natural width (left-aligned), spacer pushes "+" to the right
        hl.addWidget(self.session_tabs, 0, QtCore.Qt.AlignLeft)
        hl.addStretch(1)

        # "+" new-session button — orange chip
        self.btn_new_session = QtWidgets.QPushButton("+")
        self.btn_new_session.setObjectName("btnNewSession")
        self.btn_new_session.setFixedSize(24, 22)
        self.btn_new_session.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_new_session.setToolTip(tr('session.new'))
        hl.addWidget(self.btn_new_session)

        return container

    @staticmethod
    def _load_logo_pixmap(svg_path: str, target_h: int = 22):
        """Load an SVG into a QPixmap scaled to target_h.

        Tries QPixmap direct load first (works if Qt SVG image plugin is
        available — typical in Houdini's bundled Qt). Falls back to
        QSvgRenderer if direct load yields a null pixmap.
        """
        try:
            # 1. Direct QPixmap load (works when qsvg plugin is present)
            pix = QtGui.QPixmap(svg_path)
            if not pix.isNull():
                return pix.scaledToHeight(target_h, QtCore.Qt.SmoothTransformation)

            # 2. Fallback: QSvgRenderer (requires QtSvg module)
            try:
                from PySide6.QtSvg import QSvgRenderer
            except Exception:
                try:
                    from PySide2.QtSvg import QSvgRenderer
                except Exception:
                    return None
            renderer = QSvgRenderer(svg_path)
            if not renderer.isValid():
                return None
            # Compute target width keeping aspect ratio
            default_size = renderer.defaultSize()
            if default_size.height() > 0:
                target_w = int(default_size.width() * (target_h / default_size.height()))
            else:
                target_w = target_h
            pix2 = QtGui.QPixmap(target_w, target_h)
            pix2.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(pix2)
            renderer.render(painter)
            painter.end()
            return pix2
        except Exception:
            return None

    # ============================================================
    # Sessions drawer (slide-out) — a view over the hidden QTabBar
    # ============================================================

    def _build_session_sidebar(self):
        """Create the slide-out sessions drawer as an overlay over the panel.

        The underlying _ChromeTabBar (self.session_tabs) stays the source of
        truth for all session state; this drawer is a pure view that switches /
        closes / creates via the existing session methods.
        """
        # Dim overlay — click anywhere outside the drawer to close it
        self._session_overlay = QtWidgets.QWidget(self)
        self._session_overlay.setObjectName("sessionOverlay")
        self._session_overlay.setStyleSheet("QWidget#sessionOverlay { background: rgba(0,0,0,120); }")
        self._session_overlay.hide()
        self._session_overlay.mousePressEvent = lambda ev: self._close_session_sidebar()

        # Drawer panel
        self._session_drawer = QtWidgets.QFrame(self)
        self._session_drawer.setObjectName("sessionDrawer")
        self._session_drawer.hide()

        drawer_lay = QtWidgets.QVBoxLayout(self._session_drawer)
        drawer_lay.setContentsMargins(0, 0, 0, 0)
        drawer_lay.setSpacing(0)

        # Header row: title + new-chat
        head = QtWidgets.QHBoxLayout()
        head.setContentsMargins(14, 12, 10, 10)
        head.setSpacing(6)
        head_lbl = QtWidgets.QLabel("Sessions")
        head_lbl.setObjectName("drawerHead")
        head.addWidget(head_lbl)
        head.addStretch()
        btn_new = QtWidgets.QPushButton("✎")
        btn_new.setObjectName("drawerNewBtn")
        btn_new.setFixedSize(24, 24)
        btn_new.setCursor(QtCore.Qt.PointingHandCursor)
        btn_new.setToolTip(tr('session.new'))
        btn_new.clicked.connect(lambda: (self._close_session_sidebar(), self._new_session()))
        head.addWidget(btn_new)
        drawer_lay.addLayout(head)

        # Scrollable list of sessions
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("drawerScroll")
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._session_list_container = QtWidgets.QWidget()
        self._session_list_layout = QtWidgets.QVBoxLayout(self._session_list_container)
        self._session_list_layout.setContentsMargins(8, 6, 8, 10)
        self._session_list_layout.setSpacing(2)
        self._session_list_layout.addStretch()
        scroll.setWidget(self._session_list_container)
        drawer_lay.addWidget(scroll, 1)

        self._refresh_session_sidebar()

    def _refresh_session_sidebar(self):
        """Rebuild the drawer list from the tab bar (the session source of truth)."""
        if getattr(self, '_web_headless', False):
            return  # the drawer widgets are never shown under the web panel
        lay = getattr(self, '_session_list_layout', None)
        if lay is None:
            return
        # Clear existing rows (keep the trailing stretch at the end)
        while lay.count() > 1:
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        prefix = getattr(self, "_TAB_RUNNING_PREFIX", "")
        current_idx = self.session_tabs.currentIndex()

        for i in range(self.session_tabs.count()):
            label = self.session_tabs.tabText(i)
            bare = label[len(prefix):] if prefix and label.startswith(prefix) else label
            running = bool(prefix and label.startswith(prefix))

            row = QtWidgets.QFrame()
            row.setObjectName("drawerItem")
            row.setProperty("active", i == current_idx)
            row.setCursor(QtCore.Qt.PointingHandCursor)
            rlay = QtWidgets.QHBoxLayout(row)
            rlay.setContentsMargins(9, 7, 7, 7)
            rlay.setSpacing(8)

            dot = QtWidgets.QLabel("●")
            dot.setObjectName("drawerDot")
            dot.setVisible(i == current_idx)
            rlay.addWidget(dot)

            title = QtWidgets.QLabel(("● " if running and i != current_idx else "") + bare)
            title.setObjectName("drawerItemTitle")
            title.setProperty("active", i == current_idx)
            rlay.addWidget(title, 1)

            del_btn = QtWidgets.QPushButton("✕")
            del_btn.setObjectName("drawerDelBtn")
            del_btn.setFixedSize(20, 20)
            del_btn.setCursor(QtCore.Qt.PointingHandCursor)
            del_btn.setToolTip(tr('session.close'))
            del_btn.clicked.connect(lambda checked=False, idx=i: self._drawer_delete(idx))
            rlay.addWidget(del_btn)

            row.mousePressEvent = lambda ev, idx=i: self._drawer_select(idx)
            lay.insertWidget(lay.count() - 1, row)

        self._update_session_title()

    def _drawer_select(self, tab_index: int):
        """Drawer row clicked — switch to that session and close the drawer."""
        if 0 <= tab_index < self.session_tabs.count():
            self.session_tabs.setCurrentIndex(tab_index)  # fires _switch_session
        self._close_session_sidebar()

    def _drawer_delete(self, tab_index: int):
        """Drawer × clicked — close that session, keep the drawer open."""
        if 0 <= tab_index < self.session_tabs.count():
            self._close_session_tab(tab_index)
        self._refresh_session_sidebar()

    def _update_session_title(self):
        """Sync the header session-title label with the active tab text."""
        if getattr(self, '_web_headless', False):
            return  # the header label is never shown under the web panel
        lbl = getattr(self, 'session_title_label', None)
        if lbl is None:
            return
        idx = self.session_tabs.currentIndex()
        if idx < 0:
            return
        prefix = getattr(self, "_TAB_RUNNING_PREFIX", "")
        label = self.session_tabs.tabText(idx)
        bare = label[len(prefix):] if prefix and label.startswith(prefix) else label
        lbl.setText(bare)

    def _toggle_session_sidebar(self):
        if getattr(self, '_session_drawer', None) is None:
            return
        if self._session_drawer.isVisible():
            self._close_session_sidebar()
        else:
            self._open_session_sidebar()

    def _open_session_sidebar(self):
        if getattr(self, '_session_drawer', None) is None:
            return
        self._refresh_session_sidebar()
        self._position_session_sidebar()
        self._session_overlay.show()
        self._session_overlay.raise_()
        self._session_drawer.show()
        self._session_drawer.raise_()

    def _close_session_sidebar(self):
        if getattr(self, '_session_drawer', None) is None:
            return
        self._session_drawer.hide()
        self._session_overlay.hide()

    def _position_session_sidebar(self):
        """Keep the overlay full-size and the drawer pinned to the left edge."""
        if getattr(self, '_session_drawer', None) is None:
            return
        r = self.rect()
        self._session_overlay.setGeometry(r)
        drawer_w = min(240, max(200, int(r.width() * 0.66)))
        self._session_drawer.setGeometry(0, 0, drawer_w, r.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            if getattr(self, '_session_drawer', None) is not None and self._session_drawer.isVisible():
                self._position_session_sidebar()
        except RuntimeError:
            pass

    def _on_tab_context_menu(self, pos):
        """Tab bar right-click menu: Rename / Close / Close others."""
        tab_index = self.session_tabs.tabAt(pos)
        if tab_index < 0:
            return
        menu = QtWidgets.QMenu(self)
        # QMenu styling is driven by the global QSS
        rename_action = menu.addAction("Rename")
        menu.addSeparator()
        close_action = menu.addAction(tr('session.close'))
        close_others = menu.addAction(tr('session.close_others'))
        if self.session_tabs.count() <= 1:
            close_others.setEnabled(False)

        chosen = menu.exec_(self.session_tabs.mapToGlobal(pos))
        if chosen == rename_action:
            self._rename_session_tab(tab_index)
        elif chosen == close_action:
            self._close_session_tab(tab_index)
        elif chosen == close_others:
            # Close from back to front, skipping the current tab
            for i in range(self.session_tabs.count() - 1, -1, -1):
                if i != tab_index:
                    self._close_session_tab(i)

    def _rename_session_tab(self, tab_index: int):
        """Prompt the user for a new tab title and apply it."""
        if tab_index < 0 or tab_index >= self.session_tabs.count():
            return
        current = self.session_tabs.tabText(tab_index)
        # Strip the running prefix (e.g. "● ") if present so the user edits the bare title
        prefix = getattr(self, "_TAB_RUNNING_PREFIX", "")
        bare = current[len(prefix):] if prefix and current.startswith(prefix) else current

        new_name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Rename tab",
            "New tab name:",
            QtWidgets.QLineEdit.Normal,
            bare,
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name:
            return
        # Re-apply running prefix if the tab was running
        if prefix and current.startswith(prefix):
            new_name = prefix + new_name
        self.session_tabs.setTabText(tab_index, new_name)
        self._update_session_title()
        self._refresh_session_sidebar()
    
    def _create_session_widgets(self) -> tuple:
        """Create a single session's scroll_area / chat_container / chat_layout."""
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        scroll_area.setObjectName("chatScrollArea")
        
        chat_container = QtWidgets.QWidget()
        chat_container.setObjectName("chatContainer")
        chat_container.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        chat_layout = QtWidgets.QVBoxLayout(chat_container)
        chat_layout.setContentsMargins(0, 8, 0, 8)
        chat_layout.setSpacing(0)
        chat_layout.addStretch()

        chat_container.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Minimum
        )
        scroll_area.setWidget(chat_container)
        # Make the scroll area's viewport transparent so the panel bg shows through
        scroll_area.viewport().setAutoFillBackground(False)
        scroll_area.setStyleSheet("background: transparent;")
        scroll_area.setWidgetResizable(True)

        # ★ Attach Claude-style floating "scroll to bottom" button.
        #   Appears whenever user scrolls > 100px above the bottom, click to snap back.
        attach_scroll_to_bottom_button(scroll_area)

        return scroll_area, chat_container, chat_layout
    
    def _create_initial_session(self):
        """Create the first (default) session."""
        self._session_counter = 1
        session_id = self._session_id  # already created in __init__
        
        scroll_area, chat_container, chat_layout = self._create_session_widgets()
        self.session_stack.addWidget(scroll_area)
        
        tab_index = self.session_tabs.addTab("Chat 1")
        self.session_tabs.setTabData(tab_index, session_id)
        
        # Wire up the active references
        self.scroll_area = scroll_area
        self.chat_container = chat_container
        self.chat_layout = chat_layout
        
        # Each session has its own TodoList
        todo = self._create_todo_list(chat_container)
        self.todo_list = todo
        
        # Store into the sessions dict
        self._sessions[session_id] = {
            'scroll_area': scroll_area,
            'chat_container': chat_container,
            'chat_layout': chat_layout,
            'todo_list': todo,
            'conversation_history': self._conversation_history,
            'context_summary': self._context_summary,
            'current_response': self._current_response,
            'token_stats': self._token_stats,
        }
        self._sync_tabs_backup()
    
    def _create_todo_list(self, parent=None) -> TodoList:
        """Create a TodoList widget for a session (hidden initially; inserted into chat_layout on first use)."""
        return TodoList(parent)

    def _ensure_todo_in_chat(self, todo=None, layout=None):
        """Ensure todo_list is in chat_layout (so it follows the conversation flow).

        Args:
            todo: TodoList to insert; defaults to self.todo_list
            layout: target chat_layout; defaults to self.chat_layout
        """
        todo = todo or self.todo_list
        layout = layout or self.chat_layout
        if not todo or not layout:
            return
        # If it's already in the layout, don't re-insert
        for i in range(layout.count()):
            if layout.itemAt(i).widget() is todo:
                return
        # Insert after the last message (before the trailing stretch)
        idx = layout.count() - 1  # -1 skips the trailing stretch
        layout.insertWidget(idx, todo)
    
    def _new_session(self):
        """Create a new conversation session."""
        # Save current session state (skip if the current session is mid-agent-write to avoid overwriting)
        if self._agent_session_id != self._session_id:
            self._save_current_session_state()
        
        # Auto-save the previous session cache
        if self._auto_save_cache and self._conversation_history:
            self._save_cache()
        
        # Create the new session
        self._session_counter += 1
        new_id = str(uuid.uuid4())[:8]
        label = f"Chat {self._session_counter}"
        
        scroll_area, chat_container, chat_layout = self._create_session_widgets()
        self.session_stack.addWidget(scroll_area)
        
        tab_index = self.session_tabs.addTab(label)
        self.session_tabs.setTabData(tab_index, new_id)
        
        # Initialize new session state
        new_token_stats = {
            'input_tokens': 0, 'output_tokens': 0,
            'cache_read': 0, 'cache_write': 0,
            'total_tokens': 0, 'requests': 0,
        }
        
        todo = self._create_todo_list(chat_container)
        
        self._sessions[new_id] = {
            'scroll_area': scroll_area,
            'chat_container': chat_container,
            'chat_layout': chat_layout,
            'todo_list': todo,
            'conversation_history': [],
            'context_summary': '',
            'current_response': None,
            'token_stats': new_token_stats,
        }
        
        # Switch to the new session
        self._session_id = new_id
        self._conversation_history = []
        self._context_summary = ''
        self._current_response = None
        self._token_stats = new_token_stats
        self._pending_ops.clear()
        
        # ★ Reset sleep counter (new session starts fresh)
        if hasattr(self, '_sleep_msg_counter'):
            self._sleep_msg_counter = 0
        self._update_batch_bar()
        self.scroll_area = scroll_area
        self.chat_container = chat_container
        self.chat_layout = chat_layout
        self.todo_list = todo
        
        # Switch UI
        self.session_tabs.blockSignals(True)
        self.session_tabs.setCurrentIndex(tab_index)
        self.session_tabs.blockSignals(False)
        self.session_stack.setCurrentWidget(scroll_area)

        self._sync_tabs_backup()
        self._update_context_stats()
        self._refresh_session_sidebar()

    def _switch_session(self, tab_index: int):
        """Switch to the session at the given tab index (allowed even while the agent runs)."""
        new_session_id = self.session_tabs.tabData(tab_index)
        if not new_session_id or new_session_id == self._session_id:
            return
        
        # Save current session (only if it's not the session the agent is writing to)
        if self._agent_session_id != self._session_id:
            self._save_current_session_state()
        
        # Load the target session
        self._load_session_state(new_session_id)

        # Switch display
        sdata = self._sessions[new_session_id]
        self.session_stack.setCurrentWidget(sdata['scroll_area'])
        
        # Update button state (depends on whether the target session is the running one)
        self._update_run_buttons()
        self._update_context_stats()
        self._update_session_title()
        self._refresh_session_sidebar()

    def _close_session_tab(self, tab_index: int):
        """Close the specified tab."""
        sid = self.session_tabs.tabData(tab_index)
        # Disallow closing the session that the agent is currently running in
        if sid and self._agent_session_id == sid:
            return
        
        session_id = self.session_tabs.tabData(tab_index)
        if not session_id:
            return
        
        # If only one tab remains, don't close — just clear it
        if self.session_tabs.count() <= 1:
            self._on_clear()
            return
        
        # If we're closing the active session, switch to an adjacent tab first
        if session_id == self._session_id:
            new_index = tab_index - 1 if tab_index > 0 else tab_index + 1
            new_sid = self.session_tabs.tabData(new_index)
            if new_sid:
                self._load_session_state(new_sid)
                sdata = self._sessions[new_sid]
                self.session_stack.setCurrentWidget(sdata['scroll_area'])
        
        # Remove the tab and session data
        self.session_tabs.removeTab(tab_index)
        sdata = self._sessions.pop(session_id, None)
        if sdata and sdata.get('scroll_area'):
            self.session_stack.removeWidget(sdata['scroll_area'])
            sdata['scroll_area'].deleteLater()
        
        # ★ Once the tab is closed, also delete the matching on-disk session file
        try:
            session_file = self._cache_dir / f"session_{session_id}.json"
            if session_file.exists():
                session_file.unlink()
        except Exception:
            pass
        
        self._sync_tabs_backup()
        self._update_context_stats()
        self._update_session_title()
        self._refresh_session_sidebar()

    def _save_current_session_state(self):
        """Persist the current transient state into the _sessions dict."""
        if self._session_id not in self._sessions:
            return
        s = self._sessions[self._session_id]
        s['conversation_history'] = self._conversation_history
        s['context_summary'] = self._context_summary
        s['current_response'] = self._current_response
        s['token_stats'] = self._token_stats
    
    def _sync_tabs_backup(self):
        """Mirror tab order and labels to a plain-Python backup (Qt widgets may be gone at atexit)."""
        try:
            backup = []
            for i in range(self.session_tabs.count()):
                sid = self.session_tabs.tabData(i)
                label = self.session_tabs.tabText(i)
                if sid:
                    backup.append((sid, label))
            self._tabs_backup = backup
        except (RuntimeError, AttributeError):
            pass  # Qt widget destroyed; keep the prior backup
    
    def _load_session_state(self, session_id: str):
        """Restore the given session's state from _sessions."""
        sdata = self._sessions.get(session_id)
        if not sdata:
            return
        
        self._session_id = session_id
        self._conversation_history = sdata.get('conversation_history', [])
        self._context_summary = sdata.get('context_summary', '')
        self._current_response = sdata.get('current_response')
        self._token_stats = sdata.get('token_stats', {
            'input_tokens': 0, 'output_tokens': 0,
            'cache_read': 0, 'cache_write': 0,
            'total_tokens': 0, 'requests': 0,
        })
        self.scroll_area = sdata['scroll_area']
        self.chat_container = sdata['chat_container']
        self.chat_layout = sdata['chat_layout']
        self.todo_list = sdata.get('todo_list') or self._create_todo_list(self.chat_container)
    
    def _auto_rename_tab(self, text: str):
        """Auto-rename the current tab based on the user's first message."""
        for i in range(self.session_tabs.count()):
            if self.session_tabs.tabData(i) == self._session_id:
                current_label = self.session_tabs.tabText(i)
                if current_label.startswith("Chat "):
                    short = text[:18].replace('\n', ' ').strip()
                    if len(text) > 18:
                        short += "..."
                    self.session_tabs.setTabText(i, short)
                break
        self._update_session_title()
        self._refresh_session_sidebar()

    def _retranslate_session_tabs(self):
        """Refresh session tab bar text after a language change."""
        self.btn_new_session.setToolTip(tr('session.new'))
