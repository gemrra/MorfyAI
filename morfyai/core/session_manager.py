# -*- coding: utf-8 -*-
"""
Session Manager — 多会话管理和缓存

从 ai_tab.py 中拆分出的 Mixin，负责：
- 多会话创建/切换/关闭
- 会话标签栏
- 会话状态保存/恢复
"""

import uuid
from pathlib import Path
from morfyai.qt_compat import QtWidgets, QtCore, QtGui

from ..ui.i18n import tr
from ..ui.cursor_widgets import TodoList


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
    """多会话管理"""

    def _build_session_tabs(self) -> QtWidgets.QWidget:
        """会话标签栏 - 支持多个对话窗口"""
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

        # "+" 新建对话按钮 — orange chip
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

    def _on_tab_context_menu(self, pos):
        """Tab 栏右键菜单：Rename / Close / Close others"""
        tab_index = self.session_tabs.tabAt(pos)
        if tab_index < 0:
            return
        menu = QtWidgets.QMenu(self)
        # QMenu 样式由全局 QSS 控制
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
            # 从后往前关闭，跳过当前 tab
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
    
    def _create_session_widgets(self) -> tuple:
        """创建单个会话的 scroll_area / chat_container / chat_layout"""
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
        
        return scroll_area, chat_container, chat_layout
    
    def _create_initial_session(self):
        """创建第一个（默认）会话"""
        self._session_counter = 1
        session_id = self._session_id  # __init__ 已生成
        
        scroll_area, chat_container, chat_layout = self._create_session_widgets()
        self.session_stack.addWidget(scroll_area)
        
        tab_index = self.session_tabs.addTab("Chat 1")
        self.session_tabs.setTabData(tab_index, session_id)
        
        # 设置当前引用
        self.scroll_area = scroll_area
        self.chat_container = chat_container
        self.chat_layout = chat_layout
        
        # 每个会话独立的 TodoList
        todo = self._create_todo_list(chat_container)
        self.todo_list = todo
        
        # 存入 sessions 字典
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
        """为会话创建 TodoList 控件（初始隐藏，首次使用时插入 chat_layout）"""
        return TodoList(parent)
    
    def _ensure_todo_in_chat(self, todo=None, layout=None):
        """确保 todo_list 已在 chat_layout 中（跟随对话流）
        
        Args:
            todo: 要插入的 TodoList，默认使用 self.todo_list
            layout: 目标 chat_layout，默认使用 self.chat_layout
        """
        todo = todo or self.todo_list
        layout = layout or self.chat_layout
        if not todo or not layout:
            return
        # 如果已在 layout 中，不要重复插入
        for i in range(layout.count()):
            if layout.itemAt(i).widget() is todo:
                return
        # 插入到当前最末的消息之后（stretch 之前）
        idx = layout.count() - 1  # -1 跳过末尾 stretch
        layout.insertWidget(idx, todo)
    
    def _new_session(self):
        """新建对话会话"""
        # 保存当前会话状态（如果当前 session 正在被 agent 写入则跳过，避免覆盖）
        if self._agent_session_id != self._session_id:
            self._save_current_session_state()
        
        # 自动保存旧会话缓存
        if self._auto_save_cache and self._conversation_history:
            self._save_cache()
        
        # 创建新会话
        self._session_counter += 1
        new_id = str(uuid.uuid4())[:8]
        label = f"Chat {self._session_counter}"
        
        scroll_area, chat_container, chat_layout = self._create_session_widgets()
        self.session_stack.addWidget(scroll_area)
        
        tab_index = self.session_tabs.addTab(label)
        self.session_tabs.setTabData(tab_index, new_id)
        
        # 初始化新会话状态
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
        
        # 切换到新会话
        self._session_id = new_id
        self._conversation_history = []
        self._context_summary = ''
        self._current_response = None
        self._token_stats = new_token_stats
        self._pending_ops.clear()
        
        # ★ 重置睡眠计数器（新会话重新计数）
        if hasattr(self, '_sleep_msg_counter'):
            self._sleep_msg_counter = 0
        self._update_batch_bar()
        self.scroll_area = scroll_area
        self.chat_container = chat_container
        self.chat_layout = chat_layout
        self.todo_list = todo
        
        # 切换 UI
        self.session_tabs.blockSignals(True)
        self.session_tabs.setCurrentIndex(tab_index)
        self.session_tabs.blockSignals(False)
        self.session_stack.setCurrentWidget(scroll_area)
        
        self._sync_tabs_backup()
        self._update_context_stats()
    
    def _switch_session(self, tab_index: int):
        """切换到指定标签页的会话（运行中也允许切换）"""
        new_session_id = self.session_tabs.tabData(tab_index)
        if not new_session_id or new_session_id == self._session_id:
            return
        
        # 保存当前会话（如果当前不是 agent 正在写入的 session，正常保存）
        if self._agent_session_id != self._session_id:
            self._save_current_session_state()
        
        # 加载目标会话
        self._load_session_state(new_session_id)
        
        # 切换显示
        sdata = self._sessions[new_session_id]
        self.session_stack.setCurrentWidget(sdata['scroll_area'])
        
        # 更新按钮状态（取决于目标 session 是否就是正在运行的 session）
        self._update_run_buttons()
        self._update_context_stats()
    
    def _close_session_tab(self, tab_index: int):
        """关闭指定标签页"""
        sid = self.session_tabs.tabData(tab_index)
        # 禁止关闭正在运行的 session
        if sid and self._agent_session_id == sid:
            return
        
        session_id = self.session_tabs.tabData(tab_index)
        if not session_id:
            return
        
        # 如果只剩一个标签，不关闭，只清空
        if self.session_tabs.count() <= 1:
            self._on_clear()
            return
        
        # 如果关闭的是当前活动会话，先切到相邻标签
        if session_id == self._session_id:
            new_index = tab_index - 1 if tab_index > 0 else tab_index + 1
            new_sid = self.session_tabs.tabData(new_index)
            if new_sid:
                self._load_session_state(new_sid)
                sdata = self._sessions[new_sid]
                self.session_stack.setCurrentWidget(sdata['scroll_area'])
        
        # 移除标签和会话数据
        self.session_tabs.removeTab(tab_index)
        sdata = self._sessions.pop(session_id, None)
        if sdata and sdata.get('scroll_area'):
            self.session_stack.removeWidget(sdata['scroll_area'])
            sdata['scroll_area'].deleteLater()
        
        # ★ 关闭 tab 后同步删除对应的磁盘 session 文件
        try:
            session_file = self._cache_dir / f"session_{session_id}.json"
            if session_file.exists():
                session_file.unlink()
        except Exception:
            pass
        
        self._sync_tabs_backup()
        self._update_context_stats()
    
    def _save_current_session_state(self):
        """将当前瞬态状态存入 _sessions 字典"""
        if self._session_id not in self._sessions:
            return
        s = self._sessions[self._session_id]
        s['conversation_history'] = self._conversation_history
        s['context_summary'] = self._context_summary
        s['current_response'] = self._current_response
        s['token_stats'] = self._token_stats
    
    def _sync_tabs_backup(self):
        """同步 tab 顺序和标签名到纯 Python 备份（atexit 时 Qt widget 可能已销毁）"""
        try:
            backup = []
            for i in range(self.session_tabs.count()):
                sid = self.session_tabs.tabData(i)
                label = self.session_tabs.tabText(i)
                if sid:
                    backup.append((sid, label))
            self._tabs_backup = backup
        except (RuntimeError, AttributeError):
            pass  # Qt widget 已销毁，保留旧备份
    
    def _load_session_state(self, session_id: str):
        """从 _sessions 恢复指定会话的状态"""
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
        """根据用户首条消息自动重命名当前标签"""
        for i in range(self.session_tabs.count()):
            if self.session_tabs.tabData(i) == self._session_id:
                current_label = self.session_tabs.tabText(i)
                if current_label.startswith("Chat "):
                    short = text[:18].replace('\n', ' ').strip()
                    if len(text) > 18:
                        short += "..."
                    self.session_tabs.setTabText(i, short)
                break

    def _retranslate_session_tabs(self):
        """语言切换后更新会话标签栏翻译文本"""
        self.btn_new_session.setToolTip(tr('session.new'))
