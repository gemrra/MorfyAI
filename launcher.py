"""
MorfyAI - Launcher
"""

import sys
import os

# ============================================================
# Force-use the local lib/ directory for dependencies, and make sure
# MorfyAI's own top-level modules win over any other Houdini package that
# happens to ship a module with the same bare name.
#
# The upstream "Houdini Agent" product (a separate install) also ships a
# top-level `shared` module on PYTHONPATH. Because it loads at Houdini
# startup, its `shared` lands in sys.modules first — so a later
# `import shared` from MorfyAI returns THAT cached copy regardless of
# sys.path order, and MorfyAI's config dir resolves into the other
# product's folder under C:\Program Files (Access denied). We fix this by
# (1) putting MorfyAI's own dirs at the front of sys.path and (2) evicting
# any cached top-level modules that collide by name but live outside this
# install, so MorfyAI re-imports its own.
# ============================================================
_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
_MORFYAI_DIR = os.path.join(_ROOT_DIR, 'morfyai')


def _pick_lib_dir():
    """Vendored deps are ABI-locked to one Python minor version (.pyd
    binaries). Houdini's bundled Python varies by release (3.11 through
    H21, 3.13 as of H22), so pick whichever vendor folder matches THIS
    interpreter instead of requiring a specific Houdini Python build —
    MorfyAI adapts to whatever Houdini the user has installed.
    'lib' is the default/legacy folder (Python 3.11); newer minor
    versions get a 'lib_pyXY' sibling, added as they're supported."""
    major, minor = sys.version_info[0], sys.version_info[1]
    if (major, minor) != (3, 11):
        versioned = os.path.join(_ROOT_DIR, f'lib_py{major}{minor}')
        if os.path.isdir(versioned):
            return versioned
    return os.path.join(_ROOT_DIR, 'lib')


_LIB_DIR = _pick_lib_dir()

# Bare top-level names MorfyAI uses that also exist in the DEV copy (and in
# the unrelated upstream "Houdini Agent" product). Any of these cached from
# another install must be evicted so THIS install imports its own.
_ISOLATE = ('shared', 'main', 'morfyai', 'launcher_dev')


def _purge_foreign_modules(names):
    """Drop cached top-level modules (and submodules) whose file lives
    outside this MorfyAI install, so our own copies get imported fresh."""
    root = os.path.abspath(_ROOT_DIR)
    for k in list(sys.modules.keys()):
        if k.split('.')[0] not in names:
            continue
        mod = sys.modules.get(k)
        f = getattr(mod, '__file__', None)
        if not f or not os.path.abspath(f).startswith(root):
            try:
                del sys.modules[k]
            except KeyError:
                pass


def _prioritize_and_isolate():
    """Put this install's dirs at the front of sys.path and evict any cached
    colliding modules from a different install. MUST run on EVERY launch (not
    just first import) — otherwise, after the DEV copy has been opened in the
    same Houdini session, its cached `shared`/`main`/`morfyai` modules linger
    and the release panel resolves config/history through the DEV copy,
    silently sharing data between the two installs."""
    for _p in (_LIB_DIR, _MORFYAI_DIR, _ROOT_DIR):
        if os.path.exists(_p):
            if _p in sys.path:
                sys.path.remove(_p)
            sys.path.insert(0, _p)
    _purge_foreign_modules(_ISOLATE)


_prioritize_and_isolate()

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
    # Re-assert this install's path priority and evict any foreign (dev)
    # copies cached earlier in the session, so config/history resolve to
    # THIS install every time — not just on the first launch.
    _prioritize_and_isolate()

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
