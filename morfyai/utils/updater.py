# -*- coding: utf-8 -*-
"""
MorfyAI - Auto-Update Module (disabled in MorfyAI fork)

Originally checked GitHub for new versions, downloaded, and applied updates.
The auto-update flow is disabled in this fork; implementation kept for reference.

Thread-safe: check / download / apply can be called from background threads;
UI callbacks come back via Qt Signal.
"""

import os
import sys
import json
import shutil
import zipfile
import tempfile
from pathlib import Path
from typing import Tuple

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None

# ---------- Constants ----------

GITHUB_OWNER = "Kazama-Suichiku"
GITHUB_REPO = "Houdini-Agent"

# GitHub API endpoint — based on Release (not branch)
_API_LATEST_RELEASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

# Project root (where the VERSION file lives)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_VERSION_FILE = _PROJECT_ROOT / "VERSION"

# ETag cache file (reduces GitHub API quota usage, handles 403 rate limiting)
_ETAG_CACHE_FILE = _PROJECT_ROOT / "cache" / "update_cache.json"

# Paths to preserve (do not overwrite) during update
_PRESERVE_PATHS = frozenset({
    "config",           # user config such as API keys
    "cache",            # conversation cache, document index
    "trainData",        # training data
    ".git",             # git repo
})


# ==========================================================
# Version utilities
# ==========================================================

def get_local_version() -> str:
    """Read the local VERSION file; return the version string, or '0.0.0' on failure"""
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return "0.0.0"


def _parse_version(v: str) -> Tuple[int, ...]:
    """Parse '1.2.1' into (1, 2, 1) for comparison"""
    parts = []
    for seg in v.strip().split("."):
        try:
            parts.append(int(seg))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _is_legacy_internal_version(v: str) -> bool:
    """Detect old internal version numbers (major >= 5, e.g. 7.0.1, 6.8.3)

    Prior to v1.0.0 the project used internal versions v5.0~v7.0.1.
    Those numbers are greater than the official Release versions (1.x.x),
    which would cause the updater to wrongly think the local version is newer,
    so we need special handling to force an update.
    """
    parts = _parse_version(v)
    return len(parts) > 0 and parts[0] >= 5


def _version_gt(remote: str, local: str) -> bool:
    """remote > local ?

    Special case: if local is an old internal version (major >= 5)
    and remote is an official Release version (major < 5), force an update.
    """
    local_parts = _parse_version(local)
    remote_parts = _parse_version(remote)

    # Old internal version -> official version: force update
    if _is_legacy_internal_version(local) and not _is_legacy_internal_version(remote):
        return True

    return remote_parts > local_parts


# ==========================================================
# ETag cache
# ==========================================================

