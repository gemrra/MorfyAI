# -*- coding: utf-8 -*-
"""
Cursor-style UI components — refactored version.
Mimics the Cursor sidebar's minimal design.
Each conversation turn forms a complete block: thinking → operation → summary.
"""

from morfyai.qt_compat import QtWidgets, QtCore, QtGui
from datetime import datetime
from typing import Optional, List, Dict
import html
import math
import re
import time

from .i18n import tr

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None


def _fmt_duration(seconds: float) -> str:
    """formatizationwhenlong: <60s -> '18s', >=60s -> '1m43s'"""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m{s % 60:02d}s"


# ============================================================
# node path → canclicklink
# ============================================================

# match Houdini node path: /obj/..., /out/..., /ch/..., /shop/..., /stage/..., /mat/..., /tasks/...
_NODE_PATH_RE = re.compile(
    r'(?<!["\w/])'                          # Not preceded by a quote, word char, or /
    r'(/(?:obj|out|ch|shop|stage|mat|tasks)(?:/[\w.]+)+)'   # paththisbody
    r'(?!["\w/])'                           # Not followed by a quote, word char, or /
)

_NODE_LINK_STYLE = "color:#10b981;text-decoration:none;font-family:Consolas,Monaco,monospace;"


def _linkify_node_paths(text: str) -> str:
    """willtextin  Houdini node pathconvertswapascanclick  <a> label
    
    Uses the houdini:// scheme; click is dispatched via Qt linkActivated signal.
    """
    return _NODE_PATH_RE.sub(
        lambda m: f'<a href="houdini://{m.group(1)}" style="{_NODE_LINK_STYLE}">{m.group(1)}</a>',
        text,
    )


def _linkify_node_paths_plain(text: str) -> str:
    """willpuretextin node pathconvertswapasrichtext HTML (containingcanclicklink) 
    
    first html.escape again linkify, guaranteesafe. 
    """
    escaped = html.escape(text)
    return _linkify_node_paths(escaped).replace('\n', '<br>')


# ============================================================
# streamlightedgebox — AI respondshouldactivewheninleft sideshowstreammovegradualchangelightwith
# ============================================================

class AuroraBar(QtWidgets.QWidget):
    """Flowing gradient light strip — placed on the left of AIResponse; flows continuously during the AI reply.

    3px wide, monochrome silver-white. Samples a virtual color loop at fixed intervals
    (with phase offset) guaranteeing the stop points always advance,
    eliminating jump artifacts. Settles to very light silver-gray on stop.
    """

    _NUM_STOPS = 10  # Gradient sample-point count; higher is smoother

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(3)
        self._phase = 0.0
        self._active = False
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(30)  # ~33 fps
        self._timer.timeout.connect(self._tick)
        # Loop color-strip key colors (first == last == seamless wraparound)
        self._key_colors = [
            QtGui.QColor(226, 232, 240, 200),  # bright silver-white
            QtGui.QColor(100, 116, 139, 100),   # dark silver
            QtGui.QColor(226, 232, 240, 200),   # bright silver-white (loop close)
        ]

    # -- public API --------------------------------------------------

    def start(self):
        """startstreamlightmovedraw"""
        self._active = True
        self._phase = 0.0
        self.setFixedWidth(3)
        self.setVisible(True)
        self._timer.start()
        self.update()

    def stop(self):
        """Stop the flowing-light animation; shrink to zero width to keep the card clean."""
        self._active = False
        self._timer.stop()
        self.setFixedWidth(0)
        self.update()

    @property
    def running(self) -> bool:
        return self._active

    # -- internal ----------------------------------------------------

    def _tick(self):
        self._phase += 0.006
        if self._phase >= 1.0:
            self._phase -= 1.0
        self.update()

    def _sample(self, t: float) -> QtGui.QColor:
        """Sample from the virtual loop color-strip; t in [0, 1], smooth interpolation."""
        keys = self._key_colors
        n = len(keys) - 1  # Segment count (first/last same color = n segments cover the full loop)
        scaled = (t % 1.0) * n
        idx = int(scaled)
        frac = scaled - idx
        c1 = keys[idx]
        c2 = keys[min(idx + 1, n)]
        return QtGui.QColor(
            int(c1.red()   + (c2.red()   - c1.red())   * frac),
            int(c1.green() + (c2.green() - c1.green()) * frac),
            int(c1.blue()  + (c2.blue()  - c1.blue())  * frac),
            int(c1.alpha() + (c2.alpha() - c1.alpha()) * frac),
        )

    def paintEvent(self, event):  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect()
        if self._active:
            grad = QtGui.QLinearGradient(0, 0, 0, rect.height())
            for i in range(self._NUM_STOPS + 1):
                pos = i / self._NUM_STOPS          # fixfixeddeliveradd 0.0 → 1.0
                color = self._sample(pos + self._phase)  # phase offset
                grad.setColorAt(pos, color)
            p.fillRect(rect, grad)
        else:
            p.fillRect(rect, QtGui.QColor(148, 163, 184, 50))
        p.end()


# ============================================================
# colortheme (deepcolortheme)
# ============================================================

class CursorTheme:
    """Glassmorphism dark theme — blue/purple base + glass texture."""
    # Background colors (deep blue-black)
    BG_PRIMARY = "#0f1019"
    BG_SECONDARY = "#0c0e19"
    BG_TERTIARY = "#101224"
    BG_HOVER = "#1c1e36"
    
    # Border colors (glass edge)
    BORDER = "rgba(255,255,255,12)"
    BORDER_FOCUS = "#3b82f6"
    
    # Text colors (clearer / brighter)
    TEXT_PRIMARY = "#e2e8f0"
    TEXT_SECONDARY = "#94a3b8"
    TEXT_MUTED = "#64748b"
    TEXT_BRIGHT = "#ffffff"
    
    # Accent colors (more vivid)
    ACCENT_BLUE = "#3b82f6"
    ACCENT_GREEN = "#10b981"
    ACCENT_ORANGE = "#f59e0b"
    ACCENT_RED = "#ef4444"
    ACCENT_PURPLE = "#a78bfa"
    ACCENT_YELLOW = "#fbbf24"
    ACCENT_BEIGE = "#f59e0b"       # strongadjustcolor (replaceswaporiginalwarmcolor) — toolcall/collapsesection
    
    # messageleftedgeboundary
    BORDER_USER = "rgba(148,163,184,120)"   # User message - soft silver-gray
    BORDER_AI = "rgba(167,139,250,100)"     # AI reply — lightpurplelighthalo
    
    # font
    FONT_BODY = "'Segoe UI', 'Inter', sans-serif"
    FONT_CODE = "'Consolas', 'Monaco', 'Courier New', monospace"


# ============================================================
# cancollapsesectionblock (throughuse) 
# ============================================================

class CollapsibleSection(QtWidgets.QWidget):
    """cancollapsesectionblock - clicktitleexpand/collectstart"""
    
    def __init__(self, title: str, icon: str = "", collapsed: bool = True, parent=None):
        super().__init__(parent)
        self._collapsed = collapsed
        self._title = title
        self._icon = icon
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(0)
        
        # titlebar (canclick) 
        self.header = QtWidgets.QPushButton()
        self.header.setFlat(True)
        self.header.setCursor(QtCore.Qt.PointingHandCursor)
        self.header.clicked.connect(self.toggle)
        self._update_header()
        self.header.setObjectName("collapseHeader")
        layout.addWidget(self.header)
        
        # contentsection
        self.content_widget = QtWidgets.QWidget()
        self.content_layout = QtWidgets.QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(6, 4, 4, 4)
        self.content_layout.setSpacing(2)
        self.content_widget.setObjectName("collapseContent")
        layout.addWidget(self.content_widget)
        # Must call setVisible AFTER addWidget; otherwise a parent-less widget flashes as a standalone window
        self.content_widget.setVisible(not collapsed)
    
    def _update_header(self):
        arrow = "▶" if self._collapsed else "▼"
        icon_part = f"{self._icon} " if self._icon else ""
        self.header.setText(f"{arrow} {icon_part}{self._title}")
    
    def toggle(self):
        self._collapsed = not self._collapsed
        self.content_widget.setVisible(not self._collapsed)
        self._update_header()
    
    def set_title(self, title: str):
        self._title = title
        self._update_header()
    
    def expand(self):
        if self._collapsed:
            self.toggle()
    
    def collapse(self):
        if not self._collapsed:
            self.toggle()
    
    def add_widget(self, widget: QtWidgets.QWidget):
        self.content_layout.addWidget(widget)
    
    def add_text(self, text: str, style: str = "normal"):
        label = QtWidgets.QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        label.setObjectName("collapseText")
        label.setProperty("textStyle", style)
        self.content_layout.addWidget(label)
        return label


# ============================================================
# pulserefershow 
# ============================================================

class PulseIndicator(QtWidgets.QWidget):
    """Small pulse dot - uses opacity animation to indicate an in-progress state."""

    def __init__(self, color: str = CursorTheme.ACCENT_PURPLE, size: int = 8, parent=None):
        super().__init__(parent)
        self._color = QtGui.QColor(color)
        self._dot_size = size
        self._opacity = 1.0
        self.setFixedSize(size + 6, size + 6)

        self._anim = QtCore.QPropertyAnimation(self, b"pulseOpacity")
        self._anim.setDuration(1200)
        self._anim.setStartValue(0.25)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QtCore.QEasingCurve.InOutSine)
        self._anim.setLoopCount(-1)  # nolimitloop

    # ---- Qt Property ----
    def _get_opacity(self):
        return self._opacity

    def _set_opacity(self, v):
        self._opacity = v
        self.update()

    pulseOpacity = QtCore.Property(float, _get_opacity, _set_opacity)

    def start(self):
        self._anim.start()

    def stop(self):
        self._anim.stop()
        self._opacity = 0.0
        self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        c = QtGui.QColor(self._color)
        c.setAlphaF(self._opacity)
        p.setBrush(c)
        p.setPen(QtCore.Qt.NoPen)
        x = (self.width() - self._dot_size) / 2
        y = (self.height() - self._dot_size) / 2
        p.drawEllipse(QtCore.QRectF(x, y, self._dot_size, self._dot_size))
        p.end()


# ============================================================
# Thinking-process section (no built-in pulse; animation moved above the input box)
# ============================================================

class ThinkingSection(CollapsibleSection):
    """Thinking process - displays the AI thinking content (supports multi-round cumulative timing).
    
    The pulse/animation indicator has been moved to the ThinkingBar above the input box; this widget only shows content.
    ★ use QPlainTextEdit(readOnly), selfwithscrollitem. 
    Height computation uses the same reliable approach as ChatInput:
      QTimer.singleShot(0) latency + one by oneblock block.layout().lineCount() statisticsvisualrow. 
    """
    
    # Max height in pixels; above this we fix the height and the built-in scrollbar appears
    _MAX_HEIGHT_PX = 400
    
    def __init__(self, parent=None):
        # ★ Default collapsed — Claude-style. User can manually expand the
        #   "Thinking ..." header to inspect reasoning. The streaming
        #   indicator above the input box still shows live status.
        super().__init__(tr('thinking.init'), icon="", collapsed=True, parent=parent)
        # Prevent being stretched by the parent layout - only as tall as the content
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Maximum,
        )
        self._thinking_text = ""
        self._start_time = time.time()
        self._accumulated_seconds = 0.0
        self._round_start = time.time()
        self._round_count = 0
        
        # ★ thinkingcontent — QPlainTextEdit(readOnly), selfwithscrollitem
        self._text_font = QtGui.QFont(CursorTheme.FONT_BODY)
        self._text_font.setPixelSize(13)
        
        self.thinking_label = QtWidgets.QPlainTextEdit()
        self.thinking_label.setReadOnly(True)
        self.thinking_label.setFont(self._text_font)
        self.thinking_label.document().setDefaultFont(self._text_font)
        self.thinking_label.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.thinking_label.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.thinking_label.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.thinking_label.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        self.thinking_label.setObjectName("thinkLabel")
        # initialheightasonerow (compact) , streaminginputwhenwillmovestateaddlarge
        self._line_h = QtGui.QFontMetrics(self._text_font).lineSpacing()
        self.thinking_label.setFixedHeight(self._line_h + 12)
        self.content_layout.addWidget(self.thinking_label)
        
        # titlestyle
        self.header.setObjectName("thinkHeader")
    
    def _update_height(self):
        """based onvisualrowcount (containingautoswaprow) movestateadjustwholeheight. 
        
        Same reliable approach as ChatInput._adjust_height:
        one by oneblocktraverse block.layout().lineCount() statisticstruerealvisualrowcount. 
        """
        doc = self.thinking_label.document()
        visual_lines = 0
        block = doc.begin()
        while block.isValid():
            bl = block.layout()
            if bl and bl.lineCount() > 0:
                visual_lines += bl.lineCount()
            else:
                visual_lines += 1
            block = block.next()
        visual_lines = max(1, visual_lines)
        
        desired = self._line_h * visual_lines + 12   # 12 = padding
        self.thinking_label.setFixedHeight(min(max(desired, self._line_h + 12), self._MAX_HEIGHT_PX))
    
    def _scroll_to_bottom(self):
        """scrolltobottompart"""
        vbar = self.thinking_label.verticalScrollBar()
        vbar.setValue(vbar.maximum())
    
    def _total_elapsed(self) -> float:
        if self._finalized:
            return self._accumulated_seconds
        return self._accumulated_seconds + (time.time() - self._round_start)
    
    def append_thinking(self, text: str):
        if '\ufffd' in text:
            text = text.replace('\ufffd', '')
        self._thinking_text += text
        self.thinking_label.setPlainText(self._thinking_text)
        # ★ latencytobelowoneeventloop (ensure Qt layoutcompleteafteragaincomputeheight, and ChatInput samestrategy) 
        QtCore.QTimer.singleShot(0, self._update_height)
        QtCore.QTimer.singleShot(0, self._scroll_to_bottom)
    
    def update_time(self):
        if self._finalized:
            return
        self.set_title(tr('thinking.progress', _fmt_duration(self._total_elapsed())))
    
    @property
    def _finalized(self):
        return getattr(self, '_is_finalized', False)
    
    def resume(self):
        self._is_finalized = False
        self._round_start = time.time()
        self._round_count += 1
        self._thinking_text += f"\n{tr('thinking.round', self._round_count + 1)}\n"
        self.thinking_label.setPlainText(self._thinking_text)
        QtCore.QTimer.singleShot(0, self._update_height)
        self.set_title(tr('thinking.progress', _fmt_duration(self._total_elapsed())))
        # ★ keepcurrentcollapsestate — notforceexpand

    def finalize(self):
        if self._finalized:
            return
        self._is_finalized = True
        self._accumulated_seconds += (time.time() - self._round_start)
        total = self._accumulated_seconds
        self.set_title(tr('thinking.done', _fmt_duration(total)))
        # ★ keepcurrentcollapsestate — notforceexpand


# ============================================================
# inputboxonway "thinkingin" refershowitem (streamlightmovedraw) 
# ============================================================

class ThinkingBar(QtWidgets.QWidget):
    """showininputboxonway thinkingstaterefershowitem. 
    
    Has a left-to-right scanning highlight light effect on the text,
    indicating the AI is reasoning; replaces the original built-in pulse dot in ThinkingSection.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(18)
        self.setVisible(False)

        self._elapsed = 0.0   # second
        self._phase = 0.0     # streamlightmutuallybit [0, 1]

        # streamlightfixedwhen  ~25fps
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

    def start(self):
        self._elapsed = 0.0
        self._phase = 0.0
        self.setVisible(True)
        self._timer.start()
        self.update()

    def stop(self):
        self._timer.stop()
        self.setVisible(False)

    def set_elapsed(self, seconds: float):
        self._elapsed = seconds
        self.update()

    def _tick(self):
        self._phase += 0.025
        if self._phase > 1.0:
            self._phase -= 1.0
        self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing)

        s = int(self._elapsed)
        time_str = f"{s}s" if s < 60 else f"{s // 60}m{s % 60:02d}s"
        display = f"  ✦ {tr('thinking.progress', time_str)}"

        font = QtGui.QFont(CursorTheme.FONT_BODY, 9)
        p.setFont(font)
        fm = QtGui.QFontMetrics(font)
        y = (self.height() + fm.ascent() - fm.descent()) // 2

        x = 8
        for i, ch in enumerate(display):
            char_pos = i / max(len(display), 1)
            dist = abs(char_pos - self._phase)
            dist = min(dist, 1.0 - dist)
            glow = max(0.0, 1.0 - dist * 5.0)

            base = QtGui.QColor(CursorTheme.ACCENT_PURPLE)
            muted = QtGui.QColor(CursorTheme.TEXT_MUTED)
            r = int(muted.red()   + (base.red()   - muted.red())   * glow)
            g = int(muted.green() + (base.green() - muted.green()) * glow)
            b = int(muted.blue()  + (base.blue()  - muted.blue())  * glow)

            p.setPen(QtGui.QColor(r, g, b))
            p.drawText(x, y, ch)
            x += fm.horizontalAdvance(ch)

        p.end()


# ============================================================
# confirmmode — withinassociatepreviewconfirmwidget (replacement forpopupwindow) 
# ============================================================

class VEXPreviewInline(QtWidgets.QFrame):
    """embedconversationstreamin toolexecutepreviewcard. 
    
    userclick ✓ confirm or ✕ cancelaftervia confirmed / cancelled signalnotify. 
    """

    confirmed = QtCore.Signal()
    cancelled = QtCore.Signal()

    def __init__(self, tool_name: str, args: dict, parent=None):
        super().__init__(parent)
        self._decided = False
        # The whole card must NOT be stretched by the parent layout - only as tall as the content
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Maximum,
        )
        self.setObjectName("vexPreviewInline")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(3)

        # titlerow
        title = QtWidgets.QLabel(tr('confirm.title', tool_name))
        title.setObjectName("vexPreviewTitle")
        title.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(title)

        # ★ compactparametersummary (onlyshowkeyparameter, eachonerow, at most 6 row) 
        summary_lines = []
        for k, v in args.items():
            sv = str(v)
            if len(sv) > 120:
                sv = sv[:117] + "..."
            summary_lines.append(f"  {k}: {sv}")
        if summary_lines:
            summary_text = "\n".join(summary_lines[:6])
            if len(summary_lines) > 6:
                summary_text += f"\n  {tr('confirm.params_more', len(summary_lines))}"
            summary_lbl = QtWidgets.QLabel(summary_text)
            summary_lbl.setWordWrap(True)
            summary_lbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            summary_lbl.setObjectName("vexInlineSummary")
            summary_lbl.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding,
                QtWidgets.QSizePolicy.Maximum,
            )
            layout.addWidget(summary_lbl)

        # buttonrow (rightalign, compact) 
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addStretch()

        btn_cancel = QtWidgets.QPushButton(tr('confirm.cancel'))
        btn_cancel.setCursor(QtCore.Qt.PointingHandCursor)
        btn_cancel.setFixedHeight(24)
        btn_cancel.setObjectName("btnCancel")
        btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(btn_cancel)

        btn_confirm = QtWidgets.QPushButton(tr('confirm.execute'))
        btn_confirm.setCursor(QtCore.Qt.PointingHandCursor)
        btn_confirm.setFixedHeight(24)
        btn_confirm.setObjectName("btnConfirmGreen")
        btn_confirm.clicked.connect(self._on_confirm)
        btn_row.addWidget(btn_confirm)

        layout.addLayout(btn_row)

    def _on_confirm(self):
        if self._decided:
            return
        self._decided = True
        # ★ confirmafterdirectlyhidewholecard, notagainshow"alreadyconfirmexecute"withinembedwindow
        self.setVisible(False)
        self.setFixedHeight(0)
        self.confirmed.emit()

    def _on_cancel(self):
        if self._decided:
            return
        self._decided = True
        # ★ cancelalsodirectlyhidewholecard (andconfirmconsistent) , don'twithinembedwindow
        self.setVisible(False)
        self.setFixedHeight(0)
        self.cancelled.emit()

    def _show_decided(self, text: str, color: str):
        """After the decision, swap the entire card to a compact state."""
        layout = self.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            sub = item.layout()
            if sub:
                while sub.count():
                    si = sub.takeAt(0)
                    sw = si.widget()
                    if sw:
                        sw.deleteLater()
        lbl = QtWidgets.QLabel(text)
        lbl.setObjectName("vexPreviewStatus")
        lbl.setProperty("state", "confirmed" if color == CursorTheme.ACCENT_GREEN else "cancelled")
        lbl.style().unpolish(lbl)
        lbl.style().polish(lbl)
        layout.addWidget(lbl)
        self.setFixedHeight(30)


# ============================================================
# toolcallitem
# ============================================================

class ToolCallItem(CollapsibleSection):
    """singletoolcall — CollapsibleSection style (with Result collapseconsistent graycolorstyle) 
    
    titlebar: ▶ tool_name             (executein) 
           ▶ tool_name (1.2s)       (complete) 
    expandaftershowcomplete result text, node pathcanclickjump. 
    """

    nodePathClicked = QtCore.Signal(str)  # node pathisclick

    def __init__(self, tool_name: str, parent=None):
        super().__init__(tool_name, icon="", collapsed=True, parent=parent)
        self.tool_name = tool_name
        self._result = None
        self._success = None
        self._start_time = time.time()

        self.header.setObjectName("toolCallHeader")

        # progressitem (embed content_layout toppart, executefinishfinishafterhide) 
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setFixedHeight(2)
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setObjectName("toolProgress")
        self.content_layout.addWidget(self.progress_bar)

        self._result_label = None

    def set_result(self, result: str, success: bool = True):
        """settoolexecuteresult"""
        self._result = result
        self._success = success
        elapsed = time.time() - self._start_time

        # hideprogressitem
        self.progress_bar.setVisible(False)

        # updatetitle: onlyshowtoolname + consumewhen, noicon
        self.set_title(f"{self.tool_name} ({elapsed:.1f}s)")

        # On failure, the title uses white (brighter); on success keep gray
        if not success:
            self.header.setProperty("state", "failed")
            self.header.style().unpolish(self.header)
            self.header.style().polish(self.header)

        # addresulttext (graycolor, failedwhenwhitecolor) —— node pathcanclick
        if result.strip():
            rich_html = _linkify_node_paths_plain(result)
            self._result_label = QtWidgets.QLabel(rich_html)
            self._result_label.setWordWrap(True)
            self._result_label.setTextFormat(QtCore.Qt.RichText)
            self._result_label.setOpenExternalLinks(False)
            self._result_label.setTextInteractionFlags(
                QtCore.Qt.TextSelectableByMouse | QtCore.Qt.LinksAccessibleByMouse
            )
            self._result_label.linkActivated.connect(self._on_result_link)
            self._result_label.setObjectName("toolResultLabel")
            if not success:
                self._result_label.setProperty("state", "failed")
            self.content_layout.addWidget(self._result_label)

    def _on_result_link(self, url: str):
        """toolresultin linkisclick"""
        if url.startswith('houdini://'):
            self.nodePathClicked.emit(url[len('houdini://'):])
        elif url.startswith(('http://', 'https://')):
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))


# ============================================================
# executeprocesssectionblock
# ============================================================

class ExecutionSection(CollapsibleSection):
    """executeprocess - cardstyletoolcallshow (defaultcollapse, usermanualexpand) """

    nodePathClicked = QtCore.Signal(str)  # Bubbled up from child ToolCallItems

    def __init__(self, parent=None):
        super().__init__(tr('exec.running'), icon="", collapsed=True, parent=parent)
        self._tool_calls: List[ToolCallItem] = []
        self._start_time = time.time()
        
        # updatetitlestyle
        self.header.setObjectName("execHeader")
    
    def add_tool_call(self, tool_name: str) -> ToolCallItem:
        """addtoolcall"""
        item = ToolCallItem(tool_name, self)
        item.nodePathClicked.connect(self.nodePathClicked.emit)
        self._tool_calls.append(item)
        self.content_layout.addWidget(item)
        self._update_title()
        return item
    
    def set_tool_result(self, tool_name: str, result: str, success: bool = True):
        """settoolresult"""
        # findtolastonematch toolcall
        for item in reversed(self._tool_calls):
            if item.tool_name == tool_name and item._result is None:
                item.set_result(result, success)
                break
        self._update_title()
    
    def _update_title(self):
        """updatetitle"""
        total = len(self._tool_calls)
        done = sum(1 for item in self._tool_calls if item._result is not None)
        if done < total:
            self.set_title(tr('exec.progress', done, total))
        else:
            elapsed = time.time() - self._start_time
            self.set_title(tr('exec.done', total, _fmt_duration(elapsed)))
    
    def finalize(self):
        """completeexecute"""
        elapsed = time.time() - self._start_time
        total = len(self._tool_calls)
        
        # Fallback: force-close any leftover progress bars
        for item in self._tool_calls:
            if item._result is None:
                item.progress_bar.setVisible(False)
                item_elapsed = time.time() - item._start_time
                item.set_title(f"{item.tool_name} ({item_elapsed:.1f}s)")
                item._result = ""  # markcompleted, avoidisduplicateprocess
                item._success = True
        
        success = sum(1 for item in self._tool_calls if item._success)
        failed = total - success
        
        if failed > 0:
            self.set_title(tr('exec.done_err', success, failed, _fmt_duration(elapsed)))
        else:
            self.set_title(tr('exec.done', total, _fmt_duration(elapsed)))


# ============================================================
# imagepreviewpopupwindow (clickthumbnaildiagramzoom inview) 
# ============================================================

class ImagePreviewDialog(QtWidgets.QDialog):
    """modalimagepreviewpopupwindow — clickthumbnaildiagramafterpopupout, showoriginalsize/selfsuitshouldwindow largediagram"""

    def __init__(self, pixmap: QtGui.QPixmap, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('img.preview'))
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowMaximizeButtonHint)
        self._pixmap = pixmap

        # Decide initial window size based on image size (max 80% of screen)
        screen = QtWidgets.QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            max_w, max_h = int(avail.width() * 0.8), int(avail.height() * 0.8)
        else:
            max_w, max_h = 1200, 800
        init_w = min(pixmap.width() + 40, max_w)
        init_h = min(pixmap.height() + 40, max_h)
        self.resize(init_w, init_h)

        # deepcolorbackground
        self.setObjectName("imgPreviewDlg")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # canscrollarea
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(QtCore.Qt.AlignCenter)
        scroll.setObjectName("chatScrollArea")

        self._img_label = QtWidgets.QLabel()
        self._img_label.setAlignment(QtCore.Qt.AlignCenter)
        scroll.setWidget(self._img_label)
        layout.addWidget(scroll)

        # bottombar: sizeinfo + closebutton
        bar = QtWidgets.QHBoxLayout()
        bar.setContentsMargins(12, 4, 12, 8)
        info = QtWidgets.QLabel(f"{pixmap.width()} × {pixmap.height()} px")
        info.setObjectName("imgInfoLabel")
        bar.addWidget(info)
        bar.addStretch()
        close_btn = QtWidgets.QPushButton(tr('btn.close'))
        close_btn.setObjectName("imgCloseBtn")
        close_btn.clicked.connect(self.close)
        bar.addWidget(close_btn)
        layout.addLayout(bar)

        self._update_preview()

    def _update_preview(self):
        """based onwindowlargesmallscaleimage (keepcompareexample) """
        viewport_w = self.width() - 20
        viewport_h = self.height() - 50
        if self._pixmap.width() > viewport_w or self._pixmap.height() > viewport_h:
            scaled = self._pixmap.scaled(
                viewport_w, viewport_h,
                QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        else:
            scaled = self._pixmap
        self._img_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()
        super().keyPressEvent(event)


class ClickableImageLabel(QtWidgets.QLabel):
    """canclick imagethumbnaildiagram — clickafterpopupout ImagePreviewDialog zoom inview"""

    def __init__(self, thumb_pixmap: QtGui.QPixmap, full_pixmap: QtGui.QPixmap, parent=None):
        super().__init__(parent)
        self._full_pixmap = full_pixmap
        self.setPixmap(thumb_pixmap)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip(tr('img.click_zoom'))

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            dlg = ImagePreviewDialog(self._full_pixmap, self.window())
            dlg.exec()
        else:
            super().mousePressEvent(event)


# ============================================================
# usermessage
# ============================================================

class UserMessage(QtWidgets.QWidget):
    """usermessage - supportcollapse (exceeds 2 rowwhenautocollapse, clickexpand/collectstart) """

    _COLLAPSED_MAX_LINES = 2  # collapsewhenshow maxrowcount

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._full_text = text
        self._collapsed = False  # initialstateby _maybe_collapse decidefixed

        # Top-level horizontal layout: left spring pushes the bubble to the right edge
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 14, 4)
        layout.setSpacing(0)

        # ---- Main container (rounded bubble) ----
        self._container = QtWidgets.QWidget()
        self._container.setObjectName("userMsgContainer")
        self._container.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        # Inline stylesheet so the orange bubble paints reliably on plain QWidget,
        # regardless of host Houdini palette / global QSS cascade quirks.
        self._container.setStyleSheet(
            "QWidget#userMsgContainer {"
            " background-color: rgba(255,140,42,28);"  # Houdini orange ~11% opacity
            " border: none;"
            " border-radius: 14px;"
            "}"
            "QLabel#userMsgText {"
            " color: #ffffff;"
            " background: transparent;"
            "}"
            "QPushButton#userMsgToggle {"
            " color: #f8fafc;"
            " background: transparent;"
            " border: none;"
            " text-align: left;"
            " padding: 0;"
            "}"
        )
        self._container.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred,
            QtWidgets.QSizePolicy.Preferred,
        )
        container_layout = QtWidgets.QVBoxLayout(self._container)
        container_layout.setContentsMargins(14, 10, 14, 8)
        container_layout.setSpacing(2)

        # ---- contentlabel ----
        self.content = QtWidgets.QLabel(text)
        self.content.setWordWrap(True)
        self.content.setTextFormat(QtCore.Qt.PlainText)
        self.content.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.content.setObjectName("userMsgText")
        self.content.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        container_layout.addWidget(self.content)

        # ---- expand/collectstart button ----
        self._toggle_btn = QtWidgets.QPushButton()
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._toggle_btn.setFixedHeight(20)
        self._toggle_btn.setObjectName("userMsgToggle")
        self._toggle_btn.clicked.connect(self._toggle_collapse)
        self._toggle_btn.setVisible(False)  # defaulthide, _maybe_collapse decidefixed
        container_layout.addWidget(self._toggle_btn)

        layout.addStretch(1)
        layout.addWidget(self._container, 0, QtCore.Qt.AlignRight | QtCore.Qt.AlignTop)

        # latencydecidebreakwhetherneedscollapse (etc. QLabel completelayoutafteragaincalculaterowcount) 
        QtCore.QTimer.singleShot(0, self._maybe_collapse)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Force bubble to ~70% of parent width (consistent, browser-chat-like)
        target_w = max(200, int(self.width() * 0.70))
        if self._container.maximumWidth() != target_w:
            self._container.setMaximumWidth(target_w)
            self._container.setMinimumWidth(target_w)

    # ------------------------------------------------------------------
    def _maybe_collapse(self):
        """checktextwhetherexceedsthresholdvaluerowcount, exceedsthenautocollapse"""
        line_count = self._full_text.count('\n') + 1
        if line_count > self._COLLAPSED_MAX_LINES:
            self._collapsed = True
            self._apply_collapsed()
            self._toggle_btn.setVisible(True)
        else:
            # Text isn't long enough - no collapse button needed
            self._toggle_btn.setVisible(False)

    def _apply_collapsed(self):
        """Apply collapsed state: only show the first N lines + ellipsis."""
        lines = self._full_text.split('\n')
        preview = '\n'.join(lines[:self._COLLAPSED_MAX_LINES])
        if len(lines) > self._COLLAPSED_MAX_LINES:
            preview += ' …'
        self.content.setText(preview)
        remaining = len(lines) - self._COLLAPSED_MAX_LINES
        self._toggle_btn.setText(tr('msg.expand', remaining))

    def _apply_expanded(self):
        """applicationexpandstate: showcompletetext"""
        self.content.setText(self._full_text)
        self._toggle_btn.setText(tr('msg.collapse'))

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        if self._collapsed:
            self._apply_collapsed()
        else:
            self._apply_expanded()


# ============================================================
# AI reply block (refactored version)
# ============================================================

class AIResponse(QtWidgets.QWidget):
    """AI reply - Cursor style
    
    structure: 
    +-- thinkingprocess (cancollapse, defaultcollapse) 
    +-- executeprocess (cancollapse, defaultcollapse) 
    +-- summary (Markdown render + codeblockhighlight) 
    """
    
    createWrangleRequested = QtCore.Signal(str)  # vex_code
    nodePathClicked = QtCore.Signal(str)         # node pathisclick
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._start_time = time.time()
        self._content = ""
        self._has_thinking = False
        self._has_execution = False
        self._shell_count = 0  # Python Shell executecountcount
        
        # ★ incrementalrenderstate
        self._frozen_segments: list = []    # alreadyfreeze richtextparagraph
        self._pending_text = ""             # stillnotfreeze tailparttext
        self._in_code_fence = False         # whetherincodeblockwithin
        self._code_fence_lang = ""          # codeblocklanguage
        self._in_table = False              # whetherintablegridconsecutiverowwithin
        self._incremental_enabled = True    # whetherenableincrementalrender
        self._table_flush_timer = QtCore.QTimer(self)
        self._table_flush_timer.setSingleShot(True)
        self._table_flush_timer.setInterval(600)
        self._table_flush_timer.timeout.connect(self._flush_pending_table)
        
        # ★ toplayerhorizontallayout: transparent wrapper + card withinpart
        # Wrapper menjaga right-margin agar card sejajar dengan user bubble.
        wrapper = QtWidgets.QHBoxLayout(self)
        wrapper.setContentsMargins(0, 4, 14, 8)
        wrapper.setSpacing(0)

        self._card = QtWidgets.QWidget()
        self._card.setObjectName("aiResponseCard")
        self._card.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self._card.setStyleSheet(
            "QWidget#aiResponseCard {"
            " background-color: rgba(30,34,46,110);"
            " border-radius: 10px;"
            "}"
        )
        wrapper.addWidget(self._card, 1)

        outer = QtWidgets.QHBoxLayout(self._card)
        outer.setContentsMargins(8, 8, 10, 10)
        outer.setSpacing(0)

        # streamlightedgebox (AI respondshouldactivewhenstreammove) 
        self.aurora_bar = AuroraBar(self._card)
        outer.addWidget(self.aurora_bar)

        # contentcolumn
        content_col = QtWidgets.QVBoxLayout()
        content_col.setContentsMargins(8, 0, 0, 0)
        content_col.setSpacing(4)
        outer.addLayout(content_col, 1)
        
        # forexternalreference (originalcomedirectlyuse layout  placeway) 
        layout = content_col
        
        # === thinkingprocesssectionblock ===
        self.thinking_section = ThinkingSection(self)
        self.thinking_section.setVisible(False)
        layout.addWidget(self.thinking_section)
        
        # === executeprocesssectionblock ===
        self.execution_section = ExecutionSection(self)
        self.execution_section.setVisible(False)
        self.execution_section.nodePathClicked.connect(self.nodePathClicked.emit)
        layout.addWidget(self.execution_section)
        
        # === Python Shell sectionblock (cancollapse, defaultcollapse) ===
        self.shell_section = CollapsibleSection("Python Shell", collapsed=True, parent=self)
        self.shell_section.setVisible(False)
        self.shell_section.header.setObjectName("shellHeaderPython")
        layout.addWidget(self.shell_section)
        
        # === System Shell sectionblock (cancollapse, defaultcollapse) ===
        self._sys_shell_count = 0
        self.sys_shell_section = CollapsibleSection("System Shell", collapsed=True, parent=self)
        self.sys_shell_section.setVisible(False)
        self.sys_shell_section.header.setObjectName("shellHeaderSystem")
        layout.addWidget(self.sys_shell_section)
        
        # === summary/replyarea ===
        self.summary_frame = QtWidgets.QFrame()
        self.summary_frame.setObjectName("aiSummary")
        self._summary_layout = QtWidgets.QVBoxLayout(self.summary_frame)
        self._summary_layout.setContentsMargins(8, 8, 6, 8)
        self._summary_layout.setSpacing(4)
        
        # staterow (horizontallayout: statetext + copybutton) 
        status_row = QtWidgets.QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(8)
        
        self.status_label = QtWidgets.QLabel(tr('thinking.init'))
        self.status_label.setObjectName("aiStatusLabel")
        # Word-wrap makes the label's minimumSizeHint small, so a long status/error
        # string (a full node path during scene edits, or a long API error) can no
        # longer force the card — and the whole chat column — wider than the viewport.
        self.status_label.setWordWrap(True)
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        
        # copyallpartbutton (completeafteronly thenshow) 
        self._copy_btn = QtWidgets.QPushButton(tr('btn.copy'))
        self._copy_btn.setVisible(False)
        self._copy_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._copy_btn.setFixedHeight(22)
        self._copy_btn.setObjectName("aiCopyBtn")
        self._copy_btn.clicked.connect(self._copy_content)
        status_row.addWidget(self._copy_btn)
        
        self._summary_layout.addLayout(status_row)
        
        # ★ alreadyfreezeparagraphcontain  — incrementalrenderwhenfreeze richtext/codeblockputinthisinside
        self._frozen_container = QtWidgets.QWidget()
        self._frozen_layout = QtWidgets.QVBoxLayout(self._frozen_container)
        self._frozen_layout.setContentsMargins(0, 0, 0, 0)
        self._frozen_layout.setSpacing(0)  # paragraphbetweendistanceby HTML margin control
        self._frozen_container.setVisible(False)
        self._summary_layout.addWidget(self._frozen_container)
        
        # contentarea —— streamingstageuse QPlainTextEdit (incrementalappend O(1)) , 
        # finalize whenbyneedsreplaceswapas RichContentWidget (Markdown render) . 
        # ★ key: streamingstage fontandbetweendistancemustwithrenderafter  richText QLabel consistent, 
        # Avoids producing a jump feeling at finalize time.
        self.content_label = QtWidgets.QPlainTextEdit()
        self.content_label.setReadOnly(True)
        self.content_label.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.content_label.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.content_label.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.content_label.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        # let size hint followcontentautoaddlong (notsetfixfixedheight) 
        self.content_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum
        )
        self.content_label.setObjectName("aiContentLabel")
        # Explicitly set the font so streaming and post-render use the same family and size
        _stream_font = QtGui.QFont()
        _stream_font.setFamilies(['Segoe UI', 'Inter'])
        _stream_font.setPixelSize(14)  # with {FS_MD}=14 consistent
        self.content_label.setFont(_stream_font)
        self.content_label.document().setDefaultFont(_stream_font)
        # ★ Tighter line spacing — kept in sync with HTML line-height (see _text_to_html)
        self.content_label.document().setDocumentMargin(0)
        self._apply_line_spacing(110)  # 110% line height
        # initialheightcompact, streaminginputwhenautoaddlong
        fm = QtGui.QFontMetrics(_stream_font)
        self._content_line_h = int(fm.height() * 1.1)
        self.content_label.setFixedHeight(self._content_line_h + 4)
        self.content_label.document().contentsChanged.connect(self._auto_resize_content)
        self._summary_layout.addWidget(self.content_label)
        
        layout.addWidget(self.summary_frame)
        
        # === detailsarea (cancollapsecontentetc.) ===
        self.details_layout = QtWidgets.QVBoxLayout()
        self.details_layout.setSpacing(2)
        layout.addLayout(self.details_layout)
    
    def add_thinking(self, text: str):
        """addthinkingcontent (sectionblockdefaultcollapse — usermainmoveclickexpandonly thenshowcontent) """
        if not self._has_thinking:
            self._has_thinking = True
            self.thinking_section.setVisible(True)
            # Do not auto-expand - keep default collapsed; avoids reasoning content disturbing the conversation flow
        self.thinking_section.append_thinking(text)
    
    def update_thinking_time(self):
        """updatethinkingwhenbetween (thinkingendafternotagainupdatestatelabel) """
        if self._has_thinking:
            if self.thinking_section._finalized:
                return  # thinkingalreadyend, notagainupdate
            self.thinking_section.update_time()
            total = self.thinking_section._total_elapsed()
            self.status_label.setText(tr('thinking.progress', _fmt_duration(total)))
    
    def add_shell_widget(self, widget: 'PythonShellWidget'):
        """will PythonShellWidget addto Python Shell collapsesectionblock"""
        self._shell_count += 1
        if not self.shell_section.isVisible():
            self.shell_section.setVisible(True)
        self.shell_section.set_title(f"Python Shell ({self._shell_count})")
        self.shell_section.add_widget(widget)
    
    def add_sys_shell_widget(self, widget: 'SystemShellWidget'):
        """will SystemShellWidget addto System Shell collapsesectionblock"""
        self._sys_shell_count += 1
        if not self.sys_shell_section.isVisible():
            self.sys_shell_section.setVisible(True)
        self.sys_shell_section.set_title(f"System Shell ({self._sys_shell_count})")
        self.sys_shell_section.add_widget(widget)
    
    def add_status(self, text: str):
        """addstate (processtoolcall) """
        if text.startswith("[tool]"):
            tool_name = text[6:].strip()
            self._add_tool_call(tool_name)
        else:
            self.status_label.setText(text)
    
    def _add_tool_call(self, tool_name: str):
        """addtoolcall"""
        if not self._has_execution:
            self._has_execution = True
            self.execution_section.setVisible(True)
        self.execution_section.add_tool_call(tool_name)
        self.status_label.setText(tr('exec.tool', tool_name))
    
    def add_tool_result(self, tool_name: str, result: str):
        """addtoolresult"""
        success = not result.startswith("[err]") and not result.startswith("error") and not result.startswith("Error")
        clean_result = result.removeprefix("[ok] ").removeprefix("[err] ")
        self.execution_section.set_tool_result(tool_name, clean_result, success)
    
    def _apply_line_spacing(self, percent: int = 160):
        """as QPlainTextEdit set proportional rowbetweendistance. 
        
        Qt   QPlainTextEdit notdirectlysupport CSS line-height, 
        needsvia QTextBlockFormat.setLineHeight comerealnow. 
        percent: 160 = 1.6x line spacing.
        """
        doc = self.content_label.document()
        cursor = QtGui.QTextCursor(doc)
        cursor.select(QtGui.QTextCursor.Document)
        fmt = QtGui.QTextBlockFormat()
        fmt.setLineHeight(percent, 1)  # 1 = ProportionalHeight
        cursor.mergeBlockFormat(fmt)

    def _auto_resize_content(self):
        """based on document  realboundaryrenderheightmovestateadjustwhole QPlainTextEdit  height. 
        
        Use doc.size().height() to get the actual laid-out pixel height,
        addononesmall bottompartedgedistanceasfinalheight. 
        """
        doc = self.content_label.document()
        # ensurelayoutinfoislatest 
        doc.adjustSize()
        doc_height = int(doc.size().height())
        target = doc_height + 4  # bottompartkeep 4px remainingquantity
        min_h = self._content_line_h + 4
        target = max(target, min_h)
        current_h = self.content_label.height()
        if abs(target - current_h) > 1:
            self.content_label.setFixedHeight(target)
    
    def append_content(self, text: str):
        """appendcontent (streamingscenehighfrequencycall, needshigheffect) 
        
        ★ incrementalrenderstrategy (inspired by markstream-vue) : 
        1. textappendto _pending_text
        2. Check whether there is a completed paragraph (double-newline separation / code-block close)
        3. completedparagraphfreezeas RichText Widget, notagainchangemove
        4. notcomplete tailpartkeepin QPlainTextEdit inresumereceive delta
        """
        # ★ fix: notdiscardpackagecontainingswaprowsymbol  chunk
        # pureswaprowsymbol (\n\n) is Markdown paragraphpartinterval keysignal, 
        # discarditswillcausesmultisegmentcontentpasteconnectinonestart
        if not text.strip() and '\n' not in text:
            return
        # clearremove U+FFFD replaceswapsymbol (encoding exceptionresidualkeep) 
        if '\ufffd' in text:
            text = text.replace('\ufffd', '')
        self._content += text
        self._pending_text += text

        # tryfreezecompleted paragraph
        if self._incremental_enabled:
            self._try_freeze_completed()

            # When the pending buffer contains an unfinished table, start the delayed-freeze timer;
            # if new rows keep arriving, keep resetting; freezes 600ms after table growth stops
            if self._in_table:
                self._table_flush_timer.start()
            else:
                self._table_flush_timer.stop()

        # updateactiveareashow (onlyshownotfreeze text) 
        self.content_label.setPlainText(self._pending_text)
        self._apply_line_spacing(160)
        cursor = self.content_label.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.content_label.setTextCursor(cursor)

    _TABLE_SEP_RE_FREEZE = re.compile(r'^\|?\s*[-:]+[-| :]*$')

    def _try_freeze_completed(self):
        """detectandfreezecompleted paragraph

        detectrule: 
        - codeblock: ``` openstart → ``` close, closemergeafterwholecodeblockfreeze
        - textparagraph: twoconsecutiveswaprow (\\n\\n) partinterval textparagraphfreeze
        - tablegrid: tablehead + partintervalrow + datarow, tablegridafteroutnownottablegridrowi.e.freezewholesegment
        """
        text = self._pending_text
        if not text:
            return

        lines = text.split('\n')
        freeze_up_to = -1
        i = 0
        in_fence = self._in_code_fence
        in_table = self._in_table

        while i < len(lines):
            stripped = lines[i].strip()

            # --- Code fence ---
            if in_fence:
                if stripped.startswith('```'):
                    in_fence = False
                    freeze_up_to = i + 1
                i += 1
                continue

            if stripped.startswith('```'):
                if in_table:
                    in_table = False
                in_fence = True
                self._code_fence_lang = stripped[3:].strip()
                freeze_up_to = i
                i += 1
                continue

            # --- Table state machine ---
            if in_table:
                if stripped and '|' in stripped:
                    i += 1
                    continue
                in_table = False
                freeze_up_to = i
                i += 1
                continue

            # detecttablegridstart: currentrowcontaining | andbelowonerowispartintervalrow
            if (stripped and '|' in stripped
                    and i + 1 < len(lines)
                    and self._TABLE_SEP_RE_FREEZE.match(lines[i + 1].strip())):
                in_table = True
                i += 1
                continue

            # --- emptyrow = paragraphedgeboundary ---
            if not stripped:
                if i > 0 and freeze_up_to < i:
                    start_scan = max(0, freeze_up_to + 1 if freeze_up_to >= 0 else 0)
                    if any(lines[j].strip() for j in range(start_scan, i)):
                        freeze_up_to = i
            i += 1

        self._in_code_fence = in_fence
        self._in_table = in_table

        if freeze_up_to > 0 and not in_fence:
            frozen_text = '\n'.join(lines[:freeze_up_to])
            remaining_text = '\n'.join(lines[freeze_up_to:])

            if frozen_text.strip():
                self._freeze_text(frozen_text)

            self._pending_text = remaining_text

    def _flush_pending_table(self):
        """fixedwhen trigger: tablegridstopaddlongafterwill pending inpackagecontainingtablegrid contentallpartfreeze"""
        if not self._pending_text or not self._in_table:
            return
        if not self._pending_text.strip():
            return
        self._freeze_text(self._pending_text)
        self._pending_text = ""
        self._in_table = False
        self.content_label.setPlainText("")

    def _freeze_text(self, text: str):
        """willonesegmenttextfreezeasrichtext Widget"""
        # use SimpleMarkdown parse
        segments = SimpleMarkdown.parse_segments(text)

        for seg in segments:
            if seg[0] == 'text':
                lbl = QtWidgets.QLabel()
                lbl.setWordWrap(True)
                lbl.setTextFormat(QtCore.Qt.RichText)
                lbl.setOpenExternalLinks(False)
                lbl.setTextInteractionFlags(
                    QtCore.Qt.TextSelectableByMouse
                    | QtCore.Qt.LinksAccessibleByMouse
                )
                lbl.setText(seg[1])
                lbl.setObjectName("richText")
                lbl.linkActivated.connect(self._on_link_activated)
                self._frozen_layout.addWidget(lbl)
            elif seg[0] == 'code':
                cb = CodeBlockWidget(seg[2], seg[1], self)
                cb.createWrangleRequested.connect(self.createWrangleRequested.emit)
                # codeblockwithpreviousafterparagraphofbetweenneedsextrabetweendistance
                cb.setContentsMargins(0, 6, 0, 6)
                self._frozen_layout.addWidget(cb)
            elif seg[0] == 'image':
                img_lbl = QtWidgets.QLabel()
                img_lbl.setObjectName("richImage")
                img_lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
                img_lbl.setText(
                    f'<div style="margin:4px 0;">'
                    f'<img src="{html.escape(seg[1])}" '
                    f'style="max-width:100%;max-height:300px;border-radius:6px;">'
                    f'</div>'
                )
                img_lbl.setTextFormat(QtCore.Qt.RichText)
                self._frozen_layout.addWidget(img_lbl)

        # showfreezecontain 
        if not self._frozen_container.isVisible():
            self._frozen_container.setVisible(True)
        self._frozen_segments.append(text)
    
    def set_content(self, text: str):
        """setcontent (onceproperty, notstreamingscene, such ashistoryrestore) 
        
        ★ directlyrenderasrichtext, avoidhistoryrestorewhenalsooutnowjumpchange. 
        """
        self._content = text
        self._pending_text = ""
        self._incremental_enabled = False
        
        content = self._clean_content(text)
        if not content:
            self.content_label.setPlainText("")
            return
        
        # Render directly as a rich-text Widget; preserves a consistent look
        self.content_label.setVisible(False)
        self._freeze_text(content)
    
    @staticmethod
    def _clean_content(text: str) -> str:
        """cleanupcontentin multiremainingemptywhite (onlyin finalize whencallonce) """
        if not text:
            return ""
        import re
        cleaned = re.sub(r'\n{3,}', '\n\n', text)
        return cleaned.strip()
    
    def add_collapsible(self, title: str, content: str) -> CollapsibleSection:
        """addcancollapsecontent"""
        section = CollapsibleSection(title, collapsed=True, parent=self)
        section.add_text(content, "muted")
        self.details_layout.addWidget(section)
        return section
    
    def _copy_content(self):
        """Copy the full reply content to the clipboard."""
        content = self._clean_content(self._content)
        if content:
            QtWidgets.QApplication.clipboard().setText(content)
            # Temporary feedback
            self._copy_btn.setText(tr('btn.copied'))
            self._copy_btn.setProperty("state", "copied")
            self._copy_btn.style().unpolish(self._copy_btn)
            self._copy_btn.style().polish(self._copy_btn)
            QtCore.QTimer.singleShot(1500, self._reset_copy_btn)
    
    def _reset_copy_btn(self):
        """restorecopybuttonstyle"""
        try:
            self._copy_btn.setText(tr('btn.copy'))
            self._copy_btn.setProperty("state", "")
            self._copy_btn.style().unpolish(self._copy_btn)
            self._copy_btn.style().polish(self._copy_btn)
        except RuntimeError:
            pass  # widget alreadydestroy
    
    def start_aurora(self):
        """startleft sidestreamlightedgeboxmovedraw"""
        self.aurora_bar.start()

    def stop_aurora(self):
        """stopleft sidestreamlightedgeboxmovedraw"""
        self.aurora_bar.stop()

    def finalize(self):
        """completereply - extractfinalsummary
        
        Under incremental-render mode, most chunks have already been frozen as Widgets,
        finalize onlyneedsprocesslast  _pending_text tailpartresidualkeep. 
        """
        self.aurora_bar.stop()
        self._table_flush_timer.stop()
        
        elapsed = time.time() - self._start_time
        
        if self._has_thinking:
            self.thinking_section.finalize()
        
        # completeexecutesectionblock
        if self._has_execution:
            self.execution_section.finalize()
        
        # updatestate
        parts = []
        if self._has_thinking:
            parts.append(tr('status.thinking'))
        if self._has_execution:
            tool_count = len(self.execution_section._tool_calls)
            parts.append(tr('status.calls', tool_count))
        
        status_text = tr('status.done', _fmt_duration(elapsed))
        if parts:
            status_text += f" | {', '.join(parts)}"
        
        self.status_label.setText(status_text)
        
        # hascontentwhenshowcopybutton
        if self._clean_content(self._content):
            self._copy_btn.setVisible(True)
        
        # ★ incrementalrender finalize: processlastresidualremaining  pending_text
        content = self._clean_content(self._content)
        
        if not content:
            if self._has_execution:
                self.content_label.setPlainText(tr('status.exec_done_see_above'))
            else:
                self.content_label.setPlainText(tr('status.no_reply'))
            self.content_label.setProperty("state", "empty")
            self.content_label.style().unpolish(self.content_label)
            self.content_label.style().polish(self.content_label)
        elif self._frozen_segments:
            # incrementalmode: alreadyhasfreezeparagraph, onlyneedsprocess pending tailpart
            remaining = self._clean_content(self._pending_text)
            if remaining:
                # ★ alwayswillresidualremainingtextfreezeasrichtext, avoid finalize when jumpchange
                self._freeze_text(remaining)
                self.content_label.setVisible(False)
            else:
                # nothasresidualremainingtext, hide QPlainTextEdit
                self.content_label.setVisible(False)
        else:
            # passstatsmode (nofreezeparagraph) —— alwaysrenderasrichtextbykeepconsistentproperty
            self.content_label.setVisible(False)
            self._freeze_text(content)
    
    def _on_link_activated(self, url: str):
        """Handle link click - houdini:// jumps to a node; http(s):// opens in the system browser."""
        if url.startswith('houdini://'):
            node_path = url[len('houdini://'):]
            self.nodePathClicked.emit(node_path)
        elif url.startswith(('http://', 'https://')):
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))


