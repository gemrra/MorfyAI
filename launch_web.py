"""
MorfyAI Web Panel — standalone launcher (redesign preview).

Opens the new web-based UI (the mockup, rendered 1:1 via QWebEngineView) in a
separate window WITHOUT touching the existing panel. Use this to verify the
redesigned UI loads and chats in Houdini before the full port replaces the old
panel.

Run inside Houdini (Windows -> Python Source Editor):

    import sys; sys.path.insert(0, r"E:/AILocal/MorfyAI")
    import launch_web; launch_web.show()
"""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.join(_ROOT, "lib")
if os.path.isdir(_LIB) and _LIB not in sys.path:
    sys.path.insert(0, _LIB)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_win = None


def show():
    global _win

    # Force-reload the panel modules so edits are picked up without restart
    for name in ("morfyai.ui.web_panel",):
        if name in sys.modules:
            import importlib
            importlib.reload(sys.modules[name])

    from morfyai.qt_compat import QtWidgets, QtCore

    parent = None
    try:
        import hou
        parent = hou.qt.mainWindow()
    except Exception:
        pass

    if not QtWidgets.QApplication.instance():
        QtWidgets.QApplication([])

    try:
        from morfyai.ui.web_panel import MorfyWebPanel
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            QtWidgets.QMessageBox.critical(None, "MorfyAI Web", f"Failed to import web panel:\n{e}")
        except Exception:
            pass
        return None

    # Close a previous instance
    try:
        if _win is not None:
            _win.close()
            _win.deleteLater()
    except Exception:
        pass

    win = QtWidgets.QMainWindow(parent)
    win.setWindowTitle("MorfyAI — Redesign Preview")
    win.setWindowFlags(QtCore.Qt.Window)
    win.resize(440, 720)
    try:
        panel = MorfyWebPanel(win)
        win.setCentralWidget(panel)
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            QtWidgets.QMessageBox.critical(None, "MorfyAI Web", f"Failed to create web panel:\n{e}")
        except Exception:
            pass
        return None

    win.show()
    win.raise_()
    win.activateWindow()
    _win = win
    return win


if __name__ == "__main__":
    show()
