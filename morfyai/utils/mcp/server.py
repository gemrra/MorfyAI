# -*- coding: utf-8 -*-
from __future__ import annotations

"""FastMCP service and tool registry (OOP-split version, package name: utils.mcp).

Architecture:
    This module hosts the FastMCP HTTP service for external MCP clients.
    Low-level Houdini operations are delegated to hou_core.py wherever possible.
    Compare with client.py (internal AI-agent-facing, direct Python calls).
"""

import asyncio
import functools
import glob
import logging
import os
import queue
import tempfile
import threading
import time
import uuid
import re
from typing import Any, Optional, Callable


def _bootstrap_pywin32_from_lib():
	"""Make the vendored fastmcp/mcp stack importable.

	fastmcp + deps are installed via `pip install --target lib/`. The `mcp` package
	imports `pywintypes` (pywin32), but pywin32's .pth side-effects are NOT applied
	for a --target install, so we replicate them: ensure lib/ is on sys.path, add
	win32 / win32\\lib / Pythonwin, and register the pywin32_system32 DLL directory.
	Fully guarded — no-op if absent or not on Windows.
	"""
	import sys
	try:
		here = os.path.dirname(os.path.abspath(__file__))
		lib = os.path.abspath(os.path.join(here, "..", "..", "..", "lib"))
		if not os.path.isdir(lib):
			return
		if lib not in sys.path:
			sys.path.insert(0, lib)
		for sub in ("win32", os.path.join("win32", "lib"), "Pythonwin"):
			p = os.path.join(lib, sub)
			if os.path.isdir(p) and p not in sys.path:
				sys.path.append(p)
		dll = os.path.join(lib, "pywin32_system32")
		if os.path.isdir(dll):
			try:
				os.add_dll_directory(dll)
			except Exception:
				pass
			os.environ["PATH"] = dll + os.pathsep + os.environ.get("PATH", "")
	except Exception:
		pass


_bootstrap_pywin32_from_lib()


try:
	import hou  # type: ignore
except Exception:
	hou = None  # type: ignore

try:
	import requests
except Exception:
	requests = None  # type: ignore

try:
	from bs4 import BeautifulSoup
except Exception:
	BeautifulSoup = None  # type: ignore

from .settings import read_settings
from .logger import get_logger
from . import hou_core

log: logging.Logger = get_logger()

# runwhenglobal
mcp = None  # FastMCP instance
mcp_thread_handle: Optional[threading.Thread] = None
stop_event = threading.Event()
_server_start_time: float | None = None
_last_client_activity: float | None = None  # updated on every tool call (connection heartbeat)

# resourcesourceregister (used for flipbook image) 
_registered_flipbook_resources: set[str] = set()
_resource_lock = threading.RLock()

# simpletaskqueue (UI event loop consumecost) 
task_queue: queue.Queue = queue.Queue()


def _fastmcp_available() -> bool:
	return mcp is not None


def register_image_resource(filepath: str) -> str:
	"""willimageregisteras MCP resourcesource, returncanvia MCP HTTP access path. """
	global _registered_flipbook_resources, mcp
	if mcp is None:
		return filepath
	resource_id = f"flipbook_{uuid.uuid4().hex}.png"
	resource_url = f"file://{resource_id}"
	http_url = f"/resources/{resource_id}"
	with _resource_lock:
		if resource_url in _registered_flipbook_resources:
			return http_url

		@mcp.resource(uri=resource_url, mime_type="image/png")  # type: ignore[attr-defined]
		def _res() -> bytes:
			with open(filepath, "rb") as f:
				return f.read()

		_registered_flipbook_resources.add(resource_url)
	try:
		log.info("[MCP] registerresourcesourcesucceeded: %s", http_url)
	except Exception:
		pass
	return http_url


