"""
Shared Utilities for MorfyAI
"""

import os
from datetime import datetime

def get_repo_root(start_dir=None):
    """Get the repository root (directory containing README.md is treated as root)."""
    try:
        current = start_dir or os.path.dirname(os.path.abspath(__file__))
        # Walk upward until README.md is found or disk root is reached
        while True:
            if os.path.exists(os.path.join(current, "README.md")):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    except Exception:
        pass
    # Fallback: two levels above this file
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_config_dir():
    """Get the unified config directory: <repo_root>/config"""
    repo_root = get_repo_root()
    config_dir = os.path.join(repo_root, "config")
    os.makedirs(config_dir, exist_ok=True)
    return config_dir

def get_cache_dir():
    """Get the unified cache directory: <repo_root>/cache"""
    repo_root = get_repo_root()
    cache_dir = os.path.join(repo_root, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir

def load_config(config_name, dcc_type=None):
    """Load a config file.

    Args:
        config_name: config name
        dcc_type: DCC type ('houdini', 'maya'); if None, load shared config
    """
    config_dir = get_config_dir()

    if dcc_type:
        config_file = f"{dcc_type}_{config_name}.ini"
    else:
        config_file = f"{config_name}.ini"

    config_path = os.path.join(config_dir, config_file)
    config = {}

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines:
                    if ":" in line:
                        key, value = line.strip().split(":", 1)
                        config[key] = value
        except Exception as e:
            print(f"Failed to load config: {e}")

    return config, config_path

def save_config(config_name, config, dcc_type=None):
    """Save a config file.

    Args:
        config_name: config name
        config: config dict
        dcc_type: DCC type ('houdini', 'maya')
    """
    config_dir = get_config_dir()

    if dcc_type:
        config_file = f"{dcc_type}_{config_name}.ini"
    else:
        config_file = f"{config_name}.ini"

    config_path = os.path.join(config_dir, config_file)

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            for key, value in config.items():
                f.write(f"{key}:{value}\n")
        return True, config_path
    except Exception as e:
        print(f"Failed to save config: {e}")
        return False, ""

def get_history_path(history_name, dcc_type=None):
    """Get the history file path."""
    config_dir = get_config_dir()

    if dcc_type:
        history_file = f"{dcc_type}_{history_name}_history.txt"
    else:
        history_file = f"{history_name}_history.txt"

    return os.path.join(config_dir, history_file)

def add_to_history(history_name, entry, dcc_type=None):
    """Append an entry to the history file."""
    try:
        history_path = get_history_path(history_name, dcc_type)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(history_path, "a", encoding="utf-8") as f:
            f.write(f"{entry}|{timestamp}\n")
        return True
    except Exception as e:
        print(f"Failed to add history entry: {e}")
        return False

def load_history(history_name, dcc_type=None):
    """Load history records."""
    try:
        history_path = get_history_path(history_name, dcc_type)
        if not os.path.exists(history_path):
            return []

        with open(history_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        history = []
        for line in lines:
            if "|" in line:
                parts = line.strip().split("|")
                history.append(parts)

        return history
    except Exception as e:
        print(f"Failed to load history: {e}")
        return []
