# -*- coding: utf-8 -*-
"""
Chat View — conversation display and scrolling logic.

Extracted from ai_tab.py as a Mixin. Responsibilities:
- Appending messages to the chat area
- Scroll control (including a Claude-style floating "scroll to bottom" button)
- Toast message display
"""

from morfyai.qt_compat import QtWidgets, QtCore, QtGui
from .cursor_widgets import (
    UserMessage,
    AIResponse,
    StatusLine,
    ClickableImageLabel,
)


# ============================================================
# Floating "scroll to bottom" button — Claude-style (rounded chip / pill).
# Shown when the user scrolls up past the threshold; clicking snaps back to bottom.
# ============================================================
class FloatingScrollToBottomButton(QtWidgets.QPushButton):
    """A pill-shaped floating button anchored bottom-right of a QScrollArea.

    Appears only when the user is scrolled away from bottom by > threshold px.
    Click → snap to last message and hide.
    """

    THRESHOLD_PX = 100      # how far from bottom before button shows
    BTN_WIDTH = 44          # pill width (wider than tall = chip-like)
    BTN_HEIGHT = 32         # pill height
    MARGIN_BOTTOM = 16      # px above the scroll area's bottom edge
    MARGIN_RIGHT = 22       # px from the scroll area's right edge

    def __init__(self, scroll_area: QtWidgets.QScrollArea):
        super().__init__(scroll_area)
        self._scroll_area = scroll_area
        self.setObjectName("scrollToBottomBtn")
        self.setFixedSize(self.BTN_WIDTH, self.BTN_HEIGHT)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip("Scroll to bottom")
        self.setText("↓")   # ↓ down arrow
        self.setFlat(False)

        radius = self.BTN_HEIGHT // 2   # full pill rounding
        # Inline style — guarantees rounding even if QSS misses the selector
        self.setStyleSheet(
            "QPushButton#scrollToBottomBtn {"
            "  color: #e2e8f0;"
            "  background-color: rgba(24,26,44,235);"
            "  border: 1px solid rgba(255,255,255,32);"
            f"  border-radius: {radius}px;"
            "  font-size: 16px;"
            "  font-weight: 600;"
            "  padding: 0px 8px 2px 8px;"
            "  text-align: center;"
            "}"
            "QPushButton#scrollToBottomBtn:hover {"
            "  background-color: rgba(251,122,26,235);"
            "  border-color: rgba(251,122,26,255);"
            "  color: #ffffff;"
            "}"
            "QPushButton#scrollToBottomBtn:pressed {"
            "  background-color: rgba(234,88,12,250);"
            "}"
        )

        # Drop shadow for nicer separation from chat content
        try:
            eff = QtWidgets.QGraphicsDropShadowEffect(self)
            eff.setBlurRadius(20)
            eff.setOffset(0, 4)
            eff.setColor(QtGui.QColor(0, 0, 0, 190))
            self.setGraphicsEffect(eff)
        except Exception:
            pass

        self.hide()

        # Hook the scrollbar to track position; install resize filter on viewport
        sb = scroll_area.verticalScrollBar()
        sb.valueChanged.connect(self._on_scroll_changed)
        sb.rangeChanged.connect(self._on_scroll_changed)
        scroll_area.viewport().installEventFilter(self)
        scroll_area.installEventFilter(self)

        # Click → force scroll
        self.clicked.connect(self._snap_to_bottom)

        # Initial positioning
        QtCore.QTimer.singleShot(0, self._reposition)

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Resize:
            self._reposition()
        return False  # don't consume; let normal handling continue

    def _reposition(self):
        try:
            vp = self._scroll_area.viewport()
            vp_rect = vp.geometry()    # in scroll_area's coord space
            x = vp_rect.right() - self.width() - self.MARGIN_RIGHT
            y = vp_rect.bottom() - self.height() - self.MARGIN_BOTTOM
            self.move(max(0, x), max(0, y))
            self.raise_()
        except RuntimeError:
            pass

    def _on_scroll_changed(self, *_):
        try:
            sb = self._scroll_area.verticalScrollBar()
            if sb.maximum() <= 0:
                self.hide()
                return
            distance_from_bottom = sb.maximum() - sb.value()
            if distance_from_bottom > self.THRESHOLD_PX:
                if not self.isVisible():
                    self._reposition()
                    self.show()
                    self.raise_()
            else:
                if self.isVisible():
                    self.hide()
        except RuntimeError:
            pass

    def _snap_to_bottom(self):
        """Snap so the LAST real widget's bottom aligns with viewport bottom
        (avoids overshoot into empty stretch space)."""
        try:
            target = _compute_last_widget_scroll_target(self._scroll_area)
            sb = self._scroll_area.verticalScrollBar()
            if target is None:
                sb.setValue(sb.maximum())
            else:
                sb.setValue(target)
            self.hide()
        except RuntimeError:
            pass


