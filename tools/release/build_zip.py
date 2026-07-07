# -*- coding: utf-8 -*-
"""
MorfyAI - release zip builder.

Packages the current git-tracked tree into release/MorfyAI-<version>.zip,
laid out so extracting it directly into a Houdini packages/ folder just
works (see docs on the drop-in package format):

    MorfyAI.json   <- tiny pointer file, references $HOUDINI_PACKAGE_DIR
    MorfyAI/       <- the whole plugin (this repo's tracked files)

Also writes a <name>.sha256 sidecar the app verifies after downloading,
before ever extracting anything onto disk.

Usage (from the repo root):
    python tools/release/build_zip.py
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Tracked files/dirs that are dev-only and shouldn't ship in the release zip.
_EXCLUDE = {".mcp.json", ".gitignore", "Doc", "docs",
            "launcher_dev.py", "houdini_dev", "tools"}


def _read_version():
    with open(os.path.join(_REPO_ROOT, "VERSION"), encoding="utf-8") as f:
        return f.read().strip()


def _tracked_files():
    out = subprocess.check_output(
        ["git", "ls-files"], cwd=_REPO_ROOT, encoding="utf-8"
    )
    files = []
    for rel in out.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        top = rel.split("/", 1)[0]
        if top in _EXCLUDE:
            continue
        files.append(rel)
    return files


def _package_json():
    return {
        "enable": True,
        "env": [
            {"MORFYAI": "$HOUDINI_PACKAGE_PATH/MorfyAI"},
            {"HOUDINI_PATH": {"value": ["$MORFYAI/houdini"], "method": "prepend"}},
            {"PYTHONPATH": {"value": ["$MORFYAI"], "method": "prepend"}},
        ],
    }


def build():
    version = _read_version()
    files = _tracked_files()

    release_dir = os.path.join(_REPO_ROOT, "release")
    os.makedirs(release_dir, exist_ok=True)

    zip_name = "MorfyAI-%s.zip" % version
    zip_path = os.path.join(release_dir, zip_name)

    with tempfile.TemporaryDirectory() as tmp:
        # MorfyAI.json (sibling pointer) + MorfyAI/ (plugin contents)
        with open(os.path.join(tmp, "MorfyAI.json"), "w", encoding="utf-8") as f:
            json.dump(_package_json(), f, indent=2)
            f.write("\n")

        plugin_dir = os.path.join(tmp, "MorfyAI")
        for rel in files:
            src = os.path.join(_REPO_ROOT, rel)
            dst = os.path.join(plugin_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)

        if os.path.exists(zip_path):
            os.remove(zip_path)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, filenames in os.walk(tmp):
                for name in filenames:
                    full = os.path.join(root, name)
                    arcname = os.path.relpath(full, tmp)
                    zf.write(full, arcname)

    sha256 = hashlib.sha256()
    with open(zip_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha256.update(chunk)
    digest = sha256.hexdigest()

    sha_path = zip_path + ".sha256"
    with open(sha_path, "w", encoding="utf-8") as f:
        f.write("%s  %s\n" % (digest, zip_name))

    print("=" * 60)
    print("Built %s" % zip_path)
    print("  files   : %d" % len(files))
    print("  sha256  : %s" % digest)
    print("  sidecar : %s" % sha_path)
    print("=" * 60)
    return zip_path, digest


if __name__ == "__main__":
    build()
