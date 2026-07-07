# -*- coding: utf-8 -*-
"""
MorfyAI - one-click Houdini package installer.

Run this INSIDE Houdini (Windows -> Python Shell) using EITHER:

    import sys; sys.path.insert(0, r"H:/Dev/Apps/MorfyAI")
    import install; install.install()

or, if you prefer exec (the script will try to locate the repo itself):

    exec(open(r"H:/Dev/Apps/MorfyAI/install.py").read())

It writes a MorfyAI.json package file into $HOUDINI_USER_PREF_DIR/packages/
with MORFYAI pointed at THIS repo copy, so you never have to edit paths by
hand. Restart Houdini afterwards and the MorfyAI shelf button appears.
"""

import os
import json

_PKG_NAME = "MorfyAI.json"


def _is_repo_root(path):
    return (
        os.path.isfile(os.path.join(path, "launcher.py"))
        and os.path.isdir(os.path.join(path, "morfyai"))
        and os.path.isfile(os.path.join(path, "VERSION"))
    )


def _find_repo_root(hint=None):
    candidates = []
    if hint:
        candidates.append(os.path.abspath(hint))
    try:
        if __file__:
            candidates.append(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        pass
    candidates.append(os.getcwd())
    for parent in list(candidates):
        candidates.append(os.path.dirname(parent))
    for c in candidates:
        if c and _is_repo_root(c):
            return c
    return None


def install(repo_path=None):
    try:
        import hou
    except ImportError:
        print("ERROR: install.py must be run from inside Houdini.")
        print("Open Windows -> Python Shell and run:")
        print('  import sys; sys.path.insert(0, r"<path-to-MorfyAI>"); import install; install.install()')
        return False

    repo_root = _find_repo_root(repo_path)
    if not repo_root:
        print("ERROR: could not locate the MorfyAI repo root.")
        print("Run: install.install(r'<path-to-MorfyAI>')")
        return False

    repo_root_fwd = repo_root.replace("\\", "/")

    prefs_dir = hou.expandString("$HOUDINI_USER_PREF_DIR")
    packages_dir = os.path.join(prefs_dir, "packages")
    os.makedirs(packages_dir, exist_ok=True)

    pkg = {
        "enable": True,
        "env": [
            {"MORFYAI": repo_root_fwd},
            {"HOUDINI_PATH": {"value": ["$MORFYAI/houdini"], "method": "prepend"}},
            {"PYTHONPATH": {"value": ["$MORFYAI"], "method": "prepend"}},
        ],
    }

    out_path = os.path.join(packages_dir, _PKG_NAME)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(pkg, f, indent=2)
        f.write("\n")

    print("=" * 60)
    print("MorfyAI package installed.")
    print(f"  Repo path : {repo_root_fwd}")
    print(f"  Package   : {out_path}")
    print("Restart Houdini for the MorfyAI shelf button to appear.")
    print("=" * 60)
    return True


if __name__ == "__main__":
    install()