# ============================================================
# concisestaterow
# ============================================================

class StatusLine(QtWidgets.QLabel):
    """concisestaterow"""
    
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("statusLine")
        self.setWordWrap(True)


# ============================================================
# nodeoperationlabel
# ============================================================

class NodeOperationLabel(QtWidgets.QWidget):
    """nodeoperationlabel - show +1 node / -2 nodes, with undo/keep button"""
    
    nodeClicked = QtCore.Signal(str)      # sendnode path (clicknodenamejump) 
    undoRequested = QtCore.Signal()       # requestundothisoperation
    decided = QtCore.Signal()             # undo or keep completeafternotify (used forupdatebatchoperationbar) 
    
    # _BTN_STYLE removed — use objectName-based QSS instead
    
    def __init__(self, operation: str, count: int, node_paths: list = None, 
                 detail_text: str = None, param_diff: dict = None, parent=None):
        """
        Args:
            operation: 'create' | 'delete' | 'modify'
            count: operation node/parametercount
            node_paths: node pathlist
            detail_text: simpletextdetails (oldway, puretext)
            param_diff: parameter diff info {"param_name": str, "old_value": Any, "new_value": Any}
        """
        super().__init__(parent)
        self._node_paths = node_paths or []
        self._decided = False  # userwhetheralreadydooutselect
        
        # ifhas param_diff, useverticallayout (titlerow + diff area) 
        # otherwiseuseoriginalcome horizontallayout
        if param_diff and operation == 'modify':
            self._init_modify_layout(operation, count, param_diff)
            return
        
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(4)
        
        if operation == 'create':
            prefix = "+"
            color = CursorTheme.ACCENT_GREEN
        elif operation == 'modify':
            prefix = "~"
            color = CursorTheme.ACCENT_YELLOW
        else:
            prefix = "-"
            color = CursorTheme.ACCENT_RED
        
        if operation == 'modify':
            plural = "params" if count > 1 else "param"
        else:
            plural = "nodes" if count > 1 else "node"
        count_text = f"{prefix}{count} {plural}"
        
        count_label = QtWidgets.QLabel(count_text)
        count_label.setObjectName("nodeOpCount")
        count_label.setProperty("op", operation)
        count_label.style().unpolish(count_label)
        count_label.style().polish(count_label)
        layout.addWidget(count_label)
        
        # eachnodenameascanclickbutton
        display_paths = self._node_paths[:5]
        for path in display_paths:
            short_name = path.rsplit('/', 1)[-1] if '/' in path else path
            btn = QtWidgets.QPushButton(short_name)
            btn.setFlat(True)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.setToolTip(tr('node.click_jump', path))
            btn.setObjectName("nodePathBtn")
            btn.clicked.connect(lambda checked=False, p=path: self.nodeClicked.emit(p))
            layout.addWidget(btn)
        
        if len(self._node_paths) > 5:
            more = QtWidgets.QLabel(f"+{len(self._node_paths) - 5} more")
            more.setObjectName("nodeOpMore")
            layout.addWidget(more)
        
        # simpletextdetails (onlyinnothas param_diff whenuse) 
        if detail_text:
            detail_label = QtWidgets.QLabel(detail_text)
            detail_label.setObjectName("nodeOpDetail")
            detail_label.setToolTip(detail_text)
            layout.addWidget(detail_label)
        
        layout.addStretch()
        
        # ── Undo / Keep button ──
        self._undo_btn = QtWidgets.QPushButton(tr('btn.undo'))
        self._undo_btn.setFixedHeight(20)
        self._undo_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._undo_btn.setObjectName("btnUndoOp")
        self._undo_btn.clicked.connect(self._on_undo)
        layout.addWidget(self._undo_btn)
        
        self._keep_btn = QtWidgets.QPushButton(tr('btn.keep'))
        self._keep_btn.setFixedHeight(20)
        self._keep_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._keep_btn.setObjectName("btnKeepOp")
        self._keep_btn.clicked.connect(self._on_keep)
        layout.addWidget(self._keep_btn)
        
        # decidefixedafter statelabel (replacement forbutton) 
        self._status_label = QtWidgets.QLabel()
        self._status_label.setObjectName("nodeOpStatus")
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)
    
    def _init_modify_layout(self, operation: str, count: int, param_diff: dict):
        """modify operation dedicateduselayout: titlerow(yellowlabel+nodename+undo/keep) + diff expandshowsection"""
        self._decided = False
        
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 2)
        root.setSpacing(2)
        
        # ── firstrow: label + nodename + undo/keep ──
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(4)
        
        color = CursorTheme.ACCENT_YELLOW
        plural = "params" if count > 1 else "param"
        count_label = QtWidgets.QLabel(f"~{count} {plural}")
        count_label.setObjectName("nodeOpCount")
        count_label.setProperty("op", "modify")
        count_label.style().unpolish(count_label)
        count_label.style().polish(count_label)
        header.addWidget(count_label)
        
        for path in self._node_paths[:3]:
            short_name = path.rsplit('/', 1)[-1] if '/' in path else path
            btn = QtWidgets.QPushButton(short_name)
            btn.setFlat(True)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.setToolTip(tr('node.click_jump', path))
            btn.setObjectName("nodePathBtn")
            btn.clicked.connect(lambda checked=False, p=path: self.nodeClicked.emit(p))
            header.addWidget(btn)
        
        header.addStretch()
        
        self._undo_btn = QtWidgets.QPushButton(tr('btn.undo'))
        self._undo_btn.setFixedHeight(20)
        self._undo_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._undo_btn.setObjectName("btnUndoOp")
        self._undo_btn.clicked.connect(self._on_undo)
        header.addWidget(self._undo_btn)
        
        self._keep_btn = QtWidgets.QPushButton(tr('btn.keep'))
        self._keep_btn.setFixedHeight(20)
        self._keep_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._keep_btn.setObjectName("btnKeepOp")
        self._keep_btn.clicked.connect(self._on_keep)
        header.addWidget(self._keep_btn)
        
        self._status_label = QtWidgets.QLabel()
        self._status_label.setObjectName("nodeOpStatus")
        self._status_label.setVisible(False)
        header.addWidget(self._status_label)
        
        root.addLayout(header)
        
        # ── secondrow: Diff expandshow ──
        self._diff_widget = ParamDiffWidget(
            param_name=param_diff.get("param_name", ""),
            old_value=param_diff.get("old_value", ""),
            new_value=param_diff.get("new_value", ""),
        )
        root.addWidget(self._diff_widget)
    
    def collapse_diff(self):
        """collapse diff expandshowsection (Keep All whencall) """
        if hasattr(self, '_diff_widget') and self._diff_widget:
            self._diff_widget.collapse()
    
    def _on_undo(self):
        if self._decided:
            return
        self._decided = True
        self._undo_btn.setVisible(False)
        self._keep_btn.setVisible(False)
        self._status_label.setText(tr('status.undone'))
        self._status_label.setProperty("state", "undone")
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)
        self._status_label.setVisible(True)
        self.undoRequested.emit()
        self.decided.emit()
    
    def _on_keep(self):
        if self._decided:
            return
        self._decided = True
        self._undo_btn.setVisible(False)
        self._keep_btn.setVisible(False)
        self._status_label.setText(tr('status.kept'))
        self._status_label.setVisible(True)
        self.decided.emit()


# ============================================================
# streamingcodepreviewcomponent (Streaming VEX Apply) 
# ============================================================

