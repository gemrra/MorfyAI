# -*- coding: utf-8 -*-
from __future__ import annotations

import logging, logging.handlers
import os
from .settings import _get_cache_dir  # type: ignore

def get_logger() -> logging.Logger:
	logger = logging.getLogger("houdini.mcp")
	logger.setLevel(logging.INFO)
	logger.propagate = False

	# Houdini reloads MorfyAI modules without restarting the process. Remove any
	# old console StreamHandler left by a previous module version, while keeping
	# existing file handlers and avoiding duplicate handlers on reload.
	for existing in list(logger.handlers):
		if isinstance(existing, logging.StreamHandler) and not isinstance(existing, logging.FileHandler):
			logger.removeHandler(existing)
			try:
				existing.close()
			except Exception:
				pass

	try:
		from morfyai.utils.debug_log import log as debug_log

		class _DebugConsoleHandler(logging.Handler):
			_morfyai_debug_console_handler = True

			def emit(self, record):
				try:
					debug_log("[MCP]", self.format(record))
				except Exception:
					pass

		if not any(getattr(h, "_morfyai_debug_console_handler", False) for h in logger.handlers):
			console = _DebugConsoleHandler()
			console.setLevel(logging.INFO)
			console.setFormatter(logging.Formatter("%(levelname)s | %(threadName)s | %(message)s"))
			logger.addHandler(console)
	except Exception:
		pass

	try:
		log_dir = _get_cache_dir()
		os.makedirs(log_dir, exist_ok=True)
		log_path = os.path.abspath(os.path.join(log_dir, "houdini_mcp.log"))
		if not any(
			isinstance(h, logging.handlers.RotatingFileHandler)
			and os.path.abspath(getattr(h, "baseFilename", "")) == log_path
			for h in logger.handlers
		):
			handler = logging.handlers.RotatingFileHandler(
				log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
			)
			handler.setFormatter(logging.Formatter(
				"%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"
			))
			logger.addHandler(handler)
	except Exception:
		pass

	return logger
