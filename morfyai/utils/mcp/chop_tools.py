# -*- coding: utf-8 -*-
"""MCP tools for CHOP export flags, channel data, references, and diagnostics."""
from __future__ import annotations

import functools
import re
import threading
from typing import Any

try:
    import hou  # type: ignore
except Exception:
    hou = None  # type: ignore


def _node(path: str):
    if hou is None:
        raise RuntimeError("Houdini environment is unavailable")
    node = hou.node(path)
    if node is None:
        raise ValueError(f"Node not found: {path}")
    return node


def _chop(path: str):
    node = _node(path)
    if not callable(getattr(node, "tracks", None)) or not callable(getattr(node, "sampleRate", None)):
        raise ValueError(f"Node is not a CHOP output: {path}")
    return node


def _track(node, channel_name: str):
    track = node.track(channel_name)
    if track is None:
        names = [item.name() for item in node.tracks()]
        raise ValueError(f"Channel not found: {channel_name}. Available channels: {names}")
    return track


def _export_prefix(node) -> str:
    parm = node.parm("exportprefix")
    if parm is None:
        return ""
    try:
        return parm.evalAsString().strip()
    except Exception:
        return str(parm.eval()).strip()


def _destination_candidate(prefix: str, channel_name: str) -> str:
    if channel_name.startswith("/"):
        return channel_name
    suffix = channel_name.replace(":", "/").lstrip("/")
    if prefix:
        return prefix.rstrip("/") + "/" + suffix
    return "/" + suffix


def _export_channel_info(node, track) -> dict:
    enabled = bool(node.isExportFlagSet())
    try:
        active = bool(track.isOverrideActive())
    except Exception:
        active = False
    try:
        target = track.overrideParm()
    except Exception:
        target = None
    prefix = _export_prefix(node)
    candidate = _destination_candidate(prefix, track.name())
    resolved = target.path() if target is not None else None
    candidate_parm = None
    if resolved is None:
        try:
            candidate_parm = hou.parm(candidate)
        except Exception:
            candidate_parm = None
        if candidate_parm is not None:
            resolved = candidate_parm.path()
    if not enabled:
        status = "disabled"
    elif active and resolved:
        status = "active"
    elif resolved:
        status = "destination_found_but_not_overriding"
    else:
        status = "enabled_but_destination_unresolved"
    return {
        "channel": track.name(),
        "node_export_flag": enabled,
        "override_active": active,
        "destination_parameter": resolved,
        "destination_candidate": candidate,
        "destination_resolved": bool(resolved),
        "status": status,
    }


def _chop_channel_path(node, channel_name: str) -> str:
    return node.path().rstrip("/") + "/" + channel_name.lstrip("/")