class StreamingCodePreview(QtWidgets.QWidget):
    """streamingcodepreview — like Cursor Apply onelikeone by onerowshow AI positiveinwrite code
    
    While the tool_call parameter is streaming in, show the VEX code being written in real time.
    toolexecutefinishfinishafter, by ai_tab willitsreplaceswapaspositivestyle  ParamDiffWidget. 
    """

    def __init__(self, tool_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("streamingCodePreview")
        self._tool_name = tool_name

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(0)

        # titlerow
        self._title = QtWidgets.QLabel("✍ Writing code...")
        self._title.setObjectName("streamingCodeTitle")
        layout.addWidget(self._title)

        # codeshowsection (read-only, fixfixedmaxheight, autoscroll) 
        self._code_area = QtWidgets.QPlainTextEdit()
        self._code_area.setReadOnly(True)
        self._code_area.setObjectName("streamingCodeArea")
        self._code_area.setMaximumHeight(200)
        self._code_area.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        layout.addWidget(self._code_area)

        # recordontimealreadyshow codelength, onlyappendincremental
        self._last_len = 0

    def update_code(self, full_code: str):
        """usecompletecodestringupdateshow (incrementalappendnewpartpart) """
        if len(full_code) > self._last_len:
            delta = full_code[self._last_len:]
            self._last_len = len(full_code)
            self._code_area.moveCursor(QtGui.QTextCursor.End)
            self._code_area.insertPlainText(delta)
            # autoscrolltobottompart
            sb = self._code_area.verticalScrollBar()
            sb.setValue(sb.maximum())

    def finalize(self):
        """streamingend, updatetitle"""
        self._title.setText("✓ Code complete")
        self._title.setProperty("state", "done")
        self._title.style().unpolish(self._title)
        self._title.style().polish(self._title)


# ============================================================
# parameter Diff expandshowcomponent
# ============================================================

class ParamDiffWidget(QtWidgets.QWidget):
    """parameterchange Diff expandshow — oldvalueredbox / newvaluegreenbox
    
    - Scalar/short text: inline display as [old_value] -> [new_value]
    - multirowtext(VEXetc.): expandstyle diff, redcolorbackgrounddeleterow, greencolorbackgroundnewaddrow
    """
    
    # diff color
    _RED_BG = "#3d1f1f"       # deleterowbackground
    _RED_BORDER = "#6e3030"   # deleterowedgebox
    _RED_TEXT = "#f48771"     # deleterowtext
    _GREEN_BG = "#1f3d1f"     # newaddrowbackground
    _GREEN_BORDER = "#2e6e30" # newaddrowedgebox
    _GREEN_TEXT = "#89d185"   # newaddrowtext
    _GREY_TEXT = "#64748b"    # contextrowtext
    
    # Row-level shared style (compact, no gaps - like one full code block)
    _LINE_BASE = (
        "font-size: 11px; font-family: {font}; "
        "margin: 0px; padding: 0px 6px; "
        "border: none; border-radius: 0px; "
        "min-height: 16px; max-height: 16px;"
    )

    def __init__(self, param_name: str, old_value, new_value, parent=None):
        super().__init__(parent)
        self._collapsed = True  # ★ defaultcollapse (exposeoutpreviewwindow) 
        
        old_str = self._to_str(old_value)
        new_str = self._to_str(new_value)
        is_multiline = ('\n' in old_str or '\n' in new_str
                        or len(old_str) > 60 or len(new_str) > 60)
        
        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(0, 2, 0, 2)
        root_layout.setSpacing(0)
        
        if is_multiline:
            # ── multirow diff (VEX etc.) ──
            # titlerow: param_name ▶  (defaultcollapse, exposeoutpreviewwindow) 
            self._title_text = param_name
            self._toggle_btn = QtWidgets.QPushButton(f"▶ {param_name}")
            self._toggle_btn.setFlat(True)
            self._toggle_btn.setCursor(QtCore.Qt.PointingHandCursor)
            self._toggle_btn.setObjectName("diffToggle")
            self._toggle_btn.clicked.connect(self._toggle)
            root_layout.addWidget(self._toggle_btn)
            
            # diff contentsection (use QScrollArea packagewrap, collapsewhenexposeoutpreviewwindow) 
            self._diff_frame = QtWidgets.QFrame()
            self._diff_frame.setObjectName("diffFrame")
            diff_layout = QtWidgets.QVBoxLayout(self._diff_frame)
            diff_layout.setContentsMargins(0, 2, 0, 2)
            diff_layout.setSpacing(0)
            
            _font = CursorTheme.FONT_CODE
            
            # use difflib computerowlevel diff
            import difflib
            old_lines = old_str.splitlines(keepends=True)
            new_lines = new_str.splitlines(keepends=True)
            diff = list(difflib.unified_diff(old_lines, new_lines, n=2))
            
            # skip --- / +++ headtworow, fetchrealboundary diff row
            diff_body = diff[2:] if len(diff) > 2 else []
            
            if not diff_body:
                # nothasrealboundarydifference (or difflib nomethodprocess) → andarrangeshow
                self._add_block(diff_layout, tr('diff.old'), old_str, is_old=True)
                self._add_block(diff_layout, tr('diff.new'), new_str, is_old=False)
            else:
                for line in diff_body:
                    line_stripped = line.rstrip('\n')
                    lbl = QtWidgets.QLabel(line_stripped)
                    lbl.setObjectName("diffLine")
                    if line.startswith('@@'):
                        lbl.setProperty("diffType", "hunk")
                    elif line.startswith('-'):
                        lbl.setProperty("diffType", "del")
                    elif line.startswith('+'):
                        lbl.setProperty("diffType", "add")
                    else:
                        lbl.setProperty("diffType", "ctx")
                    diff_layout.addWidget(lbl)
            
            # ★ use QScrollArea packagewrap diff_frame, collapsewhenlimitheightandnofinishallhide
            self._scroll_area = QtWidgets.QScrollArea()
            self._scroll_area.setObjectName("diffScrollArea")
            self._scroll_area.setWidgetResizable(True)
            self._scroll_area.setFrameShape(QtWidgets.QFrame.NoFrame)
            self._scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
            self._scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
            self._scroll_area.setWidget(self._diff_frame)
            
            # previewheightconstant
            self._PREVIEW_HEIGHT = 120   # collapsewhenexposeout height(px)
            
            root_layout.addWidget(self._scroll_area)
            self._scroll_area.setMaximumHeight(self._PREVIEW_HEIGHT)  # defaultcollapse, exposeoutpreviewwindow
        else:
            # ── withinassociate diff (markerquantity) ──
            inline = QtWidgets.QHBoxLayout()
            inline.setContentsMargins(0, 0, 0, 0)
            inline.setSpacing(4)
            
            # parametername
            name_lbl = QtWidgets.QLabel(f"{param_name}:")
            name_lbl.setObjectName("diffParamName")
            inline.addWidget(name_lbl)
            
            # oldvalue (redbox)
            old_lbl = QtWidgets.QLabel(self._truncate(old_str, 30))
            old_lbl.setToolTip(f"{tr('diff.old')}: {old_str}")
            old_lbl.setObjectName("diffOldValue")
            inline.addWidget(old_lbl)
            
            # Arrow
            arrow = QtWidgets.QLabel("→")
            arrow.setObjectName("diffArrow")
            inline.addWidget(arrow)
            
            # newvalue (greenbox)
            new_lbl = QtWidgets.QLabel(self._truncate(new_str, 30))
            new_lbl.setToolTip(f"{tr('diff.new')}: {new_str}")
            new_lbl.setObjectName("diffNewValue")
            inline.addWidget(new_lbl)
            
            root_layout.addLayout(inline)
    
    def _toggle(self):
        self._collapsed = not self._collapsed
        if self._collapsed:
            # collapse → limitheight, exposeoutpreviewwindow
            self._scroll_area.setMaximumHeight(self._PREVIEW_HEIGHT)
        else:
            # expand → cancelheightlimit
            self._scroll_area.setMaximumHeight(16777215)
        arrow = "▶" if self._collapsed else "▼"
        self._toggle_btn.setText(f"{arrow} {self._title_text}")
    
    def collapse(self):
        """externalcall: forcecollapse diff (onlyformultirow diff valid) """
        if hasattr(self, '_scroll_area') and not self._collapsed:
            self._collapsed = True
            self._scroll_area.setMaximumHeight(self._PREVIEW_HEIGHT)
            self._toggle_btn.setText(f"▶ {self._title_text}")
    
    def _add_block(self, parent_layout, title: str, text: str, is_old: bool):
        """addoldvalue/newvaluewholeblock (used for difflib nodifferencewhen  fallback) """
        diff_type = "del" if is_old else "add"
        header = QtWidgets.QLabel(title)
        header.setObjectName("diffLine")
        header.setProperty("diffType", "hunk")
        parent_layout.addWidget(header)
        for line in text.splitlines():
            lbl = QtWidgets.QLabel(line)
            lbl.setObjectName("diffLine")
            lbl.setProperty("diffType", diff_type)
            parent_layout.addWidget(lbl)
    
    @staticmethod
    def _to_str(value) -> str:
        if isinstance(value, dict) and "expr" in value:
            return str(value["expr"])
        if isinstance(value, (list, tuple)):
            return ', '.join(str(v) for v in value)
        return str(value)
    
    @staticmethod
    def _truncate(s: str, max_len: int) -> str:
        return s if len(s) <= max_len else s[:max_len - 1] + "…"


# ============================================================
# cancollapsecontentblock (compatible witholdcode) 
# ============================================================

class CollapsibleContent(QtWidgets.QWidget):
    """cancollapsecontent - clicktitleexpand/collectstart"""
    
    def __init__(self, title: str, content: str = "", parent=None):
        super().__init__(parent)
        self._collapsed = True
        self._title = title
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(0)
        
        self.title_btn = QtWidgets.QPushButton(f"▶ {title}")
        self.title_btn.setFlat(True)
        self.title_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.title_btn.clicked.connect(self.toggle)
        self.title_btn.setObjectName("collapseContentTitle")
        layout.addWidget(self.title_btn)
        
        self.content_label = QtWidgets.QLabel(content)
        self.content_label.setWordWrap(True)
        self.content_label.setObjectName("collapseContentLabel")
        self.content_label.setVisible(False)
        layout.addWidget(self.content_label)
    
    def toggle(self):
        self._collapsed = not self._collapsed
        self.content_label.setVisible(not self._collapsed)
        arrow = "▶" if self._collapsed else "▼"
        self.title_btn.setText(f"{arrow} {self._title}")
    
    def set_content(self, content: str):
        self.content_label.setText(content)
    
    def expand(self):
        if self._collapsed:
            self.toggle()


# ============================================================
# countplanblock (compatible witholdcode) 
# ============================================================

class PlanBlock(QtWidgets.QWidget):
    """executecountplanshow"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._steps = []
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(2)
        
        self.title = QtWidgets.QLabel("Plan")
        self.title.setObjectName("planTitle")
        layout.addWidget(self.title)
        
        self.steps_layout = QtWidgets.QVBoxLayout()
        self.steps_layout.setSpacing(1)
        layout.addLayout(self.steps_layout)
    
    def add_step(self, text: str, status: str = "pending") -> QtWidgets.QLabel:
        icons = {"pending": "○", "running": "◎", "done": "●", "error": "✗"}
        
        label = QtWidgets.QLabel(f"{icons[status]} {text}")
        label.setObjectName("planStep")
        label.setProperty("state", status)
        label.style().unpolish(label)
        label.style().polish(label)
        self.steps_layout.addWidget(label)
        self._steps.append((label, text))
        return label
    
    def update_step(self, index: int, status: str):
        if 0 <= index < len(self._steps):
            label, text = self._steps[index]
            icons = {"pending": "○", "running": "◎", "done": "●", "error": "✗"}
            label.setText(f"{icons[status]} {text}")
            label.setProperty("state", status)
            label.style().unpolish(label)
            label.style().polish(label)


# ============================================================
# PlanDAGWidget — QPainter selfdraw DAG flowdiagram
# ============================================================

class PlanDAGWidget(QtWidgets.QWidget):
    """Houdini nodenetworkarchitecturebluediagram, use QPainter selfdraw. 

    expandshow Plan executecompleteafter  **nodenetworktopology** (setcountbluediagram) , 
    andnoexecutesteporderorder. 

    specialproperty: 
    - Color by node type (SOP=blue, OBJ=orange, MAT=green, etc.)
    - groupcontain  (terrainsystem, scattersystem etc.) 
    - newnode vs alreadyhasnode visualsectionpart
    - Bezier curve connections + arrowheads
    - autopartlayerlayout
    - Wrapped in a QScrollArea; horizontal scroll when the window is narrow
    """

    # nodetype → (fillfillcolor, edgeboxcolor, textcolor)
    _TYPE_COLORS = {
        "sop":    ("#0d1f3c", "#4a9eff", "#a3d4ff"),
        "obj":    ("#2d1f0d", "#e8a838", "#ffe0a0"),
        "mat":    ("#0d2d1a", "#34d399", "#6ee7b7"),
        "vop":    ("#1f0d2d", "#a78bfa", "#c4b5fd"),
        "rop":    ("#2d0d1a", "#f472b6", "#f9a8d4"),
        "dop":    ("#0d2d2d", "#22d3ee", "#67e8f9"),
        "lop":    ("#1a2d0d", "#a3e635", "#d9f99d"),
        "cop":    ("#2d2d0d", "#facc15", "#fef08a"),
        "chop":   ("#1f2d0d", "#84cc16", "#bef264"),
        "out":    ("#2d1215", "#f87171", "#fca5a5"),
        "subnet": ("#1a1a2e", "#818cf8", "#c7d2fe"),
        "null":   ("#1a1a1a", "#6b7280", "#9ca3af"),
        "other":  ("#1e2030", "#4a5068", "#8892a8"),
    }

    # Existing-node dimming factor
    _EXISTING_ALPHA = 0.5

    NODE_W = 160
    NODE_H = 42
    H_GAP = 50       # layerbetweendistance (horizontal, connectlinearea) 
    V_GAP = 20       # samelayernodebetweendistance (vertical) 
    PAD = 30          # Canvas inner padding
    GROUP_PAD = 16    # groupcontain withinedgedistance
    GROUP_TITLE_H = 22  # grouptitleheight

    def __init__(self, arch_data: dict = None, parent=None):
        """
        Args:
            arch_data: architecture fielddata, packagecontaining nodes, connections, groups
        """
        super().__init__(parent)
        self._arch = arch_data or {}
        self._nodes = self._arch.get("nodes", [])
        self._connections = self._arch.get("connections", [])
        self._groups = self._arch.get("groups", [])
        self._node_rects = {}      # node_id -> QRectF
        self._group_rects = {}     # group_name -> QRectF
        self._collapsed = True
        self.setObjectName("planDAG")
        self._content_w = 0
        self._content_h = 0
        self._layout_nodes()
        self._pulse_phase = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)   # ~25fps

    def _tick(self):
        self._pulse_phase = (self._pulse_phase + 0.04) % (math.pi * 2)
        # When the architecture diagram has new-node markers, give them a subtle pulse
        has_new = any(n.get("is_new", True) for n in self._nodes)
        if has_new:
            self.update()

    def set_collapsed(self, collapsed: bool):
        self._collapsed = collapsed
        if collapsed:
            self.setFixedHeight(0)
            self.setMinimumWidth(0)
        else:
            self._layout_nodes()
        self.update()

    def update_architecture(self, arch_data: dict):
        """updatearchitecturedataandrenewlayout"""
        self._arch = arch_data or {}
        self._nodes = self._arch.get("nodes", [])
        self._connections = self._arch.get("connections", [])
        self._groups = self._arch.get("groups", [])
        self._layout_nodes()
        self.update()

    # ----------------------------------------------------------
    # layoutcalculatemethod
    # ----------------------------------------------------------
    def _layout_nodes(self):
        """Sugiyama partlayerlayout: byconnecttopologyautopartlayerarrangecolumnnode. """
        if self._collapsed:
            self.setFixedHeight(0)
            self.setMinimumWidth(0)
            return
        if not self._nodes:
            self.setFixedHeight(0)
            self.setMinimumWidth(0)
            return

        node_map = {n["id"]: n for n in self._nodes}

        # ── 1) Build adjacency table ──
        children = {n["id"]: [] for n in self._nodes}      # from → [to, ...]
        parents = {n["id"]: [] for n in self._nodes}        # to   → [from, ...]
        for conn in self._connections:
            f, t = conn.get("from", ""), conn.get("to", "")
            if f in node_map and t in node_map:
                children[f].append(t)
                parents[t].append(f)

        # ── 2) computedepth (fromsourceheadstart BFS)  ──
        depths = {}
        def get_depth(nid, visited=None):
            if nid in depths:
                return depths[nid]
            if visited is None:
                visited = set()
            if nid in visited:  # Prevent cycles
                depths[nid] = 0
                return 0
            visited.add(nid)
            if not parents[nid]:
                depths[nid] = 0
                return 0
            d = max(get_depth(p, visited) for p in parents[nid]) + 1
            depths[nid] = d
            return d

        for n in self._nodes:
            get_depth(n["id"])

        # ── 3) partlayer ──
        layers = {}
        for nid, d in depths.items():
            layers.setdefault(d, []).append(nid)

        max_depth = max(layers.keys()) if layers else 0
        max_per_layer = max(len(v) for v in layers.values()) if layers else 1

        # verticaldirectionlayout (fromontobelow, moresymbolmerge Houdini nodenetworkhabit) 
        total_w = max_per_layer * (self.NODE_W + self.H_GAP) - self.H_GAP
        total_h = (max_depth + 1) * (self.NODE_H + self.V_GAP + 10) - self.V_GAP

        self._node_rects.clear()
        for depth, nids in layers.items():
            y = self.PAD + depth * (self.NODE_H + self.V_GAP + 10)
            layer_w = len(nids) * (self.NODE_W + self.H_GAP) - self.H_GAP
            start_x = self.PAD + (total_w - layer_w) / 2
            for i, nid in enumerate(nids):
                x = start_x + i * (self.NODE_W + self.H_GAP)
                self._node_rects[nid] = QtCore.QRectF(x, y, self.NODE_W, self.NODE_H)

        # ── 4) computegroupcontain  ──
        self._group_rects.clear()
        for grp in self._groups:
            grp_name = grp.get("name", "")
            grp_nids = [nid for nid in grp.get("node_ids", []) if nid in self._node_rects]
            if not grp_name or not grp_nids:
                continue
            rects = [self._node_rects[nid] for nid in grp_nids]
            gp = self.GROUP_PAD
            min_x = min(r.left() for r in rects) - gp
            min_y = min(r.top() for r in rects) - gp - self.GROUP_TITLE_H
            max_x = max(r.right() for r in rects) + gp
            max_y = max(r.bottom() for r in rects) + gp
            self._group_rects[grp_name] = (
                QtCore.QRectF(min_x, min_y, max_x - min_x, max_y - min_y),
                grp.get("color", ""),
            )

        # ── 5) finalsize ──
        all_rects = list(self._node_rects.values())
        all_rects += [r for r, _ in self._group_rects.values()]
        if all_rects:
            max_right = max(r.right() for r in all_rects)
            max_bottom = max(r.bottom() for r in all_rects)
            self._content_w = int(max_right + self.PAD)
            self._content_h = int(max_bottom + self.PAD)
        else:
            self._content_w = 200
            self._content_h = 80

        self.setMinimumWidth(self._content_w)
        self.setFixedHeight(self._content_h)

    # ----------------------------------------------------------
    # toolmethod
    # ----------------------------------------------------------
    def _elide_text(self, painter, text: str, max_width: int) -> str:
        """Truncate text by pixel width (supports CJK)."""
        fm = painter.fontMetrics()
        if fm.horizontalAdvance(text) <= max_width:
            return text
        for i in range(len(text), 0, -1):
            candidate = text[:i] + "…"
            if fm.horizontalAdvance(candidate) <= max_width:
                return candidate
        return "…"

    _GROUP_HINT_COLORS = {
        "blue":    (74, 158, 255),
        "green":   (52, 211, 153),
        "purple":  (167, 139, 250),
        "orange":  (232, 168, 56),
        "red":     (248, 113, 113),
        "cyan":    (34, 211, 238),
        "yellow":  (250, 204, 21),
        "pink":    (244, 114, 182),
    }

    # ----------------------------------------------------------
    # draw
    # ----------------------------------------------------------
    def paintEvent(self, event):
        if self._collapsed or not self._nodes:
            return

        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing)

        # ── 0) background ──
        bg_grad = QtGui.QLinearGradient(0, 0, self.width(), self.height())
        bg_grad.setColorAt(0.0, QtGui.QColor("#0d0f1a"))
        bg_grad.setColorAt(1.0, QtGui.QColor("#111420"))
        p.fillRect(self.rect(), bg_grad)

        # backgroundnetgridpoint
        grid_color = QtGui.QColor(100, 116, 139, 12)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(grid_color)
        for gx in range(0, self.width(), 20):
            for gy in range(0, self.height(), 20):
                p.drawEllipse(QtCore.QPointF(gx, gy), 0.5, 0.5)

        # ── 1) groupcontain  ──
        for grp_name, (grect, color_hint) in self._group_rects.items():
            r, g, b = self._GROUP_HINT_COLORS.get(color_hint, (167, 139, 250))
            # Semi-transparent fill
            p.setBrush(QtGui.QColor(r, g, b, 8))
            pen = QtGui.QPen(QtGui.QColor(r, g, b, 40), 1.0, QtCore.Qt.DashLine)
            p.setPen(pen)
            p.drawRoundedRect(grect, 10, 10)
            # title
            title_font = QtGui.QFont(CursorTheme.FONT_BODY.split(",")[0].strip("' "), 8)
            title_font.setWeight(QtGui.QFont.Medium)
            p.setFont(title_font)
            p.setPen(QtGui.QColor(r, g, b, 140))
            title_rect = QtCore.QRectF(grect.left() + 10, grect.top() + 3,
                                        grect.width() - 20, self.GROUP_TITLE_H - 4)
            p.drawText(title_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, grp_name)

        node_map = {n["id"]: n for n in self._nodes}

        # ── 2) Connections (Bezier curves) ──
        for conn in self._connections:
            src_id = conn.get("from", "")
            dst_id = conn.get("to", "")
            src_rect = self._node_rects.get(src_id)
            dst_rect = self._node_rects.get(dst_id)
            if not src_rect or not dst_rect:
                continue

            # connectlinecolor (fetchsourcenodetypecolor lightizationversion) 
            src_node = node_map.get(src_id, {})
            ntype = src_node.get("type", "other")
            _, border_c_hex, _ = self._TYPE_COLORS.get(ntype, self._TYPE_COLORS["other"])
            line_color = QtGui.QColor(border_c_hex)
            line_color.setAlpha(80)

            # fromsourcebottompartinpoint → targettoppartinpoint (verticallayout) 
            x1 = src_rect.center().x()
            y1 = src_rect.bottom()
            x2 = dst_rect.center().x()
            y2 = dst_rect.top()

            path = QtGui.QPainterPath()
            path.moveTo(x1, y1)
            ctrl_v = abs(y2 - y1) * 0.4
            if abs(x2 - x1) < 5:
                # purevertical
                path.cubicTo(x1, y1 + ctrl_v, x2, y2 - ctrl_v, x2, y2)
            else:
                # S shapecurve
                mid_y = (y1 + y2) / 2
                path.cubicTo(x1, mid_y, x2, mid_y, x2, y2)

            p.setPen(QtGui.QPen(line_color, 1.4))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawPath(path)

            # Arrow (towardbelow) 
            al = 6
            arr_angle = math.pi / 2
            arr_tip_x, arr_tip_y = x2, y2
            ax1 = arr_tip_x - al * math.cos(arr_angle - 0.4)
            ay1 = arr_tip_y - al * math.sin(arr_angle - 0.4)
            ax2 = arr_tip_x - al * math.cos(arr_angle + 0.4)
            ay2 = arr_tip_y - al * math.sin(arr_angle + 0.4)
            arrow = QtGui.QPolygonF([
                QtCore.QPointF(arr_tip_x, arr_tip_y),
                QtCore.QPointF(ax1, ay1),
                QtCore.QPointF(ax2, ay2),
            ])
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(line_color)
            p.drawPolygon(arrow)

            # connectlinelabel (ifhas) 
            conn_label = conn.get("label", "")
            if conn_label:
                lbl_font = QtGui.QFont(CursorTheme.FONT_BODY.split(",")[0].strip("' "), 7)
                p.setFont(lbl_font)
                lbl_color = QtGui.QColor(border_c_hex)
                lbl_color.setAlpha(100)
                p.setPen(lbl_color)
                mid_x = (x1 + x2) / 2
                mid_y_lbl = (y1 + y2) / 2
                p.drawText(QtCore.QPointF(mid_x + 4, mid_y_lbl), conn_label)

        # ── 3) node ──
        label_font = QtGui.QFont(CursorTheme.FONT_BODY.split(",")[0].strip("' "), 9)
        type_font = QtGui.QFont(CursorTheme.FONT_BODY.split(",")[0].strip("' "), 7)

        for n in self._nodes:
            nid = n["id"]
            rect = self._node_rects.get(nid)
            if not rect:
                continue

            ntype = n.get("type", "other")
            is_new = n.get("is_new", True)
            fill_c, border_c, text_c = self._TYPE_COLORS.get(ntype, self._TYPE_COLORS["other"])

            # New-node subtle pulse halo
            if is_new:
                pulse = 0.7 + 0.3 * math.sin(self._pulse_phase)
                glow_color = QtGui.QColor(border_c)
                glow_color.setAlpha(int(30 * pulse))
                glow_rect = rect.adjusted(-3, -3, 3, 3)
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(glow_color)
                p.drawRoundedRect(glow_rect, 10, 10)

            # nodebackground
            bg = QtGui.QColor(fill_c)
            alpha = 220 if is_new else int(220 * self._EXISTING_ALPHA)
            bg.setAlpha(alpha)
            p.setBrush(bg)

            # edgebox
            bc = QtGui.QColor(border_c)
            if not is_new:
                bc.setAlpha(int(255 * self._EXISTING_ALPHA))
            p.setPen(QtGui.QPen(bc, 1.5 if is_new else 1.0))
            p.drawRoundedRect(rect, 6, 6)

            # left sidetypecoloritem
            bar_w = 3
            bar_rect = QtCore.QRectF(rect.left() + 2, rect.top() + 4,
                                      bar_w, rect.height() - 8)
            p.setPen(QtCore.Qt.NoPen)
            bar_color = QtGui.QColor(border_c)
            if not is_new:
                bar_color.setAlpha(int(200 * self._EXISTING_ALPHA))
            p.setBrush(bar_color)
            p.drawRoundedRect(bar_rect, 1.5, 1.5)

            # onrow: nodelabel (label) 
            p.setFont(label_font)
            label_text = n.get("label", nid)
            label_text = self._elide_text(p, label_text, int(self.NODE_W - 20))
            tc = QtGui.QColor(text_c)
            if not is_new:
                tc.setAlpha(int(255 * self._EXISTING_ALPHA))
            p.setPen(tc)
            label_rect = QtCore.QRectF(rect.left() + 10, rect.top() + 3,
                                        rect.width() - 14, 20)
            p.drawText(label_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, label_text)

            # belowrow: type + nodename
            p.setFont(type_font)
            sub_text = f"{ntype.upper()}: {nid}"
            sub_text = self._elide_text(p, sub_text, int(self.NODE_W - 20))
            sub_color = QtGui.QColor(border_c)
            if not is_new:
                sub_color.setAlpha(int(180 * self._EXISTING_ALPHA))
            else:
                sub_color.setAlpha(180)
            p.setPen(sub_color)
            sub_rect = QtCore.QRectF(rect.left() + 10, rect.top() + 22,
                                      rect.width() - 14, 16)
            p.drawText(sub_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, sub_text)

            # Existing-node marker (overlaid with a dashed border)
            if not is_new:
                exist_pen = QtGui.QPen(QtGui.QColor(border_c), 0.8, QtCore.Qt.DotLine)
                exist_pen.setColor(QtGui.QColor(border_c).darker(150))
                p.setPen(exist_pen)
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 5, 5)

        p.end()


# ============================================================
# StreamingPlanCard - streaming Plan generation + final interactive card (two in one)
# ============================================================

class StreamingPlanCard(QtWidgets.QWidget):
    """streaming Plan card — generatestageone by onestepbuild, completeafteroriginalplaceupgradeascompletesubmitmutualcard. 

    Lifecycle:
    1. On creation, has only the title skeleton + STREAMING label
    2. on_tool_args_delta drives update_from_accumulated(), step by step rendering title -> overview -> step
    3. toolexecutefinishfinishafter, call finalize_with_data(plan_data) originalplacesupplementfill: 
       - stepdetails (sub_steps, tools, risk, deps, expected, fallback, notes) 
       - DAG architecturediagram
       - progressitem
       - Confirm / Reject button
    4. aftercontinue update_step_status / set_confirmed / set_rejected etc.methodwithold PlanViewer finishallcompatible with
    """

    planConfirmed = QtCore.Signal(dict)
    planRejected = QtCore.Signal()

    _STATUS_ICONS = {
        "pending": "○", "running": "◎", "done": "●", "error": "✗",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._plan = {}
        self._step_labels = {}   # step_id -> (icon_w, title_lbl)
        self._confirmed = False
        self._rejected = False
        self._finalized = False

        self.setObjectName("planViewerOuter")
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 6)
        outer.setSpacing(0)

        self._card = QtWidgets.QFrame(self)
        self._card.setObjectName("planViewerCard")
        self._card_lay = QtWidgets.QVBoxLayout(self._card)
        self._card_lay.setContentsMargins(14, 10, 14, 10)
        self._card_lay.setSpacing(6)

        # ── titlerow ──
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(8)
        icon_lbl = QtWidgets.QLabel("📋")
        icon_lbl.setFixedWidth(18)
        header.addWidget(icon_lbl)

        self._title_lbl = QtWidgets.QLabel("Planning...")
        self._title_lbl.setObjectName("planViewerTitle")
        self._title_lbl.setWordWrap(True)
        header.addWidget(self._title_lbl, 1)

        self._status_badge = QtWidgets.QLabel("STREAMING")
        self._status_badge.setObjectName("planStatusBadge")
        self._status_badge.setAlignment(QtCore.Qt.AlignCenter)
        self._status_badge.setFixedHeight(20)
        self._status_badge.setMinimumWidth(60)
        header.addWidget(self._status_badge)
        self._card_lay.addLayout(header)

        # ── overview ──
        self._overview_lbl = QtWidgets.QLabel("")
        self._overview_lbl.setObjectName("planOverview")
        self._overview_lbl.setWordWrap(True)
        self._overview_lbl.setVisible(False)
        self._card_lay.addWidget(self._overview_lbl)

        # ── partintervalline ──
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setObjectName("planSeparator")
        self._card_lay.addWidget(sep)

        # ── stepcontain  (streamingfillfill)  ──
        self._steps_container = QtWidgets.QWidget()
        self._steps_lay = QtWidgets.QVBoxLayout(self._steps_container)
        self._steps_lay.setContentsMargins(0, 0, 0, 0)
        self._steps_lay.setSpacing(2)
        self._card_lay.addWidget(self._steps_container)

        # ── positiveingeneraterefershow  ──
        self._loading_lbl = QtWidgets.QLabel("  ⋯ generating steps...")
        self._loading_lbl.setObjectName("planStepDep")
        self._card_lay.addWidget(self._loading_lbl)

        # ── or lessareain finalize_with_data whenmovestateadd ──
        # DAG, progressitem, button → pre-keep placeholder
        self._dag_widget = None
        self._dag_scroll = None
        self._dag_toggle = None
        self._progress_bar = None
        self._btn_row = None
        self._btn_confirm = None
        self._btn_reject = None

        outer.addWidget(self._card)

        # ── streamingtrackstate ──
        self._rendered_step_count = 0
        self._current_title = ""
        self._current_overview = ""

    # ==================================================================
    # Streaming-stage API - driven by on_tool_args_delta
    # ==================================================================

    def update_from_accumulated(self, accumulated: str):
        """from create_plan  notcomplete JSON inincrementalextractandrendercontent. """
        if self._finalized:
            return
        import re as _re

        # extract title
        m_title = _re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', accumulated)
        if m_title and m_title.group(1) != self._current_title:
            self._current_title = m_title.group(1)
            self._title_lbl.setText(self._current_title)

        # extract overview
        m_ov = _re.search(r'"overview"\s*:\s*"((?:[^"\\]|\\.)*)"', accumulated)
        if m_ov and m_ov.group(1) != self._current_overview:
            self._current_overview = m_ov.group(1)
            self._overview_lbl.setText(self._current_overview)
            self._overview_lbl.setVisible(True)

        # match steps countgroupin each step object
        steps_match = _re.search(r'"steps"\s*:\s*\[', accumulated)
        if not steps_match:
            return

        steps_json_start = steps_match.end()
        step_pattern = _re.compile(
            r'\{\s*"id"\s*:\s*"(step-\d+)"\s*,\s*'
            r'"(?:title|description)"\s*:\s*"((?:[^"\\]|\\.)*)"',
        )
        all_steps = list(step_pattern.finditer(accumulated, steps_json_start))

        # onlyrendernewoutnow  step
        for i in range(self._rendered_step_count, len(all_steps)):
            m = all_steps[i]
            self._add_streaming_step(m.group(1), m.group(2))
            self._rendered_step_count += 1

        # checkwhetherenter architecture partpart
        if '"architecture"' in accumulated:
            self._loading_lbl.setText("  ⋯ generating architecture...")

    def _add_streaming_step(self, step_id: str, text: str):
        """Streaming stage: add a single simplified-version step row."""
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        row.setContentsMargins(4, 2, 0, 0)

        icon_w = QtWidgets.QLabel("○")
        icon_w.setFixedWidth(14)
        icon_w.setObjectName("planStepIcon")
        icon_w.setProperty("state", "pending")
        row.addWidget(icon_w)

        sid_lbl = QtWidgets.QLabel(step_id)
        sid_lbl.setObjectName("planStepId")
        sid_lbl.setFixedWidth(50)
        row.addWidget(sid_lbl)

        title_lbl = QtWidgets.QLabel(text)
        title_lbl.setObjectName("planStepTitle")
        title_lbl.setWordWrap(True)
        row.addWidget(title_lbl, 1)

        w = QtWidgets.QWidget()
        w.setLayout(row)
        self._steps_lay.addWidget(w)

        # recordreferenceso that finalize whenupdate
        self._step_labels[step_id] = (icon_w, title_lbl)

    # ==================================================================
    # completestage API — toolexecuteendaftercall
    # ==================================================================

    def finalize_with_data(self, plan_data: dict):
        """usecomplete  plan_data originalplaceupgradecard — supplementfilldetails, DAG, progressitem, button. 

        This method is called only once. After the call, the card is functionally equivalent to the old PlanViewer.
        """
        if self._finalized:
            return
        self._finalized = True
        self._plan = plan_data

        # hideloadrefershow 
        self._loading_lbl.setVisible(False)

        # usecompletedataflushnewtitle + overview (overridestreamingstage maynotcompletecontent) 
        self._title_lbl.setText(plan_data.get("title", self._current_title or "Plan"))
        overview = plan_data.get("overview", "")
        if overview:
            self._overview_lbl.setText(overview)
            self._overview_lbl.setVisible(True)

        # ── clearemptystreamingstep, usecompletesteprebuild (containingdetails, deps etc.)  ──
        while self._steps_lay.count():
            item = self._steps_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._step_labels.clear()

        steps = plan_data.get("steps", [])
        phases = plan_data.get("phases", [])
        step_phase_map = {}
        for phase in phases:
            for sid in phase.get("step_ids", []):
                step_phase_map[sid] = phase.get("name", "")

        rendered_phases = set()
        for s in steps:
            step_id = s.get("id", "")

            # Phase title
            phase_name = step_phase_map.get(step_id, "")
            if phase_name and phase_name not in rendered_phases:
                rendered_phases.add(phase_name)
                phase_sep = QtWidgets.QFrame()
                phase_sep.setFrameShape(QtWidgets.QFrame.HLine)
                phase_sep.setObjectName("planPhaseSeparator")
                self._steps_lay.addWidget(phase_sep)
                phase_lbl = QtWidgets.QLabel(phase_name)
                phase_lbl.setObjectName("planPhaseHeader")
                self._steps_lay.addWidget(phase_lbl)

            # stepmainrow
            step_row = QtWidgets.QHBoxLayout()
            step_row.setSpacing(6)
            step_row.setContentsMargins(4, 2, 0, 0)

            status = s.get("status", "pending")
            icon_w = QtWidgets.QLabel(self._STATUS_ICONS.get(status, "○"))
            icon_w.setFixedWidth(14)
            icon_w.setObjectName("planStepIcon")
            icon_w.setProperty("state", status)
            step_row.addWidget(icon_w)

            sid_lbl = QtWidgets.QLabel(step_id)
            sid_lbl.setObjectName("planStepId")
            sid_lbl.setFixedWidth(50)
            step_row.addWidget(sid_lbl)

            title_text = s.get("title", s.get("description", ""))
            title_lbl = QtWidgets.QLabel(title_text)
            title_lbl.setObjectName("planStepTitle")
            title_lbl.setWordWrap(True)
            step_row.addWidget(title_lbl, 1)

            # Risk marker
            risk = s.get("risk", "")
            if risk and risk != "low":
                risk_lbl = QtWidgets.QLabel(f"⚠ {risk.upper()}")
                risk_lbl.setObjectName("planStepRisk")
                risk_lbl.setProperty("risk", risk)
                step_row.addWidget(risk_lbl)

            # depend onmark
            deps = s.get("depends_on", [])
            if deps:
                short_deps = [d.replace("step-", "s") for d in deps]
                dep_lbl = QtWidgets.QLabel(f"← {','.join(short_deps)}")
                dep_lbl.setObjectName("planStepDep")
                dep_lbl.setMaximumWidth(80)
                step_row.addWidget(dep_lbl)

            row_w = QtWidgets.QWidget()
            row_w.setLayout(step_row)
            self._steps_lay.addWidget(row_w)

            # stepdetails
            detail_w = QtWidgets.QWidget()
            detail_w.setObjectName("planStepDetail")
            detail_lay = QtWidgets.QVBoxLayout(detail_w)
            detail_lay.setContentsMargins(24, 0, 4, 4)
            detail_lay.setSpacing(2)

            for sub in s.get("sub_steps", []):
                lbl = QtWidgets.QLabel(f"  ├ {sub}")
                lbl.setObjectName("planSubStep")
                lbl.setWordWrap(True)
                detail_lay.addWidget(lbl)
            step_tools = s.get("tools", [])
            if step_tools:
                detail_lay.addWidget(QtWidgets.QLabel(f"Tools: {', '.join(step_tools)}"))
            expected = s.get("expected_result", "")
            if expected:
                lbl = QtWidgets.QLabel(f"Expected: {expected}")
                lbl.setObjectName("planStepExpected")
                lbl.setWordWrap(True)
                detail_lay.addWidget(lbl)
            fallback = s.get("fallback", "")
            if fallback:
                lbl = QtWidgets.QLabel(f"Fallback: {fallback}")
                lbl.setObjectName("planStepFallback")
                lbl.setWordWrap(True)
                detail_lay.addWidget(lbl)
            notes = s.get("notes", "")
            if notes:
                lbl = QtWidgets.QLabel(f"Note: {notes}")
                lbl.setObjectName("planStepNotes")
                lbl.setWordWrap(True)
                detail_lay.addWidget(lbl)

            if detail_lay.count() > 0:
                self._steps_lay.addWidget(detail_w)

            self._step_labels[step_id] = (icon_w, title_lbl)

        # ── DAG architecturediagram ──
        sep2 = QtWidgets.QFrame()
        sep2.setFrameShape(QtWidgets.QFrame.HLine)
        sep2.setObjectName("planSeparator")
        self._card_lay.addWidget(sep2)

        dag_header_row = QtWidgets.QHBoxLayout()
        arch_data = plan_data.get("architecture", {})
        has_real_arch = bool(arch_data and arch_data.get("nodes"))
        if not has_real_arch:
            arch_data = PlanViewer._build_step_dag(steps)

        dag_title = "Architecture" if has_real_arch else "Flow"
        dag_label = QtWidgets.QLabel(dag_title)
        dag_label.setObjectName("planSectionHeader")
        dag_header_row.addWidget(dag_label)
        dag_header_row.addStretch()

        self._dag_toggle = QtWidgets.QPushButton("▾ Collapse")
        self._dag_toggle.setObjectName("planDAGToggle")
        self._dag_toggle.setCursor(QtCore.Qt.PointingHandCursor)
        self._dag_toggle.setFixedHeight(20)
        self._dag_toggle.clicked.connect(self._toggle_dag)
        dag_header_row.addWidget(self._dag_toggle)
        self._card_lay.addLayout(dag_header_row)

        self._dag_widget = PlanDAGWidget(arch_data, self)
        self._dag_widget.set_collapsed(False)

        self._dag_scroll = QtWidgets.QScrollArea()
        self._dag_scroll.setObjectName("planDAGScroll")
        self._dag_scroll.setWidgetResizable(False)
        self._dag_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._dag_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._dag_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._dag_scroll.setWidget(self._dag_widget)
        # ★ heightfinishallfollow DAG content, notsetonlimit, ensurearchitecturediagramcompleteshow
        h = self._dag_widget._content_h
        scrollbar_h = 14  # horizontaltowardscrollitemheightpre-keep
        self._dag_scroll.setFixedHeight((h + scrollbar_h) if h > 0 else 200)
        self._card_lay.addWidget(self._dag_scroll)

        # ── progressitem ──
        self._progress_bar = QtWidgets.QProgressBar()
        self._progress_bar.setObjectName("planProgress")
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, max(len(steps), 1))
        self._progress_bar.setValue(0)
        self._card_lay.addWidget(self._progress_bar)

        # ── Confirm / Reject button ──
        self._btn_row = QtWidgets.QWidget()
        btn_lay = QtWidgets.QHBoxLayout(self._btn_row)
        btn_lay.setContentsMargins(0, 4, 0, 0)
        btn_lay.setSpacing(8)
        btn_lay.addStretch()

        self._btn_reject = QtWidgets.QPushButton("Reject")
        self._btn_reject.setObjectName("planBtnReject")
        self._btn_reject.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_reject.setFixedHeight(28)
        self._btn_reject.setMinimumWidth(80)
        self._btn_reject.clicked.connect(self._do_reject)
        btn_lay.addWidget(self._btn_reject)

        self._btn_confirm = QtWidgets.QPushButton("Confirm")
        self._btn_confirm.setObjectName("planBtnConfirm")
        self._btn_confirm.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_confirm.setFixedHeight(28)
        self._btn_confirm.setMinimumWidth(80)
        self._btn_confirm.clicked.connect(self._do_confirm)
        btn_lay.addWidget(self._btn_confirm)

        self._card_lay.addWidget(self._btn_row)

        # flushnewstate
        self._refresh_ui()

    # ==================================================================
    # PlanViewer compatible with API — finalize aftercandirectlyuse
    # ==================================================================

    def set_confirmed(self):
        self._confirmed = True
        self._plan["status"] = "confirmed"
        if self._btn_confirm:
            self._btn_confirm.setEnabled(False)
            self._btn_reject.setEnabled(False)
            self._btn_confirm.setText("✓ Confirmed")
        self._refresh_ui()

    def set_rejected(self):
        self._rejected = True
        self._plan["status"] = "rejected"
        if self._btn_confirm:
            self._btn_confirm.setEnabled(False)
            self._btn_reject.setEnabled(False)
            self._btn_reject.setText("✗ Rejected")
        self._refresh_ui()

    def update_step_status(self, step_id: str, status: str, result_summary: str = ""):
        for s in self._plan.get("steps", []):
            if s["id"] == step_id:
                s["status"] = status
                if result_summary:
                    s["result_summary"] = result_summary
                break
        if step_id in self._step_labels:
            icon_w, _ = self._step_labels[step_id]
            icon_w.setText(self._STATUS_ICONS.get(status, "○"))
            icon_w.setProperty("state", status)
            icon_w.style().unpolish(icon_w)
            icon_w.style().polish(icon_w)
        if self._progress_bar:
            self._update_progress()
        all_done = all(
            s.get("status") in ("done", "error")
            for s in self._plan.get("steps", [])
        )
        if all_done:
            self._plan["status"] = "completed"
            self._refresh_ui()

    def get_plan_data(self) -> dict:
        return self._plan

    # ==================================================================
    # withinpartmethod
    # ==================================================================

    def _do_confirm(self):
        if self._confirmed or self._rejected:
            return
        self.set_confirmed()
        self.planConfirmed.emit(dict(self._plan))

    def _do_reject(self):
        if self._confirmed or self._rejected:
            return
        self.set_rejected()
        self.planRejected.emit()

    def _toggle_dag(self):
        if not self._dag_widget:
            return
        collapsed = not self._dag_widget._collapsed
        self._dag_widget.set_collapsed(collapsed)
        self._dag_toggle.setText("▸ Expand" if collapsed else "▾ Collapse")
        if collapsed:
            self._dag_scroll.setFixedHeight(0)
        else:
            # ★ heightfinishallfollow DAG content, notsetonlimit
            h = self._dag_widget._content_h
            scrollbar_h = 14
            self._dag_scroll.setFixedHeight((h + scrollbar_h) if h > 0 else 200)

    def _update_progress(self):
        if not self._progress_bar:
            return
        steps = self._plan.get("steps", [])
        done = sum(1 for s in steps if s.get("status") == "done")
        self._progress_bar.setValue(done)

    def _refresh_ui(self):
        status = self._plan.get("status", "draft")
        badge_map = {
            "draft":     ("DRAFT",     "#64748b"),
            "confirmed": ("CONFIRMED", "#a78bfa"),
            "executing": ("EXECUTING", "#3b82f6"),
            "completed": ("COMPLETED", "#10b981"),
            "rejected":  ("REJECTED",  "#ef4444"),
        }
        text, color = badge_map.get(status, ("DRAFT", "#64748b"))
        self._status_badge.setText(text)
        self._status_badge.setStyleSheet(
            f"color: {color}; background: rgba(0,0,0,0.3); "
            f"border: 1px solid {color}; border-radius: 4px; "
            f"font-size: 10px; padding: 1px 8px; font-weight: bold;"
        )
        if self._btn_row:
            show = status == "draft" and not self._confirmed and not self._rejected
            self._btn_row.setVisible(show)
        if self._progress_bar:
            self._update_progress()


# ============================================================
# PlanViewer — Plan modesubmitmutualcard (embedchatstream) 
# ============================================================

class PlanViewer(QtWidgets.QWidget):
    """Plan executecountplansubmitmutualcard. 

    inchatstreaminrenderascancollapse card, packagecontaining: 
    - title + state
    - overview
    - steplist (containingstateicon) 
    - DAG flowdiagram (canexpand/collectstart) 
    - progressitem
    - Confirm / Reject button (onlyin awaiting_confirmation statecansee) 
    """

    planConfirmed = QtCore.Signal(dict)   # Emits plan_data
    planRejected = QtCore.Signal()

    _STATUS_ICONS = {
        "pending":  "○",
        "running":  "◎",
        "done":     "●",
        "error":    "✗",
    }

    def __init__(self, plan_data: dict, parent=None):
        super().__init__(parent)
        self._plan = plan_data
        self._step_labels = {}  # step_id -> QLabel
        self._confirmed = False
        self._rejected = False

        self.setObjectName("planViewerOuter")
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 6)
        outer.setSpacing(0)

        # ── cardcontain  ──
        self._card = QtWidgets.QFrame(self)
        self._card.setObjectName("planViewerCard")
        card_lay = QtWidgets.QVBoxLayout(self._card)
        card_lay.setContentsMargins(14, 10, 14, 10)
        card_lay.setSpacing(6)

        # ── titlerow ──
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(8)

        icon_lbl = QtWidgets.QLabel("📋")
        icon_lbl.setFixedWidth(18)
        header.addWidget(icon_lbl)

        self._title_lbl = QtWidgets.QLabel(plan_data.get("title", "Plan"))
        self._title_lbl.setObjectName("planViewerTitle")
        self._title_lbl.setWordWrap(True)
        header.addWidget(self._title_lbl, 1)

        self._status_badge = QtWidgets.QLabel("DRAFT")
        self._status_badge.setObjectName("planStatusBadge")
        self._status_badge.setAlignment(QtCore.Qt.AlignCenter)
        self._status_badge.setFixedHeight(20)
        self._status_badge.setMinimumWidth(60)
        header.addWidget(self._status_badge)

        card_lay.addLayout(header)

        # ── overview ──
        overview = plan_data.get("overview", "")
        if overview:
            ov_lbl = QtWidgets.QLabel(overview)
            ov_lbl.setObjectName("planOverview")
            ov_lbl.setWordWrap(True)
            card_lay.addWidget(ov_lbl)

        # ── complexdegree & pre-estimateoperationcount ──
        complexity = plan_data.get("complexity", "")
        est_ops = plan_data.get("estimated_total_operations", 0)
        if complexity or est_ops:
            meta_parts = []
            if complexity:
                meta_parts.append(f"Complexity: {complexity.upper()}")
            if est_ops:
                meta_parts.append(f"Est. Operations: {est_ops}")
            meta_lbl = QtWidgets.QLabel("  |  ".join(meta_parts))
            meta_lbl.setObjectName("planMetaInfo")
            card_lay.addWidget(meta_lbl)

        # ── partintervalline ──
        sep1 = QtWidgets.QFrame()
        sep1.setFrameShape(QtWidgets.QFrame.HLine)
        sep1.setObjectName("planSeparator")
        card_lay.addWidget(sep1)

        # ── steplist (addstrongversion: support phases group + substep + details) ──
        steps = plan_data.get("steps", [])
        phases = plan_data.get("phases", [])

        # build step_id → phase mapping
        step_phase_map = {}
        for phase in phases:
            for sid in phase.get("step_ids", []):
                step_phase_map[sid] = phase.get("name", "")

        rendered_phases = set()
        for s in steps:
            step_id = s.get("id", "")

            # If this step belongs to a phase and the phase has not been rendered yet -> insert the phase title
            phase_name = step_phase_map.get(step_id, "")
            if phase_name and phase_name not in rendered_phases:
                rendered_phases.add(phase_name)
                phase_sep = QtWidgets.QFrame()
                phase_sep.setFrameShape(QtWidgets.QFrame.HLine)
                phase_sep.setObjectName("planPhaseSeparator")
                card_lay.addWidget(phase_sep)
                phase_lbl = QtWidgets.QLabel(phase_name)
                phase_lbl.setObjectName("planPhaseHeader")
                card_lay.addWidget(phase_lbl)

            # ── steptitlerow ──
            step_row = QtWidgets.QHBoxLayout()
            step_row.setSpacing(6)
            step_row.setContentsMargins(4, 2, 0, 0)

            status = s.get("status", "pending")
            icon = self._STATUS_ICONS.get(status, "○")

            icon_w = QtWidgets.QLabel(icon)
            icon_w.setFixedWidth(14)
            icon_w.setObjectName("planStepIcon")
            icon_w.setProperty("state", status)
            step_row.addWidget(icon_w)

            sid_lbl = QtWidgets.QLabel(step_id)
            sid_lbl.setObjectName("planStepId")
            sid_lbl.setFixedWidth(50)
            step_row.addWidget(sid_lbl)

            # use title assteplistshowtext, description putindetailsin
            title_text = s.get("title", s.get("description", ""))
            title_lbl = QtWidgets.QLabel(title_text)
            title_lbl.setObjectName("planStepTitle")
            title_lbl.setWordWrap(True)
            step_row.addWidget(title_lbl, 1)

            # Risk marker
            risk = s.get("risk", "")
            if risk and risk != "low":
                risk_lbl = QtWidgets.QLabel(f"⚠ {risk.upper()}")
                risk_lbl.setObjectName("planStepRisk")
                risk_lbl.setProperty("risk", risk)
                step_row.addWidget(risk_lbl)

            # depend onmark (compactformat) 
            deps = s.get("depends_on", [])
            if deps:
                # Shorten "step-1" to "s1" to save space
                short_deps = [d.replace("step-", "s") for d in deps]
                dep_lbl = QtWidgets.QLabel(f"← {','.join(short_deps)}")
                dep_lbl.setObjectName("planStepDep")
                dep_lbl.setMaximumWidth(80)
                step_row.addWidget(dep_lbl)

            row_w = QtWidgets.QWidget()
            row_w.setLayout(step_row)
            card_lay.addWidget(row_w)

            # ── stepdetailsarea (sub_steps + tools + expected + fallback) ──
            detail_w = QtWidgets.QWidget()
            detail_w.setObjectName("planStepDetail")
            detail_lay = QtWidgets.QVBoxLayout(detail_w)
            detail_lay.setContentsMargins(24, 0, 4, 4)
            detail_lay.setSpacing(2)

            # substep
            sub_steps = s.get("sub_steps", [])
            for sub in sub_steps:
                sub_lbl = QtWidgets.QLabel(f"  ├ {sub}")
                sub_lbl.setObjectName("planSubStep")
                sub_lbl.setWordWrap(True)
                detail_lay.addWidget(sub_lbl)

            # toollist
            tools = s.get("tools", [])
            if tools:
                tools_lbl = QtWidgets.QLabel(f"Tools: {', '.join(tools)}")
                tools_lbl.setObjectName("planStepTools")
                detail_lay.addWidget(tools_lbl)

            # pre-periodresult
            expected = s.get("expected_result", "")
            if expected:
                exp_lbl = QtWidgets.QLabel(f"Expected: {expected}")
                exp_lbl.setObjectName("planStepExpected")
                exp_lbl.setWordWrap(True)
                detail_lay.addWidget(exp_lbl)

            # fall backstrategy
            fallback = s.get("fallback", "")
            if fallback:
                fb_lbl = QtWidgets.QLabel(f"Fallback: {fallback}")
                fb_lbl.setObjectName("planStepFallback")
                fb_lbl.setWordWrap(True)
                detail_lay.addWidget(fb_lbl)

            # Fallback note
            notes = s.get("notes", "")
            if notes:
                notes_lbl = QtWidgets.QLabel(f"Note: {notes}")
                notes_lbl.setObjectName("planStepNotes")
                notes_lbl.setWordWrap(True)
                detail_lay.addWidget(notes_lbl)

            if detail_lay.count() > 0:
                card_lay.addWidget(detail_w)

            self._step_labels[step_id] = (icon_w, title_lbl)

        # ── DAG flowdiagramarea ──
        sep2 = QtWidgets.QFrame()
        sep2.setFrameShape(QtWidgets.QFrame.HLine)
        sep2.setObjectName("planSeparator")
        card_lay.addWidget(sep2)

        dag_header_row = QtWidgets.QHBoxLayout()

        # based ondatatypedecidefixedtitle
        arch_data = plan_data.get("architecture", {})
        has_real_arch = bool(arch_data and arch_data.get("nodes"))

        if not has_real_arch:
            # ── fall back: from steps   depends_on autogeneratestepdepend ondiagram ──
            arch_data = self._build_step_dag(steps)

        dag_title = "Architecture" if has_real_arch else "Flow"
        dag_label = QtWidgets.QLabel(dag_title)
        dag_label.setObjectName("planSectionHeader")
        dag_header_row.addWidget(dag_label)
        dag_header_row.addStretch()

        self._dag_toggle = QtWidgets.QPushButton("▾ Collapse")
        self._dag_toggle.setObjectName("planDAGToggle")
        self._dag_toggle.setCursor(QtCore.Qt.PointingHandCursor)
        self._dag_toggle.setFixedHeight(20)
        self._dag_toggle.clicked.connect(self._toggle_dag)
        dag_header_row.addWidget(self._dag_toggle)
        card_lay.addLayout(dag_header_row)

        self._dag_widget = PlanDAGWidget(arch_data, self)
        self._dag_widget.set_collapsed(False)

        # Wrap the DAG in a QScrollArea; horizontal scroll appears automatically when the window is narrow
        self._dag_scroll = QtWidgets.QScrollArea()
        self._dag_scroll.setObjectName("planDAGScroll")
        self._dag_scroll.setWidgetResizable(False)  # keep DAG originalsize
        self._dag_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._dag_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._dag_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._dag_scroll.setWidget(self._dag_widget)
        # ★ heightfinishallfollow DAG content, notsetonlimit, ensurearchitecturediagramcompleteshow
        h = self._dag_widget._content_h
        scrollbar_h = 14  # horizontaltowardscrollitemheightpre-keep
        self._dag_scroll.setFixedHeight((h + scrollbar_h) if h > 0 else 200)
        card_lay.addWidget(self._dag_scroll)

        # ── progressitem ──
        self._progress_bar = QtWidgets.QProgressBar()
        self._progress_bar.setObjectName("planProgress")
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, max(len(steps), 1))
        self._progress_bar.setValue(0)
        card_lay.addWidget(self._progress_bar)

        # ── buttonrow ──
        self._btn_row = QtWidgets.QWidget()
        btn_lay = QtWidgets.QHBoxLayout(self._btn_row)
        btn_lay.setContentsMargins(0, 4, 0, 0)
        btn_lay.setSpacing(8)
        btn_lay.addStretch()

        self._btn_reject = QtWidgets.QPushButton("Reject")
        self._btn_reject.setObjectName("planBtnReject")
        self._btn_reject.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_reject.setFixedHeight(28)
        self._btn_reject.setMinimumWidth(80)
        self._btn_reject.clicked.connect(self._do_reject)
        btn_lay.addWidget(self._btn_reject)

        self._btn_confirm = QtWidgets.QPushButton("Confirm")
        self._btn_confirm.setObjectName("planBtnConfirm")
        self._btn_confirm.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_confirm.setFixedHeight(28)
        self._btn_confirm.setMinimumWidth(80)
        self._btn_confirm.clicked.connect(self._do_confirm)
        btn_lay.addWidget(self._btn_confirm)

        card_lay.addWidget(self._btn_row)

        outer.addWidget(self._card)
        self._refresh_ui()

    # ----------------------------------------------------------
    # Shared methods
    # ----------------------------------------------------------

    def set_confirmed(self):
        """confirmafterdisablebutton"""
        self._confirmed = True
        self._plan["status"] = "confirmed"
        self._btn_confirm.setEnabled(False)
        self._btn_reject.setEnabled(False)
        self._btn_confirm.setText("✓ Confirmed")
        self._refresh_ui()

    def set_rejected(self):
        """rejectafterdisablebutton"""
        self._rejected = True
        self._plan["status"] = "rejected"
        self._btn_confirm.setEnabled(False)
        self._btn_reject.setEnabled(False)
        self._btn_reject.setText("✗ Rejected")
        self._refresh_ui()

    def update_step_status(self, step_id: str, status: str, result_summary: str = ""):
        """realwhenupdatesomestep state (executestagecall) """
        # updatewithinpartdata
        for s in self._plan.get("steps", []):
            if s["id"] == step_id:
                s["status"] = status
                if result_summary:
                    s["result_summary"] = result_summary
                break

        # updatesteplist UI
        if step_id in self._step_labels:
            icon_w, desc_lbl = self._step_labels[step_id]
            icon = self._STATUS_ICONS.get(status, "○")
            icon_w.setText(icon)
            icon_w.setProperty("state", status)
            icon_w.style().unpolish(icon_w)
            icon_w.style().polish(icon_w)

        # Architecture diagram is a static blueprint; step-state changes do not need to update it
        # self._dag_widget expandshow isfinalnodenetworktopology

        # updateprogressitem
        self._update_progress()

        # checkwhetherallpartcomplete
        all_done = all(
            s.get("status") in ("done", "error")
            for s in self._plan.get("steps", [])
        )
        if all_done:
            self._plan["status"] = "completed"
            self._refresh_ui()

    def get_plan_data(self) -> dict:
        return self._plan

    # ----------------------------------------------------------
    # withinpartmethod
    # ----------------------------------------------------------

    def _do_confirm(self):
        if self._confirmed or self._rejected:
            return
        self.set_confirmed()
        self.planConfirmed.emit(dict(self._plan))

    def _do_reject(self):
        if self._confirmed or self._rejected:
            return
        self.set_rejected()
        self.planRejected.emit()

    @staticmethod
    def _build_step_dag(steps: list) -> dict:
        """from steps   depends_on relationautobuildstepdepend on DAG data. 

        when plan nothas architecture fieldwhenasfall backapproach, 
        willsteplistconvertswapas PlanDAGWidget canaccept  architecture format. 
        """
        nodes = []
        connections = []

        # collectsetall depends_on relation
        has_any_deps = any(s.get("depends_on") for s in steps)

        for s in steps:
            sid = s.get("id", "")
            title = s.get("title", s.get("description", sid))
            # cutfetchprevious 20 characteras label
            label = title[:20] + ("…" if len(title) > 20 else "")
            nodes.append({
                "id": sid,
                "label": label,
                "type": "sop",   # defaulttype
                "is_new": True,
                "params": ", ".join(s.get("tools", [])[:2]) if s.get("tools") else "",
            })

            # depend onrelation → connectline
            for dep_id in (s.get("depends_on") or []):
                connections.append({"from": dep_id, "to": sid})

        # nothasdepend onrelationwhen, autogeneratelinepropertychain
        if not has_any_deps and len(steps) > 1:
            for i in range(len(steps) - 1):
                connections.append({
                    "from": steps[i]["id"],
                    "to": steps[i + 1]["id"],
                })

        # Try to build from phases (if any - usually not reached here, but kept for compatibility)
        return {
            "nodes": nodes,
            "connections": connections,
            "groups": [],
        }

    def _toggle_dag(self):
        collapsed = not self._dag_widget._collapsed
        self._dag_widget.set_collapsed(collapsed)
        self._dag_toggle.setText("▸ Expand" if collapsed else "▾ Collapse")
        # ★ syncscrollareaheight
        if collapsed:
            self._dag_scroll.setFixedHeight(0)
        else:
            # DAG contentheight + scrollitemmayoccupyuse emptybetween
            h = self._dag_widget._content_h
            scrollbar_h = 14  # horizontaltowardscrollitemheightpre-keep
            self._dag_scroll.setFixedHeight(h + scrollbar_h)
            self._dag_scroll.setMinimumHeight(h)

    def _update_progress(self):
        steps = self._plan.get("steps", [])
        done = sum(1 for s in steps if s.get("status") == "done")
        self._progress_bar.setValue(done)

    def _refresh_ui(self):
        status = self._plan.get("status", "draft")
        badge_map = {
            "draft":     ("DRAFT",     "#64748b"),
            "confirmed": ("CONFIRMED", "#a78bfa"),
            "executing": ("EXECUTING", "#3b82f6"),
            "completed": ("COMPLETED", "#10b981"),
            "rejected":  ("REJECTED",  "#ef4444"),
        }
        text, color = badge_map.get(status, ("DRAFT", "#64748b"))
        self._status_badge.setText(text)
        self._status_badge.setStyleSheet(
            f"color: {color}; background: rgba(0,0,0,0.3); "
            f"border: 1px solid {color}; border-radius: 4px; "
            f"font-size: 10px; padding: 1px 8px; font-weight: bold;"
        )
        # buttoncanseeproperty
        show_buttons = status in ("draft", "confirmed") and not self._confirmed and not self._rejected
        self._btn_row.setVisible(show_buttons and status == "draft")
        self._update_progress()


# ============================================================
# AskQuestionCard — AI mainmoveasksubmitmutualcard (Plan ruleplanstage) 
# ============================================================

class AskQuestionCard(QtWidgets.QFrame):
    """embedchatstreamin  AI askcard. 

    When the AI needs to clarify info during the Plan planning stage, it sends a question via the ask_question tool.
    userviasingleselect/multiselect/selfbytextanswerafter, clickraisesubmitbutton. 
    Answers are returned to the background thread via the answered signal.

    questions structureexample:
        [
            {
                "id": "q1",
                "prompt": "Do you want to use HeightField or Grid?",
                "options": [
                    {"id": "hf", "label": "HeightField (recommended)"},
                    {"id": "grid", "label": "Grid"}
                ],
                "allow_multiple": false,
                "allow_free_text": true
            }
        ]
    """

    answered = QtCore.Signal(dict)    # Emits the answer dict: {q_id: [selected_option_ids], ...}
    cancelled = QtCore.Signal()       # usercancel

    def __init__(self, questions: list, parent=None):
        super().__init__(parent)
        self._questions = questions
        self._answered = False
        self._widgets = {}  # q_id -> {"buttons": [...], "group": QButtonGroup, "free_text": QLineEdit}

        self.setObjectName("askQuestionCard")
        self.setFrameShape(QtWidgets.QFrame.NoFrame)

        main_lay = QtWidgets.QVBoxLayout(self)
        main_lay.setContentsMargins(14, 10, 14, 10)
        main_lay.setSpacing(8)

        # ── title ──
        title_row = QtWidgets.QHBoxLayout()
        title_row.setSpacing(6)
        icon_lbl = QtWidgets.QLabel("❓")
        icon_lbl.setFixedWidth(18)
        title_row.addWidget(icon_lbl)
        title_lbl = QtWidgets.QLabel("AI needs your input to proceed")
        title_lbl.setObjectName("askQuestionTitle")
        title_lbl.setWordWrap(True)
        title_row.addWidget(title_lbl, 1)
        main_lay.addLayout(title_row)

        # ── eachissue ──
        for q in questions:
            q_id = q.get("id", "")
            prompt = q.get("prompt", "")
            options = q.get("options", [])
            allow_multiple = q.get("allow_multiple", False)
            allow_free_text = q.get("allow_free_text", False)

            # issuepartintervalline
            sep = QtWidgets.QFrame()
            sep.setFrameShape(QtWidgets.QFrame.HLine)
            sep.setObjectName("askQuestionSep")
            main_lay.addWidget(sep)

            # issuetext
            q_lbl = QtWidgets.QLabel(f"{q_id.upper()}: {prompt}")
            q_lbl.setObjectName("askQuestionPrompt")
            q_lbl.setWordWrap(True)
            main_lay.addWidget(q_lbl)

            # selectitem
            btn_group = None
            buttons = []
            if not allow_multiple:
                btn_group = QtWidgets.QButtonGroup(self)
                btn_group.setExclusive(True)

            for opt in options:
                opt_id = opt.get("id", "")
                opt_label = opt.get("label", "")
                if allow_multiple:
                    btn = QtWidgets.QCheckBox(opt_label)
                else:
                    btn = QtWidgets.QRadioButton(opt_label)
                    btn_group.addButton(btn)
                btn.setObjectName("askQuestionOption")
                btn.setProperty("opt_id", opt_id)
                main_lay.addWidget(btn)
                buttons.append(btn)

            # selfbytextinput
            free_text = None
            if allow_free_text:
                free_text = QtWidgets.QLineEdit()
                free_text.setObjectName("askQuestionFreeText")
                free_text.setPlaceholderText("Or type your answer here...")
                main_lay.addWidget(free_text)

            self._widgets[q_id] = {
                "buttons": buttons,
                "group": btn_group,
                "free_text": free_text,
                "allow_multiple": allow_multiple,
            }

        # ── buttonrow ──
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setContentsMargins(0, 6, 0, 0)
        btn_row.addStretch()

        self._btn_cancel = QtWidgets.QPushButton("Skip")
        self._btn_cancel.setObjectName("askQuestionBtnCancel")
        self._btn_cancel.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_cancel.setFixedHeight(28)
        self._btn_cancel.setMinimumWidth(60)
        self._btn_cancel.clicked.connect(self._do_cancel)
        btn_row.addWidget(self._btn_cancel)

        self._btn_submit = QtWidgets.QPushButton("Submit Answer")
        self._btn_submit.setObjectName("askQuestionBtnSubmit")
        self._btn_submit.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_submit.setFixedHeight(28)
        self._btn_submit.setMinimumWidth(100)
        self._btn_submit.clicked.connect(self._do_submit)
        btn_row.addWidget(self._btn_submit)

        main_lay.addLayout(btn_row)

    def _collect_answers(self) -> dict:
        """collectsetuser answer"""
        answers = {}
        for q_id, w_info in self._widgets.items():
            selected = []
            for btn in w_info["buttons"]:
                if btn.isChecked():
                    selected.append(btn.property("opt_id"))
            # selfbytext
            free_text = w_info.get("free_text")
            if free_text and free_text.text().strip():
                selected.append(f"__free_text__:{free_text.text().strip()}")
            answers[q_id] = selected
        return answers

    def _do_submit(self):
        if self._answered:
            return
        self._answered = True
        answers = self._collect_answers()
        self._btn_submit.setEnabled(False)
        self._btn_cancel.setEnabled(False)
        self._btn_submit.setText("✓ Submitted")
        self.answered.emit(answers)

    def _do_cancel(self):
        if self._answered:
            return
        self._answered = True
        self._btn_submit.setEnabled(False)
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.setText("Skipped")
        self.cancelled.emit()


# ============================================================
# Markdown parser (specialized version)
# ============================================================

class SimpleMarkdown:
    """will Markdown convertswapas Qt Rich Text HTML (addstrongversion) 

    supportspecialproperty: 
    - title (# ~ ####)
    - Bold / italic / strikethrough / inline code
    - noorderlist / hasorderlist / tasklist / nestedlist
    - referenceblock (multirowmerge, supportgradualchangebackground) 
    - Tables (center / left-align / right-align)
    - Horizontal rule
    - link [text](url) / auto URL detect
    - image ![alt](url)
    - footnote [^id] / [^id]: ...
    - convertmeaningcharacter \\* \\` etc.
    - Fenced code blocks (handed to CodeBlockWidget)
    """

    _CODE_BLOCK_RE = re.compile(r'```(\w*)\n(.*?)```', re.DOTALL)
    _TABLE_SEP_RE = re.compile(r'^\|?\s*[-:]+[-| :]*$')  # Table header separator row
    # autodetectbare URL
    _AUTO_URL_RE = re.compile(
        r'(?<!["\w/=])(?<!\]\()(?<!\[)'       # Not preceded by quote, word char, =, ](, or [
        r'(https?://[^\s<>\)\]\"\'`]+)'        # URL thisbody
    )
    # footnotereference
    _FOOTNOTE_REF_RE = re.compile(r'\[\^(\w+)\](?!:)')
    # footnotefixedmeaning
    _FOOTNOTE_DEF_RE = re.compile(r'^\[\^(\w+)\]:\s*(.*)')
    # imagesyntax
    _IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
    # listindentationdetect
    _LIST_ITEM_RE = re.compile(r'^(\s*)([-*]|\d+\.)\s+(.*)')
    # tasklist
    _TASK_ITEM_RE = re.compile(r'^(\s*)[-*]\s+\[([ xX])\]\s+(.*)')

    # -------- Public interface --------

    @classmethod
    def parse_segments(cls, text: str) -> list:
        """willtextsplitas ('text', html), ('code', lang, raw_code), ('image', url, alt) paragraph"""
        segments: list = []
        last = 0
        for m in cls._CODE_BLOCK_RE.finditer(text):
            before = text[last:m.start()]
            if before.strip():
                cls._parse_text_with_images(before, segments)
            segments.append(('code', m.group(1) or '', m.group(2).rstrip()))
            last = m.end()
        after = text[last:]
        if after.strip():
            cls._parse_text_with_images(after, segments)
        if not segments and text.strip():
            cls._parse_text_with_images(text, segments)
        return segments

    @classmethod
    def _parse_text_with_images(cls, text: str, segments: list):
        """willtextparagraphenteronestepsplitoutindependentstand  image segment
        
        onlyhasindependentoccupyonerow  ![alt](url) only thenasindependentstand image segment, 
        rowwithin imagesyntaxstillbyrowwithinformatprocess. 
        """
        lines = text.split('\n')
        buf_lines: list = []

        def _flush_buf():
            if buf_lines:
                joined = '\n'.join(buf_lines)
                if joined.strip():
                    segments.append(('text', cls._text_to_html(joined)))
                buf_lines.clear()

        for line in lines:
            stripped = line.strip()
            img_match = cls._IMAGE_RE.fullmatch(stripped)
            if img_match:
                _flush_buf()
                segments.append(('image', img_match.group(2), img_match.group(1)))
            else:
                buf_lines.append(line)
        _flush_buf()

    @classmethod
    def has_rich_content(cls, text: str) -> bool:
        """decidebreaktextwhetherpackagecontaining Markdown format"""
        if '```' in text:
            return True
        if re.search(r'^#{1,4}\s', text, re.MULTILINE):
            return True
        if '**' in text or '`' in text:
            return True
        if re.search(r'^[-*]\s', text, re.MULTILINE):
            return True
        if re.search(r'^\d+\.\s', text, re.MULTILINE):
            return True
        if '|' in text and re.search(r'^\|.+\|', text, re.MULTILINE):
            return True
        if cls._IMAGE_RE.search(text):
            return True
        if cls._FOOTNOTE_REF_RE.search(text):
            return True
        return False

    # -------- blocklevelparse --------

    @classmethod
    def _get_indent(cls, line: str) -> int:
        """returnrow indentationemptygridcount"""
        return len(line) - len(line.lstrip())

    @classmethod
    def _text_to_html(cls, text: str) -> str:
        lines = text.split('\n')
        out: list = []
        i = 0
        n = len(lines)

        # Nested-list state stack: [(tag, indent_level), ...]
        list_stack: list = []
        # referenceblockbuffer
        quote_buf: list = []
        # footnotefixedmeaningcollectset
        footnotes: dict = {}

        # firstall: collectsetfootnotefixedmeaning
        remaining_lines: list = []
        for line in lines:
            fn_match = cls._FOOTNOTE_DEF_RE.match(line.strip())
            if fn_match:
                footnotes[fn_match.group(1)] = fn_match.group(2)
            else:
                remaining_lines.append(line)
        lines = remaining_lines
        n = len(lines)

        def _flush_all_lists():
            while list_stack:
                _, ltag = list_stack.pop()
                out.append(f'</{ltag}>')

        def _flush_lists_to_indent(target_indent: int):
            """closeallindentationgreater than target_indent  listlayerlevel"""
            while list_stack and list_stack[-1][0] > target_indent:
                _, ltag = list_stack.pop()
                out.append(f'</{ltag}>')

        def _flush_quote():
            nonlocal quote_buf
            if quote_buf:
                q_html = '<br>'.join(cls._inline(q, footnotes) for q in quote_buf)
                out.append(
                    f'<div style="border-left:2px solid rgba(148,163,184,50);padding:8px 14px;'
                    f'margin:8px 0;'
                    f'background:transparent;'
                    f'color:#cbd5e1;border-radius:0 6px 6px 0;'
                    f'line-height:1.1;">{q_html}</div>'
                )
                quote_buf = []

        while i < n:
            raw_line = lines[i]
            s = raw_line.strip()

            # ---- empty line ----
            if not s:
                _flush_quote()
                _flush_all_lists()
                out.append('<div style="height:4px;"></div>')
                i += 1
                continue

            # ---- horizontal rule ----
            if re.match(r'^[-*_]{3,}\s*$', s):
                _flush_quote()
                _flush_all_lists()
                out.append(
                    '<hr style="border:none;border-top:1px solid rgba(255,255,255,8);margin:16px 0;width:100%;">'
                )
                i += 1
                continue

            # ---- table ----
            if '|' in s and i + 1 < n and cls._TABLE_SEP_RE.match(lines[i + 1].strip()):
                _flush_quote()
                _flush_all_lists()
                table_html = cls._parse_table(lines, i)
                if table_html:
                    out.append(table_html[0])
                    i = table_html[1]
                    continue

            # ---- headers ----
            header_match = re.match(r'^(#{1,4})\s+(.+)', s)
            if header_match:
                _flush_quote()
                _flush_all_lists()
                lvl = len(header_match.group(1))
                content = header_match.group(2)
                styles = {
                    1: ('1.5em', '#f1f5f9', '700', '18px 0 8px 0', 'border-bottom:1px solid rgba(255,255,255,12);padding-bottom:8px;letter-spacing:0.3px;'),
                    2: ('1.3em', '#e2e8f0', '600', '16px 0 6px 0', 'letter-spacing:0.2px;'),
                    3: ('1.1em', '#cbd5e1', '600', '12px 0 4px 0', ''),
                    4: ('1.0em', '#94a3b8', '600', '10px 0 3px 0', ''),
                }
                sz, clr, wt, mg, extra = styles[lvl]
                out.append(
                    f'<p style="font-size:{sz};font-weight:{wt};'
                    f'color:{clr};margin:{mg};{extra}">'
                    f'{cls._inline(content, footnotes)}</p>'
                )
                i += 1
                continue

            # ---- blockquote (mergeconsecutiverow) ----
            if s.startswith('> '):
                _flush_all_lists()
                quote_buf.append(s[2:])
                i += 1
                continue
            elif s.startswith('>'):
                _flush_all_lists()
                quote_buf.append(s[1:].lstrip())
                i += 1
                continue
            else:
                _flush_quote()

            # ---- task list (with nesting support) ----
            task_match = cls._TASK_ITEM_RE.match(raw_line)
            if task_match:
                indent = len(task_match.group(1))
                _flush_lists_to_indent(indent)
                if not list_stack or list_stack[-1][0] < indent:
                    out.append(
                        '<ul style="margin:2px 0;padding-left:4px;list-style:none;">'
                    )
                    list_stack.append((indent, 'ul'))
                checked = task_match.group(2) in ('x', 'X')
                box = (
                    '<span style="color:#10b981;font-weight:bold;margin-right:6px;">✓</span>'
                    if checked else
                    '<span style="color:#64748b;margin-right:6px;">○</span>'
                )
                text_style = 'color:#64748b;text-decoration:line-through;' if checked else ''
                out.append(
                    f'<li style="margin:4px 0;line-height:1.1;{text_style}">'
                    f'{box}{cls._inline(task_match.group(3), footnotes)}</li>'
                )
                i += 1
                continue

            # ---- unordered / ordered list (with nesting) ----
            list_match = cls._LIST_ITEM_RE.match(raw_line)
            if list_match:
                indent = len(list_match.group(1))
                marker = list_match.group(2)
                item_text = list_match.group(3)
                is_ordered = marker[-1] == '.'
                new_tag = 'ol' if is_ordered else 'ul'

                _flush_lists_to_indent(indent)

                if not list_stack or list_stack[-1][0] < indent:
                    # openstartnewnestedlayerlevel
                    if is_ordered:
                        out.append(
                            '<ol style="margin:4px 0;padding-left:22px;color:#94a3b8;">'
                        )
                    else:
                        out.append(
                            '<ul style="margin:4px 0;padding-left:22px;'
                            'list-style-type:disc;color:#94a3b8;">'
                        )
                    list_stack.append((indent, new_tag))
                elif list_stack[-1][1] != new_tag:
                    # samelayerlevelbuttypeswitch
                    old_indent, old_tag = list_stack.pop()
                    out.append(f'</{old_tag}>')
                    if is_ordered:
                        out.append(
                            '<ol style="margin:4px 0;padding-left:22px;color:#94a3b8;">'
                        )
                    else:
                        out.append(
                            '<ul style="margin:4px 0;padding-left:22px;'
                            'list-style-type:disc;color:#94a3b8;">'
                        )
                    list_stack.append((indent, new_tag))

                out.append(
                    f'<li style="margin:4px 0;line-height:1.1;color:{CursorTheme.TEXT_PRIMARY};">'
                    f'{cls._inline(item_text, footnotes)}</li>'
                )
                i += 1
                continue

            # ---- normal paragraph ----
            _flush_all_lists()
            out.append(
                f'<p style="margin:4px 0;line-height:1.1;color:#e2e8f0;">'
                f'{cls._inline(s, footnotes)}</p>'
            )
            i += 1

        _flush_quote()
        _flush_all_lists()

        # renderfootnotefixedmeaningarea (ifhas) 
        if footnotes:
            out.append(
                '<hr style="border:none;border-top:1px solid rgba(255,255,255,8);'
                'margin:12px 0 6px 0;width:40%;">'
            )
            for fn_id, fn_text in footnotes.items():
                out.append(
                    f'<p style="margin:2px 0;font-size:0.85em;color:{CursorTheme.TEXT_SECONDARY};'
                    f'line-height:1.4;">'
                    f'<sup style="color:#60a5fa;">[{html.escape(fn_id)}]</sup> '
                    f'{cls._inline(fn_text, footnotes)}</p>'
                )

        return '\n'.join(out)

    # -------- tablegridparse --------

    @classmethod
    def _parse_table(cls, lines: list, start: int) -> tuple:
        """parse Markdown tablegrid, return (html, next_line_index)"""
        header_line = lines[start].strip()
        if start + 1 >= len(lines):
            return None
        sep_line = lines[start + 1].strip()

        # parsealignway
        sep_cells = [c.strip() for c in sep_line.strip('|').split('|')]
        aligns = []
        for c in sep_cells:
            c = c.strip()
            if c.startswith(':') and c.endswith(':'):
                aligns.append('center')
            elif c.endswith(':'):
                aligns.append('right')
            else:
                aligns.append('left')

        def _parse_row(line: str) -> list:
            line = line.strip()
            if line.startswith('|'):
                line = line[1:]
            if line.endswith('|'):
                line = line[:-1]
            return [c.strip() for c in line.split('|')]

        # tablehead
        headers = _parse_row(header_line)

        # tablebody
        rows = []
        j = start + 2
        while j < len(lines):
            row_s = lines[j].strip()
            if not row_s or '|' not in row_s:
                break
            rows.append(_parse_row(row_s))
            j += 1

        # Generate HTML (very minimal: no outer border, no zebra stripes, only bottom-line separators)
        tbl = [
            '<table style="border-collapse:collapse;'
            'margin:10px 0;width:100%;font-size:0.92em;">'
        ]

        # thead
        tbl.append('<tr>')
        for ci, h in enumerate(headers):
            align = aligns[ci] if ci < len(aligns) else 'left'
            tbl.append(
                f'<th style="border-bottom:2px solid rgba(255,255,255,12);'
                f'padding:7px 14px;'
                f'background:transparent;color:#e2e8f0;font-weight:600;'
                f'text-align:{align};font-size:0.95em;">{cls._inline(h)}</th>'
            )
        tbl.append('</tr>')

        # tbody — statsonebackground, onlybottomlinepartinterval
        for ri, row in enumerate(rows):
            tbl.append('<tr>')
            for ci, cell in enumerate(row):
                align = aligns[ci] if ci < len(aligns) else 'left'
                border_bottom = (
                    'border-bottom:1px solid rgba(255,255,255,5);'
                    if ri < len(rows) - 1 else ''
                )
                tbl.append(
                    f'<td style="{border_bottom}padding:7px 14px;'
                    f'background:transparent;color:{CursorTheme.TEXT_PRIMARY};'
                    f'text-align:{align};line-height:1.5;">{cls._inline(cell)}</td>'
                )
            tbl.append('</tr>')

        tbl.append('</table>')
        return ('\n'.join(tbl), j)

    # -------- rowwithinparse --------

    @classmethod
    def _inline(cls, text: str, footnotes: dict = None) -> str:
        """Inline format: **bold**, *italic*, ~~strikethrough~~, `code`, [link](url),
        ![image](url), [^footnote], autoURL, convertmeaningcharacter, node path"""
        # 1. processconvertmeaningcharacter: firstwill \X replaceswapasoccupybitsymbol, lastagainstilloriginal
        _ESC_MAP = {}
        _esc_counter = [0]

        def _replace_escape(m):
            key = f'\x00ESC{_esc_counter[0]}\x00'
            _ESC_MAP[key] = m.group(1)  # isconvertmeaning character
            _esc_counter[0] += 1
            return key

        text = re.sub(r'\\([\\`*_~\[\]()#>!|])', _replace_escape, text)

        # 2. HTML convertmeaning
        text = html.escape(text)

        # 3. Inline image ![alt](url) (inline-level, not its own line)
        text = re.sub(
            r'!\[([^\]]*)\]\(([^)]+)\)',
            r'<img src="\2" alt="\1" style="max-width:100%;max-height:200px;'
            r'border-radius:4px;margin:2px 0;vertical-align:middle;">',
            text,
        )

        # 4. link [text](url)
        text = re.sub(
            r'\[([^\]]+?)\]\(([^)]+?)\)',
            r'<a href="\2" style="color:#818cf8;text-decoration:none;'
            r'border-bottom:1px solid rgba(129,140,248,0.3);">\1</a>',
            text,
        )

        # 5. footnotereference [^id]
        if footnotes:
            def _fn_ref(m):
                fid = m.group(1)
                if fid in footnotes:
                    return (
                        f'<sup style="color:#818cf8;cursor:pointer;">'
                        f'<a href="#fn-{html.escape(fid)}" style="color:#818cf8;'
                        f'text-decoration:none;">[{html.escape(fid)}]</a></sup>'
                    )
                return m.group(0)
            text = cls._FOOTNOTE_REF_RE.sub(_fn_ref, text)

        # 6. Bold
        text = re.sub(r'\*\*(.+?)\*\*', r'<b style="color:#f1f5f9;font-weight:600;">\1</b>', text)
        # 7. deleteline
        text = re.sub(r'~~(.+?)~~', r'<s style="color:#64748b;">\1</s>', text)
        # 8. Italic
        text = re.sub(r'(?<!\*)\*([^*]+?)\*(?!\*)', r'<i style="color:#cbd5e1;">\1</i>', text)
        # 9. rowwithincode
        text = re.sub(
            r'`([^`]+?)`',
            r'<code style="background:rgba(255,255,255,8);padding:2px 7px;border-radius:5px;'
            r'font-family:Consolas,Monaco,monospace;color:#c9d1d9;'
            r'font-size:0.88em;border:1px solid rgba(255,255,255,5);">\1</code>',
            text,
        )
        # 10. auto URL detect (barelink) 
        text = cls._AUTO_URL_RE.sub(
            r'<a href="\1" style="color:#818cf8;text-decoration:none;">\1</a>',
            text,
        )
        # 11. Houdini node path → canclicklink
        text = _linkify_node_paths(text)

        # 12. stilloriginalconvertmeaningcharacter
        for key, char in _ESC_MAP.items():
            text = text.replace(key, html.escape(char))

        return text