def _setup_fastmcp_tools():
	"""in FastMCP instanceonregisteralltool. """
	global mcp
	if mcp is None:
		return

	def ok(message: str = "", data: Any | None = None) -> dict:
		return {"status": "success", "message": message, "data": data}

	def err(message: str, code: Optional[str] = None, data: Any | None = None) -> dict:
		payload = {"status": "error", "message": message}
		if code:
			payload["code"] = code
		if data is not None:
			payload["data"] = data
		return payload

	def tool_wrapper(fn: Callable[..., dict]) -> Callable[..., dict]:
		@functools.wraps(fn)  # preserve fn's signature so FastMCP sees real params (not *args)
		def _wrapped(*args, **kwargs) -> dict:
			global _last_client_activity
			_last_client_activity = time.time()   # heartbeat: a client just called a tool
			try:
				return fn(*args, **kwargs)
			except Exception as e:
				log.exception("MCP tool error in %s", getattr(fn, "__name__", "<tool>"))
				return err(f"withinparterror: {e}", code="internal_error")
		_wrapped.__name__ = getattr(fn, "__name__", "wrapped")
		return _wrapped

	@mcp.tool  # type: ignore[attr-defined]
	@tool_wrapper
	def check_node_errors(node_path: str | None = None) -> dict:
		"""checknodeerror (delegate to hou_core sharedlayer) """
		success, msg, errors = hou_core.check_errors(node_path)
		return ok(msg, errors) if success else err(msg)

	@mcp.tool  # type: ignore[attr-defined]
	@tool_wrapper
	def display_node_result(node_path: str) -> dict:
		"""setnodeshowflag (delegate to hou_core sharedlayer) """
		success, msg = hou_core.set_display_flag(node_path)
		return ok(msg) if success else err(msg)

	@mcp.tool  # type: ignore[attr-defined]
	@tool_wrapper
	def get_houdini_help(help_type: str, item_name: str) -> dict:
		if requests is None:
			return err("requests notinstall. ")
		if BeautifulSoup is None:
			return err("bs4 notinstall. pleaseinstall beautifulsoup4. ")
		base_url = "https://www.sidefx.com/docs/houdini/"
		url_mapping = {
			"obj": f"nodes/obj/{item_name}.html",
			"sop": f"nodes/sop/{item_name}.html",
			"vex_function": f"vex/functions/{item_name}.html",
			"vex_expression": "vex/snippets.html",
			"python_hou": f"hom/hou/{item_name}.html",
		}
		if help_type not in url_mapping:
			return err(f"Unsupported help type: {help_type}")
		full_url = base_url + url_mapping[help_type]
		s = read_settings()
		resp = requests.get(full_url, timeout=s.request_timeout)
		if resp.status_code != 200:
			return err(f"Failed to fetch help page. Status code: {resp.status_code}")
		soup = BeautifulSoup(resp.text, 'html.parser')
		h1 = soup.find('h1', class_='title')
		if h1:
			title_text = (h1.contents[0].strip() if h1.contents else "").strip()
			subtitle = h1.find('span', class_='subtitle')
			subtitle_text = subtitle.get_text(strip=True) if subtitle else ""
			title = f"{title_text} - {subtitle_text}" if subtitle_text else title_text
		else:
			title = "No title found"
		des = soup.find('p', class_="summary")
		description = des.get_text(strip=True) if des else ''
		parameters: list[dict[str, Any]] = []
		for param_div in soup.find_all("div", class_="parameter"):
			name_tag = param_div.find("p", class_="label")
			desc_tag = param_div.find("div", class_="content")
			if not name_tag or not desc_tag:
				continue
			param_name = name_tag.get_text(strip=True)
			param_desc_p = desc_tag.find("p")
			param_desc = param_desc_p.get_text(strip=True) if param_desc_p else ""
			options: list[dict[str, str]] = []
			defs = desc_tag.find("div", class_="defs")
			if defs:
				for def_item in defs.find_all("div", class_="def"):
					label = def_item.find("p", class_="label")
					d2 = def_item.find("div", class_="content")
					if label and d2:
						options.append({
							"name": label.get_text(strip=True),
							"description": d2.get_text(strip=True),
						})
			parameters.append({"name": param_name, "description": param_desc, "options": options or None})

		def extract_section(section_id: str) -> list[dict[str, str]]:
			items: list[dict[str, str]] = []
			inouts = soup.find("div", id=f'{section_id}-body')
			if inouts:
				for def_item in inouts.find_all("div", class_="def"):
					label = def_item.find("p", class_="label")
					desc_div = def_item.find("div", class_="content")
					if label and desc_div:
						items.append({"name": label.get_text(strip=True), "description": desc_div.get_text(strip=True)})
			return items

		return ok("Help content retrieved successfully.", {
			"title": title,
			"url": full_url,
			"description": description,
			"parameters": parameters,
			"inputs": extract_section("inputs"),
			"outputs": extract_section("outputs"),
		})

	@mcp.tool  # type: ignore[attr-defined]
	@tool_wrapper
	def get_available_node_types(parent_path: str) -> dict:
		if hou is None:
			return err("Houdini environmentunavailable. ")
		parent = hou.node(parent_path)
		if not parent:
			return err(f"parentnode {parent_path} notfindto! ")
		node_type_category = parent.childTypeCategory()
		if not node_type_category:
			return err(f"node {parent_path} cannotpackagecontainingsubnode! ")
		node_types = node_type_category.nodeTypes()
		type_names = list(node_types.keys())
		categories: dict[str, list[dict[str, Any]]] = {}
		for type_name, node_type in node_types.items():
			try:
				category = node_type.category().name()
				categories.setdefault(category, []).append({
					"name": type_name,
					"label": node_type.description() if hasattr(node_type, 'description') else type_name,
				})
			except Exception:
				continue
		return ok(
			f"succeededgetnode {parent_path}  canusesubnodetype, shared {len(type_names)} kind. ",
			{
				"node_types": type_names,
				"categories": categories,
				"parent_category": node_type_category.name(),
				"total_count": len(type_names),
			},
		)

	@mcp.tool  # type: ignore[attr-defined]
	@tool_wrapper
	def set_node_parameter(node_path: str, param_name: str, value: Any) -> dict:
		if hou is None:
			return err("Houdini environmentunavailable. ")
		node = hou.node(node_path)
		if not node:
			return err(f"node {node_path} notfindto! ")
		parm = node.parm(param_name)
		if not parm:
			parm_tuple = node.parmTuple(param_name)
			if not parm_tuple:
				return err(f"node {node_path} innotfindtoparameter '{param_name}'! ")
			if isinstance(value, (list, tuple)):
				parm_tuple.set(value)
				actual_value = parm_tuple.eval()
			else:
				return err(f"parameter '{param_name}' istupleparameter, needsraiseforlistortuplevalue! ")
		else:
			if isinstance(value, (list, tuple)):
				return err(f"parameter '{param_name}' issingleparameter, cannotsetlistvalue! ")
			parm.set(value)
			actual_value = parm.eval()
		return ok(
			f"succeededsetnode {node_path}  parameter '{param_name}'. ",
			{"node_path": node_path, "parameter": param_name, "set_value": value, "actual_value": actual_value},
		)

	@mcp.tool  # type: ignore[attr-defined]
	@tool_wrapper
	def get_node_parameters(node_path: str, include_hidden: bool = False) -> dict:
		if hou is None:
			return err("Houdini environmentunavailable. ")
		node = hou.node(node_path)
		if not node:
			return err(f"node {node_path} notfindto! ")
		parameters: dict[str, Any] = {}
		parm_groups: dict[str, list[str]] = {}
		for parm in node.parms():
			try:
				if not include_hidden and parm.isHidden():
					continue
				parm_template = parm.parmTemplate()
				group_name = "General"
				try:
					if hasattr(parm_template, 'folderName'):
						folder_name = parm_template.folderName()
						if folder_name:
							group_name = folder_name
				except Exception:
					pass
				parm_groups.setdefault(group_name, [])
				try:
					current_value = parm.eval()
				except Exception:
					current_value = "nomethodget"
				default_value = None
				try:
					if hasattr(parm_template, 'defaultValue'):
						default_value = parm_template.defaultValue()
				except Exception:
					pass
				help_text = ""
				try:
					if hasattr(parm_template, 'help'):
						help_info = parm_template.help()
						if help_info:
							help_text = help_info
				except Exception:
					pass
				parameters[parm.name()] = {
					"name": parm.name(),
					"label": parm.description(),
					"type": parm_template.type().name() if hasattr(parm_template, 'type') else "unknown",
					"current_value": current_value,
					"default_value": default_value,
					"is_locked": parm.isLocked(),
					"has_keyframes": parm.isTimeDependent(),
					"help": help_text,
				}
				parm_groups[group_name].append(parm.name())
			except Exception:
				continue
		tuples: dict[str, Any] = {}
		for parm_tuple in node.parmTuples():
			try:
				if not include_hidden and parm_tuple.isHidden():
					continue
				try:
					current_value = parm_tuple.eval()
				except Exception:
					current_value = "nomethodget"
				tuples[parm_tuple.name()] = {
					"name": parm_tuple.name(),
					"label": parm_tuple.description(),
					"size": len(parm_tuple),
					"current_value": current_value,
					"components": [p.name() for p in parm_tuple],
				}
			except Exception:
				continue
		return ok(
			f"succeededgetnode {node_path}  parameterinfo. ",
			{
				"node_path": node_path,
				"node_type": node.type().name(),
				"node_label": node.type().description(),
				"parameters": parameters,
				"parameter_tuples": tuples,
				"parameter_groups": parm_groups,
				"total_params": len(parameters),
			},
		)

	@mcp.tool  # type: ignore[attr-defined]
	@tool_wrapper
	def create_node(parent_path: str, node_type: str, node_name: str = "") -> dict:
		"""createnode (delegate to hou_core sharedlayer) """
		success, msg, node = hou_core.create_node(parent_path, node_type, node_name)
		if not success:
			return err(msg)
		return ok("Node created successfully.", {"node_path": node.path() if node else ""})

	@mcp.tool  # type: ignore[attr-defined]
	@tool_wrapper
	def delete_node(node_path: str) -> dict:
		"""deletenode (delegate to hou_core sharedlayer) """
		success, msg = hou_core.delete_node(node_path)
		return ok(msg) if success else err(msg)

	@mcp.tool  # type: ignore[attr-defined]
	@tool_wrapper
	def execute_python_code(code: str) -> dict:
		import contextlib, io
		try:
			if hou is None:
				return err("Houdini environmentunavailable. ")
			exec_globals: dict[str, Any] = {"hou": hou}
			exec_locals: dict[str, Any] = {}
			stdout_buffer = io.StringIO()
			with contextlib.redirect_stdout(stdout_buffer):
				try:
					result = eval(code.strip(), exec_globals, exec_locals)
					return ok("tableexpressionexecutesucceeded", {"result": repr(result), "stdout": stdout_buffer.getvalue(), "type": "expression"})
				except SyntaxError:
					stdout_buffer.seek(0); stdout_buffer.truncate(0)
					exec(code.strip(), exec_globals, exec_locals)
					result_hint = "codeexecutecomplete"
					if exec_locals:
						local_vars = {k: v for k, v in exec_locals.items() if not k.startswith('__')}
						if local_vars:
							result_hint = f"local variables: {list(local_vars.keys())}"
					return ok(result_hint, {"result": "executesucceeded", "stdout": stdout_buffer.getvalue(), "type": "statement", "local_variables": list(exec_locals.keys()) if exec_locals else []})
		except Exception as e:
			return err(f"execution failed: {e}")

	@mcp.tool  # type: ignore[attr-defined]
	@tool_wrapper
	def connect_nodes(output_node_path: str, input_node_path: str, input_index: int = 0) -> dict:
		"""connectnode (delegate to hou_core sharedlayer) """
		success, msg = hou_core.connect_nodes(output_node_path, input_node_path, input_index)
		if not success:
			return err(msg)
		return ok(msg, {"output_node": output_node_path, "input_node": input_node_path, "input_index": input_index})

	@mcp.tool  # type: ignore[attr-defined]
	@tool_wrapper
	def get_node_info(node_path: str) -> dict:
		"""getnodeinfo (delegate to hou_core sharedlayer) """
		success, msg, info = hou_core.get_node_info(node_path)
		return ok(msg, info) if success else err(msg)

	@mcp.tool  # type: ignore[attr-defined]
	@tool_wrapper
	def create_node_network(network_config: dict) -> dict:
		if hou is None:
			return err("Houdini environmentunavailable. ")
		parent_path = network_config.get("parent_path")
		nodes_config = network_config.get("nodes", [])
		connections_config = network_config.get("connections", [])
		if not parent_path:
			return err("missing parent_path parameter! ")
		parent = hou.node(parent_path)
		if not parent:
			return err(f"parentnode {parent_path} notfindto! ")
		created_nodes: dict[str, dict[str, Any]] = {}
		created_connections: list[dict[str, Any]] = []
		errors: list[str] = []
		for node_config in nodes_config:
			try:
				node_type = node_config.get("type")
				node_name = node_config.get("name", "")
				# support "parameters" and "parms" twokindwritemethod
				parameters = node_config.get("parameters") or node_config.get("parms", {})
				if not node_type:
					errors.append(f"nodeconfigmissing type: {node_config}")
					continue
				_nm = (str(node_name).strip() if node_name else None)
				if _nm:
					import re as _re
					_nm2 = _re.sub(r"[^A-Za-z0-9_]+", "_", _nm).strip("_")
					_nm = _nm2 if _nm2 else None
				node = parent.createNode(node_type, _nm)
				actual_name = node.name()
				created_nodes[actual_name] = {"path": node.path(), "type": node_type, "requested_name": node_name}
				for param_name, value in parameters.items():
					try:
						parm = node.parm(param_name)
						if parm:
							parm.set(value)
						else:
							parm_tuple = node.parmTuple(param_name)
							if parm_tuple:
								parm_tuple.set(value)
					except Exception as param_error:
						errors.append(f"setnode {actual_name} parameter {param_name} failed: {str(param_error)}")
				try:
					_t = node.type().name().lower()
					if _t == "attribwrangle":
						_sn = node.parm("snippet")
						if _sn and not parameters.get("snippet"):
							if not (_sn.eval() or "").strip():
								_sn.set("@pscale = fit01(rand(@ptnum + ch('seed')), 0.1, 0.5);")
					elif _t == "scatter":
						_np = node.parm("npts")
						if _np and not parameters.get("npts"):
							_np.set(200)
				except Exception:
					pass
			except Exception as node_error:
				errors.append(f"createnodefailed: {str(node_error)}")
		for conn_config in connections_config:
			try:
				from_name = conn_config.get("from") or conn_config.get("src")
				to_name = conn_config.get("to") or conn_config.get("dst")
				input_index = int(conn_config.get("input_index", conn_config.get("input", 0)) or 0)
				from_node = None
				to_node = None
				for name, info in created_nodes.items():
					if name == from_name or info["requested_name"] == from_name:
						from_node = hou.node(info["path"])
					if name == to_name or info["requested_name"] == to_name:
						to_node = hou.node(info["path"])
				if not from_node:
					errors.append(f"notfindtosourcenode: {from_name}")
					continue
				if not to_node:
					errors.append(f"notfindtotargetnode: {to_name}")
					continue
				to_node.setInput(input_index, from_node)
				created_connections.append({"from": from_node.path(), "to": to_node.path(), "input_index": input_index})
			except Exception as conn_error:
				errors.append(f"Failed to establish connection: {str(conn_error)}")
		try:
			parent.layoutChildren()
		except Exception:
			pass
		# note: notagainautoguessconnectrelation. 
		# Rationale: auto-wiring (e.g., chaining nodes by creation order or guessing
		# copytopoints inputs) leads to unpredictable results. Connections must be
		# explicitly specified by the caller via the `connections` config.
		success_message = f"Successfully created {len(created_nodes)} node(s) and {len(created_connections)} connection(s)"
		if errors:
			success_message += f", buthas {len(errors)} error"
		try:
			if created_nodes:
				last_node = hou.node(list(created_nodes.values())[-1]["path"])
				if last_node:
					last_node.setDisplayFlag(True)
					last_node.setRenderFlag(True)
		except Exception:
			pass
		return {
			"status": ("success" if created_nodes else "error"),
			"message": success_message,
			"data": {
				"parent_path": parent_path,
				"created_nodes": created_nodes,
				"created_connections": created_connections,
				"errors": errors,
			},
		}

	@mcp.tool  # type: ignore[attr-defined]
	@tool_wrapper
	def auto_layout_nodes(parent_path: str, spacing: tuple = (2.0, 2.0)) -> dict:
		if hou is None:
			return err("Houdini environmentunavailable. ")
		parent = hou.node(parent_path)
		if not parent:
			return err(f"parent node {parent_path} not found!")
		parent.layoutChildren(horizontal_spacing=spacing[0], vertical_spacing=spacing[1])
		return ok(f"Auto-layout completed for {len(parent.children())} nodes.")

	@mcp.tool  # type: ignore[attr-defined]
	@tool_wrapper
	def list_children(parent_path: str) -> dict:
		if hou is None:
			return err("Houdini environmentunavailable. ")
		parent = hou.node(parent_path)
		if not parent:
			return err(f"parent node {parent_path} not found!")
		children = parent.children()
		child_info = [{"name": c.name(), "type": c.type().name()} for c in children]
		return ok("Children nodes retrieved successfully.", child_info)

	# ========================================
	# NetworkBox tool (delegate to hou_core sharedlayer) 
	# ========================================

	@mcp.tool  # type: ignore[attr-defined]
	@tool_wrapper
	def create_network_box(
		parent_path: str,
		name: str = "",
		comment: str = "",
		color_preset: str = "",
		node_paths: list | None = None,
	) -> dict:
		"""create NetworkBox andoptionalplacewillnodeaddenteritsin"""
		success, msg, box = hou_core.create_network_box(
			parent_path, name, comment, color_preset, node_paths or []
		)
		if success:
			return ok(msg, {"box_name": box.name() if box else name})
		return err(msg)

	@mcp.tool  # type: ignore[attr-defined]
	@tool_wrapper
	def add_nodes_to_box(
		parent_path: str,
		box_name: str,
		node_paths: list,
		auto_fit: bool = True,
	) -> dict:
		"""willnodeaddtoalreadyhas  NetworkBox"""
		success, msg = hou_core.add_nodes_to_box(parent_path, box_name, node_paths, auto_fit)
		return ok(msg) if success else err(msg)

	@mcp.tool  # type: ignore[attr-defined]
	@tool_wrapper
	def list_network_boxes(parent_path: str) -> dict:
		"""columnoutnetworkinall NetworkBox anditscontent"""
		success, msg, boxes_info = hou_core.list_network_boxes(parent_path)
		return ok(msg, boxes_info) if success else err(msg)

	@mcp.tool  # type: ignore[attr-defined]
	def get_task_queue_status() -> dict:
		return {"status": "success", "message": "Task queue status retrieved.", "data": {"tasks_in_queue": task_queue.qsize(), "recent_results": getattr(mcp, "recent_results", []) if mcp else []}}

	@mcp.tool(name="viewport_flipbook", description="render Houdini viewportandreturnimageresourcesourcelink")  # type: ignore[attr-defined]
	@tool_wrapper
	def viewport_flipbook(start_frame: int = 1, end_frame: int = 24) -> dict:
		global _registered_flipbook_resources
		if not read_settings().enable_flipbook:
			return err("viewport_flipbook is disabled in settings (enable_flipbook=false).")
		timeId = time.time_ns()
		if hou is None:
			return err("Houdini environmentunavailable. ")
		viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
		if viewer is None:
			return err("findnotto Scene Viewer, mustin GUI moderun. ")
		tmp_dir = tempfile.gettempdir()
		output_template = os.path.join(tmp_dir, f"flipbook_{timeId}.$F4.jpg")
		resolution = (100, 100)
		timeline = hou.playbar
		if not start_frame:
			start_frame = int(timeline.frameRange()[0])
		if not end_frame:
			end_frame = int(timeline.frameRange()[1])
		flip_settings = viewer.flipbookSettings().stash()
		flip_settings.output(output_template)
		flip_settings.frameRange((start_frame, end_frame))
		flip_settings.resolution(resolution)
		flip_settings.outputToMPlay(False)
		viewer.flipbook(viewer.curViewport(), flip_settings)
		glob_path = output_template.replace("$F4", "*").replace("$F", "*")
		image_files = sorted(glob.glob(glob_path))
		if not image_files:
			return err("nothasgenerateimage, pleasechecksceneset. ")
		frames = []
		for idx, filepath in enumerate(image_files, start=start_frame):
			url = register_image_resource(filepath)
			frames.append({"frame": idx, "path": url})
		with _resource_lock:
			_registered_flipbook_resources.clear()
		return ok(
			f"generate {len(frames)} frameimage. ",
			{"image_width": resolution[0], "image_height": resolution[1], "frames": frames},
		)

	@mcp.tool(name="health", description="MCP health check")  # type: ignore[attr-defined]
	def health() -> dict:
		now = time.time()
		uptime = (now - _server_start_time) if _server_start_time else None
		s = read_settings()
		return {
			"status": "success",
			"message": "OK",
			"data": {
				"hou_available": bool(hou is not None),
				"uptime_sec": uptime,
				"config": {
					"host": s.host,
					"port": s.port,
					"transport": s.transport,
					"flipbook_enabled": s.enable_flipbook,
				},
			},
		}