def register_tools(mcp, ok, err, wrapper, task_queue=None, ui_thread_id=None):
    """Register CHOP tools. HOM calls are marshalled to Houdini's UI thread."""

    def add(fn):
        guarded = wrapper(fn)

        @functools.wraps(fn)
        def on_houdini_thread(*args, **kwargs):
            target_thread = ui_thread_id() if callable(ui_thread_id) else None
            if task_queue is None or target_thread is None or threading.get_ident() == target_thread:
                return guarded(*args, **kwargs)
            event = threading.Event()
            result = []

            def run():
                try:
                    result.append(guarded(*args, **kwargs))
                finally:
                    event.set()

            task_queue.put(run)
            if not event.wait(180):
                return err(
                    "Timed out waiting for Houdini's UI thread. Ensure the MorfyAI panel is open.",
                    code="ui_thread_timeout",
                )
            return result[0] if result else err("Houdini UI task returned no result")

        on_houdini_thread.__name__ = fn.__name__
        on_houdini_thread.__doc__ = fn.__doc__
        mcp.tool(on_houdini_thread)
        return fn

    def get_chop_export_flag(chop_path: str) -> dict:
        """Read whether a CHOP node's export flag is enabled."""
        try:
            node = _chop(chop_path)
            return ok(
                "CHOP export flag retrieved",
                {"chop_path": node.path(), "export_enabled": bool(node.isExportFlagSet())},
            )
        except Exception as exc:
            return err(str(exc))
    add(get_chop_export_flag)

    def set_chop_export_flag(chop_path: str, enabled: bool) -> dict:
        """Enable or disable a CHOP node's export flag."""
        try:
            node = _chop(chop_path)
            previous = bool(node.isExportFlagSet())
            if previous != bool(enabled):
                with hou.undos.group("Set CHOP export flag"):
                    node.setExportFlag(bool(enabled))
            current = bool(node.isExportFlagSet())
            return ok(
                "CHOP export flag updated",
                {"chop_path": node.path(), "previous": previous, "export_enabled": current},
            )
        except Exception as exc:
            return err(str(exc))
    add(set_chop_export_flag)

    def evaluate_chop_channel(
        chop_path: str,
        channel_name: str,
        frame: float | None = None,
        time: float | None = None,
    ) -> dict:
        """Evaluate a CHOP channel at a frame or time; defaults to Houdini's current frame."""
        try:
            if frame is not None and time is not None:
                raise ValueError("Pass either frame or time, not both.")
            node = _chop(chop_path)
            track = _track(node, channel_name)
            if time is not None:
                sample_time = float(time)
                sample_frame = float(hou.timeToFrame(sample_time))
                value = float(track.evalAtTime(sample_time))
                mode = "time"
            else:
                sample_frame = float(hou.frame() if frame is None else frame)
                sample_time = float(hou.frameToTime(sample_frame))
                value = float(track.evalAtFrame(sample_frame))
                mode = "frame"
            return ok(
                "CHOP channel evaluated",
                {
                    "chop_path": node.path(),
                    "channel": track.name(),
                    "sampled_by": mode,
                    "frame": sample_frame,
                    "time": sample_time,
                    "value": value,
                },
            )
        except Exception as exc:
            return err(str(exc))
    add(evaluate_chop_channel)

    def list_chop_channels(chop_path: str) -> dict:
        """List output channels with sample count, time/frame range, and sample rate."""
        try:
            node = _chop(chop_path)
            sample_rate = float(node.sampleRate())
            start_sample, end_sample = node.sampleRange()
            start_time = float(node.samplesToTime(start_sample))
            end_time = float(node.samplesToTime(end_sample))
            channels = []
            for track in node.tracks():
                channels.append(
                    {
                        "name": track.name(),
                        "sample_count": int(track.numSamples()),
                        "sample_rate": sample_rate,
                        "sample_range": [start_sample, end_sample],
                        "time_range": [start_time, end_time],
                        "frame_range": [
                            float(hou.timeToFrame(start_time)),
                            float(hou.timeToFrame(end_time)),
                        ],
                    }
                )
            return ok(
                "CHOP channels listed",
                {
                    "chop_path": node.path(),
                    "sample_rate": sample_rate,
                    "sample_range": [start_sample, end_sample],
                    "time_range": [start_time, end_time],
                    "frame_range": [
                        float(hou.timeToFrame(start_time)),
                        float(hou.timeToFrame(end_time)),
                    ],
                    "channel_count": len(channels),
                    "channels": channels,
                },
            )
        except Exception as exc:
            return err(str(exc))
    add(list_chop_channels)

    def inspect_chop_exports(chop_path: str) -> dict:
        """Inspect a CHOP node's export flag, channel destinations, and active status."""
        try:
            node = _chop(chop_path)
            channels = [_export_channel_info(node, track) for track in node.tracks()]
            return ok(
                "CHOP exports inspected",
                {
                    "chop_path": node.path(),
                    "export_enabled": bool(node.isExportFlagSet()),
                    "export_prefix": _export_prefix(node),
                    "channel_count": len(channels),
                    "active_count": sum(1 for item in channels if item["status"] == "active"),
                    "channels": channels,
                },
            )
        except Exception as exc:
            return err(str(exc))
    add(inspect_chop_exports)

    def create_chop_channel_reference(
        target_parameter_path: str,
        chop_path: str,
        channel_name: str,
        replace_existing: bool = False,
    ) -> dict:
        """Create a parameter expression that references a CHOP output channel."""
        try:
            node = _chop(chop_path)
            track = _track(node, channel_name)
            target = hou.parm(target_parameter_path)
            if target is None:
                raise ValueError(f"Parameter not found: {target_parameter_path}")
            channel_path = _chop_channel_path(node, track.name())
            escaped_path = channel_path.replace("\\", "\\\\").replace('"', '\\"')
            expression = f'chop("{escaped_path}")'
            try:
                previous_expression = target.expression()
                previous_language = target.expressionLanguage()
            except Exception:
                previous_expression = None
                previous_language = None
            previous_keyframes = list(target.keyframes())
            previous_value = target.eval()
            if previous_expression == expression:
                return ok(
                    "CHOP channel reference already exists",
                    {
                        "parameter": target.path(),
                        "chop_channel": channel_path,
                        "expression": expression,
                        "value": target.eval(),
                        "changed": False,
                    },
                )
            if not replace_existing and (target.isTimeDependent() or target.keyframes()):
                raise ValueError(
                    f"Parameter already has animation or an expression: {target.path()}. "
                    "Set replace_existing=true to replace it."
                )
            try:
                with hou.undos.group("Create CHOP channel reference"):
                    target.setExpression(expression, language=hou.exprLanguage.Hscript)
                value = target.eval()
            except Exception:
                target.deleteAllKeyframes()
                if previous_expression:
                    target.setExpression(previous_expression, language=previous_language)
                elif previous_keyframes:
                    target.setKeyframes(previous_keyframes)
                else:
                    target.set(previous_value)
                raise
            return ok(
                "CHOP channel reference created",
                {
                    "parameter": target.path(),
                    "chop_channel": channel_path,
                    "expression": expression,
                    "value": value,
                    "changed": True,
                },
            )
        except Exception as exc:
            return err(str(exc))
    add(create_chop_channel_reference)

    def inspect_chop_channel_reference(target_parameter_path: str) -> dict:
        """Inspect a parameter expression and resolve any referenced CHOP channel."""
        try:
            target = hou.parm(target_parameter_path)
            if target is None:
                raise ValueError(f"Parameter not found: {target_parameter_path}")
            try:
                expression = target.expression()
                language = target.expressionLanguage().name()
            except Exception:
                expression = ""
                language = None
            match = re.search(r"""chop\s*\(\s*["']([^"']+)["']\s*\)""", expression)
            channel_path = match.group(1) if match else None
            source_node = None
            channel_name = None
            resolved = False
            if channel_path:
                split_at = channel_path.rfind("/")
                source_path = channel_path[:split_at] or "/"
                channel_name = channel_path[split_at + 1 :]
                source_node = hou.node(source_path)
                if source_node is not None and callable(getattr(source_node, "track", None)):
                    resolved = source_node.track(channel_name) is not None
            try:
                value = target.eval()
            except Exception as exc:
                value = None
                evaluation_error = str(exc)
            else:
                evaluation_error = None
            return ok(
                "CHOP channel reference inspected",
                {
                    "parameter": target.path(),
                    "expression": expression or None,
                    "expression_language": language,
                    "is_chop_reference": channel_path is not None,
                    "chop_channel": channel_path,
                    "source_node": source_node.path() if source_node is not None else None,
                    "channel": channel_name,
                    "source_resolved": resolved,
                    "value": value,
                    "evaluation_error": evaluation_error,
                },
            )
        except Exception as exc:
            return err(str(exc))
    add(inspect_chop_channel_reference)

    def capture_chop_view(
        chop_path: str,
        view_type: str = "motion_fx",
        width: int = 1280,
        height: int = 720,
    ) -> dict:
        """Capture a CHOP in the Motion FX View or the current Channel Editor."""
        previous_node = None
        pane = None
        changed_node = False
        try:
            node = _chop(chop_path)
            view_name = view_type.strip().lower()
            view_types = {
                "motion_fx": hou.paneTabType.ChannelViewer,
                "channel_editor": hou.paneTabType.ChannelEditor,
            }
            if view_name not in view_types:
                raise ValueError("view_type must be motion_fx or channel_editor")
            desktop = hou.ui.curDesktop()
            panes = [p for p in desktop.paneTabs() if p.type() == view_types[view_name]]
            if not panes:
                label = "Motion FX View" if view_name == "motion_fx" else "Channel Editor"
                raise RuntimeError(f"{label} is not open in the current Houdini desktop")
            pane = panes[0]
            if view_name == "motion_fx":
                previous_node = pane.currentNode()
                pane.setCurrentNode(node)
                changed_node = True
            if hasattr(hou.ui, "triggerUpdate"):
                hou.ui.triggerUpdate()
            from .advanced_tools import _capture
            image = _capture(pane, width, height, "chop_view")
            image.update(
                {
                    "chop_path": node.path(),
                    "view_type": view_name,
                    "pane": pane.name(),
                    "scope": "Houdini window capture with the requested CHOP view visible",
                }
            )
            return ok("CHOP view captured", image)
        except Exception as exc:
            return err(str(exc))
        finally:
            if changed_node and pane is not None:
                try:
                    pane.setCurrentNode(previous_node)
                    if hasattr(hou.ui, "triggerUpdate"):
                        hou.ui.triggerUpdate()
                except Exception:
                    pass
    add(capture_chop_view)

    def inspect_chop_network_diagnostics(chop_network_path: str, cook_nodes: bool = False) -> dict:
        """Inspect errors and warnings on every node under a CHOP network."""
        try:
            root = _node(chop_network_path)
            category = root.type().category()
            child_category = root.childTypeCategory()
            category_name = category.name().lower() if category is not None else ""
            child_name = child_category.name().lower() if child_category is not None else ""
            if category_name not in ("chop", "chopnet") and child_name not in ("chop", "chopnet"):
                raise ValueError(f"Node is not a CHOP node or CHOP network: {chop_network_path}")
            nodes = []
            stack = [root]
            seen = set()
            while stack:
                current = stack.pop()
                path = current.path()
                if path in seen:
                    continue
                seen.add(path)
                nodes.append(current)
                try:
                    children = list(current.children())
                except Exception:
                    children = []
                stack.extend(reversed(children))
            nodes.sort(key=lambda item: item.path())
            cook_errors = []
            if cook_nodes:
                for current in nodes:
                    try:
                        current.cook(force=True)
                    except Exception as exc:
                        cook_errors.append({"node": current.path(), "message": str(exc)})
            results = []
            for current in nodes:
                try:
                    errors = [str(message) for message in (current.errors() or [])]
                except Exception as exc:
                    errors = [str(exc)]
                try:
                    warnings = [str(message) for message in (current.warnings() or [])]
                except Exception as exc:
                    warnings = [str(exc)]
                if errors or warnings:
                    results.append(
                        {
                            "node": current.path(),
                            "type": current.type().name(),
                            "errors": errors,
                            "warnings": warnings,
                        }
                    )
            return ok(
                "CHOP network diagnostics collected",
                {
                    "network_path": root.path(),
                    "nodes_checked": len(nodes),
                    "cook_requested": bool(cook_nodes),
                    "nodes_with_messages": results,
                    "cook_errors": cook_errors,
                    "error_count": sum(len(row["errors"]) for row in results) + len(cook_errors),
                    "warning_count": sum(len(row["warnings"]) for row in results),
                },
            )
        except Exception as exc:
            return err(str(exc))
    add(inspect_chop_network_diagnostics)
