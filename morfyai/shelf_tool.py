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
    print("=" * 60)
    print("MorfyAI Error Traceback:")
    print("=" * 60)
    traceback.print_exc()
    print("=" * 60)