def _route_server_logs_to_debug_console():
	"""Send uvicorn / fastmcp / starlette logs to MorfyAI's Debug Console instead of
	letting them spam the native Houdini Console (the 'POST /mcp 200 OK' lines).

	Replaces those loggers' stream handlers with one that forwards to debug_log and
	stops propagation to the root logger. Safe to call repeatedly (uvicorn re-installs
	its own handlers at startup, so we re-assert for a few seconds after launch)."""
	import logging
	try:
		from morfyai.utils.debug_log import log as _dbg
	except Exception:
		_dbg = None

	class _DebugConsoleHandler(logging.Handler):
		def emit(self, record):
			try:
				if _dbg:
					_dbg(f"[MCP] {record.getMessage()}")
			except Exception:
				pass

	handler = _DebugConsoleHandler()
	handler.setLevel(logging.INFO)
	for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "uvicorn.asgi",
				 "fastmcp", "FastMCP", "mcp", "starlette"):
		try:
			lg = logging.getLogger(name)
			lg.handlers = [handler]
			lg.propagate = False
			lg.setLevel(logging.INFO)
		except Exception:
			pass


def _mcp_thread_runner():
	if not _fastmcp_available():
		return
	try:
		if os.name == 'nt' and hasattr(asyncio, 'WindowsProactorEventLoopPolicy'):
			asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
	except Exception:
		pass
	loop = asyncio.new_event_loop()
	asyncio.set_event_loop(loop)

	async def run_server_until_stopped():
		global mcp, _server_start_time
		if mcp is None:
			return
		s = read_settings()
		host = s.host or "127.0.0.1"
		port = s.port or 9000
		transport = s.transport or "streamable-http"
		try:
			# show_banner=False: FastMCP's ASCII banner is printed straight to
			# stdout via rich.Console (not through logging), so
			# _route_server_logs_to_debug_console() below never catches it —
			# it always leaked into the native Houdini Console regardless.
			server_task = asyncio.create_task(mcp.run_async(transport=transport, host=host, port=port, show_banner=False))
		except Exception as e:
			log.exception("Failed to start MCP server: %s", e)
			return
		_server_start_time = time.time()
		log.info("MCP server started at http://%s:%s/mcp/", host, port)
		# Keep uvicorn's access logs out of the Houdini Console — route to MorfyAI's
		# Debug Console. uvicorn installs its handlers as it boots, so re-assert for ~3s.
		_route_server_logs_to_debug_console()
		try:
			_n = 0
			while not stop_event.is_set():
				await asyncio.sleep(0.1)
				_n += 1
				if _n <= 30 and _n % 5 == 0:
					_route_server_logs_to_debug_console()
		finally:
			log.info("🛑 Shutdown requested. Cancelling server...")
			server_task.cancel()
			try:
				await server_task
			except asyncio.CancelledError:
				pass
			log.info("Server shutdown completed.")

	loop.run_until_complete(run_server_until_stopped())
	loop.close()