# ============================================================
# syntaxhighlight 
# ============================================================

class SyntaxHighlighter:
    """Code syntax highlighting - token-based coloring.
    
    supportlanguage: VEX, Python, JSON, YAML, Bash/Shell, JavaScript/TypeScript,
    HScript, GLSL, Markdown
    """

    COL = {
        'keyword':  '#569CD6',
        'type':     '#4EC9B0',
        'builtin':  '#DCDCAA',
        'string':   '#CE9178',
        'comment':  '#6A9955',
        'number':   '#B5CEA8',
        'attr':     '#9CDCFE',
        'key':      '#9CDCFE',    # JSON / YAML key
        'constant': '#569CD6',    # true / false / null
        'operator': '#D4D4D4',    # operators
        'directive': '#C586C0',   # preprocessor / shebang
    }

    # ---- VEX ----
    VEX_KW = frozenset(
        'if else for while return break continue foreach do switch case default'.split()
    )
    VEX_TY = frozenset(
        'float vector vector2 vector4 int string void matrix matrix3 dict'.split()
    )
    VEX_BI = frozenset(
        'set getattrib setattrib point prim detail chf chi chs chv chramp '
        'length normalize fit fit01 rand noise sin cos pow sqrt abs min max '
        'clamp lerp smooth cross dot addpoint addprim addvertex removeprim '
        'removepoint npoints nprims printf sprintf push pop append resize len '
        'find sort sample_direction_uniform pcopen pcfilter nearpoint '
        'nearpoints xyzdist primuv'.split()
    )

    # ---- Python ----
    PY_KW = frozenset(
        'import from def class return if else elif for while try except finally '
        'with as in not and or is None True False pass break continue raise '
        'yield lambda global nonlocal del assert'.split()
    )
    PY_BI = frozenset(
        'print len range str int float list dict tuple set type isinstance '
        'enumerate zip map filter sorted reversed open super property '
        'staticmethod classmethod hasattr getattr setattr'.split()
    )

    # ---- JavaScript / TypeScript ----
    JS_KW = frozenset(
        'var let const function return if else for while do switch case default '
        'break continue new this typeof instanceof void delete throw try catch '
        'finally class extends import export from as async await yield of in '
        'static get set super'.split()
    )
    JS_TY = frozenset(
        'string number boolean any void never unknown object symbol bigint '
        'undefined null Array Promise Map Set Record Partial Required Readonly '
        'interface type enum namespace'.split()
    )
    JS_BI = frozenset(
        'console log warn error parseInt parseFloat isNaN isFinite '
        'JSON Math Date RegExp Object Array String Number Boolean '
        'setTimeout setInterval clearTimeout clearInterval '
        'fetch require module exports process'.split()
    )

    # ---- Bash / Shell ----
    BASH_KW = frozenset(
        'if then else elif fi for do done while until case esac in '
        'function return exit break continue select'.split()
    )
    BASH_BI = frozenset(
        'echo printf cd ls cp mv rm mkdir rmdir cat grep sed awk find '
        'chmod chown tar gzip gunzip curl wget git pip python node npm '
        'export source alias unalias set unset read eval exec test '
        'true false shift'.split()
    )

    # ---- HScript ----
    HSCRIPT_KW = frozenset(
        'if else endif for foreach end set setenv echo opcf opcd '
        'opparm oprm opadd opsave opload chadd chkey chls optype '
        'opflag opname opset oppane opproperty'.split()
    )

    # ---- GLSL ----
    GLSL_KW = frozenset(
        'if else for while do return break continue discard switch case default '
        'struct void const in out inout uniform varying attribute '
        'layout precision highp mediump lowp flat smooth noperspective '
        'centroid sample'.split()
    )
    GLSL_TY = frozenset(
        'float vec2 vec3 vec4 int ivec2 ivec3 ivec4 uint uvec2 uvec3 uvec4 '
        'bool bvec2 bvec3 bvec4 mat2 mat3 mat4 mat2x2 mat2x3 mat2x4 '
        'mat3x2 mat3x3 mat3x4 mat4x2 mat4x3 mat4x4 '
        'sampler1D sampler2D sampler3D samplerCube sampler2DShadow'.split()
    )
    GLSL_BI = frozenset(
        'texture texture2D textureCube normalize length distance dot cross '
        'reflect refract mix clamp smoothstep step min max abs sign floor '
        'ceil fract mod pow exp log sqrt inversesqrt sin cos tan asin acos atan '
        'radians degrees dFdx dFdy fwidth'.split()
    )

    @classmethod
    def highlight_vex(cls, code: str) -> str:
        return cls._tokenize(code, cls.VEX_KW, cls.VEX_TY, cls.VEX_BI,
                              '//', ('/*', '*/'), '@')

    @classmethod
    def highlight_python(cls, code: str) -> str:
        return cls._tokenize(code, cls.PY_KW, frozenset(), cls.PY_BI,
                              '#', None, None)

    @classmethod
    def highlight_javascript(cls, code: str) -> str:
        return cls._tokenize(code, cls.JS_KW, cls.JS_TY, cls.JS_BI,
                              '//', ('/*', '*/'), None)

    @classmethod
    def highlight_bash(cls, code: str) -> str:
        return cls._tokenize(code, cls.BASH_KW, frozenset(), cls.BASH_BI,
                              '#', None, '$')

    @classmethod
    def highlight_hscript(cls, code: str) -> str:
        return cls._tokenize(code, cls.HSCRIPT_KW, frozenset(), frozenset(),
                              '#', None, '$')

    @classmethod
    def highlight_glsl(cls, code: str) -> str:
        return cls._tokenize(code, cls.GLSL_KW, cls.GLSL_TY, cls.GLSL_BI,
                              '//', ('/*', '*/'), None)

    @classmethod
    def highlight_json(cls, code: str) -> str:
        """JSON highlighting: color keys and value sections."""
        parts: list = []
        i, n = 0, len(code)
        # simplestate: ononenotemptywhitecharacteris { or , orrowfirst → belowonestringis key
        expect_key = True

        while i < n:
            c = code[i]

            # emptywhite
            if c in (' ', '\t', '\n', '\r'):
                parts.append(c)
                if c == '\n':
                    expect_key = True
                i += 1
                continue

            # string
            if c == '"':
                j = i + 1
                while j < n and code[j] != '"':
                    if code[j] == '\\':
                        j += 1
                    j += 1
                if j < n:
                    j += 1
                s = code[i:j]
                # decidebreakis key stillis value
                # key afterface (skipemptywhite) shouldthisis :
                rest = code[j:].lstrip()
                if expect_key and rest.startswith(':'):
                    parts.append(cls._span('key', s))
                    expect_key = False
                else:
                    parts.append(cls._span('string', s))
                i = j
                continue

            # Colon
            if c == ':':
                parts.append(html.escape(c))
                expect_key = False
                i += 1
                continue

            # Comma
            if c == ',':
                parts.append(html.escape(c))
                expect_key = True
                i += 1
                continue

            # largeincludenumber / wayincludenumber
            if c in ('{', '['):
                parts.append(html.escape(c))
                expect_key = True
                i += 1
                continue
            if c in ('}', ']'):
                parts.append(html.escape(c))
                i += 1
                continue

            # countcharacter
            if c.isdigit() or (c == '-' and i + 1 < n and code[i + 1].isdigit()):
                j = i + 1 if c == '-' else i
                while j < n and (code[j].isdigit() or code[j] in ('.', 'e', 'E', '+', '-')):
                    j += 1
                parts.append(cls._span('number', code[i:j]))
                i = j
                continue

            # true / false / null
            for kw in ('true', 'false', 'null'):
                if code[i:i + len(kw)] == kw:
                    parts.append(cls._span('constant', kw))
                    i += len(kw)
                    break
            else:
                parts.append(html.escape(c))
                i += 1

        return ''.join(parts)

    @classmethod
    def highlight_yaml(cls, code: str) -> str:
        """YAML highlighting: key-value sections, comments, list markers."""
        parts: list = []
        lines = code.split('\n')
        for li, line in enumerate(lines):
            if li > 0:
                parts.append('\n')

            stripped = line.lstrip()

            # Comments
            if stripped.startswith('#'):
                parts.append(cls._span('comment', line))
                continue

            # documentpartintervalsymbol ---
            if stripped in ('---', '...'):
                parts.append(cls._span('directive', line))
                continue

            # listitem - xxx: value
            indent = line[:len(line) - len(stripped)]
            if indent:
                parts.append(html.escape(indent))

            # check key: value format
            colon_pos = stripped.find(':')
            if colon_pos > 0 and (colon_pos + 1 >= len(stripped) or stripped[colon_pos + 1] == ' '):
                # processlistmark
                key_part = stripped[:colon_pos]
                if key_part.startswith('- '):
                    parts.append(html.escape('- '))
                    key_part = key_part[2:]

                parts.append(cls._span('key', key_part))
                parts.append(html.escape(':'))

                value_part = stripped[colon_pos + 1:]
                if value_part:
                    # Check value-side comment
                    comment_pos = value_part.find(' #')
                    if comment_pos >= 0:
                        val = value_part[:comment_pos]
                        comment = value_part[comment_pos:]
                        parts.append(cls._highlight_yaml_value(val))
                        parts.append(cls._span('comment', comment))
                    else:
                        parts.append(cls._highlight_yaml_value(value_part))
            else:
                # listitemorpurevalue
                if stripped.startswith('- '):
                    parts.append(html.escape('- '))
                    parts.append(cls._highlight_yaml_value(stripped[2:]))
                else:
                    parts.append(html.escape(stripped))

        return ''.join(parts)

    @classmethod
    def _highlight_yaml_value(cls, value: str) -> str:
        """highlight YAML value"""
        v = value.strip()
        if not v:
            return html.escape(value)

        # keeppreviousimportemptygrid
        leading = value[:len(value) - len(value.lstrip())]
        result = html.escape(leading) if leading else ''

        # string (withguidenumber) 
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            return result + cls._span('string', v)
        # boolean / null
        if v.lower() in ('true', 'false', 'yes', 'no', 'on', 'off', 'null', '~'):
            return result + cls._span('constant', v)
        # countcharacter
        try:
            float(v)
            return result + cls._span('number', v)
        except ValueError:
            pass
        return result + html.escape(v)

    @classmethod
    def _tokenize(cls, code, keywords, types, builtins,
                   comment_single, comment_multi, attr_prefix):
        parts: list = []
        i, n = 0, len(code)
        while i < n:
            c = code[i]
            # --- single-line comment ---
            if comment_single and code[i:i + len(comment_single)] == comment_single:
                end = code.find('\n', i)
                if end == -1:
                    end = n
                parts.append(cls._span('comment', code[i:end]))
                i = end
                continue
            # --- multi-line comment ---
            if comment_multi and code[i:i + len(comment_multi[0])] == comment_multi[0]:
                end = code.find(comment_multi[1], i + len(comment_multi[0]))
                end = n if end == -1 else end + len(comment_multi[1])
                parts.append(cls._span('comment', code[i:end]))
                i = end
                continue
            # --- strings ---
            if c in ('"', "'", '`'):
                # Template literals (JS backtick strings)
                if c == '`':
                    j = i + 1
                    while j < n and code[j] != '`':
                        if code[j] == '\\':
                            j += 1
                        j += 1
                    if j < n:
                        j += 1
                    parts.append(cls._span('string', code[i:j]))
                    i = j
                    continue
                triple = code[i:i + 3]
                if triple in ('"""', "'''"):
                    end = code.find(triple, i + 3)
                    end = n if end == -1 else end + 3
                    parts.append(cls._span('string', code[i:end]))
                    i = end
                    continue
                j = i + 1
                while j < n and code[j] != c and code[j] != '\n':
                    if code[j] == '\\':
                        j += 1
                    j += 1
                if j < n and code[j] == c:
                    j += 1
                parts.append(cls._span('string', code[i:j]))
                i = j
                continue
            # --- attribute prefix (@P, $VAR etc.) ---
            if (attr_prefix and c == attr_prefix
                    and i + 1 < n and (code[i + 1].isalpha() or code[i + 1] == '_')):
                j = i + 1
                while j < n and (code[j].isalnum() or code[j] in ('_', '.')):
                    j += 1
                parts.append(cls._span('attr', code[i:j]))
                i = j
                continue
            # --- preprocessor directive (#include, #define) ---
            if c == '#' and (not comment_single or comment_single != '#'):
                if i == 0 or code[i - 1] == '\n':
                    end = code.find('\n', i)
                    if end == -1:
                        end = n
                    parts.append(cls._span('directive', code[i:end]))
                    i = end
                    continue
            # --- identifier / keyword ---
            if c.isalpha() or c == '_':
                j = i
                while j < n and (code[j].isalnum() or code[j] == '_'):
                    j += 1
                word = code[i:j]
                if word in keywords:
                    parts.append(cls._span('keyword', word))
                elif word in types:
                    parts.append(cls._span('type', word))
                elif word in builtins:
                    parts.append(cls._span('builtin', word))
                else:
                    parts.append(html.escape(word))
                i = j
                continue
            # --- number (including hex 0x...) ---
            if c.isdigit() or (c == '.' and i + 1 < n and code[i + 1].isdigit()):
                j = i
                if c == '0' and j + 1 < n and code[j + 1] in ('x', 'X'):
                    j += 2
                    while j < n and (code[j].isdigit() or code[j] in 'abcdefABCDEF'):
                        j += 1
                else:
                    while j < n and (code[j].isdigit() or code[j] in ('.', 'e', 'E', '+', '-', 'f')):
                        if code[j] in ('+', '-') and j > 0 and code[j - 1] not in ('e', 'E'):
                            break
                        j += 1
                parts.append(cls._span('number', code[i:j]))
                i = j
                continue
            parts.append(html.escape(c))
            i += 1
        return ''.join(parts)

    @classmethod
    def _span(cls, tok_type: str, text: str) -> str:
        color = cls.COL.get(tok_type, '#D4D4D4')
        return f'<span style="color:{color};">{html.escape(text)}</span>'


