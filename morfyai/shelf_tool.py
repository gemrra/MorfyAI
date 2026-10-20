"""
MorfyAI - Shelf Tool Entry Point
Copy this code into a Houdini Shelf Tool to launch MorfyAI.
"""

import sys
import os

# Add tool path to Python path
tool_path = r"E:\AILocal\MorfyAI"
if tool_path not in sys.path:
    sys.path.insert(0, tool_path)

try:
    if 'launcher' in sys.modules:
        import importlib
        import launcher
        importlib.reload(launcher)
    else:
        import launcher

    launcher.show_tool()

except Exception as e:
    import hou
    hou.ui.displayMessage(
        f"Failed to launch MorfyAI:\n\n{str(e)}",
        severity=hou.severityType.Error,
        title="MorfyAI Error"
    )
    import traceback
    try:
        from morfyai.utils.debug_log import log as _debug_log
        _debug_log("[Shelf Tool] MorfyAI failed to launch:", e, "\n", traceback.format_exc())
    except Exception:
        pass