def ensure_mcp_running(auto_start: bool = True) -> tuple[bool, str]:
	global mcp, mcp_thread_handle
	try:
		from fastmcp import FastMCP  # type: ignore
	except Exception:
		return False, "fastmcp notinstall, skip MCP service start. "
	if hou is None:
		return False, "notdetectto Houdini environment (hou) , skip MCP service start. "
	s = read_settings()
	if not s.enabled:
		return False, "configdisable MCP (mcp_enabled=false) . "
	if mcp_thread_handle and mcp_thread_handle.is_alive():
		return True, "MCP service alreadyinrun. "
	mcp = FastMCP("Houdini MCP Server")  # type: ignore
	_setup_fastmcp_tools()
	if auto_start:
		mcp_thread_handle = threading.Thread(target=_mcp_thread_runner, daemon=True)
		mcp_thread_handle.start()
		try:
			def _process_tasks():
				while not task_queue.empty():
					try:
						fn = task_queue.get_nowait()
						fn()
					except Exception as e:
						try:
							hou.ui.displayMessage(f"Task error: {e}")
						except Exception:
							pass
			if hasattr(hou, 'ui') and hou.ui is not None:
				hou.ui.addEventLoopCallback(_process_tasks)
		except Exception:
			pass
	return True, "MCP service alreadystart. "


