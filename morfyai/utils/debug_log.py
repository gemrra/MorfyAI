# -*- coding: utf-8 -*-
"""Lightweight debug log ring-buffer for MorfyAI.

Use `log("Tag", "message", ...)` to append a line that's viewable from the
in-app Debug Console (overflow menu → Debug Console) without polluting
Houdini's main Console window.

Messages are buffered in MorfyAI's in-app Debug Console. Optional stdout echo is off by default.
"""

from __future__ import annotations

import os
import sys
import threading
from collections import deque
from datetime import datetime
from typing import Iterable, List, Optional

_BUFFER_SIZE = 2000  # max lines retained

_buffer: deque = deque(maxlen=_BUFFER_SIZE)
_lock = threading.Lock()
# MorfyAI diagnostics always stay in the in-app Debug Console. Do not let an
# inherited environment variable spill them into Houdini's native console.
_echo_stdout: bool = os.environ.get("MORFY_DEBUG", "0") in ("1", "true", "True", "yes")


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(*parts) -> None:
    """Append a line to the in-app debug buffer.

    Args are stringified and joined with space. A timestamp is prefixed.
    MorfyAI diagnostics are kept in the in-app Debug Console.
    """
    try:
        msg = " ".join(str(p) for p in parts)
    except Exception:
        msg = "<debug_log: failed to stringify args>"
    line = f"{_now()}  {msg}"
    with _lock:
        _buffer.append(line)
    if _echo_stdout:
        try:
            sys.__stdout__.write(line + "\n")
            sys.__stdout__.flush()
        except Exception:
            pass


def get_lines() -> List[str]:
    """Return a snapshot of the buffer."""
    with _lock:
        return list(_buffer)


def clear() -> None:
    """Drop all buffered lines."""
    with _lock:
        _buffer.clear()


def set_echo_stdout(enabled: bool) -> None:
    """Compatibility shim: MorfyAI never echoes diagnostics to stdout."""
    global _echo_stdout
    _echo_stdout = bool(enabled)


def is_echo_stdout() -> bool:
    return _echo_stdout


def install_exception_routing(package_root: str) -> None:
    """Route uncaught MorfyAI exceptions to this buffer, preserving host hooks.

    Exceptions originating outside the MorfyAI package are passed to the
    exception hooks that were already installed by Houdini or Python.
    """
    import os
    import sys
    import traceback

    root = os.path.normcase(os.path.realpath(package_root))
    root_is_file = os.path.isfile(root)

    def _traceback_is_morfyai(tb) -> bool:
        while tb is not None:
            filename = os.path.normcase(os.path.realpath(tb.tb_frame.f_code.co_filename))
            if root_is_file and filename == root:
                return True
            try:
                if not root_is_file and os.path.commonpath((root, filename)) == root:
                    return True
            except (OSError, ValueError):
                pass
            tb = tb.tb_next
        return False

    current_sys_hook = sys.excepthook
    if getattr(current_sys_hook, "_morfyai_exception_router_root", None) != root:
        def _sys_exception_hook(exc_type, exc_value, exc_tb):
            if _traceback_is_morfyai(exc_tb):
                log("[Exception]", "".join(traceback.format_exception(exc_type, exc_value, exc_tb)).rstrip())
                return
            current_sys_hook(exc_type, exc_value, exc_tb)

        _sys_exception_hook._morfyai_exception_router_root = root
        sys.excepthook = _sys_exception_hook

    try:
        import threading
        current_thread_hook = threading.excepthook
        if getattr(current_thread_hook, "_morfyai_exception_router_root", None) != root:
            def _thread_exception_hook(args):
                if _traceback_is_morfyai(args.exc_traceback):
                    log("[Thread Exception]", "".join(traceback.format_exception(
                        args.exc_type, args.exc_value, args.exc_traceback
                    )).rstrip())
                    return
                current_thread_hook(args)

            _thread_exception_hook._morfyai_exception_router_root = root
            threading.excepthook = _thread_exception_hook
    except Exception:
        pass


def buffer_size() -> int:
    with _lock:
        return len(_buffer)