# ============================================================
# cancollapse Shell outputarea (Python Shell / System Shell shareduse) 
# ============================================================

class _CollapsibleShellOutput(QtWidgets.QWidget):
    """cancollapse  Shell outputarea
    
    - Default collapsed: only show 4 rows; scroll passes through to parent window
    - expandafter: showallpartcontent, scrollroundcanscrollwithinassociatearea
    """

    _COLLAPSED_LINES = 4
    _MAX_EXPANDED_H = 400  # expandaftermaxheight

    def __init__(self, content_html: str, bg_color: str = "#141428",
                 parent=None):
        super().__init__(parent)
        self._collapsed = True
        self._full_h = 0
        self._collapsed_h = 0
        # Infer variant (python / system) based on background color
        self._variant = "system" if bg_color == "#141414" else "python"

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── QTextEdit (outputcontent) ──
        self._text = QtWidgets.QTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        self._text.setObjectName("shellOutput")
        self._text.setProperty("variant", self._variant)
        self._text.setHtml(
            f'<pre style="margin:0;white-space:pre;font-family:Consolas,Monaco,monospace;'
            f'font-size:12px;">{content_html}</pre>'
        )
        lay.addWidget(self._text)

        # computesize
        doc = self._text.document()
        doc.setDocumentMargin(4)
        self._full_h = int(doc.size().height()) + 16

        # computecollapseheight (4 row) 
        fm = self._text.fontMetrics()
        line_h = fm.lineSpacing() if fm.lineSpacing() > 0 else 17
        self._collapsed_h = self._COLLAPSED_LINES * line_h + 16  # 16 = padding

        # Decide whether to collapse (skip if content is fewer than 4 rows)
        self._needs_collapse = self._full_h > self._collapsed_h + line_h

        if self._needs_collapse:
            # initialcollapsestate
            self._text.setFixedHeight(self._collapsed_h)
            self._text.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self._text.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            # installeventfilter interceptcutscrollround
            self._text.viewport().installEventFilter(self)

            # computetotalrowcount
            total_lines = content_html.count('<br>') + content_html.count('\n') + 1
            remaining = max(0, total_lines - self._COLLAPSED_LINES)

            # ── expand/collectstart toggle bar ──
            self._toggle = QtWidgets.QLabel(
                f"  ▼ expand ({remaining} moremultirow)"
            )
            self._toggle.setCursor(QtCore.Qt.PointingHandCursor)
            self._toggle.setObjectName("shellToggle")
            self._toggle.setProperty("variant", self._variant)
            self._toggle.mousePressEvent = lambda e: self._toggle_collapse()
            self._toggle.setFixedHeight(22)
            lay.addWidget(self._toggle)
            self._remaining = remaining
        else:
            # Content is short - no collapse needed; show in full
            h = min(self._full_h, self._MAX_EXPANDED_H)
            self._text.setFixedHeight(h)
            self._text.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self._text.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

    def _toggle_collapse(self):
        """switchcollapse/expand"""
        self._collapsed = not self._collapsed
        if self._collapsed:
            # collapse
            self._text.setFixedHeight(self._collapsed_h)
            self._text.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self._text.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self._text.verticalScrollBar().setValue(0)
            self._toggle.setText(f"  ▼ Expand ({self._remaining} more lines)")
        else:
            # expand
            h = min(self._full_h, self._MAX_EXPANDED_H)
            self._text.setFixedHeight(h)
            if self._full_h > self._MAX_EXPANDED_H:
                self._text.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
            else:
                self._text.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self._text.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
            self._toggle.setText("  ▲ Collapse")

    def eventFilter(self, obj, event):
        """When collapsed, scroll-wheel events pass through to the parent window."""
        if (event.type() == QtCore.QEvent.Wheel
                and self._collapsed and self._needs_collapse):
            # Forward the scroll event to the parent ScrollArea
            parent = self.parent()
            while parent:
                if isinstance(parent, QtWidgets.QScrollArea):
                    QtWidgets.QApplication.sendEvent(parent.viewport(), event)
                    return True
                parent = parent.parent()
            return True  # Swallow even if not found, to avoid inner scroll
        return super().eventFilter(obj, event)


# ============================================================
# Python Shell executewindow
# ============================================================

class PythonShellWidget(QtWidgets.QFrame):
    """Python Shell executeresult — showcode + output + error"""
    
    def __init__(self, code: str, output: str = "", error: str = "",
                 exec_time: float = 0.0, success: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("PythonShellWidget")
        
        self.setProperty("state", "ok" if success else "error")
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # ---- header: Python Shell + executewhenbetween ----
        header = QtWidgets.QWidget()
        header.setObjectName("pyShellHeader")
        hl = QtWidgets.QHBoxLayout(header)
        hl.setContentsMargins(8, 4, 8, 4)
        hl.setSpacing(6)
        
        title_lbl = QtWidgets.QLabel("PYTHON SHELL")
        title_lbl.setObjectName("pyShellTitle")
        hl.addWidget(title_lbl)
        
        hl.addStretch()
        
        if exec_time > 0:
            time_lbl = QtWidgets.QLabel(f"{exec_time:.2f}s")
            time_lbl.setObjectName("shellTimeLbl")
            hl.addWidget(time_lbl)
        
        status_lbl = QtWidgets.QLabel("ok" if success else "err")
        status_lbl.setObjectName("shellStatusOk" if success else "shellStatusErr")
        hl.addWidget(status_lbl)
        
        layout.addWidget(header)
        
        # ---- codearea ----
        code_widget = QtWidgets.QTextEdit()
        code_widget.setReadOnly(True)
        code_widget.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        code_widget.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        code_widget.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        code_widget.setObjectName("shellCodeEdit")
        
        # Python syntaxhighlight
        highlighted_code = SyntaxHighlighter.highlight_python(code)
        code_widget.setHtml(f'<pre style="margin:0;white-space:pre;">{highlighted_code}</pre>')
        
        # codesectionheightselfsuitshould (mosthigh 200px)
        doc = code_widget.document()
        doc.setDocumentMargin(4)
        code_h = min(int(doc.size().height()) + 16, 200)
        code_widget.setFixedHeight(code_h)
        layout.addWidget(code_widget)
        
        # ---- outputarea (cancollapse) ----
        has_output = bool(output and output.strip())
        has_error = bool(error and error.strip())
        
        if has_output or has_error:
            parts = []
            if has_output:
                parts.append(f'<span style="color:{CursorTheme.TEXT_PRIMARY};">'
                             f'{html.escape(output.strip())}</span>')
            if has_error:
                parts.append(f'<span style="color:{CursorTheme.ACCENT_RED};">'
                             f'{html.escape(error.strip())}</span>')
            content_html = '<br>'.join(parts)
            layout.addWidget(_CollapsibleShellOutput(content_html, "#141428", self))
        
        elif not success:
            err_label = QtWidgets.QLabel("Execution failed (no details)")
            err_label.setObjectName("shellErrFallback")
            layout.addWidget(err_label)


class SystemShellWidget(QtWidgets.QFrame):
    """System Shell executeresult — showcommandcommand + stdout/stderr + exitcode"""

    def __init__(self, command: str, output: str = "", error: str = "",
                 exit_code: int = 0, exec_time: float = 0.0,
                 success: bool = True, cwd: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("SystemShellWidget")

        self.setProperty("state", "ok" if success else "error")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- header: SHELL + cwd + executewhenbetween + exitcode ----
        header = QtWidgets.QWidget()
        header.setObjectName("sysShellHeader")
        hl = QtWidgets.QHBoxLayout(header)
        hl.setContentsMargins(8, 4, 8, 4)
        hl.setSpacing(6)

        title_lbl = QtWidgets.QLabel("SHELL")
        title_lbl.setObjectName("sysShellTitle")
        hl.addWidget(title_lbl)

        if cwd:
            # onlyshowlasttwolayerdirectory
            parts = cwd.replace('\\', '/').rstrip('/').split('/')
            short_cwd = '/'.join(parts[-2:]) if len(parts) >= 2 else cwd
            cwd_lbl = QtWidgets.QLabel(short_cwd)
            cwd_lbl.setObjectName("shellCwdLbl")
            hl.addWidget(cwd_lbl)

        hl.addStretch()

        if exec_time > 0:
            time_lbl = QtWidgets.QLabel(f"{exec_time:.2f}s")
            time_lbl.setObjectName("shellTimeLbl")
            hl.addWidget(time_lbl)

        code_lbl = QtWidgets.QLabel(f"exit {exit_code}")
        code_lbl.setObjectName("shellStatusOk" if exit_code == 0 else "shellStatusErr")
        hl.addWidget(code_lbl)

        layout.addWidget(header)

        # ---- commandcommandarea ----
        cmd_widget = QtWidgets.QTextEdit()
        cmd_widget.setReadOnly(True)
        cmd_widget.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        cmd_widget.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        cmd_widget.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        cmd_widget.setObjectName("shellCmdEdit")

        # commandcommandshow: with $ or > prefix
        import html as _html
        prefix = "&gt;" if "win" in __import__('sys').platform else "$"
        cmd_html = (
            f'<pre style="margin:0;white-space:pre;">'
            f'<span style="color:{CursorTheme.ACCENT_GREEN};">{prefix}</span> '
            f'{_html.escape(command)}</pre>'
        )
        cmd_widget.setHtml(cmd_html)

        doc = cmd_widget.document()
        doc.setDocumentMargin(4)
        cmd_h = min(int(doc.size().height()) + 16, 80)
        cmd_widget.setFixedHeight(cmd_h)
        layout.addWidget(cmd_widget)

        # ---- outputarea (cancollapse) ----
        has_output = bool(output and output.strip())
        has_error = bool(error and error.strip())

        if has_output or has_error:
            parts = []
            if has_output:
                parts.append(f'<span style="color:{CursorTheme.TEXT_PRIMARY};">'
                             f'{_html.escape(output.strip())}</span>')
            if has_error:
                parts.append(f'<span style="color:{CursorTheme.ACCENT_RED};">'
                             f'{_html.escape(error.strip())}</span>')
            content_html = '<br>'.join(parts)
            layout.addWidget(_CollapsibleShellOutput(content_html, "#141414", self))

        elif not success:
            err_label = QtWidgets.QLabel("Command failed (no details)")
            err_label.setObjectName("shellErrFallback")
            layout.addWidget(err_label)


# ============================================================
# codeblockcomponent
# ============================================================

class CodeBlockWidget(QtWidgets.QFrame):
    """Code block - syntax highlighting + line numbers + copy + collapse + create Wrangle (VEX-specific).
    
    ★ Phase 6 addstrong:
    - greater than 5 rowwhenautoshowrownumber
    - exceeds 15 rowdefaultcollapse, clickexpand
    - languagelabelshowin header
    """

    createWrangleRequested = QtCore.Signal(str)  # vex_code

    _VEX_INDICATORS = (
        '@P', '@Cd', '@N', '@v', '@ptnum', '@numpt', '@opinput',
        'chf(', 'chi(', 'chs(', 'chv(', 'chramp(',
        'addpoint', 'addprim', 'setattrib', 'getattrib',
        'vector ', 'float ', '#include',
    )

    _COLLAPSE_THRESHOLD = 15   # exceedsthisrowcountdefaultcollapse
    _LINE_NUM_THRESHOLD = 5    # exceedsthisrowcountshowrownumber
    _MAX_HEIGHT = 400          # maxheight

    def __init__(self, code: str, language: str = "", parent=None):
        super().__init__(parent)
        self._code = code
        self._lang = language.lower()
        self._line_count = code.count('\n') + 1
        self._collapsed = self._line_count > self._COLLAPSE_THRESHOLD
        self._show_line_numbers = self._line_count > self._LINE_NUM_THRESHOLD

        self.setObjectName("CodeBlockWidget")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- header ----
        header = QtWidgets.QWidget()
        header.setObjectName("codeBlockHeader")
        hl = QtWidgets.QHBoxLayout(header)
        hl.setContentsMargins(8, 3, 4, 3)
        hl.setSpacing(4)

        lang_text = self._lang.upper() or ("VEX" if self._is_vex() else "CODE")
        # languagelabel + rowcountinfo
        lang_info = f"{lang_text}"
        if self._line_count > 1:
            lang_info += f"  ({self._line_count} row)"
        lang_lbl = QtWidgets.QLabel(lang_info)
        lang_lbl.setObjectName("codeBlockLang")
        hl.addWidget(lang_lbl)
        hl.addStretch()

        # operationbuttonlist (hover whenshow) 
        self._action_btns: list = []

        # collapse/expandbutton (onlyinexceedsthresholdvaluewhenshow, alwayscansee) 
        if self._line_count > self._COLLAPSE_THRESHOLD:
            self._toggle_btn = QtWidgets.QPushButton(
                f"expand ({self._line_count} row)" if self._collapsed else "collectstart"
            )
            self._toggle_btn.setCursor(QtCore.Qt.PointingHandCursor)
            self._toggle_btn.setObjectName("codeBlockBtn")
            self._toggle_btn.clicked.connect(self._toggle_collapse)
            hl.addWidget(self._toggle_btn)

        copy_btn = QtWidgets.QPushButton("Copy")
        copy_btn.setCursor(QtCore.Qt.PointingHandCursor)
        copy_btn.setObjectName("codeBlockBtn")
        copy_btn.clicked.connect(self._on_copy)
        copy_btn.setVisible(False)
        hl.addWidget(copy_btn)
        self._action_btns.append(copy_btn)

        if self._lang in ('vex', 'vfl', '') and self._is_vex():
            wrangle_btn = QtWidgets.QPushButton("Create Wrangle")
            wrangle_btn.setCursor(QtCore.Qt.PointingHandCursor)
            wrangle_btn.setObjectName("codeBlockBtnGreen")
            wrangle_btn.clicked.connect(lambda: self.createWrangleRequested.emit(self._code))
            wrangle_btn.setVisible(False)
            hl.addWidget(wrangle_btn)
            self._action_btns.append(wrangle_btn)

        layout.addWidget(header)

        # ---- code area ----
        self._code_edit = QtWidgets.QTextEdit()
        self._code_edit.setReadOnly(True)
        self._code_edit.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        self._code_edit.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._code_edit.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._code_edit.setObjectName("codeBlockEdit")

        highlighted = self._highlight()
        code_html = self._add_line_numbers(highlighted) if self._show_line_numbers else highlighted
        self._code_edit.setHtml(
            f'<pre style="margin:0;white-space:pre;">{code_html}</pre>'
        )
        # auto-height (capped)
        doc = self._code_edit.document()
        doc.setDocumentMargin(4)
        self._full_h = int(doc.size().height()) + 20

        # computecollapseheight (COLLAPSE_THRESHOLD row) 
        fm = self._code_edit.fontMetrics()
        line_h = fm.lineSpacing() if fm.lineSpacing() > 0 else 17
        self._collapsed_h = self._COLLAPSE_THRESHOLD * line_h + 20

        if self._collapsed:
            self._code_edit.setFixedHeight(min(self._collapsed_h, self._MAX_HEIGHT))
            self._code_edit.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        else:
            self._code_edit.setFixedHeight(min(self._full_h, self._MAX_HEIGHT))

        layout.addWidget(self._code_edit)

    def _add_line_numbers(self, highlighted_code: str) -> str:
        """ashighlightcodeaddrownumber (use HTML table layout) """
        lines = highlighted_code.split('\n')
        width = len(str(len(lines)))
        result: list = []
        num_color = '#4a5568'  # Dark-gray line numbers
        sep_color = 'rgba(255,255,255,6)'  # partintervalline

        for i, line in enumerate(lines, 1):
            num = str(i).rjust(width)
            result.append(
                f'<span style="color:{num_color};user-select:none;'
                f'padding-right:12px;border-right:1px solid {sep_color};'
                f'margin-right:12px;">{num}</span>{line}'
            )
        return '\n'.join(result)

    def _toggle_collapse(self):
        """switchcodeblockcollapse/expand"""
        self._collapsed = not self._collapsed
        if self._collapsed:
            self._code_edit.setFixedHeight(min(self._collapsed_h, self._MAX_HEIGHT))
            self._code_edit.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self._code_edit.verticalScrollBar().setValue(0)
            self._toggle_btn.setText(f"Expand ({self._line_count} lines)")
        else:
            self._code_edit.setFixedHeight(min(self._full_h, self._MAX_HEIGHT))
            if self._full_h > self._MAX_HEIGHT:
                self._code_edit.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
            else:
                self._code_edit.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self._toggle_btn.setText("Collapse")

    # --- helpers ---
    def _is_vex(self) -> bool:
        return any(ind in self._code for ind in self._VEX_INDICATORS)

    def _highlight(self) -> str:
        lang = self._lang
        # VEX autodetect
        if lang in ('vex', 'vfl') or (not lang and self._is_vex()):
            return SyntaxHighlighter.highlight_vex(self._code)
        # Python
        if lang in ('python', 'py'):
            return SyntaxHighlighter.highlight_python(self._code)
        # JSON
        if lang == 'json':
            return SyntaxHighlighter.highlight_json(self._code)
        # YAML
        if lang in ('yaml', 'yml'):
            return SyntaxHighlighter.highlight_yaml(self._code)
        # Bash / Shell
        if lang in ('bash', 'sh', 'shell', 'zsh', 'powershell', 'ps1', 'bat', 'cmd'):
            return SyntaxHighlighter.highlight_bash(self._code)
        # JavaScript / TypeScript
        if lang in ('javascript', 'js', 'typescript', 'ts', 'jsx', 'tsx'):
            return SyntaxHighlighter.highlight_javascript(self._code)
        # HScript
        if lang in ('hscript', 'hs'):
            return SyntaxHighlighter.highlight_hscript(self._code)
        # GLSL / HLSL / shader
        if lang in ('glsl', 'hlsl', 'shader', 'frag', 'vert', 'wgsl'):
            return SyntaxHighlighter.highlight_glsl(self._code)
        # C / C++ / C# (use GLSL tokenizer as base — similar syntax)
        if lang in ('c', 'cpp', 'c++', 'cxx', 'h', 'hpp', 'cs', 'csharp'):
            return SyntaxHighlighter.highlight_glsl(self._code)
        # XML / HTML — use plain escaped (simple approach)
        if lang in ('xml', 'html', 'svg'):
            return html.escape(self._code)
        # Fallback: no highlighting
        return html.escape(self._code)

    def enterEvent(self, event):
        for btn in self._action_btns:
            btn.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        for btn in self._action_btns:
            btn.setVisible(False)
        super().leaveEvent(event)

    def _on_copy(self):
        QtWidgets.QApplication.clipboard().setText(self._code)
        btn = self.sender()
        if btn:
            btn.setText("Copied")
            QtCore.QTimer.singleShot(1500, lambda: btn.setText("Copy"))

    # _btn_css removed — styling now via QSS objectName selectors


# ============================================================
# richtextcontentcomponent
# ============================================================

class RichContentWidget(QtWidgets.QWidget):
    """render Markdown text + submitmutualstylecodeblock

    Layout style similar to Cursor / GitHub Copilot Chat:
    - Text paragraphs compact, comfortable line height
    - Clear separation between code blocks and body text
    - tablegrid, link, listetc.completesupport
    - Houdini node pathautochangeascanclicklink
    """

    createWrangleRequested = QtCore.Signal(str)
    nodePathClicked = QtCore.Signal(str)  # node pathisclick

    # _TEXT_STYLE removed — use objectName-based QSS instead

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)  # paragraphbetweendistanceby HTML margin control

        segments = SimpleMarkdown.parse_segments(text)

        for seg in segments:
            if seg[0] == 'text':
                lbl = QtWidgets.QLabel()
                lbl.setWordWrap(True)
                lbl.setTextFormat(QtCore.Qt.RichText)
                lbl.setOpenExternalLinks(False)  # Isselfselfprocesslink
                lbl.setTextInteractionFlags(
                    QtCore.Qt.TextSelectableByMouse
                    | QtCore.Qt.LinksAccessibleByMouse
                )
                lbl.setText(seg[1])
                lbl.setObjectName("richText")
                lbl.linkActivated.connect(self._on_link)
                layout.addWidget(lbl)
            elif seg[0] == 'code':
                cb = CodeBlockWidget(seg[2], seg[1], self)
                cb.createWrangleRequested.connect(self.createWrangleRequested.emit)
                cb.setContentsMargins(0, 6, 0, 6)
                layout.addWidget(cb)
            elif seg[0] == 'image':
                img_url = seg[1]
                img_alt = seg[2] if len(seg) > 2 else ''
                img_lbl = QtWidgets.QLabel()
                img_lbl.setObjectName("richImage")
                img_lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
                img_lbl.setWordWrap(False)
                img_lbl.setText(
                    f'<div style="margin:4px 0;">'
                    f'<img src="{html.escape(img_url)}" '
                    f'alt="{html.escape(img_alt)}" '
                    f'style="max-width:100%;max-height:300px;border-radius:6px;">'
                    f'</div>'
                )
                img_lbl.setTextFormat(QtCore.Qt.RichText)
                layout.addWidget(img_lbl)

    def _on_link(self, url: str):
        """processlinkclick"""
        if url.startswith('houdini://'):
            self.nodePathClicked.emit(url[len('houdini://'):])
        else:
            # External links open in the browser
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))


# ============================================================
# Node context bar (Houdini-specific)
# ============================================================

class NodeContextBar(QtWidgets.QFrame):
    """showcurrent Houdini network path / selectednode"""

    refreshRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setObjectName("NodeContextBar")

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 6, 0)
        lay.setSpacing(6)

        self.path_label = QtWidgets.QLabel("/obj")
        self.path_label.setObjectName("ctxPathLabel")
        lay.addWidget(self.path_label)

        self.sel_label = QtWidgets.QLabel("")
        self.sel_label.setObjectName("ctxSelLabel")
        self.sel_label.setVisible(False)
        lay.addWidget(self.sel_label)

        lay.addStretch()

        ref_btn = QtWidgets.QPushButton("R")
        ref_btn.setFixedSize(22, 22)
        ref_btn.setFlat(True)
        ref_btn.setCursor(QtCore.Qt.PointingHandCursor)
        ref_btn.setObjectName("ctxRefreshBtn")
        ref_btn.clicked.connect(self.refreshRequested.emit)
        lay.addWidget(ref_btn)

    def update_context(self, path: str = "", selected: list = None):
        self.path_label.setText(path if path else "/obj")
        if selected:
            names = [n.rsplit('/', 1)[-1] for n in selected[:3]]
            text = ', '.join(names)
            if len(selected) > 3:
                text += f" +{len(selected) - 3}"
            self.sel_label.setText(text)
            self.sel_label.setVisible(True)
        else:
            self.sel_label.setText("")
            self.sel_label.setVisible(False)


# ============================================================
# toolexecutestatebar
# ============================================================

class ToolStatusBar(QtWidgets.QFrame):
    """bottomparttoolstatebar — showcurrentpositiveinexecute toolname + pulserefershow """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setObjectName("toolStatusBar")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(4)

        self._pulse = PulseIndicator(CursorTheme.ACCENT_BEIGE, 5, self)
        lay.addWidget(self._pulse)

        self._label = QtWidgets.QLabel("")
        self._label.setObjectName("toolStatusLabel")
        lay.addWidget(self._label)
        lay.addStretch()

        self.setVisible(False)

    def show_tool(self, tool_name: str):
        """showpositiveinexecute tool"""
        self._label.setText(f"⚡ {tool_name}")
        self._pulse.start()
        self.setVisible(True)

    def hide_tool(self):
        """hidetoolstate"""
        self._pulse.stop()
        self.setVisible(False)
        self._label.setText("")


# ============================================================
# statsonestaterefershowbar (merge ThinkingBar + ToolStatusBar) 
# ============================================================