def _compute_last_widget_scroll_target(scroll_area: QtWidgets.QScrollArea):
    """Return the scrollbar value that anchors the last visible chat widget
    to the bottom of the viewport, with a small breathing pad.

    Returns None if no suitable widget can be located (caller should fall back
    to sb.maximum()).
    """
    try:
        container = scroll_area.widget()
        if container is None:
            return None
        layout = container.layout()
        if layout is None:
            return None
        # Iterate backwards for the last *visible widget* item (skip stretch / hidden)
        last_widget = None
        for i in range(layout.count() - 1, -1, -1):
            item = layout.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is None:
                continue   # spacer / sub-layout
            if not w.isVisible():
                continue
            last_widget = w
            break
        if last_widget is None:
            return None
        # last_widget's bottom in container coord space
        last_bottom = last_widget.y() + last_widget.height()
        viewport_h = scroll_area.viewport().height()
        # Anchor last widget's bottom = viewport bottom (minus small breathing pad)
        BREATH_PAD = 6
        target = last_bottom + BREATH_PAD - viewport_h
        sb = scroll_area.verticalScrollBar()
        target = max(sb.minimum(), min(sb.maximum(), target))
        return target
    except Exception:
        return None


def attach_scroll_to_bottom_button(scroll_area: QtWidgets.QScrollArea):
    """Attach a floating scroll-to-bottom button to the given scroll area.

    Idempotent — calling twice on the same scroll_area is safe.
    Stores the button as `scroll_area._scroll_to_bottom_btn` for later access.
    """
    if getattr(scroll_area, '_scroll_to_bottom_btn', None) is not None:
        return scroll_area._scroll_to_bottom_btn
    btn = FloatingScrollToBottomButton(scroll_area)
    scroll_area._scroll_to_bottom_btn = btn
    # Also attach the overshoot clamp — prevents wheel-scrolling past last message
    attach_overshoot_clamp(scroll_area)
    return btn


def attach_overshoot_clamp(scroll_area: QtWidgets.QScrollArea):
    """Prevent user from scrolling below the last real message into empty space.

    Root cause: chat_layout uses `addStretch()` at the end and the chat_container
    has `setWidgetResizable(True)`, so the scrollbar's maximum extends past the
    actual content bottom. We clamp valueChanged so the view can never sit below
    the last visible widget.

    Idempotent — calling twice is safe (signal connections are tracked).
    """
    if getattr(scroll_area, '_overshoot_clamp_installed', False):
        return
    scroll_area._overshoot_clamp_installed = True

    sb = scroll_area.verticalScrollBar()
    # Re-entrancy guard: setValue triggers valueChanged again; we must not
    # recurse into another clamp inside the handler.
    state = {'guard': False}

    # Allow a small slack so the very-last 1-2 px don't fight the user;
    # primary purpose is to stop big overshoots into empty stretch space.
    SLACK_PX = 4

    def _on_value_changed(val: int):
        if state['guard']:
            return
        try:
            target = _compute_last_widget_scroll_target(scroll_area)
            if target is None:
                return
            if val > target + SLACK_PX:
                state['guard'] = True
                try:
                    sb.setValue(target)
                finally:
                    state['guard'] = False
        except RuntimeError:
            pass

    sb.valueChanged.connect(_on_value_changed)


