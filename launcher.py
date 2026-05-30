"""
MorfyAI - Launcher
"""

import sys
import os

# ============================================================
# Force-use the local lib/ directory for dependencies
# ============================================================
_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
_LIB_DIR = os.path.join(_ROOT_DIR, 'lib')

if os.path.exists(_LIB_DIR):
    if _LIB_DIR in sys.path:
        sys.path.remove(_LIB_DIR)
    sys.path.insert(0, _LIB_DIR)

# ============================================================

def detect_dcc():
    """Detect the currently-running DCC application."""
    try:
        import hou
        return "houdini"
    except ImportError:
        pass

    return None

def launch_morfyai():
    """Launch MorfyAI"""
    tool_path = os.path.join(os.path.dirname(__file__), "morfyai")
    if tool_path not in sys.path:
        sys.path.insert(0, tool_path)

    # Purge legacy package-name leftovers (HOUDINI_HIP_MANAGER -> morfyai migration)
    old_mods = [k for k in sys.modules if k.startswith('HOUDINI_HIP_MANAGER')]
    for k in old_mods:
        del sys.modules[k]

    try:
        if 'main' in sys.modules:
            import importlib
            import main
            importlib.reload(main)
        else:
            import main

        return main.show_tool()
    except Exception as e:
        print(f"Failed to launch MorfyAI: {e}")
        import traceback
        traceback.print_exc()
        return None

def launch():
    """Auto-detect host and launch."""
    dcc = detect_dcc()

    if dcc == "houdini":
        print("Houdini detected, launching MorfyAI - Houdini Assistant...")
        return launch_morfyai()
    else:
        print("Error: Houdini not detected.")
        print("Please run this tool inside Houdini.")
        return None

# Global variable to store the window instance
_agent_window = None

def show_tool():
    """Unified entry function."""
    global _agent_window
    _agent_window = launch()
    return _agent_window

if __name__ == "__main__":
    show_tool()
