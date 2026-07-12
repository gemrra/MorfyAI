# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict
import os, tempfile

try:
	from shared.common_utils import load_config as _load_config, get_cache_dir as _get_cache_dir
except Exception:
	def _get_cache_dir() -> str:
		try:
			here = os.path.dirname(os.path.abspath(__file__))
			cur = here
			while True:
				if os.path.exists(os.path.join(cur, "README.md")):
					break
				parent = os.path.dirname(cur)
				if parent == cur:
					break
				cur = parent
			cache_dir = os.path.join(cur, "cache")
			os.makedirs(cache_dir, exist_ok=True)
			return cache_dir
		except Exception:
			return tempfile.gettempdir()

	def _load_config(config_name: str, dcc_type: Optional[str] = None):
		cfg_dir = os.path.join(os.path.dirname(_get_cache_dir()), "config")
		os.makedirs(cfg_dir, exist_ok=True)
		fname = f"{dcc_type + '_' if dcc_type else ''}{config_name}.ini"
		path = os.path.join(cfg_dir, fname)
		cfg: Dict[str, str] = {}
		if os.path.exists(path):
			try:
				with open(path, "r", encoding="utf-8") as f:
					for line in f:
						if ":" in line:
							k, v = line.strip().split(":", 1)
							cfg[k] = v
			except Exception:
				pass
		return cfg, path


def _find_repo_root() -> Optional[str]:
	try:
		cur = os.path.dirname(os.path.abspath(__file__))
		while True:
			if os.path.exists(os.path.join(cur, "README.md")):
				return cur
			parent = os.path.dirname(cur)
			if parent == cur:
				return None
			cur = parent
	except Exception:
		return None


def _default_port() -> int:
	"""9000 for a normal (release) install, 9001 for the dev-mode copy.

	IMPORTANT: this can NOT be a Houdini package env var (e.g. a
	MORFYAI_MCP_PORT set in MorfyAI-Dev.json) — package env vars are merged
	into the single houdini.exe process's environment, not scoped per
	package, so a var set by the dev package is equally visible to the
	release install's code running in the same session. That was tried and
	caused the release install to also bind 9001, leaving 9000 empty.
	Instead this is derived from something that can never leak: whether
	THIS install's own repo root ships launcher_dev.py, a dev-only file the
	release zip build always excludes (see tools/release/build_zip.py
	_EXCLUDE). Each install's settings.py resolves its own root, so there's
	no cross-install leakage possible.
	"""
	root = _find_repo_root()
	if root and os.path.exists(os.path.join(root, "launcher_dev.py")):
		return 9001
	return 9000


@dataclass
class MCPSettings:
	enabled: bool = True
	host: str = "127.0.0.1"
	port: int = 9000
	transport: str = "streamable-http"
	request_timeout: float = 12.0
	request_retries: int = 2
	request_backoff: float = 0.5
	enable_flipbook: bool = False
	help_server_port: int = 48626  # Houdini local help server port


def read_settings() -> MCPSettings:
	cfg_dict, _ = _load_config("ai", dcc_type="houdini")

	def _bool(val: Optional[str], default: bool) -> bool:
		if val is None:
			return default
		return str(val).strip().lower() in {"1", "true", "yes", "on"}

	def _int(val: Optional[str], default: int) -> int:
		try:
			return int(val) if val is not None else default
		except Exception:
			return default

	def _float(val: Optional[str], default: float) -> float:
		try:
			return float(val) if val is not None else default
		except Exception:
			return default

	return MCPSettings(
		enabled=_bool(cfg_dict.get("mcp_enabled"), True),
		host=cfg_dict.get("mcp_host", "127.0.0.1"),
		port=_int(cfg_dict.get("mcp_port"), _default_port()),
		transport=cfg_dict.get("mcp_transport", "streamable-http"),
		request_timeout=_float(cfg_dict.get("mcp_request_timeout"), 12.0),
		request_retries=_int(cfg_dict.get("mcp_request_retries"), 2),
		request_backoff=_float(cfg_dict.get("mcp_request_backoff"), 0.5),
		enable_flipbook=_bool(cfg_dict.get("mcp_enable_flipbook"), False),
		help_server_port=_int(cfg_dict.get("mcp_help_server_port"), 48626),
	)
