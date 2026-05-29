# -*- coding: utf-8 -*-
"""
Qt compatibility shim — unifies PySide6 / PySide2 imports.

Houdini 20.5 and earlier ship with PySide2; Houdini 21+ ships with PySide6.
All modules import QtWidgets / QtCore / QtGui / QSettings from here so we
don't need per-file try/except blocks.

Usage:
    from morfyai.qt_compat import QtWidgets, QtCore, QtGui, QSettings
"""

try:
    from PySide6 import QtWidgets, QtCore, QtGui          # noqa: F401
    from PySide6.QtCore import QSettings                   # noqa: F401
    PYSIDE_VERSION = 6
except ImportError:
    from PySide2 import QtWidgets, QtCore, QtGui          # noqa: F401
    from PySide2.QtCore import QSettings                   # noqa: F401
    PYSIDE_VERSION = 2


def invoke_on_main(receiver, slot_name: str, *args):
    """Thread-safely invoke a slot on the main thread (PySide2 / PySide6 compatible).

    PySide6 supports QMetaObject.invokeMethod + Q_ARG;
    PySide2 lacks Q_ARG, so we fall back to QTimer.singleShot(0, lambda).

    Args:
        receiver: target QObject (only used by PySide6)
        slot_name: slot method name
        *args: arguments passed to the slot
    """
    if PYSIDE_VERSION == 6:
        q_args = [QtCore.Q_ARG(type(a), a) for a in args]
        QtCore.QMetaObject.invokeMethod(
            receiver, slot_name,
            QtCore.Qt.QueuedConnection,
            *q_args
        )
    else:
        # PySide2: queue onto the main thread via QTimer.singleShot
        method = getattr(receiver, slot_name)
        QtCore.QTimer.singleShot(0, lambda: method(*args))