class ChatViewMixin:
    """Conversation display and scroll logic."""

    def _add_user_message(self, text: str, images: list = None):
        """Add a user message (may include clickable thumbnails for attached images)."""
        msg = UserMessage(text, self.chat_container)
        # If images are present, add a row of clickable thumbnails below the message
        if images:
            img_row = QtWidgets.QHBoxLayout()
            img_row.setSpacing(4)
            img_row.setContentsMargins(12, 0, 12, 4)
            for b64_data, _mt, thumb in images:
                # Restore the full pixmap from base64 for the zoom preview
                full_pixmap = QtGui.QPixmap()
                full_pixmap.loadFromData(__import__('base64').b64decode(b64_data))
                thumb_scaled = thumb.scaled(48, 48, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                lbl = ClickableImageLabel(thumb_scaled, full_pixmap)
                lbl.setObjectName("imgThumb")
                img_row.addWidget(lbl)
            img_row.addStretch()
            msg.layout().addLayout(img_row)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, msg)
        # Force scroll: when the user sends a message, they always want to see it appear
        self._scroll_to_bottom(force=True)

    def _add_ai_response(self) -> AIResponse:
        """Add an AI response block."""
        response = AIResponse(self.chat_container)
        response.createWrangleRequested.connect(self._on_create_wrangle)
        response.nodePathClicked.connect(self._navigate_to_node)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, response)
        self._current_response = response
        self._scroll_to_bottom(force=True)
        return response

    def _is_user_scrolled_up(self) -> bool:
        """Check whether the user is browsing history (scrollbar not at bottom)."""
        scrollbar = self.scroll_area.verticalScrollBar()
        # If the scrollbar is more than 100 px away from the bottom, treat as "browsing"
        return scrollbar.maximum() - scrollbar.value() > 100

    def _scroll_to_bottom(self, force: bool = False):
        """Scroll to the bottom while respecting the user's viewing position.

        Throttled to avoid flooding the event loop.

        Args:
            force: force the scroll (used for new messages).
        """
        if force or not self._is_user_scrolled_up():
            # Throttle: if a pending timer is already scheduled, skip this call
            if not hasattr(self, '_scroll_timer'):
                self._scroll_timer = QtCore.QTimer(self)
                self._scroll_timer.setSingleShot(True)
                self._scroll_timer.setInterval(60)
                self._scroll_timer.timeout.connect(self._do_scroll)
            if not self._scroll_timer.isActive():
                self._scroll_timer.start()

    def _do_scroll(self):
        """Perform the actual scroll — anchor on the bottom of the last real message
        (so the view doesn't slip into the empty stretch area)."""
        try:
            sb = self.scroll_area.verticalScrollBar()
            target = _compute_last_widget_scroll_target(self.scroll_area)
            if target is None:
                sb.setValue(sb.maximum())
            else:
                sb.setValue(target)
            # Hide floating button if present (we're now at bottom)
            btn = getattr(self.scroll_area, '_scroll_to_bottom_btn', None)
            if btn is not None:
                btn.hide()
        except RuntimeError:
            pass  # widget may already be destroyed

    def _scroll_agent_to_bottom(self, force: bool = False):
        """Scroll the agent's session if it is currently visible; otherwise skip."""
        # Only scroll when the visible session matches the agent session
        if self._agent_session_id and self._agent_session_id != self._session_id:
            return  # agent runs in a background session — don't interrupt what the user is viewing
        self._scroll_to_bottom(force=force)

    def _show_toast(self, text: str, duration_ms: int = 3000):
        """Show a temporary toast at the bottom of the chat area; auto-dismisses."""
        toast = StatusLine(text)
        # Must use insertWidget before the stretch — otherwise addWidget puts it
        # after the stretch and subsequent messages end up with empty gaps.
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, toast)
        self._scroll_to_bottom(force=True)
        def _remove():
            try:
                self.chat_layout.removeWidget(toast)
                toast.setParent(None)
                toast.deleteLater()
            except RuntimeError:
                pass
        QtCore.QTimer.singleShot(duration_ms, _remove)
