# -*- coding: utf-8 -*-
"""Lightweight debug log ring-buffer for MorfyAI.

Use `log("Tag", "message", ...)` to append a line that's viewable from the
in-app Debug Console (overflow menu → Debug Console) without polluting
Houdini's main Console window.

By default the message is buffered silently. Set the env var MORFY_DEBUG=1
(or call `set_echo_stdout(True)`) if you also want it printed to stdout.
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
_echo_stdout: bool = os.environ.get("MORFY_DEBUG", "0") in ("1", "true", "True", "yes")


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(*parts) -> None:
    """Append a line to the in-app debug buffer.

    Args are stringified and joined with space. A timestamp is prefixed.
    If MORFY_DEBUG env var is set, the line is also written to stdout.
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
    """Toggle whether `log()` also writes to stdout."""
    global _echo_stdout
    _echo_stdout = bool(enabled)


def is_echo_stdout() -> bool:
    return _echo_stdout


def buffer_size() -> int:
    with _lock:
        return len(_buffer)