class UnifiedStatusBar(QtWidgets.QWidget):
    """statsonestaterefershowbar — mergethinkingstate, generatestateandtoolexecutestateasoneitemrefershowitem. 

    Exposes four hooks:
        start()                 showthinkingin + streamlightmovedraw
        show_generating()       showgeneratein + streamlightmovedraw (API iterateetc.pending) 
        show_tool(tool_name)    showtoolexecutein + pulsemovedraw
        stop()                  hidestatebar
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        self.setObjectName("unifiedStatusBar")
        self.setVisible(False)

        self._mode = None  # 'thinking' | 'generating' | 'tool' | None
        self._elapsed = 0.0
        self._phase = 0.0

        # streamlightfixedwhen  ~25fps
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

    # ---- Public API ----

    def start(self):
        """startthinkingmode (compatible withold ThinkingBar.start) """
        self._mode = 'thinking'
        self._elapsed = 0.0
        self._phase = 0.0
        self.setVisible(True)
        self._timer.start()
        self.update()

    def stop(self):
        """stopallstate (compatible withold ThinkingBar.stop) """
        self._mode = None
        self._timer.stop()
        self.setVisible(False)

    def set_elapsed(self, seconds: float):
        """updatethinkingconsumewhen (compatible withold ThinkingBar.set_elapsed) """
        self._elapsed = seconds
        self.update()

    def show_generating(self):
        """switchtogeneratemode — API requestetc.pendingin

        intoolexecutefinishfinishafter, belowoneround LLM respondshouldstartpreviousshow, 
        fillsupplement"thinkingend → belowroundcontenttoreach"ofbetween visualemptywhiteperiod. 
        """
        self._mode = 'generating'
        self._phase = 0.0
        self.setVisible(True)
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def show_planning(self, progress: str = ""):
        """switchtoruleplanmode — show Plan generateprogress

        Args:
            progress: progresstext, such as "step 3" oremptystring
        """
        self._mode = 'planning'
        self._planning_progress = progress
        self.setVisible(True)
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def show_tool(self, tool_name: str):
        """switchtotoolexecutemode"""
        self._mode = 'tool'
        self._tool_name = tool_name
        self._phase = 0.0
        self.setVisible(True)
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def hide_tool(self):
        """hidetoolstate → autoswitchto generating mode (etc.pendingbelowround API respondshould) """
        if self._mode == 'tool':
            # notfinishallhide, switchto generating modebyfillsupplementvisualemptywhite
            self.show_generating()

    # ---- withinpart ----

    def _tick(self):
        self._phase += 0.025
        if self._phase > 1.0:
            self._phase -= 1.0
        self.update()

    def paintEvent(self, event):
        if self._mode == 'thinking':
            self._paint_thinking(event)
        elif self._mode == 'generating':
            self._paint_generating(event)
        elif self._mode == 'planning':
            self._paint_planning(event)
        elif self._mode == 'tool':
            self._paint_tool(event)

    def _paint_thinking(self, event):
        """drawthinkingstate — streamlighttext"""
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        text = f"Thinking {self._elapsed:.1f}s" if self._elapsed > 0 else "Thinking..."
        font = QtGui.QFont(CursorTheme.FONT_BODY, 10)
        p.setFont(font)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(text)
        x = (w - tw) // 2
        y = (h + fm.ascent() - fm.descent()) // 2
        # bottomcolortext
        p.setPen(QtGui.QColor(100, 116, 139, 120))
        p.drawText(x, y, text)
        # Streaming-light highlight (scan effect)
        grad = QtGui.QLinearGradient(x, 0, x + tw, 0)
        pos = self._phase
        before = max(0.0, pos - 0.15)
        after = min(1.0, pos + 0.15)
        grad.setColorAt(0.0, QtGui.QColor(226, 232, 240, 0))
        if before > 0:
            grad.setColorAt(before, QtGui.QColor(226, 232, 240, 0))
        grad.setColorAt(pos, QtGui.QColor(226, 232, 240, 200))
        if after < 1.0:
            grad.setColorAt(after, QtGui.QColor(226, 232, 240, 0))
        grad.setColorAt(1.0, QtGui.QColor(226, 232, 240, 0))
        p.setPen(QtGui.QPen(QtGui.QBrush(grad), 0))
        p.drawText(x, y, text)
        p.end()

    def _paint_generating(self, event):
        """drawgeneratestate — streamlighttext (with thinking similarbutusewarmcoloradjust + differenttext) """
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        text = "Generating..."
        font = QtGui.QFont(CursorTheme.FONT_BODY, 10)
        p.setFont(font)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(text)
        x = (w - tw) // 2
        y = (h + fm.ascent() - fm.descent()) // 2
        # bottomcolortext (warmgraycolor) 
        p.setPen(QtGui.QColor(139, 116, 100, 120))
        p.drawText(x, y, text)
        # streamlighthighlight (warmwhitecolorscanpassed) 
        grad = QtGui.QLinearGradient(x, 0, x + tw, 0)
        pos = self._phase
        before = max(0.0, pos - 0.15)
        after = min(1.0, pos + 0.15)
        grad.setColorAt(0.0, QtGui.QColor(240, 226, 210, 0))
        if before > 0:
            grad.setColorAt(before, QtGui.QColor(240, 226, 210, 0))
        grad.setColorAt(pos, QtGui.QColor(240, 232, 220, 200))
        if after < 1.0:
            grad.setColorAt(after, QtGui.QColor(240, 226, 210, 0))
        grad.setColorAt(1.0, QtGui.QColor(240, 226, 210, 0))
        p.setPen(QtGui.QPen(QtGui.QBrush(grad), 0))
        p.drawText(x, y, text)
        p.end()

    def _paint_planning(self, event):
        """drawruleplanstate — purplecoloradjuststreamlight + progresstext"""
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        progress = getattr(self, '_planning_progress', '')
        text = f"Planning... {progress}" if progress else "Planning..."
        font = QtGui.QFont(CursorTheme.FONT_BODY, 10)
        p.setFont(font)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(text)
        x = (w - tw) // 2
        y = (h + fm.ascent() - fm.descent()) // 2
        # bottomcolortext (purplegraycolor) 
        p.setPen(QtGui.QColor(139, 120, 160, 120))
        p.drawText(x, y, text)
        # streamlighthighlight (purplewhitecolorscanpassed) 
        grad = QtGui.QLinearGradient(x, 0, x + tw, 0)
        pos = self._phase
        before = max(0.0, pos - 0.15)
        after = min(1.0, pos + 0.15)
        grad.setColorAt(0.0, QtGui.QColor(200, 180, 240, 0))
        if before > 0:
            grad.setColorAt(before, QtGui.QColor(200, 180, 240, 0))
        grad.setColorAt(pos, QtGui.QColor(220, 200, 250, 220))
        if after < 1.0:
            grad.setColorAt(after, QtGui.QColor(200, 180, 240, 0))
        grad.setColorAt(1.0, QtGui.QColor(200, 180, 240, 0))
        p.setPen(QtGui.QPen(QtGui.QBrush(grad), 0))
        p.drawText(x, y, text)
        p.end()

    def _paint_tool(self, event):
        """Draw the tool-execution state - streaming-light text (gold accent, unified with Thinking/Generating style)."""
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        tool_name = getattr(self, '_tool_name', '')
        text = f"Exec: {tool_name}" if tool_name else "Executing..."
        font = QtGui.QFont(CursorTheme.FONT_BODY, 10)
        p.setFont(font)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(text)
        x = (w - tw) // 2
        y = (h + fm.ascent() - fm.descent()) // 2
        # Base color text (dark gold)
        p.setPen(QtGui.QColor(170, 145, 100, 120))
        p.drawText(x, y, text)
        # Streaming highlight (gold scan)
        grad = QtGui.QLinearGradient(x, 0, x + tw, 0)
        pos = self._phase
        before = max(0.0, pos - 0.15)
        after = min(1.0, pos + 0.15)
        grad.setColorAt(0.0, QtGui.QColor(212, 190, 140, 0))
        if before > 0:
            grad.setColorAt(before, QtGui.QColor(212, 190, 140, 0))
        grad.setColorAt(pos, QtGui.QColor(230, 210, 170, 220))
        if after < 1.0:
            grad.setColorAt(after, QtGui.QColor(212, 190, 140, 0))
        grad.setColorAt(1.0, QtGui.QColor(212, 190, 140, 0))
        p.setPen(QtGui.QPen(QtGui.QBrush(grad), 0))
        p.drawText(x, y, text)
        p.end()


# ============================================================
# VEX previewconfirmconversationbox
# ============================================================

class VEXPreviewDialog(QtWidgets.QDialog):
    """VEX codepreviewconversationbox — userconfirmafteronly thenexecutecreateoperation"""

    def __init__(self, tool_name: str, args: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Confirm execution: {tool_name}")
        self.setMinimumSize(560, 400)
        self.setObjectName("vexPreviewDlg")

        self._accepted = False
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # toolname
        title = QtWidgets.QLabel(f"Tool: {tool_name}")
        title.setObjectName("vexDlgTitle")
        layout.addWidget(title)

        # parametersummary
        summary_parts = []
        if 'node_name' in args:
            summary_parts.append(f"nodename: {args['node_name']}")
        if 'wrangle_type' in args:
            summary_parts.append(f"type: {args['wrangle_type']}")
        if 'run_over' in args:
            summary_parts.append(f"Run Over: {args['run_over']}")
        if 'parent_path' in args:
            summary_parts.append(f"parentpath: {args['parent_path']}")
        if 'node_type' in args:
            summary_parts.append(f"nodetype: {args['node_type']}")
        if 'node_path' in args:
            summary_parts.append(f"node path: {args['node_path']}")
        if summary_parts:
            info = QtWidgets.QLabel("  |  ".join(summary_parts))
            info.setObjectName("vexDlgInfo")
            info.setWordWrap(True)
            layout.addWidget(info)

        # VEX code / mainneedparameter
        vex_code = args.get('vex_code', '')
        param_value = args.get('value', '')
        code_text = vex_code or param_value or str(args)

        code_edit = QtWidgets.QPlainTextEdit()
        code_edit.setPlainText(code_text)
        code_edit.setReadOnly(True)
        code_edit.setObjectName("vexDlgCode")
        layout.addWidget(code_edit, 1)

        # buttonrow
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QtWidgets.QPushButton("Cancel")
        btn_cancel.setFixedHeight(30)
        btn_cancel.setObjectName("dlgBtnCancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_confirm = QtWidgets.QPushButton("✓ Confirm")
        btn_confirm.setFixedHeight(30)
        btn_confirm.setObjectName("dlgBtnConfirm")
        btn_confirm.clicked.connect(self.accept)
        btn_row.addWidget(btn_confirm)

        layout.addLayout(btn_row)


# ============================================================
# node pathsupplementallpopupoutbox
# ============================================================

class NodeCompleterPopup(QtWidgets.QListWidget):
    """node pathautosupplementallpopupoutwindow — ininput @ whenshowscenenodelist"""

    pathSelected = QtCore.Signal(str)  # userselectedonenode path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(QtCore.Qt.ToolTip | QtCore.Qt.FramelessWindowHint)
        self.setFixedWidth(320)
        self.setMaximumHeight(200)
        self.setObjectName("nodeCompleter")
        self.itemActivated.connect(self._on_item_activated)
        self.setVisible(False)
        self._all_paths: list = []

    def set_node_paths(self, paths: list):
        """setoptional node pathlist"""
        self._all_paths = paths

    def show_filtered(self, prefix: str, anchor_widget: QtWidgets.QWidget, cursor_rect):
        """based onprefixfilterandshow"""
        self.clear()
        lower_prefix = prefix.lower()
        matches = [p for p in self._all_paths if lower_prefix in p.lower()][:30]
        if not matches:
            self.setVisible(False)
            return
        for p in matches:
            self.addItem(p)
        # fixedbittocursorbelowway
        global_pos = anchor_widget.mapToGlobal(cursor_rect.bottomLeft())
        self.move(global_pos.x(), global_pos.y() + 4)
        self.setVisible(True)
        self.setCurrentRow(0)

    def _on_item_activated(self, item):
        self.pathSelected.emit(item.text())
        self.setVisible(False)

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            current = self.currentItem()
            if current:
                self.pathSelected.emit(current.text())
                self.setVisible(False)
                return
        elif event.key() == QtCore.Qt.Key_Escape:
            self.setVisible(False)
            return
        super().keyPressEvent(event)


# ============================================================
# slashcommandcommandpopupoutbox
# ============================================================

# ── slashcommandcommandregistertable ──
# each: (command, icon, label_zh, label_en, description_zh, description_en, category)
SLASH_COMMANDS = [
    # ── sessionmanage ──
    ("clear",     "🗑",  "clearemptyconversation",     "Clear Chat",      "clearemptycurrentconversationhistory",           "Clear current conversation",   "session"),
    ("new",       "✨",  "createsession",     "New Chat",         "createonenewconversation",           "Create a new conversation",    "session"),
    # ── memorysystem ──
    ("memory",    "🧠",  "memorystate",     "Memory Status",    "viewlong-termmemorystatisticsandcorememory", "View memory stats & core memories", "memory"),
    ("remember",  "📌",  "rememberpreference",     "Remember",         "willcontentwritecorememory",         "Save content to core memory",  "memory"),
    ("forget",    "🧹",  "clearremovememory",     "Forget",           "searchanddeletespecifiedmemory",         "Search and delete a memory",   "memory"),
    ("search_mem","🔍",  "searchmemory",     "Search Memory",    "inlong-termmemoryinsearch",           "Search long-term memory",      "memory"),
    ("memories",  "📚",  "memorylibrary",       "Memory Library",   "openmemory managementwindow",         "Open memory manager (full CRUD)", "memory"),
    # ── Houdini scene ──
    ("network",   "🌐",  "readnetwork",     "Read Network",     "readcurrentnetworkstructure",           "Read current network structure","scene"),
    ("selection", "👆",  "readselected",     "Read Selection",   "readcurrentselectednodeinfo",       "Read selected node info",      "scene"),
    ("skills",    "⚡",  "skillcanlist",     "List Skills",      "columnoutallcanuse Skill",         "List all available skills",    "scene"),
    # ── tool ──
    ("status",    "📊",  "systemstate",     "System Status",    "viewmemory/growth/contextstatistics",   "View memory/growth/context stats", "tool"),
    ("export",    "💾",  "importouttraining",     "Export Training",  "importoutconversationastrainingdata",         "Export conversation as training data", "tool"),
    ("image",     "🖼",  "attachimage",     "Attach Image",     "fromfileselectimageattachtomessage",   "Select image to attach",       "tool"),
    ("help",      "❓",  "help",         "Help",             "showallcanuseslashcommandcommand",       "Show all available commands",   "tool"),
]

# bypartclassgroup title
_SLASH_CATEGORY_LABELS = {
    "session": ("── session ──", "── Session ──"),
    "memory":  ("── memory ──", "── Memory ──"),
    "scene":   ("── scene ──", "── Scene ──"),
    "tool":    ("── tool ──", "── Tools ──"),
}


class SlashCommandPopup(QtWidgets.QListWidget):
    """slashcommandcommandpopupoutwindow — ininput / whenshowcanusecommandcommand"""

    commandSelected = QtCore.Signal(str)  # userselectedonecommandcommandname

    def __init__(self, parent=None):
        super().__init__(parent)
        self._flags_applied = False
        self.setFixedWidth(300)
        self.setMaximumHeight(320)
        self.setObjectName("slashCompleter")
        self.itemActivated.connect(self._on_item_activated)
        self.setVisible(False)

    def show_filtered(self, prefix: str, anchor_widget: QtWidgets.QWidget,
                      cursor_rect, lang: str = 'zh'):
        """based onprefixfilterandshowcommandcommandlist"""
        if not self._flags_applied:
            self._flags_applied = True
            self.setWindowFlags(QtCore.Qt.ToolTip | QtCore.Qt.FramelessWindowHint)

        self.clear()
        lower_prefix = prefix.lower()
        is_zh = (lang == 'zh')

        # bypartclassgroup
        last_cat = None
        match_count = 0
        for cmd, icon, lbl_zh, lbl_en, desc_zh, desc_en, cat in SLASH_COMMANDS:
            label = lbl_zh if is_zh else lbl_en
            desc = desc_zh if is_zh else desc_en
            # matchcommandcommandname, label, description
            if lower_prefix and not any(lower_prefix in s.lower() for s in (cmd, label, desc)):
                continue
            # partclasstitle
            if cat != last_cat:
                last_cat = cat
                cat_label = _SLASH_CATEGORY_LABELS.get(cat, ("──", "──"))
                header_item = QtWidgets.QListWidgetItem(cat_label[0] if is_zh else cat_label[1])
                header_item.setFlags(QtCore.Qt.NoItemFlags)  # notoptional
                font = header_item.font()
                font.setPointSize(max(7, font.pointSize() - 1))
                header_item.setFont(font)
                header_item.setForeground(QtGui.QColor(120, 130, 160))
                self.addItem(header_item)
            # commandcommanditem
            display_text = f"{icon}  /{cmd}    {desc}"
            item = QtWidgets.QListWidgetItem(display_text)
            item.setData(QtCore.Qt.UserRole, cmd)
            self.addItem(item)
            match_count += 1

        if match_count == 0:
            self.setVisible(False)
            return

        # fixedbittocursorbelowway
        global_pos = anchor_widget.mapToGlobal(cursor_rect.bottomLeft())
        self.move(global_pos.x(), global_pos.y() + 4)
        # movestateadjustwholeheight
        row_h = 24
        total_h = min(320, (self.count()) * row_h + 12)
        self.setFixedHeight(max(80, total_h))
        self.setVisible(True)
        # selectedfirstnottitleitem
        for i in range(self.count()):
            if self.item(i).flags() & QtCore.Qt.ItemIsSelectable:
                self.setCurrentRow(i)
                break

    def _on_item_activated(self, item):
        cmd = item.data(QtCore.Qt.UserRole)
        if cmd:
            self.commandSelected.emit(cmd)
            self.setVisible(False)

    def select_next(self):
        """selectedbelowoneoptionalitem"""
        row = self.currentRow()
        for i in range(row + 1, self.count()):
            if self.item(i).flags() & QtCore.Qt.ItemIsSelectable:
                self.setCurrentRow(i)
                return

    def select_prev(self):
        """selectedononeoptionalitem"""
        row = self.currentRow()
        for i in range(row - 1, -1, -1):
            if self.item(i).flags() & QtCore.Qt.ItemIsSelectable:
                self.setCurrentRow(i)
                return

    def confirm_current(self) -> bool:
        """confirmcurrentselecteditem, returnwhethersucceeded"""
        current = self.currentItem()
        if current:
            cmd = current.data(QtCore.Qt.UserRole)
            if cmd:
                self.commandSelected.emit(cmd)
                self.setVisible(False)
                return True
        return False

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.confirm_current()
            return
        elif event.key() == QtCore.Qt.Key_Escape:
            self.setVisible(False)
            return
        super().keyPressEvent(event)


# ============================================================
# inputarea
# ============================================================

class ChatInput(QtWidgets.QPlainTextEdit):
    """chatinputbox — selfsuitshouldheight, supportautoswaprow, multirowinput, imagepaste/drag
    
    Core logic: count all visible lines in the document (including soft-wrap lines) and compute target height from line height,
    so the input box grows upward without hiding existing rows.
    support @node path supplementallandfrom Network Editor dragnode. 
    """
    
    sendRequested = QtCore.Signal()
    imageDropped = QtCore.Signal(QtGui.QImage)  # pasteordragimagewhentrigger
    atTriggered = QtCore.Signal(str, QtCore.QRect)  # @ triggersupplementall: (currentprefix, cursorrectangle)
    slashTriggered = QtCore.Signal(str, QtCore.QRect)  # / triggersupplementall: (currentprefix, cursorrectangle)
    
    _MIN_H = 44
    _MAX_H = 220
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(tr('placeholder'))
        # ensureautoswaprow
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        self.setWordWrapMode(QtGui.QTextOption.WrapAtWordBoundaryOrAnywhere)
        # Hide scrollbar (only appears when height is insufficient)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        # enabledrag
        self.setAcceptDrops(True)
        self.setObjectName("chatInput")
        self.setMinimumHeight(self._MIN_H)
        self.setMaximumHeight(self._MAX_H)
        
        # ★ PySide2 / PySide6 cross-platform IME support (Chinese / Japanese / Korean)
        # ------------------------------------------------------------------
        # issuebackground: 
        #   PySide2 embed Houdini when, macOS / Windows oninputmethodmaynotactivate. 
        #   macOS NSTextInputClient protocol depends heavily on inputMethodQuery return values
        #   correct cursorrectangle/surroundingtext/cursorpositionetc.info, otherwise IME waitselectwindow
        #   cannot be positioned correctly — or worse, the popup never appears.
        # ------------------------------------------------------------------
        # 1. explicitenableinputmethod
        self.setAttribute(QtCore.Qt.WA_InputMethodEnabled, True)
        # 2. explicitsetfocuspointstrategy, ensure Tab/Click allcangetfocuspoint
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        # 3. setinputmethodhint: selfbytext
        try:
            self.setInputMethodHints(QtCore.Qt.ImhNone)
        except Exception:
            pass  # A few PySide2 versions do not support this call
        # 4. macOS specialhas: ensurefocuspointrectanglecansee (someembedscenebelowdefaultclose) 
        try:
            self.setAttribute(QtCore.Qt.WA_MacShowFocusRect, True)
        except Exception:
            pass
        
        # use textChanged, andlatencytobelowoneeventloopexecute (ensurelayoutfirstcomplete) 
        self.textChanged.connect(self._schedule_adjust)
        self.textChanged.connect(self._check_at_trigger)
        self.textChanged.connect(self._check_slash_trigger)
        # @ supplementallstate
        self._at_active = False
        self._at_start_pos = -1
        self._completer_popup: 'NodeCompleterPopup | None' = None
        # / slashcommandcommandsupplementallstate
        self._slash_active = False
        self._slash_start_pos = -1
        self._slash_popup: 'SlashCommandPopup | None' = None
        # ★ IME pre-editstatetrace
        self._ime_composing = False
    
    def set_completer_popup(self, popup: 'NodeCompleterPopup'):
        """Set node-completion popup reference, used for keyboard navigation and auto-close."""
        self._completer_popup = popup

    def set_slash_popup(self, popup: 'SlashCommandPopup'):
        """setslashcommandcommandpopupoutboxreference"""
        self._slash_popup = popup
    
    def _schedule_adjust(self):
        """latencyadjustwholeheight, ensuredocumentlayoutalreadyupdate"""
        QtCore.QTimer.singleShot(0, self._adjust_height)
    
    def _adjust_height(self):
        """Auto-adjust height based on visual line count (including soft-wraps) — growing upward."""
        doc = self.document()
        # Count all visible lines (including soft-wrap lines from word-wrap)
        visual_lines = 0
        block = doc.begin()
        while block.isValid():
            bl = block.layout()
            if bl and bl.lineCount() > 0:
                visual_lines += bl.lineCount()
            else:
                visual_lines += 1
            block = block.next()
        # Empty document still counts as at least 1 row
        visual_lines = max(1, visual_lines)
        
        # rowhigh
        line_h = self.fontMetrics().lineSpacing()
        # contentheight = rowcount * rowhigh
        content_h = visual_lines * line_h
        # addon padding(8*2) + border(1*2) + extraremainingquantity
        margins = self.contentsMargins()
        frame_w = self.frameWidth()
        padding = margins.top() + margins.bottom() + frame_w * 2 + 18
        total = content_h + padding
        
        h = max(self._MIN_H, min(self._MAX_H, total))
        if h != self.height():
            self.setFixedHeight(h)
            # notifyparentlayoutrenewpartmatchemptybetween
            self.updateGeometry()
    
    def _hide_completer(self):
        """hidesupplementallpopupoutbox"""
        if self._completer_popup and self._completer_popup.isVisible():
            self._completer_popup.setVisible(False)

    def _check_at_trigger(self):
        """detectinputin  @ character, triggernode pathsupplementall"""
        cursor = self.textCursor()
        pos = cursor.position()
        text = self.toPlainText()
        if not text or pos == 0:
            if self._at_active:
                self._at_active = False
                self._hide_completer()
            return

        # lookupcursorpreviousrecent  @
        left = text[:pos]
        at_idx = left.rfind('@')
        if at_idx == -1:
            if self._at_active:
                self._at_active = False
                self._hide_completer()
            return

        # Content after @ cannot contain whitespace (otherwise treated as end of mention)
        prefix_after_at = left[at_idx + 1:]
        if ' ' in prefix_after_at or '\n' in prefix_after_at:
            if self._at_active:
                self._at_active = False
                self._hide_completer()
            return

        self._at_active = True
        self._at_start_pos = at_idx
        # Emit signal so the outer ai_tab can supply the node list
        crect = self.cursorRect(cursor)
        self.atTriggered.emit(prefix_after_at, crect)

    def cancel_at_completion(self):
        """cancelcurrent @ supplementallandhidepopupoutbox"""
        self._at_active = False
        self._at_start_pos = -1
        self._hide_completer()

    def insert_at_completion(self, path: str):
        """willsupplementallresultinserttext, replaceswap @prefix"""
        if self._at_start_pos < 0:
            return
        cursor = self.textCursor()
        pos = cursor.position()
        # selectedfrom @ tocurrentposition textandreplaceswap
        cursor.setPosition(self._at_start_pos)
        cursor.setPosition(pos, QtGui.QTextCursor.KeepAnchor)
        cursor.insertText(path + " ")
        self.setTextCursor(cursor)
        self._at_active = False
        self._at_start_pos = -1

    def _is_completer_visible(self) -> bool:
        """supplementallpopupoutboxwhethercansee"""
        return (self._completer_popup is not None
                and self._completer_popup.isVisible()
                and self._completer_popup.count() > 0)

    # ---- slashcommandcommandsupplementall ----

    def _check_slash_trigger(self):
        """detectinputin  / character, triggerslashcommandcommandsupplementall (onlyinrowfirstorpure / startwhentrigger) """
        cursor = self.textCursor()
        pos = cursor.position()
        text = self.toPlainText()

        if not text or pos == 0:
            if self._slash_active:
                self._slash_active = False
                self._hide_slash()
            return

        # onlywhen / intextmoststartwhentrigger (wholeinputas /xxx) 
        if not text.startswith('/'):
            if self._slash_active:
                self._slash_active = False
                self._hide_slash()
            return

        # extract / aftertocursorposition content
        prefix_after_slash = text[1:pos]
        # ifpackagecontainingemptygridorswaprow, descriptionalreadyexceedoutcommandcommandnamerange
        if ' ' in prefix_after_slash or '\n' in prefix_after_slash:
            if self._slash_active:
                self._slash_active = False
                self._hide_slash()
            return

        self._slash_active = True
        self._slash_start_pos = 0
        crect = self.cursorRect(cursor)
        self.slashTriggered.emit(prefix_after_slash, crect)

    def _hide_slash(self):
        """hideslashcommandcommandpopupoutbox"""
        if self._slash_popup and self._slash_popup.isVisible():
            self._slash_popup.setVisible(False)

    def cancel_slash_completion(self):
        """cancelcurrentslashcommandcommandsupplementall"""
        self._slash_active = False
        self._slash_start_pos = -1
        self._hide_slash()

    def insert_slash_completion(self, command: str):
        """slashcommandcommandisselectedafter, clearemptyinputbox (commandcommandwilldirectlyexecute, notneedskeeptext) """
        self.clear()
        self._slash_active = False
        self._slash_start_pos = -1

    def _is_slash_visible(self) -> bool:
        """slashcommandcommandpopupoutboxwhethercansee"""
        return (self._slash_popup is not None
                and self._slash_popup.isVisible()
                and self._slash_popup.count() > 0)

    def inputMethodQuery(self, query):
        """★ macOS IME keyfix: asinputmethodraiseforcursorpositionandsurroundingtextinfo
        
        The macOS input-method framework (NSTextInputClient protocol) queries this method:
          - ImEnabled       → thiswidgetwhetheracceptinputmethodinput
          - ImCursorRectangle → cursorinwidgetin rectanglearea (used forfixedbitwaitselectbox) 
          - ImSurroundingText -> text around the cursor (helps association / smart word picking)
          - ImCursorPosition  → cursorinsurroundingtextin position
          - ImFont           → currentfontinfo
          - ImHints          → inputmethodhint
        
        If we do not override this method, PySide2 embedded in Houdini (especially on macOS)
        may return wrong values or zero rectangles, causing the IME to not activate or the candidate box position to be wrong.
        """
        qt = QtCore.Qt
        if query == qt.ImEnabled:
            return True
        if query == qt.ImCursorRectangle:
            # Return the cursor rectangle in the widget coordinate system
            cursor_rect = self.cursorRect()
            return cursor_rect
        if query == qt.ImFont:
            return self.font()
        if query == qt.ImCursorPosition:
            tc = self.textCursor()
            block = tc.block()
            return tc.position() - block.position()
        if query == qt.ImSurroundingText:
            tc = self.textCursor()
            block = tc.block()
            return block.text()
        if query == qt.ImCurrentSelection:
            tc = self.textCursor()
            return tc.selectedText()
        try:
            if query == qt.ImHints:
                return qt.ImhNone
        except Exception:
            pass
        # otherquerysubmitgiveparentclass
        return super().inputMethodQuery(query)

    def inputMethodEvent(self, event):
        """★ IME input-method event handling (Chinese / Japanese / Korean etc.) — cross-platform hardened version.
        
        PySide2 in Houdini environmentbelowneedsexplicitprocess inputMethodEvent, 
        otherwiseintextinputmethod pre-edit (composing) andraisesubmit (commit) maynomethodnormalwork. 
        
        IME workflow: 
        1. User starts entering pinyin -> preeditString non-empty (composing state)
        2. userselectwaitselectword → commitString non-empty, preeditString clearempty
        3. userby Esc cancel → preeditString clearempty, commitString asempty
        
        macOS special note:
        - some PySide2 versionin macOS onnotwillcorrectpassdeliver commit event
        - needsensure commitString ismanualinserttextcursor
        """
        preedit = event.preeditString()
        commit = event.commitString()
        
        # update composing state
        self._ime_composing = bool(preedit)
        
        # firstletparentclassprocess (standardpath) 
        super().inputMethodEvent(event)
        
        # macOS PySide2 fixsupplement: ifparentclassnothascorrectprocess commitString, 
        # manualwillalreadyconfirm textinsertcursorposition. 
        # Sanity check: if there is commit text but it cannot be found in the current text (meaning the parent class missed it),
        # thenmanualinsert. 
        if commit and not preedit:
            tc = self.textCursor()
            current_text = self.toPlainText()
            # simplecheck: if commit  textincursorpositionbeforedoes not exist, manualinsert
            # Note: this is a conservative check — only kicks in when the parent class certainly did not handle the event
            pos = tc.position()
            before = current_text[:pos]
            if not before.endswith(commit):
                tc.insertText(commit)
                self.setTextCursor(tc)
    
    def keyPressEvent(self, event):
        key = event.key()
        
        # ★ IME composing in: notinterceptcutanybykey, allpartsubmitgiveinputmethodprocess
        # While the user is composing pinyin / selecting candidates, Enter/Esc etc. should be handled by the IME,
        # andnotrigger"sendmessage"or"cancelsupplementall"
        if self._ime_composing:
            super().keyPressEvent(event)
            return
        
        # ── @ supplementallactivewhen keydiskprocess ──
        if self._at_active and self._is_completer_visible():
            popup = self._completer_popup
            
            if key == QtCore.Qt.Key_Escape:
                # Escape: cancelsupplementall + hidepopupwindow
                self.cancel_at_completion()
                return
            
            if key == QtCore.Qt.Key_Up:
                # Up: inlistinonmove
                row = popup.currentRow()
                if row > 0:
                    popup.setCurrentRow(row - 1)
                return
            
            if key == QtCore.Qt.Key_Down:
                # Down: inlistinbelowmove
                row = popup.currentRow()
                if row < popup.count() - 1:
                    popup.setCurrentRow(row + 1)
                return
            
            if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and not (event.modifiers() & QtCore.Qt.ShiftModifier):
                # Enter: selectedcurrentitem (andnotsendmessage) 
                current = popup.currentItem()
                if current:
                    self.insert_at_completion(current.text())
                    self._hide_completer()
                return
            
            if key == QtCore.Qt.Key_Tab:
                # Tab: alsocanselectedcurrentitem
                current = popup.currentItem()
                if current:
                    self.insert_at_completion(current.text())
                    self._hide_completer()
                return
        
        elif self._at_active and key == QtCore.Qt.Key_Escape:
            # supplementallactivebutpopupwindownotcansee (such asnomatchresult) : stillallow Escape cancel
            self.cancel_at_completion()
            return

        # ── / slashcommandcommandsupplementallactivewhen keydiskprocess ──
        if self._slash_active and self._is_slash_visible():
            popup = self._slash_popup

            if key == QtCore.Qt.Key_Escape:
                self.cancel_slash_completion()
                return

            if key == QtCore.Qt.Key_Up:
                popup.select_prev()
                return

            if key == QtCore.Qt.Key_Down:
                popup.select_next()
                return

            if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and not (event.modifiers() & QtCore.Qt.ShiftModifier):
                if popup.confirm_current():
                    return

            if key == QtCore.Qt.Key_Tab:
                if popup.confirm_current():
                    return

        elif self._slash_active and key == QtCore.Qt.Key_Escape:
            self.cancel_slash_completion()
            return

        # ── commonrulekeydiskprocess ──
        if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            if event.modifiers() & QtCore.Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.sendRequested.emit()
                return
        
        super().keyPressEvent(event)
    
    def mousePressEvent(self, event):
        """clicktextareawhen, ifsupplementallpopupwindowcanseethenclose"""
        if self._is_completer_visible():
            self.cancel_at_completion()
        if self._is_slash_visible():
            self.cancel_slash_completion()
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        """★ On focus-in, ensure the IME activates correctly (macOS key fix).
        
        On macOS, when QPlainTextEdit is embedded in a host application like Houdini,
        the IME may not auto-activate on focus-in. By explicitly calling update() and
        renewset WA_InputMethodEnabled, forcesystemrenewcheck IME state. 
        """
        super().focusInEvent(event)
        # ensure IME flagstillthenvalid
        self.setAttribute(QtCore.Qt.WA_InputMethodEnabled, True)
        # triggerwidgetredraw, betweenconnectnotifysystemrenewquery inputMethodQuery
        self.update()

    def focusOutEvent(self, event):
        """On focus-out, close the completion popup and reset IME state."""
        self._ime_composing = False  # replace IME state
        # Delayed close: if focus shifted to the popup itself (user clicked the popup), do not close
        QtCore.QTimer.singleShot(100, self._check_focus_dismiss)
        super().focusOutEvent(event)

    def _check_focus_dismiss(self):
        """Check whether to close the popup due to focus-out."""
        if not self.hasFocus():
            if self._is_completer_visible():
                if self._completer_popup and not self._completer_popup.hasFocus():
                    self.cancel_at_completion()
            if self._is_slash_visible():
                if self._slash_popup and not self._slash_popup.hasFocus():
                    self.cancel_slash_completion()

    def resizeEvent(self, event):
        """Recompute height when window width changes (auto-wrap may change the row count)."""
        super().resizeEvent(event)
        self._schedule_adjust()

    # ---- dragnodesupport ----
    
    def dragEnterEvent(self, event):
        """acceptcomeself Houdini Network Editor  node pathdrag"""
        mime = event.mimeData()
        if mime.hasText():
            text = mime.text().strip()
            # checkwhetherlike Houdini node path
            if text.startswith('/') and '/' in text[1:]:
                event.acceptProposedAction()
                return
        # alsoacceptimagedrag (originalhaslogic) 
        if mime.hasImage() or mime.hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event):
        """dragreleaseput: preferredchecknode path, itstimeprocessimage"""
        mime = event.mimeData()
        # 1) Houdini node pathdrag
        if mime.hasText():
            text = mime.text().strip()
            if text.startswith('/') and '/' in text[1:]:
                cursor = self.cursorForPosition(
                    event.position().toPoint() if hasattr(event.position(), 'toPoint') else event.pos()
                )
                cursor.insertText(text + " ")
                self.setTextCursor(cursor)
                event.acceptProposedAction()
                return
        # 2) imagedrag
        if mime.hasImage():
            image = mime.imageData()
            if image and not image.isNull():
                self.imageDropped.emit(image)
                event.acceptProposedAction()
                return
        if mime.hasUrls():
            _IMG_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
            for url in mime.urls():
                if url.isLocalFile():
                    import os
                    ext = os.path.splitext(url.toLocalFile())[1].lower()
                    if ext in _IMG_EXTS:
                        img = QtGui.QImage(url.toLocalFile())
                        if not img.isNull():
                            self.imageDropped.emit(img)
                            event.acceptProposedAction()
                            return
        super().dropEvent(event)
    
    # ---- imagepastesupport ----
    
    def insertFromMimeData(self, source):
        """Override paste: support pasting images from the clipboard."""
        if source.hasImage():
            image = source.imageData()
            if image and not image.isNull():
                self.imageDropped.emit(image)
                return
        # pastefile pathin image
        if source.hasUrls():
            _IMG_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
            for url in source.urls():
                if url.isLocalFile():
                    import os
                    ext = os.path.splitext(url.toLocalFile())[1].lower()
                    if ext in _IMG_EXTS:
                        img = QtGui.QImage(url.toLocalFile())
                        if not img.isNull():
                            self.imageDropped.emit(img)
                            return
        # defaulttextpaste
        super().insertFromMimeData(source)


# ============================================================
# stopbutton
# ============================================================

class StopButton(QtWidgets.QPushButton):
    """stopbutton"""
    
    def __init__(self, parent=None):
        super().__init__("Stop", parent)
        self.setObjectName("btnStop")


# ============================================================
# sendbutton
# ============================================================

class SendButton(QtWidgets.QPushButton):
    """sendbutton"""
    
    def __init__(self, parent=None):
        super().__init__("Send", parent)
        self.setObjectName("btnSend")


# ============================================================
# Todo system
# ============================================================

class TodoItem(QtWidgets.QWidget):
    """single Todo item"""
    
    statusChanged = QtCore.Signal(str, str)
    
    def __init__(self, todo_id: str, text: str, status: str = "pending", parent=None):
        super().__init__(parent)
        self.todo_id = todo_id
        self.text = text
        self.status = status
        
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(4)
        
        self.status_label = QtWidgets.QLabel()
        self.status_label.setFixedWidth(14)
        layout.addWidget(self.status_label)
        
        self.text_label = QtWidgets.QLabel(text)
        self.text_label.setWordWrap(True)
        layout.addWidget(self.text_label, 1)
        
        self._update_style()
    
    def _update_style(self):
        icons = {
            "pending": "○",
            "in_progress": "◎", 
            "done": "●",
            "error": "✗"
        }
        
        icon = icons.get(self.status, "○")
        
        self.status_label.setText(icon)
        self.status_label.setObjectName("todoStatusIcon")
        self.status_label.setProperty("state", self.status)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        
        self.text_label.setObjectName("todoText")
        self.text_label.setProperty("state", self.status)
        self.text_label.style().unpolish(self.text_label)
        self.text_label.style().polish(self.text_label)
    
    def set_status(self, status: str):
        self.status = status
        self._update_style()
        self.statusChanged.emit(self.todo_id, status)


class TodoList(QtWidgets.QWidget):
    """Todo list - show AI  taskcountplan (cardstyleboxbody) """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._todos = {}
        
        # Outermost layer has no spacing
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 4)
        outer.setSpacing(0)
        
        # cardcontain 
        self._card = QtWidgets.QFrame(self)
        self._card.setObjectName("todoCard")
        card_layout = QtWidgets.QVBoxLayout(self._card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(4)
        
        # titlerow
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(6)
        
        self.title_label = QtWidgets.QLabel("Todo")
        self.title_label.setObjectName("todoTitle")
        header.addWidget(self.title_label)
        
        self.count_label = QtWidgets.QLabel("0/0")
        self.count_label.setObjectName("todoCount")
        header.addWidget(self.count_label)
        
        header.addStretch()
        
        self.clear_btn = QtWidgets.QPushButton("Clear")
        self.clear_btn.setFixedHeight(20)
        self.clear_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.clear_btn.setObjectName("todoClearBtn")
        self.clear_btn.clicked.connect(self.clear_all)
        header.addWidget(self.clear_btn)
        
        card_layout.addLayout(header)
        
        # partintervalline
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setObjectName("todoSeparator")
        card_layout.addWidget(sep)
        
        # tasklist
        self.list_layout = QtWidgets.QVBoxLayout()
        self.list_layout.setSpacing(2)
        self.list_layout.setContentsMargins(0, 2, 0, 0)
        card_layout.addLayout(self.list_layout)
        
        outer.addWidget(self._card)
        self.setVisible(False)
    
    def add_todo(self, todo_id: str, text: str, status: str = "pending") -> TodoItem:
        if todo_id in self._todos:
            self._todos[todo_id].text_label.setText(text)
            self._todos[todo_id].set_status(status)
            return self._todos[todo_id]
        
        item = TodoItem(todo_id, text, status, self)
        self._todos[todo_id] = item
        self.list_layout.addWidget(item)
        self._update_count()
        self.setVisible(True)
        return item
    
    def update_todo(self, todo_id: str, status: str):
        if todo_id in self._todos:
            self._todos[todo_id].set_status(status)
            self._update_count()
    
    def remove_todo(self, todo_id: str):
        if todo_id in self._todos:
            item = self._todos.pop(todo_id)
            item.deleteLater()
            self._update_count()
            if not self._todos:
                self.setVisible(False)
    
    def clear_all(self):
        for item in self._todos.values():
            item.deleteLater()
        self._todos.clear()
        self._update_count()
        self.setVisible(False)
    
    def _update_count(self):
        total = len(self._todos)
        done = sum(1 for item in self._todos.values() if item.status == "done")
        self.count_label.setText(f"{done}/{total}")
    
    def get_pending_todos(self) -> list:
        return [
            {"id": todo_id, "text": item.text, "status": item.status}
            for todo_id, item in self._todos.items()
            if item.status not in ("done", "error")
        ]
    
    def get_all_todos(self) -> list:
        return [
            {"id": todo_id, "text": item.text, "status": item.status}
            for todo_id, item in self._todos.items()
        ]
    
    def get_todos_data(self) -> list:
        """returncanordercolumnization  todo list (used forcachesave/restore) """
        return [
            {"id": todo_id, "text": item.text, "status": item.status}
            for todo_id, item in self._todos.items()
        ]

    def restore_todos(self, todos_data: list):
        """fromordercolumnizationdatarestore todo list"""
        if not todos_data:
            return
        for td in todos_data:
            tid = td.get('id', '')
            text = td.get('text', '')
            status = td.get('status', 'pending')
            if tid and text:
                self.add_todo(tid, text, status)

    def get_todos_summary(self) -> str:
        if not self._todos:
            return ""
        
        lines = ["Current Todo List:"]
        for todo_id, item in self._todos.items():
            status_icons = {
                "pending": "[ ]",
                "in_progress": "[~]",
                "done": "[x]",
                "error": "[!]"
            }
            icon = status_icons.get(item.status, "[ ]")
            lines.append(f"  {icon} {item.text}")
        
        pending = [item for item in self._todos.values() if item.status == "pending"]
        if pending:
            lines.append(f"\nReminder: {len(pending)} tasks pending.")
        
        return "\n".join(lines)


# ============================================================
# Token Analytics Panel - modern minimalist visualization analysis panel
# ============================================================

class _BarWidget(QtWidgets.QWidget):
    """Horizontal bar widget — used to visualize token usage ratios."""

    def __init__(self, segments: list, max_val: float, parent=None):
        """
        segments: [(value, color_hex), ...]
        max_val: globalmaxvalue (used foralign) 
        """
        super().__init__(parent)
        self._segments = segments
        self._max = max(max_val, 1)
        self.setFixedHeight(14)
        self.setMinimumWidth(60)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        x = 0.0
        for val, color in self._segments:
            seg_w = (val / self._max) * w
            if seg_w < 0.5:
                continue
            painter.setBrush(QtGui.QColor(color))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRoundedRect(QtCore.QRectF(x, 1, seg_w, h - 2), 2, 2)
            x += seg_w
        painter.end()


class TokenAnalyticsPanel(QtWidgets.QDialog):
    """Token useanalyzepanel - align Cursor style

    newadd: 
    - Pre-estimated cost (based on actual model pricing)
    - inference Token (Reasoning) 
    - latency (Latency) 
    - eachrowcostuse
    - Currency toggle (USD / IDR) dengan live rate fetch
    """

    _COL_HEADERS = [
        "#", "Time", "Model", "Input", "Cache↓", "Cache↑",
        "Output", "Think", "Total", "Latency", "Cost", "",
    ]

    # ★ Module-level cache untuk USD→IDR rate (persists across dialog open/close)
    #   Tuple of (rate, fetched_timestamp). Cache valid for 1 hour.
    _idr_rate_cache = None
    _IDR_CACHE_TTL_SEC = 3600

    # Signal for thread-to-main-thread rate delivery
    rateFetched = QtCore.Signal(float, str)   # rate (0 = error), error_msg

    def __init__(self, call_records: list, token_stats: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Token usage analytics")
        self.setMinimumSize(920, 560)
        self.resize(1020, 640)
        self.setObjectName("tokenPanel")

        # State for currency switching
        self._records = call_records
        self._stats = token_stats
        self._currency = "USD"          # "USD" | "IDR"
        self._idr_rate = 0.0            # USD → IDR multiplier (0 = not loaded yet)
        # Hydrate from cache if still fresh
        if TokenAnalyticsPanel._idr_rate_cache:
            rate, ts = TokenAnalyticsPanel._idr_rate_cache
            if (time.time() - ts) < self._IDR_CACHE_TTL_SEC and rate > 0:
                self._idr_rate = rate

        # Connect cross-thread signal
        self.rateFetched.connect(self._on_rate_fetched)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        # ---- summarycard ----
        self._summary_card = self._build_summary(call_records, token_stats)
        root.addWidget(self._summary_card)

        # ---- callclearfinetable ----
        root.addWidget(self._build_table(call_records), 1)

        # ---- bottompartbutton + Currency selector ----
        self.should_reset_stats = False
        foot = QtWidgets.QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(10)

        reset_btn = QtWidgets.QPushButton("Reset stats")
        reset_btn.setFixedWidth(82)
        reset_btn.setObjectName("tokenResetBtn")
        reset_btn.clicked.connect(self._on_reset)
        foot.addWidget(reset_btn)

        # Currency selector chip
        cur_lbl = QtWidgets.QLabel("Currency:")
        cur_lbl.setObjectName("tokenCurrencyLabel")
        cur_lbl.setStyleSheet(f"color:{CursorTheme.TEXT_MUTED}; font-size:11px;")
        foot.addWidget(cur_lbl)

        self._currency_combo = QtWidgets.QComboBox()
        self._currency_combo.setObjectName("tokenCurrencyCombo")
        self._currency_combo.addItem("USD ($)", "USD")
        self._currency_combo.addItem("IDR (Rp)", "IDR")
        self._currency_combo.setFixedWidth(96)
        self._currency_combo.setFixedHeight(26)
        self._currency_combo.setStyleSheet(
            "QComboBox#tokenCurrencyCombo {"
            "  background: rgba(22,24,42,200);"
            "  border: 1px solid rgba(255,255,255,28);"
            "  border-radius: 13px;"
            "  padding: 2px 10px;"
            "  color: #e2e8f0;"
            "  font-size: 11px;"
            "}"
            "QComboBox#tokenCurrencyCombo:hover {"
            "  border-color: rgba(251,122,26,180);"
            "}"
            "QComboBox#tokenCurrencyCombo::drop-down {"
            "  border: none; width: 18px;"
            "}"
        )
        self._currency_combo.currentIndexChanged.connect(self._on_currency_changed)
        foot.addWidget(self._currency_combo)

        # Rate hint label (shows live rate or "Fetching...")
        self._rate_hint = QtWidgets.QLabel("")
        self._rate_hint.setObjectName("tokenRateHint")
        self._rate_hint.setStyleSheet(
            f"color:{CursorTheme.TEXT_MUTED}; font-size:10px; padding-left:4px;"
        )
        foot.addWidget(self._rate_hint)

        foot.addStretch()
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.setFixedWidth(72)
        close_btn.setObjectName("tokenCloseBtn")
        close_btn.clicked.connect(self.accept)
        foot.addWidget(close_btn)
        root.addLayout(foot)

    def _on_reset(self):
        """userclickreplacebutton"""
        self.should_reset_stats = True
        self.accept()

    # ---- Currency handling ----------------------------------------------

    def _format_cost(self, usd_amount: float) -> str:
        """Format a USD amount according to current selected currency."""
        if usd_amount <= 0:
            return "Rp 0" if self._currency == "IDR" else "$0.00"
        if self._currency == "IDR":
            if self._idr_rate <= 0:
                # Rate not loaded yet — fall back to USD with marker
                return f"${usd_amount:.4f}*"
            idr = usd_amount * self._idr_rate
            # Indonesian-style formatting (dot thousands separator)
            if idr >= 1_000_000:
                return f"Rp {idr/1_000_000:.2f}M"
            elif idr >= 1_000:
                return f"Rp {int(round(idr)):,}".replace(",", ".")
            else:
                return f"Rp {int(round(idr))}"
        # USD
        if usd_amount >= 1.0:
            return f"${usd_amount:.2f}"
        else:
            return f"${usd_amount:.4f}"

    def _on_currency_changed(self, idx: int):
        new_cur = self._currency_combo.itemData(idx) or "USD"
        self._currency = new_cur
        if new_cur == "IDR" and self._idr_rate <= 0:
            self._rate_hint.setText("Fetching live rate…")
            self._start_idr_rate_fetch()
        elif new_cur == "IDR":
            self._update_rate_hint()
        else:
            self._rate_hint.setText("")
        self._rebuild_dynamic_displays()

    def _update_rate_hint(self):
        if self._currency != "IDR" or self._idr_rate <= 0:
            self._rate_hint.setText("")
            return
        # Show "1 USD = Rp 15.800 (live)"
        rate_int = int(round(self._idr_rate))
        rate_fmt = f"{rate_int:,}".replace(",", ".")
        self._rate_hint.setText(f"1 USD = Rp {rate_fmt} (live, cached 1h)")

    def _start_idr_rate_fetch(self):
        """Fetch USD→IDR rate in a background thread, emit rateFetched on done."""
        import threading
        t = threading.Thread(target=self._fetch_idr_rate_blocking, daemon=True)
        t.start()

    def _fetch_idr_rate_blocking(self):
        """Runs in worker thread — fetches rate from open.er-api.com (free, no API key)."""
        try:
            import urllib.request, json, ssl
            ctx = ssl.create_default_context()
            try:
                # Some embedded Python installs have an outdated CA bundle
                ctx.check_hostname = True
                ctx.verify_mode = ssl.CERT_REQUIRED
            except Exception:
                pass
            req = urllib.request.Request(
                "https://open.er-api.com/v6/latest/USD",
                headers={'User-Agent': 'MorfyAI/1.2 (TokenAnalytics)'}
            )
            with urllib.request.urlopen(req, timeout=6, context=ctx) as resp:
                raw = resp.read().decode('utf-8')
            data = json.loads(raw)
            rate = float(data.get('rates', {}).get('IDR', 0))
            if rate <= 0:
                self.rateFetched.emit(0.0, "IDR rate not in API response")
                return
            # Update module-level cache
            TokenAnalyticsPanel._idr_rate_cache = (rate, time.time())
            self.rateFetched.emit(rate, "")
        except Exception as e:
            self.rateFetched.emit(0.0, f"{type(e).__name__}: {e}")

    @QtCore.Slot(float, str)
    def _on_rate_fetched(self, rate: float, err: str):
        if rate > 0:
            self._idr_rate = rate
            self._update_rate_hint()
            self._rebuild_dynamic_displays()
        else:
            self._rate_hint.setText(f"Rate fetch failed — {err[:48]}")
            # Revert to USD
            try:
                self._currency_combo.blockSignals(True)
                self._currency_combo.setCurrentIndex(0)
                self._currency = "USD"
            finally:
                self._currency_combo.blockSignals(False)

    def _rebuild_dynamic_displays(self):
        """Re-render the summary card (where Est. Cost lives) and the cost
        column in the detail table whenever currency changes.
        """
        try:
            new_summary = self._build_summary(self._records, self._stats)
            # Swap the old summary card with the new one
            root = self.layout()
            old = self._summary_card
            root.replaceWidget(old, new_summary)
            old.setParent(None)
            old.deleteLater()
            self._summary_card = new_summary
            # Re-render cost cells in the detail table by rebuilding it
            # (rows reference _format_cost via record loop)
            # For simplicity: leave the table content as-is but trigger a
            # full repaint — the per-row cost is generated in _make_record_row
            # which uses _format_cost; rebuilding only requires re-running that.
            self._refresh_table_costs()
        except Exception:
            pass

    def _refresh_table_costs(self):
        """Update the cost column (index 10) in every existing data row."""
        try:
            for row_w in self.findChildren(QtWidgets.QWidget, "tokenDataRow"):
                # Each row's children are the 12 cell QLabels in order.
                labels = row_w.findChildren(QtWidgets.QLabel, "tokenDataCell")
                if len(labels) < 11:
                    continue
                # Read the original USD cost from the row's stored attribute
                usd_cost = getattr(row_w, '_usd_cost', None)
                if usd_cost is None:
                    continue
                cost_label = labels[10]
                cost_label.setText(self._format_cost(usd_cost) if usd_cost > 0 else "-")
        except Exception:
            pass

    # -------- summarysection --------
    def _build_summary(self, records, stats) -> QtWidgets.QWidget:
        card = QtWidgets.QFrame()
        card.setObjectName("tokenSummaryCard")
        grid = QtWidgets.QGridLayout(card)
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)

        total_in = stats.get('input_tokens', 0)
        total_out = stats.get('output_tokens', 0)
        reasoning = stats.get('reasoning_tokens', 0)
        cache_r = stats.get('cache_read', 0)
        cache_w = stats.get('cache_write', 0)
        reqs = stats.get('requests', 0)
        total = stats.get('total_tokens', 0)
        cost = stats.get('estimated_cost', 0.0)
        cache_total = cache_r + cache_w
        hit_rate = (cache_r / cache_total * 100) if cache_total > 0 else 0

        # averagelatency
        latencies = [r.get('latency', 0) for r in records if r.get('latency', 0) > 0]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0

        # costuseformatization — currency-aware (respects USD/IDR toggle)
        cost_str = self._format_cost(cost)

        metrics = [
            ("Requests",       f"{reqs}",               CursorTheme.ACCENT_BLUE),
            ("Input",          self._fmt_k(total_in),    CursorTheme.ACCENT_PURPLE),
            ("Output",         self._fmt_k(total_out),   CursorTheme.ACCENT_GREEN),
            ("Reasoning",      self._fmt_k(reasoning),   CursorTheme.ACCENT_YELLOW),
            ("Cache Hit",      self._fmt_k(cache_r),     "#10b981"),
            ("Hit Rate",       f"{hit_rate:.1f}%",       "#10b981"),
            ("Avg Latency",    f"{avg_latency:.1f}s",    CursorTheme.TEXT_SECONDARY),
            ("Est. Cost",      cost_str,                 CursorTheme.ACCENT_BLUE),
        ]
        for col, (label, value, color) in enumerate(metrics):
            lbl = QtWidgets.QLabel(label)
            lbl.setObjectName("tokenMetricLabel")
            lbl.setAlignment(QtCore.Qt.AlignCenter)
            grid.addWidget(lbl, 0, col)

            val = QtWidgets.QLabel(value)
            val.setObjectName("tokenMetricValue")
            # Per-metric dynamic color via inline (unique per column)
            val.setStyleSheet(f"color:{color};")
            val.setAlignment(QtCore.Qt.AlignCenter)
            grid.addWidget(val, 1, col)

        # progressitem: input vs output vs cache
        if total > 0:
            bar = _BarWidget([
                (cache_r, "#10b981"),
                (cache_w, CursorTheme.ACCENT_ORANGE),
                (max(total_in - cache_r - cache_w, 0), CursorTheme.ACCENT_PURPLE),
                (reasoning, CursorTheme.ACCENT_YELLOW),
                (max(total_out - reasoning, 0), CursorTheme.ACCENT_GREEN),
            ], total)
            bar.setFixedHeight(8)
            grid.addWidget(bar, 2, 0, 1, len(metrics))

        return card

    # -------- clearfinetable --------
    def _build_table(self, records) -> QtWidgets.QWidget:
        container = QtWidgets.QFrame()
        container.setObjectName("tokenTableCard")
        vbox = QtWidgets.QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # title
        title_lbl = QtWidgets.QLabel(f"  Call details ({len(records)} calls)")
        title_lbl.setObjectName("tokenTableTitle")
        vbox.addWidget(title_lbl)

        if not records:
            empty = QtWidgets.QLabel("  No API calls recorded yet")
            empty.setObjectName("tokenTableEmpty")
            vbox.addWidget(empty)
            return container

        # scrolltablegridarea
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setObjectName("chatScrollArea")

        table_widget = QtWidgets.QWidget()
        table_layout = QtWidgets.QVBoxLayout(table_widget)
        table_layout.setContentsMargins(8, 0, 8, 8)
        table_layout.setSpacing(0)

        # tablehead
        hdr = self._make_row_widget(self._COL_HEADERS, is_header=True)
        table_layout.addWidget(hdr)

        # Find max total for the bar chart
        max_total = max((r.get('total_tokens', 0) for r in records), default=1)

        # latest callshowinmostonface
        for display_idx, (orig_idx, rec) in enumerate(
            reversed(list(enumerate(records)))
        ):
            row = self._make_record_row(orig_idx, rec, max_total)
            table_layout.addWidget(row)

        table_layout.addStretch()
        scroll.setWidget(table_widget)
        vbox.addWidget(scroll, 1)

        return container

    # Column-width definitions
    _COL_WIDTHS = [24, 50, 90, 54, 54, 54, 54, 48, 54, 44, 52, 0]

    def _make_row_widget(self, cells: list, is_header=False) -> QtWidgets.QWidget:
        """createonerow (tableheadordatarow) """
        row_w = QtWidgets.QWidget()
        row_h = QtWidgets.QHBoxLayout(row_w)
        row_h.setContentsMargins(4, 3, 4, 3)
        row_h.setSpacing(2)

        font_size = "10px" if is_header else "11px"
        fg = CursorTheme.TEXT_MUTED if is_header else CursorTheme.TEXT_PRIMARY
        weight = "bold" if is_header else "normal"
        font_family = f"font-family:'Consolas','Monaco',monospace;" if not is_header else ""

        widths = self._COL_WIDTHS

        for i, text in enumerate(cells):
            lbl = QtWidgets.QLabel(str(text))
            lbl.setObjectName("tokenHeaderCell" if is_header else "tokenDataCell")
            if i < len(widths) and widths[i] > 0:
                lbl.setFixedWidth(widths[i])
            # countcharactercolumnrightalign
            lbl.setAlignment(QtCore.Qt.AlignRight if 3 <= i <= 10 else QtCore.Qt.AlignLeft)
            if i < len(widths) and widths[i] == 0:
                row_h.addWidget(lbl, 1)
            else:
                row_h.addWidget(lbl)

        if is_header:
            row_w.setObjectName("tokenHeaderRow")

        return row_w

    def _make_record_row(self, idx: int, rec: dict, max_total: float) -> QtWidgets.QWidget:
        """buildsingleitemrecordrow"""
        row_w = QtWidgets.QWidget()
        row_w.setObjectName("tokenDataRow")
        row_h = QtWidgets.QHBoxLayout(row_w)
        row_h.setContentsMargins(4, 2, 4, 2)
        row_h.setSpacing(2)

        ts = rec.get('timestamp', '')
        if len(ts) > 10:
            ts = ts[11:19]
        model = rec.get('model', '-')
        if len(model) > 12:
            model = model[:10] + '..'
        inp = rec.get('input_tokens', 0)
        c_hit = rec.get('cache_hit', 0)
        c_miss = rec.get('cache_miss', 0)
        out = rec.get('output_tokens', 0)
        reasoning = rec.get('reasoning_tokens', 0)
        total = rec.get('total_tokens', 0)
        latency = rec.get('latency', 0)

        # singletimecostuse (preferredusepre-computevalue) 
        row_cost = rec.get('estimated_cost', 0.0)
        if not row_cost:
            try:
                from morfyai.utils.token_optimizer import calculate_cost
                row_cost = calculate_cost(
                    model=rec.get('model', ''),
                    input_tokens=inp,
                    output_tokens=out,
                    cache_hit=c_hit,
                    cache_miss=c_miss,
                    reasoning_tokens=reasoning,
                )
            except Exception:
                row_cost = 0.0

        # Currency-aware row cost (uses dialog's current currency selection)
        cost_str = self._format_cost(row_cost) if row_cost > 0 else "-"
        latency_str = f"{latency:.1f}s" if latency > 0 else "-"

        # Store raw USD cost on row widget so currency toggles can re-format
        row_w._usd_cost = row_cost

        cells = [
            str(idx + 1),
            ts,
            model,
            self._fmt_k(inp),
            self._fmt_k(c_hit),
            self._fmt_k(c_miss),
            self._fmt_k(out),
            self._fmt_k(reasoning) if reasoning > 0 else "-",
            self._fmt_k(total),
            latency_str,
            cost_str,
        ]
        widths = self._COL_WIDTHS[:-1]  # removegolast  stretch
        colors = [
            CursorTheme.TEXT_MUTED,       # #
            CursorTheme.TEXT_MUTED,       # whenbetween
            CursorTheme.TEXT_PRIMARY,     # model
            CursorTheme.ACCENT_PURPLE,    # Input
            "#10b981",                    # Cache Hit
            CursorTheme.ACCENT_ORANGE,    # Cache Write
            CursorTheme.ACCENT_GREEN,     # Output
            CursorTheme.ACCENT_YELLOW,    # Reasoning
            CursorTheme.TEXT_BRIGHT,      # Total
            CursorTheme.TEXT_SECONDARY,   # latency
            CursorTheme.ACCENT_BLUE,      # costuse
        ]
        for i, text in enumerate(cells):
            lbl = QtWidgets.QLabel(text)
            lbl.setObjectName("tokenDataCell")
            if i < len(widths):
                lbl.setFixedWidth(widths[i])
            align = QtCore.Qt.AlignRight if i >= 3 else QtCore.Qt.AlignLeft
            lbl.setAlignment(align)
            c = colors[i] if i < len(colors) else CursorTheme.TEXT_PRIMARY
            # Per-column unique color via inline
            lbl.setStyleSheet(f"color:{c};")
            row_h.addWidget(lbl)

        # Mini bar chart
        bar = _BarWidget([
            (c_hit, "#10b981"),
            (c_miss, CursorTheme.ACCENT_ORANGE),
            (max(inp - c_hit - c_miss, 0), CursorTheme.ACCENT_PURPLE),
            (reasoning, CursorTheme.ACCENT_YELLOW),
            (max(out - reasoning, 0), CursorTheme.ACCENT_GREEN),
        ], max_total)
        row_h.addWidget(bar, 1)

        return row_w

    @staticmethod
    def _fmt_k(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 10_000:
            return f"{n / 1000:.1f}K"
        if n >= 1000:
            return f"{n / 1000:.1f}K"
        return str(n)


# ============================================================
# updatenotifybanner (startwhendetecttonewversion → inputsectiononwaybanner) 
# ============================================================

class UpdateNotificationBanner(QtWidgets.QFrame):
    """updatenotifybanner — ininputareaonwayshownewversionhint
    
    Lightweight banner; does not interrupt the chat flow.
    usercanclick"standi.e.update"orclosebanner. 
    supportshowupdatesummary (release_notes firstrow) . 
    """
    
    updateClicked = QtCore.Signal()   # click"standi.e.update"
    dismissClicked = QtCore.Signal()  # click"close"
    
    def __init__(self, remote_version: str, release_name: str = "",
                 local_version: str = "", release_notes: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("updateNotifyBanner")
        self.setVisible(False)  # defaulthide, byexternalcall show()
        
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(10, 5, 6, 5)
        row.setSpacing(8)
        
        # icon
        icon_lbl = QtWidgets.QLabel("🚀")
        icon_lbl.setFixedWidth(18)
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        row.addWidget(icon_lbl)
        
        # Left side: version + summary (vertically stacked)
        text_widget = QtWidgets.QWidget()
        text_layout = QtWidgets.QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        
        # versioninfotext
        info_text = tr('update.notify_banner', local_version, remote_version)
        if release_name:
            info_text += f"  —  {release_name}"
        info_lbl = QtWidgets.QLabel(info_text)
        info_lbl.setObjectName("updateNotifyInfo")
        info_lbl.setWordWrap(False)
        text_layout.addWidget(info_lbl)
        
        # updatesummary (firstrow, smallcharacter) 
        if release_notes and release_notes.strip():
            notes_lbl = QtWidgets.QLabel(release_notes.strip())
            notes_lbl.setObjectName("updateNotifyNotes")
            notes_lbl.setWordWrap(True)
            notes_lbl.setStyleSheet("color: inherit; opacity: 0.85; font-size: 0.92em;")
            text_layout.addWidget(notes_lbl)
        
        row.addWidget(text_widget, 1)
        
        # "standi.e.update" button
        update_btn = QtWidgets.QPushButton(tr('update.notify_update_now'))
        update_btn.setObjectName("updateNotifyBtn")
        update_btn.setCursor(QtCore.Qt.PointingHandCursor)
        update_btn.setFixedHeight(22)
        update_btn.clicked.connect(self.updateClicked.emit)
        row.addWidget(update_btn)
        
        # closebutton
        dismiss_btn = QtWidgets.QPushButton("✕")
        dismiss_btn.setObjectName("updateNotifyDismiss")
        dismiss_btn.setFixedSize(18, 18)
        dismiss_btn.setCursor(QtCore.Qt.PointingHandCursor)
        dismiss_btn.setToolTip(tr('update.notify_dismiss_tip'))
        dismiss_btn.clicked.connect(self._on_dismiss)
        row.addWidget(dismiss_btn)
    
    def _on_dismiss(self):
        self.setVisible(False)
        self.dismissClicked.emit()


# ============================================================
# Plugin Manager Dialog — pluginmanagepanel
# ============================================================

class PluginManagerDialog(QtWidgets.QDialog):
    """pluginmanagepanel

    Opened from the overflow menu; lists all plugins; supports enable/disable, reload, settings.
    """

    pluginStateChanged = QtCore.Signal()  # pluginstatechangeizationwhennotify

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pluginManagerDlg")
        self.setWindowTitle(tr('plugin.manager_title'))
        self.setMinimumSize(620, 480)
        self.resize(660, 520)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ═══════ Header titlebar ═══════
        header = QtWidgets.QFrame()
        header.setObjectName("pmHeader")
        header.setFixedHeight(44)
        header_lay = QtWidgets.QHBoxLayout(header)
        header_lay.setContentsMargins(16, 0, 16, 0)
        header_lay.setSpacing(8)

        title_lbl = QtWidgets.QLabel(f"🔌  {tr('plugin.manager_title')}")
        title_lbl.setObjectName("pmTitle")
        header_lay.addWidget(title_lbl)
        header_lay.addStretch()

        self._stats_label = QtWidgets.QLabel("")
        self._stats_label.setObjectName("pmStatsLabel")
        header_lay.addWidget(self._stats_label)

        root.addWidget(header)

        # ═══════ Tab Bar (underline style) ═══════
        self._tabs = QtWidgets.QTabWidget()
        self._tabs.setObjectName("pmTabs")
        self._tabs.setDocumentMode(True)  # godrop pane edgebox, morenowgeneration

        # ── Tab 1: Plugins ──
        plugins_page = QtWidgets.QWidget()
        plugins_page.setObjectName("pmTabPage")
        plugins_lay = QtWidgets.QVBoxLayout(plugins_page)
        plugins_lay.setContentsMargins(12, 10, 12, 6)
        plugins_lay.setSpacing(6)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("pmScroll")
        self._list_container = QtWidgets.QWidget()
        self._list_container.setObjectName("pmScrollInner")
        self._list_layout = QtWidgets.QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        scroll.setWidget(self._list_container)
        plugins_lay.addWidget(scroll, 1)

        self._tabs.addTab(plugins_page, f"  {tr('plugin.tab_plugins')}  ")

        # ── Tab 2: Tools ──
        tools_page = QtWidgets.QWidget()
        tools_page.setObjectName("pmTabPage")
        tools_lay = QtWidgets.QVBoxLayout(tools_page)
        tools_lay.setContentsMargins(12, 10, 12, 6)
        tools_lay.setSpacing(6)

        # searchbox
        self._tools_search = QtWidgets.QLineEdit()
        self._tools_search.setObjectName("pmSearchEdit")
        self._tools_search.setPlaceholderText(tr('plugin.search_tools'))
        self._tools_search.setClearButtonEnabled(True)
        self._tools_search.textChanged.connect(self._filter_tools)
        tools_lay.addWidget(self._tools_search)

        tools_scroll = QtWidgets.QScrollArea()
        tools_scroll.setWidgetResizable(True)
        tools_scroll.setObjectName("pmScroll")
        self._tools_container = QtWidgets.QWidget()
        self._tools_container.setObjectName("pmScrollInner")
        self._tools_layout = QtWidgets.QVBoxLayout(self._tools_container)
        self._tools_layout.setContentsMargins(0, 0, 0, 0)
        self._tools_layout.setSpacing(4)
        tools_scroll.setWidget(self._tools_container)
        tools_lay.addWidget(tools_scroll, 1)

        self._tabs.addTab(tools_page, f"  {tr('plugin.tab_tools')}  ")

        # ── Tab 3: Skills ──
        skills_page = QtWidgets.QWidget()
        skills_page.setObjectName("pmTabPage")
        skills_lay = QtWidgets.QVBoxLayout(skills_page)
        skills_lay.setContentsMargins(12, 10, 12, 6)
        skills_lay.setSpacing(6)

        skills_scroll = QtWidgets.QScrollArea()
        skills_scroll.setWidgetResizable(True)
        skills_scroll.setObjectName("pmScroll")
        self._skills_container = QtWidgets.QWidget()
        self._skills_container.setObjectName("pmScrollInner")
        self._skills_layout = QtWidgets.QVBoxLayout(self._skills_container)
        self._skills_layout.setContentsMargins(0, 0, 0, 0)
        self._skills_layout.setSpacing(6)
        skills_scroll.setWidget(self._skills_container)
        skills_lay.addWidget(skills_scroll, 1)

        # Skill directoryconfig
        skill_dir_frame = QtWidgets.QFrame()
        skill_dir_frame.setObjectName("pmSkillDirFrame")
        skill_dir_lay = QtWidgets.QHBoxLayout(skill_dir_frame)
        skill_dir_lay.setContentsMargins(10, 6, 10, 6)
        skill_dir_lay.setSpacing(8)
        skill_dir_icon = QtWidgets.QLabel("📁")
        skill_dir_icon.setStyleSheet("background: transparent; font-size: 13px;")
        skill_dir_lay.addWidget(skill_dir_icon)
        skill_dir_lbl = QtWidgets.QLabel(tr('plugin.skill_dir_label'))
        skill_dir_lbl.setObjectName("pmSubLabel")
        skill_dir_lay.addWidget(skill_dir_lbl)
        self._skill_dir_edit = QtWidgets.QLineEdit()
        self._skill_dir_edit.setObjectName("pmPathEdit")
        self._skill_dir_edit.setPlaceholderText(tr('plugin.skill_dir_placeholder'))
        self._skill_dir_edit.setReadOnly(True)
        skill_dir_lay.addWidget(self._skill_dir_edit, 1)
        btn_browse_skill = QtWidgets.QPushButton(tr('plugin.skill_dir_browse'))
        btn_browse_skill.setObjectName("pmBtnSecondary")
        btn_browse_skill.setCursor(QtCore.Qt.PointingHandCursor)
        btn_browse_skill.clicked.connect(self._browse_skill_dir)
        skill_dir_lay.addWidget(btn_browse_skill)
        skills_lay.addWidget(skill_dir_frame)

        self._tabs.addTab(skills_page, f"  {tr('plugin.tab_skills')}  ")

        root.addWidget(self._tabs, 1)

        # ═══════ Footer bottompartbar ═══════
        footer = QtWidgets.QFrame()
        footer.setObjectName("pmFooter")
        footer.setFixedHeight(42)
        footer_lay = QtWidgets.QHBoxLayout(footer)
        footer_lay.setContentsMargins(14, 0, 14, 0)
        footer_lay.setSpacing(8)

        btn_open_dir = QtWidgets.QPushButton(f"📂  {tr('plugin.open_folder')}")
        btn_open_dir.setObjectName("pmFooterBtn")
        btn_open_dir.setCursor(QtCore.Qt.PointingHandCursor)
        btn_open_dir.clicked.connect(self._open_plugins_dir)
        footer_lay.addWidget(btn_open_dir)

        footer_lay.addStretch()

        btn_reload_all = QtWidgets.QPushButton(f"↻  {tr('plugin.reload_all')}")
        btn_reload_all.setObjectName("pmBtnPrimary")
        btn_reload_all.setCursor(QtCore.Qt.PointingHandCursor)
        btn_reload_all.clicked.connect(self._reload_all)
        footer_lay.addWidget(btn_reload_all)

        root.addWidget(footer)

        # Tab switchflushnew
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # loadpluginlist
        self._refresh_list()
        self._update_stats()

    def _update_stats(self):
        """update header statisticslabel"""
        try:
            from ..utils.hooks import list_plugins
            plugins = list_plugins()
            enabled = sum(1 for p in plugins if p.get("_enabled"))
            self._stats_label.setText(f"{enabled}/{len(plugins)} {tr('plugin.stats_active')}")
        except Exception:
            self._stats_label.setText("")

    def _refresh_list(self):
        """flushnewpluginlist"""
        # clearemptyolditem
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            from ..utils.hooks import list_plugins
            plugins = list_plugins()
        except Exception as e:
            lbl = QtWidgets.QLabel(f"⚠ {tr('plugin.load_error')}: {e}")
            lbl.setObjectName("pmErrorLabel")
            self._list_layout.addWidget(lbl)
            self._list_layout.addStretch()
            return

        if not plugins:
            # Empty state — pretty onboarding hint
            empty_frame = QtWidgets.QFrame()
            empty_frame.setObjectName("pmEmptyState")
            ev = QtWidgets.QVBoxLayout(empty_frame)
            ev.setContentsMargins(20, 40, 20, 40)
            ev.setSpacing(10)
            ev.setAlignment(QtCore.Qt.AlignCenter)

            icon_lbl = QtWidgets.QLabel("🔌")
            icon_lbl.setStyleSheet("font-size: 28px; background: transparent;")
            icon_lbl.setAlignment(QtCore.Qt.AlignCenter)
            ev.addWidget(icon_lbl)

            hint1 = QtWidgets.QLabel(tr('plugin.empty_title'))
            hint1.setObjectName("pmEmptyTitle")
            hint1.setAlignment(QtCore.Qt.AlignCenter)
            ev.addWidget(hint1)

            hint2 = QtWidgets.QLabel(tr('plugin.empty_hint'))
            hint2.setObjectName("pmEmptyHint")
            hint2.setAlignment(QtCore.Qt.AlignCenter)
            hint2.setWordWrap(True)
            ev.addWidget(hint2)

            self._list_layout.addWidget(empty_frame)
        else:
            for info in plugins:
                row = self._create_plugin_row(info)
                self._list_layout.addWidget(row)

        self._list_layout.addStretch()
        self._update_stats()

    def _create_plugin_row(self, info: dict) -> QtWidgets.QWidget:
        """createsinglepluginrow (cardstyle) """
        row = QtWidgets.QFrame()
        row.setObjectName("pmCard")

        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(10)

        # State indicator light
        enabled = info.get("_enabled", False)
        dot = QtWidgets.QLabel("●")
        dot.setFixedWidth(12)
        dot.setStyleSheet(
            f"color: {'#6ecf72' if enabled else '#5a5040'}; "
            f"font-size: 8px; background: transparent;"
        )
        dot.setAlignment(QtCore.Qt.AlignCenter)
        h.addWidget(dot)

        # left side: name + metadatainfo
        left = QtWidgets.QVBoxLayout()
        left.setSpacing(3)

        name = info.get("name", "Unknown")
        version = info.get("version", "")
        author = info.get("author", "")

        name_lbl = QtWidgets.QLabel(
            f"<span style='font-weight:600; color:#e0d4c0'>{name}</span>"
            f"  <span style='color:#7a6e5e; font-size:10px'>v{version}</span>"
        )
        name_lbl.setObjectName("pmCardName")
        left.addWidget(name_lbl)

        desc = info.get("description", "")
        if author:
            desc = f"by {author}  ·  {desc}" if desc else f"by {author}"
        if desc:
            desc_lbl = QtWidgets.QLabel(desc)
            desc_lbl.setObjectName("pmCardDesc")
            desc_lbl.setWordWrap(True)
            left.addWidget(desc_lbl)

        h.addLayout(left, 1)

        # operationbuttongroup
        actions = QtWidgets.QHBoxLayout()
        actions.setSpacing(4)

        # setbutton (onlyhas settings whenshow) 
        if info.get("settings"):
            btn_settings = QtWidgets.QPushButton("⚙")
            btn_settings.setObjectName("pmIconBtn")
            btn_settings.setFixedSize(28, 28)
            btn_settings.setCursor(QtCore.Qt.PointingHandCursor)
            btn_settings.setToolTip(tr('plugin.settings'))
            btn_settings.clicked.connect(
                lambda checked=False, n=name, i=info: self._open_settings(n, i))
            actions.addWidget(btn_settings)

        # reloadbutton
        btn_reload = QtWidgets.QPushButton("↻")
        btn_reload.setObjectName("pmIconBtn")
        btn_reload.setFixedSize(28, 28)
        btn_reload.setCursor(QtCore.Qt.PointingHandCursor)
        btn_reload.setToolTip(tr('plugin.reload'))
        btn_reload.clicked.connect(
            lambda checked=False, n=name: self._on_reload(n))
        actions.addWidget(btn_reload)

        # enable/disabletoggle
        toggle = QtWidgets.QCheckBox()
        toggle.setChecked(enabled)
        toggle.setToolTip(tr('plugin.toggle_tip'))
        toggle.stateChanged.connect(
            lambda state, n=name: self._on_toggle(n, state == QtCore.Qt.Checked))
        actions.addWidget(toggle)

        h.addLayout(actions)

        return row

    def _on_toggle(self, plugin_name: str, enabled: bool):
        """enable/disableplugin"""
        try:
            from ..utils.hooks import enable_plugin, disable_plugin
            if enabled:
                enable_plugin(plugin_name)
            else:
                disable_plugin(plugin_name)
            self.pluginStateChanged.emit()
        except Exception as e:
            _dbg(f"[PluginManager] Toggle error: {e}")

    def _on_reload(self, plugin_name: str):
        """reloadsingleplugin"""
        try:
            from ..utils.hooks import reload_plugin
            reload_plugin(plugin_name)
            self._refresh_list()
            self.pluginStateChanged.emit()
        except Exception as e:
            _dbg(f"[PluginManager] Reload error: {e}")

    def _reload_all(self):
        """reloadallpartplugin"""
        try:
            from ..utils.hooks import reload_all_plugins
            reload_all_plugins()
            self._refresh_list()
            # ifcurrentin Tools/Skills tab, alsoflushnew
            idx = self._tabs.currentIndex()
            if idx == 1:
                self._refresh_tools_list()
            elif idx == 2:
                self._refresh_skills_list()
            self.pluginStateChanged.emit()
        except Exception as e:
            _dbg(f"[PluginManager] Reload all error: {e}")

    def _open_plugins_dir(self):
        """open plugins directory"""
        try:
            from ..utils.hooks import get_plugins_dir
            import os, subprocess
            import sys as _sys
            plugins_dir = get_plugins_dir()
            plugins_dir.mkdir(parents=True, exist_ok=True)
            if _sys.platform == 'win32':
                os.startfile(str(plugins_dir))
            elif _sys.platform == 'darwin':
                subprocess.Popen(['open', str(plugins_dir)])
            else:
                subprocess.Popen(['xdg-open', str(plugins_dir)])
        except Exception as e:
            _dbg(f"[PluginManager] Open dir error: {e}")

    def _on_tab_changed(self, index: int):
        """Tab switchwhenflushnewforshouldlist"""
        if index == 1:
            self._refresh_tools_list()
        elif index == 2:
            self._refresh_skills_list()

    def _filter_tools(self, text: str):
        """searchboxfiltertoollist"""
        text = text.strip().lower()
        for i in range(self._tools_layout.count()):
            item = self._tools_layout.itemAt(i)
            w = item.widget() if item else None
            if w is None:
                continue
            if w.objectName() == "pmCard":
                tool_name = w.property("toolName") or ""
                tool_desc = w.property("toolDesc") or ""
                visible = (not text) or text in tool_name.lower() or text in tool_desc.lower()
                w.setVisible(visible)
            elif w.objectName() == "pmGroupHeader":
                # grouptitle: ifsearchboxhascontentthenhidegrouptitle
                w.setVisible(not text)

    # ---------- Tools Tab ----------

    def _refresh_tools_list(self):
        """flushnewtoollist"""
        while self._tools_layout.count():
            item = self._tools_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            from ..utils.tool_registry import get_tool_registry
            reg = get_tool_registry()
            tools = reg.list_all()
        except Exception as e:
            lbl = QtWidgets.QLabel(f"⚠ {tr('plugin.load_error')}: {e}")
            lbl.setObjectName("pmErrorLabel")
            self._tools_layout.addWidget(lbl)
            self._tools_layout.addStretch()
            return

        if not tools:
            lbl = QtWidgets.QLabel(tr('plugin.no_tools'))
            lbl.setObjectName("pmEmptyHint")
            lbl.setAlignment(QtCore.Qt.AlignCenter)
            self._tools_layout.addWidget(lbl)
        else:
            # bycomesourcegroup
            groups = {}
            for t in tools:
                source = t.get("source", "core")
                groups.setdefault(source, []).append(t)

            source_icons = {
                "core": "🔧",
                "skill": "🧠",
                "plugin": "🔌",
                "user": "👤",
                "user_skill": "📐",
            }
            source_labels = {
                "core": tr('plugin.group_core'),
                "skill": tr('plugin.group_skill'),
                "plugin": tr('plugin.group_plugin'),
                "user": tr('plugin.group_user'),
                "user_skill": tr('plugin.group_user_skill'),
            }

            for source in ("core", "skill", "user_skill", "plugin", "user"):
                items = groups.get(source, [])
                if not items:
                    continue

                # grouptitle
                group_lbl = QtWidgets.QLabel(
                    f"{source_icons.get(source, '•')}  {source_labels.get(source, source)}"
                    f"  ({len(items)})"
                )
                group_lbl.setObjectName("pmGroupHeader")
                self._tools_layout.addWidget(group_lbl)

                for t in items:
                    row = self._create_tool_row(t)
                    self._tools_layout.addWidget(row)

        self._tools_layout.addStretch()

    def _create_tool_row(self, info: dict) -> QtWidgets.QWidget:
        """createsingletoolrow (compactcard) """
        row = QtWidgets.QFrame()
        row.setObjectName("pmCard")

        name = info.get("name", "")
        desc = info.get("description", "")[:100]
        enabled = info.get("enabled", True)
        modes = info.get("modes", [])
        tags = info.get("tags", [])

        # savestoreattributeused forsearchfilter
        row.setProperty("toolName", name)
        row.setProperty("toolDesc", desc)

        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(8)

        left = QtWidgets.QVBoxLayout()
        left.setSpacing(2)

        name_lbl = QtWidgets.QLabel(f"<span style='font-weight:600; color:#e0d4c0'>{name}</span>")
        name_lbl.setObjectName("pmCardName")
        left.addWidget(name_lbl)

        if desc:
            desc_lbl = QtWidgets.QLabel(desc)
            desc_lbl.setObjectName("pmCardDesc")
            desc_lbl.setWordWrap(True)
            left.addWidget(desc_lbl)

        # labelbar (modes + tags)
        if modes or tags:
            tag_row = QtWidgets.QHBoxLayout()
            tag_row.setSpacing(4)
            for m in modes[:3]:  # at mostshow 3  mode label
                tag = QtWidgets.QLabel(m)
                tag.setObjectName("pmTagBadge")
                tag_row.addWidget(tag)
            for t_str in tags[:2]:
                tag = QtWidgets.QLabel(t_str)
                tag.setObjectName("pmTagBadgeAlt")
                tag_row.addWidget(tag)
            tag_row.addStretch()
            left.addLayout(tag_row)

        h.addLayout(left, 1)

        # enable/disabletoggle
        toggle = QtWidgets.QCheckBox()
        toggle.setChecked(enabled)
        toggle.setToolTip(tr('plugin.tool_toggle_tip'))
        toggle.stateChanged.connect(
            lambda state, n=name: self._on_tool_toggle(n, state == QtCore.Qt.Checked))
        h.addWidget(toggle)

        return row

    def _on_tool_toggle(self, tool_name: str, enabled: bool):
        """enable/disabletool"""
        try:
            from ..utils.tool_registry import get_tool_registry
            reg = get_tool_registry()
            reg.set_enabled(tool_name, enabled)
            reg.save_disabled_to_config()
        except Exception as e:
            _dbg(f"[PluginManager] Tool toggle error: {e}")

    # ---------- Skills Tab ----------

    def _refresh_skills_list(self):
        """flushnew Skill list"""
        while self._skills_layout.count():
            item = self._skills_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            from ..skills import list_skills
            skills = list_skills()
        except Exception as e:
            lbl = QtWidgets.QLabel(f"⚠ {tr('plugin.load_error')}: {e}")
            lbl.setObjectName("pmErrorLabel")
            self._skills_layout.addWidget(lbl)
            self._skills_layout.addStretch()
            return

        if not skills:
            # emptystate
            empty_frame = QtWidgets.QFrame()
            empty_frame.setObjectName("pmEmptyState")
            ev = QtWidgets.QVBoxLayout(empty_frame)
            ev.setContentsMargins(20, 40, 20, 40)
            ev.setSpacing(10)
            ev.setAlignment(QtCore.Qt.AlignCenter)

            icon_lbl = QtWidgets.QLabel("🧠")
            icon_lbl.setStyleSheet("font-size: 28px; background: transparent;")
            icon_lbl.setAlignment(QtCore.Qt.AlignCenter)
            ev.addWidget(icon_lbl)

            hint_lbl = QtWidgets.QLabel(tr('plugin.no_skills'))
            hint_lbl.setObjectName("pmEmptyHint")
            hint_lbl.setAlignment(QtCore.Qt.AlignCenter)
            ev.addWidget(hint_lbl)

            self._skills_layout.addWidget(empty_frame)
        else:
            for s in skills:
                row = self._create_skill_row(s)
                self._skills_layout.addWidget(row)

        self._skills_layout.addStretch()

        # loaduser Skill directory
        try:
            from ..skills import _get_user_skill_dir
            user_dir = _get_user_skill_dir()
            if user_dir:
                self._skill_dir_edit.setText(str(user_dir))
        except Exception:
            pass

    def _create_skill_row(self, info: dict) -> QtWidgets.QWidget:
        """createsingle Skill row (cardstyle) """
        row = QtWidgets.QFrame()
        row.setObjectName("pmCard")

        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        # icon
        icon_lbl = QtWidgets.QLabel("🧠")
        icon_lbl.setFixedWidth(20)
        icon_lbl.setStyleSheet("font-size: 14px; background: transparent;")
        icon_lbl.setAlignment(QtCore.Qt.AlignCenter)
        h.addWidget(icon_lbl)

        left = QtWidgets.QVBoxLayout()
        left.setSpacing(3)

        name = info.get("name", "Unknown")
        name_lbl = QtWidgets.QLabel(
            f"<span style='font-weight:600; color:#e0d4c0'>{name}</span>"
        )
        name_lbl.setObjectName("pmCardName")
        left.addWidget(name_lbl)

        desc = info.get("description", "")
        if desc:
            desc_lbl = QtWidgets.QLabel(desc[:120])
            desc_lbl.setObjectName("pmCardDesc")
            desc_lbl.setWordWrap(True)
            left.addWidget(desc_lbl)

        params = info.get("parameters", {})
        if params:
            param_names = list(params.keys())[:5]
            tag_row = QtWidgets.QHBoxLayout()
            tag_row.setSpacing(4)
            for p in param_names:
                tag = QtWidgets.QLabel(p)
                tag.setObjectName("pmTagBadge")
                tag_row.addWidget(tag)
            tag_row.addStretch()
            left.addLayout(tag_row)

        h.addLayout(left, 1)

        # Skill enable/disabletoggle (key must match the registry key in skills/__init__.py)
        tool_name = f"skill__{name}"
        enabled = True
        try:
            from ..utils.tool_registry import get_tool_registry
            enabled = get_tool_registry().is_enabled(tool_name)
        except Exception:
            pass

        toggle = QtWidgets.QCheckBox()
        toggle.setChecked(enabled)
        toggle.setToolTip(tr('plugin.tool_toggle_tip'))
        toggle.stateChanged.connect(
            lambda state, n=tool_name: self._on_tool_toggle(n, state == QtCore.Qt.Checked))
        h.addWidget(toggle)

        return row

    def _browse_skill_dir(self):
        """Browse and select user skill directory."""
        dir_path = QtWidgets.QFileDialog.getExistingDirectory(
            self, tr('plugin.skill_dir_browse'), "")
        if dir_path:
            self._skill_dir_edit.setText(dir_path)
            # saveto config/houdini_ai.ini
            try:
                import configparser
                from pathlib import Path
                config_dir = Path(__file__).resolve().parent.parent.parent / "config"
                ini_path = config_dir / "houdini_ai.ini"
                cfg = configparser.ConfigParser()
                if ini_path.exists():
                    cfg.read(str(ini_path), encoding='utf-8')
                if not cfg.has_section("skills"):
                    cfg.add_section("skills")
                cfg.set("skills", "user_skill_dir", dir_path)
                with open(ini_path, 'w', encoding='utf-8') as f:
                    cfg.write(f)
                _dbg(f"[Skills] User skill directory set: {dir_path}")
            except Exception as e:
                _dbg(f"[Skills] Failed to save skill directory: {e}")

    def _open_settings(self, plugin_name: str, info: dict):
        """openpluginsetconversationbox"""
        dlg = PluginSettingsPage(
            plugin_name=plugin_name,
            settings_schema=info.get("settings", []),
            parent=self,
        )
        dlg.exec_()


class PluginSettingsPage(QtWidgets.QDialog):
    """pluginsetpage — based on settings schema autogenerateconfigtablesingle

    settings schema format:
        [
            {"key": "log_level", "type": "string", "label": "Log Level", "default": "info", "options": [...]},
            {"key": "enable_x", "type": "bool", "label": "Enable X", "default": True},
        ]
    """

    def __init__(self, plugin_name: str, settings_schema: list, parent=None):
        super().__init__(parent)
        self.setObjectName("pluginSettingsDlg")
        self.setWindowTitle(f"{tr('plugin.settings')} — {plugin_name}")
        self.setMinimumWidth(420)
        self._plugin_name = plugin_name
        self._schema = settings_schema
        self._widgets: dict = {}  # key -> widget

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # titlebar
        header = QtWidgets.QFrame()
        header.setObjectName("pmHeader")
        header.setFixedHeight(40)
        header_lay = QtWidgets.QHBoxLayout(header)
        header_lay.setContentsMargins(14, 0, 14, 0)
        title = QtWidgets.QLabel(f"⚙  {plugin_name}")
        title.setObjectName("pmTitle")
        header_lay.addWidget(title)
        root.addWidget(header)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # readcurrentsetvalue
        try:
            from ..utils.hooks import get_plugin_setting
        except ImportError:
            get_plugin_setting = lambda pn, k, d=None: d

        # generatetablesingle
        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        form.setContentsMargins(0, 0, 0, 0)

        for item in settings_schema:
            key = item.get("key", "")
            label = item.get("label", key)
            stype = item.get("type", "string")
            default = item.get("default")
            options = item.get("options")
            current_val = get_plugin_setting(plugin_name, key, default)

            if stype == "bool":
                cb = QtWidgets.QCheckBox()
                cb.setChecked(bool(current_val))
                form.addRow(label, cb)
                self._widgets[key] = cb

            elif stype == "string" and options:
                combo = QtWidgets.QComboBox()
                for opt in options:
                    combo.addItem(str(opt))
                if current_val and str(current_val) in [str(o) for o in options]:
                    combo.setCurrentText(str(current_val))
                form.addRow(label, combo)
                self._widgets[key] = combo

            else:
                # string / number
                le = QtWidgets.QLineEdit()
                le.setText(str(current_val) if current_val is not None else "")
                le.setPlaceholderText(str(default) if default is not None else "")
                form.addRow(label, le)
                self._widgets[key] = le

        layout.addLayout(form)
        layout.addStretch()

        root.addLayout(layout, 1)

        # bottompartbuttonbar
        footer = QtWidgets.QFrame()
        footer.setObjectName("pmFooter")
        footer.setFixedHeight(42)
        footer_lay = QtWidgets.QHBoxLayout(footer)
        footer_lay.setContentsMargins(14, 0, 14, 0)
        footer_lay.addStretch()

        btn_cancel = QtWidgets.QPushButton(tr('plugin.cancel'))
        btn_cancel.setObjectName("pmFooterBtn")
        btn_cancel.setCursor(QtCore.Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        footer_lay.addWidget(btn_cancel)

        btn_save = QtWidgets.QPushButton(tr('plugin.save'))
        btn_save.setObjectName("pmBtnPrimary")
        btn_save.setCursor(QtCore.Qt.PointingHandCursor)
        btn_save.clicked.connect(self._save)
        footer_lay.addWidget(btn_save)

        root.addWidget(footer)

    def _save(self):
        """saveset"""
        try:
            from ..utils.hooks import set_plugin_setting
        except ImportError:
            self.reject()
            return

        for item in self._schema:
            key = item.get("key", "")
            stype = item.get("type", "string")
            widget = self._widgets.get(key)
            if not widget:
                continue

            if stype == "bool":
                value = widget.isChecked()
            elif isinstance(widget, QtWidgets.QComboBox):
                value = widget.currentText()
            else:
                value = widget.text()

            set_plugin_setting(self._plugin_name, key, value)

        self.accept()


# ============================================================
# Rules Editor Dialog — usercustomruleedit 
# ============================================================

class RulesEditorDialog(QtWidgets.QDialog):
    """usercustomruleedit conversationbox

    left side: rulelist + operationbutton
    right side: title + contenteditsection (oremptystateguideimport) 
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("rulesEditorDlg")
        self.setWindowTitle(tr('rules.title'))
        self.setMinimumSize(580, 400)
        self.resize(640, 440)
        self._current_rule_id: Optional[str] = None
        self._rules: list = []
        self._dirty = False

        self._build_ui()
        self._load_rules()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- titlebar ----
        header = QtWidgets.QFrame()
        header.setObjectName("rulesHeader")
        header.setFixedHeight(40)
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(14, 0, 14, 0)
        header_layout.setSpacing(8)

        title_lbl = QtWidgets.QLabel(f"📋  {tr('rules.title')}")
        title_lbl.setObjectName("rulesEditorTitle")
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()

        self._count_label = QtWidgets.QLabel("")
        self._count_label.setObjectName("rulesCountLabel")
        header_layout.addWidget(self._count_label)

        root.addWidget(header)

        # ---- mainbody ----
        body = QtWidgets.QHBoxLayout()
        body.setContentsMargins(10, 8, 10, 0)
        body.setSpacing(8)

        # ── left sidepanel ──
        left_panel = QtWidgets.QFrame()
        left_panel.setObjectName("rulesLeftPanel")
        left_panel.setFixedWidth(200)
        left_v = QtWidgets.QVBoxLayout(left_panel)
        left_v.setContentsMargins(0, 0, 0, 0)
        left_v.setSpacing(6)

        self._list_widget = QtWidgets.QListWidget()
        self._list_widget.setObjectName("rulesList")
        self._list_widget.currentRowChanged.connect(self._on_rule_selected)
        left_v.addWidget(self._list_widget, 1)

        # operationbutton
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(4)

        self._btn_add = QtWidgets.QPushButton(f"＋ {tr('rules.add')}")
        self._btn_add.setObjectName("rulesAddBtn")
        self._btn_add.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_add.clicked.connect(self._on_add)
        btn_row.addWidget(self._btn_add)

        self._btn_delete = QtWidgets.QPushButton("✕")
        self._btn_delete.setObjectName("rulesDelBtn")
        self._btn_delete.setFixedWidth(28)
        self._btn_delete.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_delete.setToolTip(tr('rules.delete'))
        self._btn_delete.clicked.connect(self._on_delete)
        btn_row.addWidget(self._btn_delete)

        left_v.addLayout(btn_row)
        body.addWidget(left_panel)

        # ── right sidepanel (QStackedWidget: emptystate / editsection) ──
        self._right_stack = QtWidgets.QStackedWidget()
        self._right_stack.setObjectName("rulesRightStack")

        # page 0: emptystateguideimport
        empty_page = QtWidgets.QWidget()
        empty_lay = QtWidgets.QVBoxLayout(empty_page)
        empty_lay.setAlignment(QtCore.Qt.AlignCenter)

        empty_icon = QtWidgets.QLabel("📝")
        empty_icon.setAlignment(QtCore.Qt.AlignCenter)
        empty_icon.setStyleSheet("font-size: 32px; background: transparent;")
        empty_lay.addWidget(empty_icon)

        self._empty_label = QtWidgets.QLabel(tr('rules.empty_hint'))
        self._empty_label.setObjectName("rulesEmptyHint")
        self._empty_label.setAlignment(QtCore.Qt.AlignCenter)
        self._empty_label.setWordWrap(True)
        empty_lay.addWidget(self._empty_label)

        # emptystatebelow createbutton
        empty_add_btn = QtWidgets.QPushButton(f"＋ {tr('rules.add')}")
        empty_add_btn.setObjectName("rulesAddBtn")
        empty_add_btn.setCursor(QtCore.Qt.PointingHandCursor)
        empty_add_btn.setFixedWidth(120)
        empty_add_btn.clicked.connect(self._on_add)
        empty_btn_wrap = QtWidgets.QHBoxLayout()
        empty_btn_wrap.setAlignment(QtCore.Qt.AlignCenter)
        empty_btn_wrap.addWidget(empty_add_btn)
        empty_lay.addLayout(empty_btn_wrap)

        self._right_stack.addWidget(empty_page)  # index 0

        # page 1: editsection
        edit_page = QtWidgets.QWidget()
        edit_lay = QtWidgets.QVBoxLayout(edit_page)
        edit_lay.setContentsMargins(0, 0, 0, 0)
        edit_lay.setSpacing(6)

        self._title_edit = QtWidgets.QLineEdit()
        self._title_edit.setObjectName("rulesTitleEdit")
        self._title_edit.setPlaceholderText(tr('rules.placeholder_title'))
        self._title_edit.textChanged.connect(self._on_title_changed)
        edit_lay.addWidget(self._title_edit)

        self._content_edit = QtWidgets.QPlainTextEdit()
        self._content_edit.setObjectName("rulesContentEdit")
        self._content_edit.setPlaceholderText(tr('rules.placeholder_content'))
        self._content_edit.textChanged.connect(self._on_content_changed)
        edit_lay.addWidget(self._content_edit, 1)

        # bottompartstaterow
        bottom_row = QtWidgets.QHBoxLayout()
        bottom_row.setSpacing(6)

        self._source_label = QtWidgets.QLabel("")
        self._source_label.setObjectName("rulesSourceLabel")
        bottom_row.addWidget(self._source_label, 1)

        self._btn_toggle = QtWidgets.QPushButton(tr('rules.disable'))
        self._btn_toggle.setObjectName("rulesToggleBtn")
        self._btn_toggle.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_toggle.clicked.connect(self._on_toggle_enabled)
        bottom_row.addWidget(self._btn_toggle)

        edit_lay.addLayout(bottom_row)

        self._right_stack.addWidget(edit_page)  # index 1

        body.addWidget(self._right_stack, 1)
        root.addLayout(body, 1)

        # ---- bottompartbar ----
        footer = QtWidgets.QFrame()
        footer.setObjectName("rulesFooter")
        footer.setFixedHeight(36)
        footer_lay = QtWidgets.QHBoxLayout(footer)
        footer_lay.setContentsMargins(14, 0, 14, 0)
        footer_lay.setSpacing(6)
        footer_lay.addStretch()

        self._btn_open_dir = QtWidgets.QPushButton(f"📂  {tr('rules.open_folder')}")
        self._btn_open_dir.setObjectName("rulesFooterBtn")
        self._btn_open_dir.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_open_dir.clicked.connect(self._on_open_dir)
        footer_lay.addWidget(self._btn_open_dir)

        root.addWidget(footer)

        # initialshowemptystate
        self._right_stack.setCurrentIndex(0)

    def _load_rules(self):
        """from rules_manager loadallrule"""
        try:
            from ..utils.rules_manager import get_all_rules
            self._rules = get_all_rules(force_reload=True)
        except Exception as e:
            _dbg(f"[RulesEditor] Failed to load rules: {e}")
            self._rules = []

        self._refresh_list()

    def _refresh_list(self):
        """flushnewleft siderulelist"""
        self._list_widget.blockSignals(True)
        self._list_widget.clear()

        for r in self._rules:
            title = r.get("title", "") or tr('rules.untitled')
            source = r.get("source", "ui")
            enabled = r.get("enabled", True)

            # constructshowtext
            prefix = ""
            if source == "file":
                prefix = "[F] "
            if not enabled:
                prefix += "(" + tr('rules.disable') + ") "

            item = QtWidgets.QListWidgetItem(prefix + title)
            # disable rulegraycolorshow
            if not enabled:
                item.setForeground(QtCore.Qt.gray)
            self._list_widget.addItem(item)

        self._list_widget.blockSignals(False)

        # updatecountcount
        enabled_count = sum(1 for r in self._rules if r.get("enabled", True))
        self._count_label.setText(tr('rules.count', enabled_count))

        # emptystate / editsectionswitch
        has_rules = len(self._rules) > 0
        if not has_rules:
            self._right_stack.setCurrentIndex(0)  # emptystatepage
        else:
            self._right_stack.setCurrentIndex(1)  # editpage

        # restoreselected
        if self._current_rule_id:
            for i, r in enumerate(self._rules):
                if r.get("id") == self._current_rule_id:
                    self._list_widget.setCurrentRow(i)
                    break
        elif has_rules:
            self._list_widget.setCurrentRow(0)

    def _on_rule_selected(self, row: int):
        """selectedrulewhenupdateright sideeditsection"""
        if row < 0 or row >= len(self._rules):
            self._current_rule_id = None
            self._set_editor_enabled(False)
            return

        rule = self._rules[row]
        self._current_rule_id = rule.get("id")
        is_file = rule.get("source") == "file"

        # updateeditsection
        self._title_edit.blockSignals(True)
        self._content_edit.blockSignals(True)

        self._title_edit.setText(rule.get("title", ""))
        self._content_edit.setPlainText(rule.get("content", ""))

        self._title_edit.blockSignals(False)
        self._content_edit.blockSignals(False)

        # fileruleread-only
        self._title_edit.setReadOnly(is_file)
        self._content_edit.setReadOnly(is_file)

        # sourcelabel
        if is_file:
            fp = rule.get("file_path", "")
            self._source_label.setText(f"{tr('rules.file_readonly')}  {fp}")
        else:
            self._source_label.setText("")

        # enable/disablebutton
        enabled = rule.get("enabled", True)
        if is_file:
            self._btn_toggle.setVisible(False)
        else:
            self._btn_toggle.setVisible(True)
            self._btn_toggle.setText(
                tr('rules.disable') if enabled else tr('rules.enable')
            )

        self._set_editor_enabled(True)

    def _set_editor_enabled(self, enabled: bool):
        """switchright sidepanel: editsection / emptystate"""
        if enabled:
            self._right_stack.setCurrentIndex(1)
        else:
            self._right_stack.setCurrentIndex(0)

    def _on_title_changed(self, text: str):
        """titlechangewhenrealwhensave"""
        if self._current_rule_id and not self._current_rule_id.startswith("file:"):
            for r in self._rules:
                if r.get("id") == self._current_rule_id:
                    r["title"] = text
                    self._dirty = True
                    break
            self._auto_save()
            # updatelistshow
            row = self._list_widget.currentRow()
            if 0 <= row < self._list_widget.count():
                item = self._list_widget.item(row)
                if item:
                    item.setText(text or tr('rules.untitled'))

    def _on_content_changed(self):
        """contentchangewhenrealwhensave"""
        if self._current_rule_id and not self._current_rule_id.startswith("file:"):
            text = self._content_edit.toPlainText()
            for r in self._rules:
                if r.get("id") == self._current_rule_id:
                    r["content"] = text
                    self._dirty = True
                    break
            self._auto_save()

    def _auto_save(self):
        """autosave UI rule"""
        if not self._dirty:
            return
        try:
            from ..utils.rules_manager import save_all_ui_rules
            ui_rules = [r for r in self._rules if r.get("source", "ui") == "ui"]
            save_all_ui_rules(ui_rules)
            self._dirty = False
        except Exception as e:
            _dbg(f"[RulesEditor] Auto-save failed: {e}")

    def _on_add(self):
        """newaddoneitem UI rule"""
        try:
            from ..utils.rules_manager import add_rule
            rule = add_rule(title=tr('rules.untitled'), content="")
            rule["source"] = "ui"
            self._rules.append(rule)
            self._current_rule_id = rule["id"]
            self._refresh_list()
            # selectedcreate rule
            self._list_widget.setCurrentRow(len(self._rules) - 1)
        except Exception as e:
            _dbg(f"[RulesEditor] Add rule failed: {e}")

    def _on_delete(self):
        """deletecurrentselected  UI rule"""
        if not self._current_rule_id:
            return
        if self._current_rule_id.startswith("file:"):
            return  # filerulenotallowin UI indelete

        # confirm
        current_rule = None
        for r in self._rules:
            if r.get("id") == self._current_rule_id:
                current_rule = r
                break
        if not current_rule:
            return

        title = current_rule.get("title", tr('rules.untitled'))
        reply = QtWidgets.QMessageBox.question(
            self, tr('rules.delete'),
            tr('rules.delete_confirm', title),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        try:
            from ..utils.rules_manager import delete_rule
            delete_rule(self._current_rule_id)
            self._rules = [r for r in self._rules if r.get("id") != self._current_rule_id]
            self._current_rule_id = None
            self._refresh_list()
        except Exception as e:
            _dbg(f"[RulesEditor] Delete rule failed: {e}")

    def _on_toggle_enabled(self):
        """switchcurrentrule enable/disablestate"""
        if not self._current_rule_id or self._current_rule_id.startswith("file:"):
            return

        for r in self._rules:
            if r.get("id") == self._current_rule_id:
                new_enabled = not r.get("enabled", True)
                r["enabled"] = new_enabled
                self._dirty = True
                self._auto_save()
                self._refresh_list()
                # updatebuttontext
                self._btn_toggle.setText(
                    tr('rules.disable') if new_enabled else tr('rules.enable')
                )
                break

    def _on_open_dir(self):
        """open rules/ directory"""
        try:
            from ..utils.rules_manager import get_rules_dir, ensure_rules_dir
            import os, subprocess
            import sys as _sys
            ensure_rules_dir()
            rules_dir = get_rules_dir()
            if _sys.platform == 'win32':
                os.startfile(str(rules_dir))
            elif _sys.platform == 'darwin':
                subprocess.Popen(['open', str(rules_dir)])
            else:
                subprocess.Popen(['xdg-open', str(rules_dir)])
        except Exception as e:
            _dbg(f"[RulesEditor] Open dir failed: {e}")

    def resizeEvent(self, event):
        """adjustwholeemptystatehint position"""
        super().resizeEvent(event)
        # let empty_label overrideright sideeditarea
        if hasattr(self, '_empty_label') and self._empty_label.parent():
            self._empty_label.setGeometry(self._empty_label.parent().rect())


# ============================================================
# About Dialog — kredit, lisensi, transparansi
# ============================================================

class AboutDialog(QtWidgets.QDialog):
    """About panel — name, version, license, credits."""

    APP_NAME = "MorfyAI"
    APP_TAGLINE = "Houdini Assistant"
    APP_SUBTAGLINE = "Part of the MorfyFX ecosystem"
    AUTHOR = "gemrra"
    ORIGINAL_AUTHOR = "KazamaSuichiku"
    ORIGINAL_PROJECT = "Houdini Agent"
    ORIGINAL_BASE_VERSION = "1.5.5"   # last upstream Houdini Agent version this fork branched from
    AI_COLLABORATOR = "Claude (Anthropic)"
    LICENSE = "MIT License"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aboutDialog")
        self.setWindowTitle(f"About {self.APP_NAME}")
        self.setMinimumWidth(460)
        self.setModal(True)

        version = self._read_version()

        # ── root layout ──
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(10)

        # ── header: logo + app name + tagline ──
        header_row = QtWidgets.QHBoxLayout()
        header_row.setSpacing(14)
        header_row.setContentsMargins(0, 0, 0, 0)

        # Logo
        logo_pix = self._load_about_logo(target_h=56)
        if logo_pix is not None and not logo_pix.isNull():
            logo_lbl = QtWidgets.QLabel()
            logo_lbl.setPixmap(logo_pix)
            logo_lbl.setFixedSize(logo_pix.width(), 56)
            logo_lbl.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
            header_row.addWidget(logo_lbl, 0, QtCore.Qt.AlignTop)

        # Name + tagline column
        name_col = QtWidgets.QVBoxLayout()
        name_col.setSpacing(2)
        name_col.setContentsMargins(0, 2, 0, 0)

        name_lbl = QtWidgets.QLabel(f"{self.APP_NAME}")
        name_lbl.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: #ff8c2a;"
        )
        name_col.addWidget(name_lbl)

        tagline_lbl = QtWidgets.QLabel(self.APP_TAGLINE)
        tagline_lbl.setStyleSheet("font-size: 13px; color: #cbd5e1;")
        name_col.addWidget(tagline_lbl)

        sub_lbl = QtWidgets.QLabel(self.APP_SUBTAGLINE)
        sub_lbl.setStyleSheet("font-size: 11px; color: #64748b; font-style: italic;")
        name_col.addWidget(sub_lbl)

        header_row.addLayout(name_col, 1)
        root.addLayout(header_row)

        # ── separator ──
        sep1 = QtWidgets.QFrame()
        sep1.setFrameShape(QtWidgets.QFrame.HLine)
        sep1.setStyleSheet("background: rgba(255,255,255,18); max-height: 1px; border: none;")
        root.addWidget(sep1)

        # ── meta info ──
        meta_grid = QtWidgets.QGridLayout()
        meta_grid.setSpacing(6)
        meta_grid.setColumnStretch(1, 1)

        def _row(r: int, key: str, value: str, value_mono: bool = False, value_accent: bool = False):
            k = QtWidgets.QLabel(key)
            k.setStyleSheet("color: #64748b; font-size: 12px;")
            v = QtWidgets.QLabel(value)
            v.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            v.setTextFormat(QtCore.Qt.RichText)
            font_style = "font-family: 'Consolas', monospace;" if value_mono else ""
            color = "#ff8c2a" if value_accent else "#e2e8f0"
            v.setStyleSheet(f"color: {color}; font-size: 12px; {font_style}")
            v.setWordWrap(True)
            meta_grid.addWidget(k, r, 0, QtCore.Qt.AlignTop)
            meta_grid.addWidget(v, r, 1)

        _row(0, "Version", f"v{version}", value_mono=True)
        _row(1, "Maintainer", self.AUTHOR, value_accent=True)
        _row(2, "License", self.LICENSE)
        _row(3, "UI Framework", "PySide / PyQt (Qt)")

        root.addLayout(meta_grid)

        # ── separator ──
        sep2 = QtWidgets.QFrame()
        sep2.setFrameShape(QtWidgets.QFrame.HLine)
        sep2.setStyleSheet("background: rgba(255,255,255,18); max-height: 1px; border: none;")
        root.addWidget(sep2)

        # ── credits ──
        credits_title = QtWidgets.QLabel("Credits & Attribution")
        credits_title.setStyleSheet(
            "color: #94a3b8; font-size: 11px; font-weight: bold; "
            "letter-spacing: 0.05em; text-transform: uppercase;"
        )
        root.addWidget(credits_title)

        credits_text = QtWidgets.QLabel(
            f"<b>{self.APP_NAME}</b> is maintained by <b>{self.AUTHOR}</b> "
            f"as part of the <b>MorfyFX</b> ecosystem. This plugin is a continuation "
            f"of the open-source <b>{self.ORIGINAL_PROJECT}</b> "
            f"(v{self.ORIGINAL_BASE_VERSION}), originally created by "
            f"<b>{self.ORIGINAL_AUTHOR}</b>. Full credit for the core agent engine, "
            f"tool integrations, multi-session management, and all underlying "
            f"functionality goes to them and the original "
            f"{self.ORIGINAL_PROJECT} contributors.<br><br>"

            f"MorfyAI is developed by <b>{self.AUTHOR}</b> with iterative "
            f"assistance from <b>{self.AI_COLLABORATOR}</b>.<br><br>"

            f"Released under the <b>{self.LICENSE}</b> — the original copyright "
            f"notice and license are preserved in this distribution."
        )
        credits_text.setWordWrap(True)
        credits_text.setStyleSheet("color: #cbd5e1; font-size: 12px; line-height: 1.6;")
        credits_text.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        root.addWidget(credits_text)

        # ── separator (above contact) ──
        sep_contact = QtWidgets.QFrame()
        sep_contact.setFrameShape(QtWidgets.QFrame.HLine)
        sep_contact.setStyleSheet("background: rgba(255,255,255,18); max-height: 1px; border: none;")
        root.addWidget(sep_contact)

        # ── contact / feedback ──
        contact_title = QtWidgets.QLabel("Feedback & Contact")
        contact_title.setStyleSheet(
            "color: #94a3b8; font-size: 11px; font-weight: bold; "
            "letter-spacing: 0.05em; text-transform: uppercase;"
        )
        root.addWidget(contact_title)

        contact_email = "hello.gemrra@gmail.com"
        contact_text = QtWidgets.QLabel(
            f"Bug reports, feature requests, or general feedback are welcome — "
            f"reach the maintainer at "
            f"<a href='mailto:{contact_email}' style='color:#ff8c2a; text-decoration:none;'>"
            f"<b>{contact_email}</b></a>."
        )
        contact_text.setWordWrap(True)
        contact_text.setStyleSheet("color: #cbd5e1; font-size: 12px; line-height: 1.6;")
        contact_text.setTextFormat(QtCore.Qt.RichText)
        contact_text.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse | QtCore.Qt.LinksAccessibleByMouse
        )
        contact_text.setOpenExternalLinks(True)
        root.addWidget(contact_text)

        # ── separator ──
        sep3 = QtWidgets.QFrame()
        sep3.setFrameShape(QtWidgets.QFrame.HLine)
        sep3.setStyleSheet("background: rgba(255,255,255,18); max-height: 1px; border: none;")
        root.addWidget(sep3)

        # ── transparency notice ──
        transparency = QtWidgets.QLabel(
            "This plugin is provided as-is, with no warranty. "
            "Source code, dependencies, and behavior are open and auditable."
        )
        transparency.setWordWrap(True)
        transparency.setStyleSheet("color: #64748b; font-size: 11px; font-style: italic;")
        root.addWidget(transparency)

        root.addStretch(1)

        # ── close button ──
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_close = QtWidgets.QPushButton("Close")
        btn_close.setMinimumWidth(90)
        btn_close.setStyleSheet(
            "QPushButton {"
            " background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "  stop:0 #fb7a1a, stop:1 #ea580c);"
            " color: #ffffff; border: none; border-radius: 8px;"
            " padding: 6px 18px; font-weight: bold;"
            "}"
            "QPushButton:hover {"
            " background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "  stop:0 #ff9342, stop:1 #fb7a1a);"
            "}"
        )
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

        # ── dialog background ──
        self.setStyleSheet(
            "QDialog#aboutDialog {"
            " background: #0d0e13;"
            " border: 1px solid rgba(255,255,255,18);"
            " border-radius: 10px;"
            "}"
        )

    @staticmethod
    def _read_version() -> str:
        """Read VERSION file from plugin root."""
        try:
            from pathlib import Path
            here = Path(__file__).resolve()
            # morfyai/ui/cursor_widgets.py  →  parent.parent.parent = plugin root
            version_file = here.parent.parent.parent / "VERSION"
            if version_file.exists():
                return version_file.read_text(encoding="utf-8").strip() or "unknown"
        except Exception:
            pass
        return "unknown"

    @staticmethod
    def _load_about_logo(target_h: int = 56):
        """Load the MorfyFX logo for the About dialog header."""
        try:
            from pathlib import Path
            here = Path(__file__).resolve()
            assets_dir = here.parent.parent / "assets"
            candidates = [
                assets_dir / "morfyfx-logodarkbg.png",
                assets_dir / "morfyfx-logodarkbg.svg",
                assets_dir / "morfyfx-logomain.svg",
            ]
            logo_path = next((p for p in candidates if p.exists()), None)
            if logo_path is None:
                return None
            # PNG: direct QPixmap load, scaled smoothly
            pix = QtGui.QPixmap(str(logo_path))
            if not pix.isNull():
                return pix.scaledToHeight(target_h, QtCore.Qt.SmoothTransformation)
            return None
        except Exception:
            return None