def _load_etag_cache() -> dict:
    """Load the ETag cache (contains last ETag and release data)"""
    try:
        if _ETAG_CACHE_FILE.exists():
            with open(_ETAG_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_etag_cache(data: dict):
    """Save the ETag cache"""
    try:
        _ETAG_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_ETAG_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ==========================================================
# Check for updates
# ==========================================================

# Module-level cache: zipball_url of latest release (written by check_update, read by download_and_apply)
_cached_zipball_url: str = ""


def check_update(timeout: float = 8.0) -> dict:
    """Check GitHub Releases for a newer version

    Uses an ETag cache mechanism:
    - First request: record ETag + full release data
    - Subsequent requests: send If-None-Match -> 304 does not count against rate limit
    - On 403 rate limit: fall back to cached data

    Returns:
        {
            'has_update': bool,
            'local_version': str,
            'remote_version': str,   # Release tag (e.g. 'v1.2.1' -> '1.2.1')
            'release_name': str,     # Release title
            'release_notes': str,    # Release notes (first line)
            'error': str,            # Error message ('' on success)
        }
    """
    global _cached_zipball_url
    
    result = {
        'has_update': False,
        'local_version': get_local_version(),
        'remote_version': '',
        'release_name': '',
        'release_notes': '',
        'error': '',
    }
    
    try:
        import requests  # type: ignore
    except ImportError:
        lib_dir = str(_PROJECT_ROOT / "lib")
        if lib_dir not in sys.path:
            sys.path.insert(0, lib_dir)
        import requests  # type: ignore
    
    # Load ETag cache
    etag_cache = _load_etag_cache()

    try:
        headers = {"Accept": "application/vnd.github.v3+json"}

        # If we have a cached ETag, use a conditional request (304 doesn't count toward API quota)
        cached_etag = etag_cache.get("etag", "")
        if cached_etag:
            headers["If-None-Match"] = cached_etag

        resp = requests.get(_API_LATEST_RELEASE, headers=headers, timeout=timeout)

        if resp.status_code == 304:
            # 304 Not Modified: Release data unchanged, use cache
            data = etag_cache.get("release_data", {})
            if not data:
                result['error'] = "Cache data invalid, please retry later"
                return result
        elif resp.status_code == 404:
            result['error'] = "No Release version available"
            return result
        elif resp.status_code == 403:
            # 403: API rate limited — fall back to cache
            cached_data = etag_cache.get("release_data", {})
            if cached_data:
                data = cached_data
                # Don't error out, silently use cache (release_notes will reflect this)
            else:
                result['error'] = "GitHub API rate limited (403), please retry in a few minutes"
                return result
        elif resp.status_code != 200:
            result['error'] = f"GitHub API returned {resp.status_code}"
            return result
        else:
            # 200 OK: parse new data and update cache
            data = resp.json()
            new_etag = resp.headers.get("ETag", "")
            _save_etag_cache({
                "etag": new_etag,
                "release_data": data,
            })

        # Parse release data
        tag = data.get("tag_name", "")
        remote_ver = tag.lstrip("vV")  # strip v/V prefix
        result['remote_version'] = remote_ver
        result['release_name'] = data.get("name", "") or tag

        # Release notes (use first line as a summary)
        body = data.get("body", "") or ""
        result['release_notes'] = body.split("\n")[0].strip() if body else ""

        # Cache the download URL (zipball_url is provided by GitHub)
        _cached_zipball_url = data.get("zipball_url", "")

        # Compare versions — if remote_version is empty, treat as parse failure
        if not remote_ver:
            result['error'] = "Could not parse remote version"
            return result

        result['has_update'] = _version_gt(remote_ver, result['local_version'])

    except Exception as e:
        # On network error, try to fall back to cache
        cached_data = etag_cache.get("release_data", {})
        if cached_data:
            tag = cached_data.get("tag_name", "")
            remote_ver = tag.lstrip("vV")
            if remote_ver:
                result['remote_version'] = remote_ver
                result['release_name'] = cached_data.get("name", "") or tag
                body = cached_data.get("body", "") or ""
                result['release_notes'] = body.split("\n")[0].strip() if body else ""
                _cached_zipball_url = cached_data.get("zipball_url", "")
                result['has_update'] = _version_gt(remote_ver, result['local_version'])
                return result

        if 'Timeout' in type(e).__name__:
            result['error'] = "Connection to GitHub timed out, please check your network"
        else:
            result['error'] = f"Update check failed: {e}"

    return result


# ==========================================================
# Download & apply update
# ==========================================================

def download_and_apply(progress_callback=None) -> dict:
    """Download the latest Release version and overwrite local files

    check_update() must have been called first to cache the zipball_url.

    Args:
        progress_callback: optional callback (stage: str, percent: int) -> None
            stage: 'downloading' | 'extracting' | 'applying' | 'done'
            percent: 0-100

    Returns:
        {'success': bool, 'error': str, 'updated_files': int}
    """
    global _cached_zipball_url
    
    def _progress(stage: str, pct: int):
        if progress_callback:
            try:
                progress_callback(stage, pct)
            except Exception:
                pass
    
    if not _cached_zipball_url:
        return {'success': False, 'error': 'Download URL not found, please check for updates first', 'updated_files': 0}
    
    try:
        import requests  # type: ignore
    except ImportError:
        lib_dir = str(_PROJECT_ROOT / "lib")
        if lib_dir not in sys.path:
            sys.path.insert(0, lib_dir)
        import requests  # type: ignore
    
    tmp_dir = None
    try:
        # ---- 1. Download Release ZIP ----
        _progress('downloading', 0)
        resp = requests.get(_cached_zipball_url, stream=True, timeout=60)
        resp.raise_for_status()

        total_size = int(resp.headers.get('content-length', 0))

        tmp_dir = tempfile.mkdtemp(prefix="morfyai_update_")
        zip_path = os.path.join(tmp_dir, "update.zip")

        downloaded = 0
        with open(zip_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        _progress('downloading', min(95, int(downloaded / total_size * 95)))

        _progress('downloading', 100)

        # ---- 2. Extract ----
        _progress('extracting', 0)
        extract_dir = os.path.join(tmp_dir, "extracted")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_dir)
        _progress('extracting', 100)

        # GitHub ZIP extracts to a single top-level directory, e.g. Houdini-Agent-main/
        entries = os.listdir(extract_dir)
        if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
            source_root = os.path.join(extract_dir, entries[0])
        else:
            source_root = extract_dir

        # ---- 3. Overwrite files ----
        _progress('applying', 0)
        updated_count = 0
        target_root = str(_PROJECT_ROOT)

        for dirpath, dirnames, filenames in os.walk(source_root):
            # Compute relative path
            rel_dir = os.path.relpath(dirpath, source_root)

            # Skip directories that should be preserved
            top_dir = rel_dir.split(os.sep)[0] if rel_dir != '.' else ''
            if top_dir in _PRESERVE_PATHS:
                continue

            # Filter subdirectories (don't recurse into preserved dirs)
            dirnames[:] = [d for d in dirnames if d not in _PRESERVE_PATHS]

            # Ensure target directory exists
            target_dir = os.path.join(target_root, rel_dir) if rel_dir != '.' else target_root
            os.makedirs(target_dir, exist_ok=True)

            for fname in filenames:
                src_file = os.path.join(dirpath, fname)
                dst_file = os.path.join(target_dir, fname)

                try:
                    shutil.copy2(src_file, dst_file)
                    updated_count += 1
                except PermissionError:
                    # .pyd / .dll may be locked, skip
                    pass
                except Exception:
                    pass

        _progress('applying', 100)
        _progress('done', 100)

        return {'success': True, 'error': '', 'updated_files': updated_count}

    except Exception as e:
        return {'success': False, 'error': str(e), 'updated_files': 0}

    finally:
        # Clean up temp directory
        if tmp_dir and os.path.exists(tmp_dir):
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass


# ==========================================================
# Restart the plugin
# ==========================================================

def restart_plugin():
    """Restart the MorfyAI plugin window

    Achieves a "restart" effect by reloading modules and calling show_tool().
    Must be called on the Qt main thread.
    """
    try:
        import importlib

        # Force-remove all loaded morfyai modules
        mods_to_remove = [k for k in sys.modules if k.startswith('morfyai')]
        for k in mods_to_remove:
            del sys.modules[k]

        # Re-import and launch
        # Note: _reload_modules in main.py handles module reloading
        if 'morfyai.main' in sys.modules:
            del sys.modules['morfyai.main']

        from morfyai.main import show_tool
        return show_tool()
        
    except Exception as e:
        _dbg(f"[Updater] Restart failed: {e}")
        import traceback
        traceback.print_exc()
        return None
