"""
MorfyAI - Dev-mode launcher.

Runs the DEVELOPMENT copy of MorfyAI (this repo) independently from an
installed release, so you can iterate here without touching the stable
release you use day to day.

Registered by a separate Houdini package (MorfyAI-Dev.json) under a
distinct "MorfyAI Dev" menu, with a UNIQUE entry-module name
(`launcher_dev`) so it never collides with the release's `launcher` in
sys.modules. Each launch re-imports the correct copy from scratch, so only
one of dev/release is live at a time — switching between them is fine, but
they are not meant to be open simultaneously.

Data separation is automatic: config/cache/history all resolve relative to
each install's own repo root (shared.common_utils.get_repo_root walks up to
the README.md beside it), so dev writes to <dev repo>/config and the release
writes to its own — they never share API keys, history, or memory.
"""

import sys
import os

_DEV_ROOT = os.path.dirname(os.path.abspath(__file__))

# Bare top-level names MorfyAI uses that also exist in the release copy (and
# in the unrelated upstream "Houdini Agent" product). Any of these cached
# from another install must be evicted so the dev copy imports its own.
_ISOLATE = ("launcher", "main", "shared", "morfyai")


def _pick_lib_dir():
    """Same version-aware pick as launcher.py -- see its _pick_lib_dir for
    why: vendored .pyd binaries are locked to one Python minor version, and
    Houdini's bundled Python differs by release, so use whichever vendor
    folder matches THIS interpreter."""
    major, minor = sys.version_info[0], sys.version_info[1]
    if (major, minor) != (3, 11):
        versioned = os.path.join(_DEV_ROOT, f"lib_py{major}{minor}")
        if os.path.isdir(versioned):
            return versioned
    return os.path.join(_DEV_ROOT, "lib")


def _prioritize_and_isolate():
    # Put this dev install's dirs at the very front of sys.path.
    for p in (_pick_lib_dir(),
              os.path.join(_DEV_ROOT, "morfyai"),
              _DEV_ROOT):
        if os.path.isdir(p):
            if p in sys.path:
                sys.path.remove(p)
            sys.path.insert(0, p)

    # Drop any cached copy of a colliding module whose file lives outside
    # this dev root (i.e. the release copy, or Houdini Agent's).
    root = os.path.abspath(_DEV_ROOT)
    for k in list(sys.modules.keys()):
        if k.split(".")[0] not in _ISOLATE:
            continue
        mod = sys.modules.get(k)
        f = getattr(mod, "__file__", None)
        if not f or not os.path.abspath(f).startswith(root):
            sys.modules.pop(k, None)


def show_tool():
    _prioritize_and_isolate()
    try:
        import importlib
        if "main" in sys.modules:
            import main
            importlib.reload(main)
        else:
            import main
        return main.show_tool()
    except Exception as e:
        print(f"Failed to launch MorfyAI (dev): {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    show_tool()