def stop_mcp_server(timeout: float = 3.0) -> tuple[bool, str]:
	global mcp_thread_handle, _server_start_time
	if not (mcp_thread_handle and mcp_thread_handle.is_alive()):
		return True, "MCP service notrun. "
	stop_event.set()
	mcp_thread_handle.join(timeout=timeout)
	if mcp_thread_handle.is_alive():
		return False, "MCP service notintimeoutwhenbetweenwithinstop. "
	_server_start_time = None
	return True, "MCP service stopped. "


def get_mcp_status() -> dict:
	s = read_settings()
	running = bool(mcp_thread_handle and mcp_thread_handle.is_alive())
	uptime = (time.time() - _server_start_time) if (_server_start_time) else None
	secs = (time.time() - _last_client_activity) if _last_client_activity else None
	return {
		"running": running,
		"host": s.host,
		"port": s.port,
		"transport": s.transport,
		"uptime_sec": uptime,
		"last_client_activity_sec": round(secs, 1) if secs is not None else None,
		"client_connected": bool(secs is not None and secs < 60),
	}


# ⚠️ Module-level auto-start has been removed.
# Rationale: imports should not produce side effects (starting threads, registering callbacks, etc.).
# Use ensure_mcp_running() to start it explicitly from the call site. 
# example: 
#   from utils.mcp.server import ensure_mcp_running
#   ensure_mcp_running(auto_start=True)