# ============================================================
# Debug Console — in-app log viewer (replaces Houdini Console spam)
# ============================================================

class DebugConsoleDialog(QtWidgets.QDialog):
    """In-app viewer for the MorfyAI debug log buffer.

    Diagnostic events from the plugin are routed into a ring buffer via
    `utils.debug_log.log()` instead of printing to Houdini's main Console.
    This dialog displays them with refresh / clear / copy controls.
    """

    _REFRESH_MS = 1000  # auto-refresh interval

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("debugConsoleDialog")
        self.setWindowTitle("MorfyAI - Debug Console")
        self.setMinimumSize(640, 420)
        self.setModal(False)  # non-modal so user can keep using the panel

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # ── header row ──
        header_row = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Debug Console")
        title.setStyleSheet("color: #ff8c2a; font-size: 14px; font-weight: bold;")
        header_row.addWidget(title)

        self._count_lbl = QtWidgets.QLabel("0 lines")
        self._count_lbl.setStyleSheet("color: #64748b; font-size: 11px;")
        header_row.addWidget(self._count_lbl)

        header_row.addStretch(1)

        try:
            from ..utils import debug_log as _dlmod
            initial_echo = _dlmod.is_echo_stdout()
        except Exception:
            initial_echo = False
        self._chk_echo = QtWidgets.QCheckBox("Also echo to stdout")
        self._chk_echo.setChecked(initial_echo)
        self._chk_echo.setToolTip(
            "When enabled, new log lines are also written to Houdini's main Console."
        )
        self._chk_echo.toggled.connect(self._on_echo_toggled)
        self._chk_echo.setStyleSheet("color: #94a3b8; font-size: 11px;")
        header_row.addWidget(self._chk_echo)

        root.addLayout(header_row)

        # ── log view ──
        self._view = QtWidgets.QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self._view.setStyleSheet(
            "QPlainTextEdit {"
            " background: #07080c;"
            " color: #cbd5e1;"
            " border: 1px solid rgba(255,255,255,12);"
            " border-radius: 6px;"
            " padding: 8px 10px;"
            " font-family: 'Consolas', 'Monaco', 'Courier New', monospace;"
            " font-size: 11px;"
            "}"
        )
        root.addWidget(self._view, 1)

        # ── controls ──
        ctrl_row = QtWidgets.QHBoxLayout()

        btn_refresh = QtWidgets.QPushButton("Refresh")
        btn_refresh.clicked.connect(self._refresh)
        btn_refresh.setStyleSheet(self._secondary_btn_style())
        ctrl_row.addWidget(btn_refresh)

        btn_copy = QtWidgets.QPushButton("Copy all")
        btn_copy.clicked.connect(self._copy_all)
        btn_copy.setStyleSheet(self._secondary_btn_style())
        ctrl_row.addWidget(btn_copy)

        btn_clear = QtWidgets.QPushButton("Clear")
        btn_clear.clicked.connect(self._on_clear)
        btn_clear.setStyleSheet(self._secondary_btn_style())
        ctrl_row.addWidget(btn_clear)

        ctrl_row.addStretch(1)

        btn_close = QtWidgets.QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_close.setStyleSheet(
            "QPushButton {"
            " background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "  stop:0 #fb7a1a, stop:1 #ea580c);"
            " color: #ffffff; border: none; border-radius: 6px;"
            " padding: 6px 18px; font-weight: bold;"
            "}"
            "QPushButton:hover {"
            " background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "  stop:0 #ff9342, stop:1 #fb7a1a);"
            "}"
        )
        ctrl_row.addWidget(btn_close)

        root.addLayout(ctrl_row)

        # ── dialog bg ──
        self.setStyleSheet(
            "QDialog#debugConsoleDialog {"
            " background: #0d0e13;"
            " border: 1px solid rgba(255,255,255,18);"
            " border-radius: 10px;"
            "}"
        )

        # ── auto-refresh ──
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self._REFRESH_MS)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

        # initial fill
        self._refresh()

    @staticmethod
    def _secondary_btn_style() -> str:
        return (
            "QPushButton {"
            " background: rgba(255,255,255,8);"
            " color: #cbd5e1;"
            " border: 1px solid rgba(255,255,255,16);"
            " border-radius: 6px;"
            " padding: 5px 14px;"
            " font-size: 12px;"
            "}"
            "QPushButton:hover {"
            " background: rgba(255,255,255,14);"
            " color: #ffffff;"
            "}"
        )

    def _refresh(self):
        try:
            from ..utils import debug_log as _dlmod
            lines = _dlmod.get_lines()
        except Exception:
            lines = []

        # Preserve scroll position if user scrolled up; auto-stick when at bottom
        scrollbar = self._view.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 4

        self._view.setPlainText("\n".join(lines) if lines else "(no debug events yet)")

        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())

        self._count_lbl.setText(f"{len(lines)} line{'s' if len(lines) != 1 else ''}")

    def _on_clear(self):
        try:
            from ..utils import debug_log as _dlmod
            _dlmod.clear()
        except Exception:
            pass
        self._refresh()

    def _copy_all(self):
        text = self._view.toPlainText()
        QtWidgets.QApplication.clipboard().setText(text)

    def _on_echo_toggled(self, enabled: bool):
        try:
            from ..utils import debug_log as _dlmod
            _dlmod.set_echo_stdout(bool(enabled))
        except Exception:
            pass

    def closeEvent(self, event):
        try:
            self._timer.stop()
        except Exception:
            pass
        super().closeEvent(event)
