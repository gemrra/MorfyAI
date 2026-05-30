# -*- coding: utf-8 -*-
"""
Theme Engine — manages QSS template rendering and font-scale handling.

Uses placeholders such as {FS_BODY} in style_template.qss to render the final
QSS string at the current scale. The scale preference is persisted to QSettings.
"""

from pathlib import Path
from morfyai.qt_compat import QtCore

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None


class ThemeEngine:
    """Theme engine: load the QSS template, apply font scaling, persist preferences."""

    # Baseline font sizes (px)
    BASE_SIZES = {
        "FS_MICRO": 10,
        "FS_XS": 11,
        "FS_SM": 12,
        "FS_BODY": 13,
        "FS_MD": 14,
        "FS_LG": 16,
        "FS_XL": 17,
    }

    SCALE_MIN = 0.7
    SCALE_MAX = 1.5
    SCALE_STEP = 0.1

    def __init__(self):
        self._scale: float = 1.0
        self._template: str = ""

    # ---- Template loading ----

    def load_template(self, path: Path):
        """Load the QSS template from a file."""
        try:
            self._template = path.read_text("utf-8")
        except Exception as e:
            _dbg(f"[ThemeEngine] Template load failed: {e}")
            self._template = ""

    # ---- Scale control ----

    @property
    def scale(self) -> float:
        return self._scale

    def set_scale(self, scale: float):
        """Set the scale (automatically clamped to [0.7, 1.5])."""
        self._scale = max(self.SCALE_MIN, min(self.SCALE_MAX, round(scale, 2)))

    def zoom_in(self):
        self.set_scale(self._scale + self.SCALE_STEP)

    def zoom_out(self):
        self.set_scale(self._scale - self.SCALE_STEP)

    def zoom_reset(self):
        self.set_scale(1.0)

    @property
    def scale_percent(self) -> int:
        return int(round(self._scale * 100))

    # ---- Rendering ----

    def render(self) -> str:
        """Replace placeholders ({FS_*}, {ASSETS_URL}) with concrete values."""
        if not self._template:
            return ""
        qss = self._template
        for name, base in self.BASE_SIZES.items():
            qss = qss.replace("{" + name + "}", str(round(base * self._scale)))
        # Inject absolute path to morfyai/assets/ as a Qt-compatible URL (forward slashes)
        try:
            assets_dir = Path(__file__).resolve().parent.parent / "assets"
            assets_url = str(assets_dir).replace("\\", "/")
            qss = qss.replace("{ASSETS_URL}", assets_url)
        except Exception:
            qss = qss.replace("{ASSETS_URL}", "")
        return qss

    # ---- Persistence ----

    def save_preference(self):
        """Save the current scale to QSettings."""
        try:
            settings = QtCore.QSettings("MorfyAI", "Settings")
            settings.setValue("font_scale", self._scale)
        except Exception:
            pass

    def load_preference(self):
        """Load the saved scale from QSettings."""
        try:
            settings = QtCore.QSettings("MorfyAI", "Settings")
            val = settings.value("font_scale", 1.0)
            self.set_scale(float(val))
        except Exception:
            self._scale = 1.0
