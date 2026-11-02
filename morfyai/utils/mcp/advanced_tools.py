# -*- coding: utf-8 -*-
"""Extended Houdini rig, animation, geometry and viewport MCP tools.

All functions are registered on the in-Houdini FastMCP server. Operations that
change the current frame restore it when they are only inspecting data.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import functools
import uuid
from typing import Any

try:
    import hou  # type: ignore
except Exception:
    hou = None  # type: ignore

_REGISTERED_VIEWER_STATES: set[str] = set()
_ACTIVE_UNDO_GROUPS: list[tuple[str, Any]] = []


def _node(path: str):
    if hou is None:
        raise RuntimeError("Houdini environment is unavailable")
    n = hou.node(path)
    if n is None:
        raise ValueError(f"Node not found: {path}")
    return n


def _parm(path: str, name: str):
    n = _node(path)
    p = n.parm(name) or n.parmTuple(name)
    if p is None:
        raise ValueError(f"Parameter not found: {path}/{name}")
    return n, p


def _set_value(p, value):
    p.set(tuple(value) if isinstance(value, list) else value)


def _as_scalar_parm(p):
    return p[0] if not hasattr(p, "expression") and hasattr(p, "__getitem__") else p


def _set_menu_value(parm, value):
    template = parm.parmTemplate()
    items = list(_safe_value(template.menuItems, ()) or ())
    labels = list(_safe_value(template.menuLabels, ()) or ())
    for index, item in enumerate(items):
        if str(value) == str(item) or (index < len(labels) and str(value).lower() == str(labels[index]).lower()):
            parm.set(index)
            return
    parm.set(value)


def _controller_shape(value):
    return {"circle": "circles", "square": "box", "cube": "box"}.get(str(value).lower(), value)


def _rebase_bound_channels(node, previous_values):
    updated = []
    for key, raw in node.userDataDict().items():
        if not key.startswith("morfyai_handle_binding:"):
            continue
        try:
            meta = json.loads(raw); source = hou.parm(meta["source"]); target = hou.parm(key.split(":", 1)[1])
            if source is None or target is None or target.path() not in previous_values:
                continue
            base = float(source.eval()) - float(previous_values[target.path()])
            target.setExpression(f'ch("{source.path()}") - {base:.17g}', language=hou.exprLanguage.Hscript)
            meta["base_value"] = base; node.setUserData(key, json.dumps(meta)); updated.append(target.path())
        except Exception:
            continue
    return updated


def _safe_value(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _matrix_values(value):
    if value is None:
        return None
    if hasattr(value, "asTuple"):
        return list(value.asTuple())
    return list(value) if isinstance(value, (tuple, list)) else str(value)


def _geometry(path: str, frame: int | None = None):
    n = _node(path)
    old = hou.frame()
    if frame is not None:
        hou.setFrame(int(frame))
    try:
        return n.geometry(), old
    except Exception:
        if frame is not None:
            hou.setFrame(old)
        raise


def _capture(pane, width: int, height: int, prefix: str):
    if pane is None:
        raise RuntimeError("Requested Houdini pane is not open")
    path = os.path.join(tempfile.gettempdir(), f"morfyai_{prefix}_{os.getpid()}_{uuid.uuid4().hex[:8]}.png")
    # Capture Houdini through Qt; HOM does not expose a portable viewport image
    # method across the supported Houdini versions.
    pixmap = hou.qt.mainWindow().grab()
    if int(width) > 0 and int(height) > 0:
        try:
            from PySide6 import QtCore
        except ImportError:
            from PySide2 import QtCore
        aspect = QtCore.Qt.KeepAspectRatio if hasattr(QtCore.Qt, "KeepAspectRatio") else QtCore.Qt.AspectRatioMode.KeepAspectRatio
        smooth = QtCore.Qt.SmoothTransformation if hasattr(QtCore.Qt, "SmoothTransformation") else QtCore.Qt.TransformationMode.SmoothTransformation
        ignore_aspect = QtCore.Qt.IgnoreAspectRatio if hasattr(QtCore.Qt, "IgnoreAspectRatio") else QtCore.Qt.AspectRatioMode.IgnoreAspectRatio
        pixmap = pixmap.scaled(int(width), int(height), ignore_aspect, smooth)
    if not pixmap.save(path):
        raise RuntimeError("Qt could not save the Houdini window capture")
    if not os.path.isfile(path):
        raise RuntimeError("Houdini did not produce the requested image")
    return {"path": path, "width": pixmap.width(), "height": pixmap.height()}


def register_tools(mcp, ok, err, wrapper, task_queue=None, ui_thread_id=None):
    """Register the expanded MCP surface. Tool names match the user proposal."""

    def add(fn, name=None, description=None):
        fn.__name__ = name or fn.__name__
        fn.__doc__ = description or fn.__doc__ or fn.__name__
        guarded = wrapper(fn)
        @functools.wraps(fn)
        def on_houdini_thread(*args, **kwargs):
            target_thread = ui_thread_id() if callable(ui_thread_id) else None
            if task_queue is None or target_thread is None or threading.get_ident() == target_thread:
                return guarded(*args, **kwargs)
            event = threading.Event(); result = []
            def run():
                try: result.append(guarded(*args, **kwargs))
                finally: event.set()
            task_queue.put(run)
            if not event.wait(180):
                return err("Timed out waiting for Houdini's UI thread. Ensure the MorfyAI panel is open.", code="ui_thread_timeout")
            return result[0] if result else err("Houdini UI task returned no result")
        on_houdini_thread.__name__ = fn.__name__
        on_houdini_thread.__doc__ = fn.__doc__
        mcp.tool(on_houdini_thread)
        return fn

    # 1. Controller and rig interface
    def create_rig_controller(parent_path: str, name: str, shape: str = "circle", color: list | None = None,
                              size: float = 1.0, position: list | None = None, orientation: list | None = None) -> dict:
        """Create a visible, selectable Null controller object in an OBJ network."""
        try:
            parent = _node(parent_path)
            ctrl = parent.createNode("null", name or "CTRL")
            if ctrl.parm("controltype") is not None:
                _set_menu_value(ctrl.parm("controltype"), _controller_shape(shape))
            if ctrl.parm("geoscale") is not None:
                ctrl.parm("geoscale").set(float(size))
            if position is not None and ctrl.parmTuple("t"):
                ctrl.parmTuple("t").set(tuple(position))
            if orientation is not None and ctrl.parmTuple("r"):
                ctrl.parmTuple("r").set(tuple(orientation))
            if color is not None:
                ctrl.setColor(hou.Color(tuple(color[:3])))
            ctrl.setUserData("morfyai_controller", "1")
            return ok("Controller created", {"path": ctrl.path(), "shape": shape, "color": color, "size": size})
        except Exception as e:
            return err(str(e))
    add(create_rig_controller)

    def configure_controller(controller_path: str, shape: str | None = None, color: list | None = None,
                             orientation: list | None = None, display_scale: float | None = None) -> dict:
        """Change controller display shape, color, orientation or display scale."""
        try:
            n = _node(controller_path)
            if shape is not None and n.parm("controltype"):
                _set_menu_value(n.parm("controltype"), _controller_shape(shape))
            if color is not None:
                n.setColor(hou.Color(tuple(color[:3])))
            rebased = []
            if orientation is not None:
                previous = {}
                for key, raw in n.userDataDict().items():
                    if key.startswith("morfyai_handle_binding:"):
                        try:
                            meta = json.loads(raw)
                            if meta.get("source", "").endswith(("/rx", "/ry", "/rz")):
                                target_path = key.split(":", 1)[1]; target = hou.parm(target_path)
                                if target is not None: previous[target_path] = float(target.eval())
                        except Exception: pass
                n.parmTuple("r").set(tuple(orientation))
                rebased = _rebase_bound_channels(n, previous)
            if display_scale is not None and n.parm("geoscale"):
                n.parm("geoscale").set(float(display_scale))
            return ok("Controller display updated", {"path": n.path(), "rig_values_preserved": rebased})
        except Exception as e: return err(str(e))
    add(configure_controller)

    def set_controller_channels(controller_path: str, channels: dict) -> dict:
        """Set parameter channel keyability, lock state and visibility."""
        try:
            n = _node(controller_path); result = {}
            for name, spec in channels.items():
                p = n.parm(name)
                if p is None: result[name] = "missing"; continue
                if "locked" in spec and hasattr(p, "lock"): p.lock(bool(spec["locked"]))
                if "active" in spec:
                    if hasattr(p, "setSelect"): p.setSelect(bool(spec["active"]))
                    if hasattr(p, "setAutoSelect"): p.setAutoSelect(bool(spec["active"]))
                if "hidden" in spec:
                    group = n.parmTemplateGroup(); template = group.find(name)
                    if template is not None and hasattr(template, "hide"):
                        template = template.clone(); template.hide(bool(spec["hidden"]))
                        group.replace(name, template); n.setParmTemplateGroup(group)
                result[name] = {"locked": _safe_value(p.isLocked, False), "active": _safe_value(p.isSelected, None),
                                "hidden": _safe_value(p.isHidden, None), "scoped": _safe_value(p.isScoped, None)}
            return ok("Controller channel settings applied", result)
        except Exception as e: return err(str(e))
    add(set_controller_channels)

    def create_parameter(node_path: str, name: str, label: str = "", parm_type: str = "float",
                         default: Any = 0.0, minimum: float | None = None, maximum: float | None = None,
                         menu: list | None = None) -> dict:
        """Add a spare scalar, toggle, string or menu parameter to a node."""
        try:
            n = _node(node_path)
            types = {"float": hou.FloatParmTemplate, "int": hou.IntParmTemplate, "toggle": hou.ToggleParmTemplate,
                     "string": hou.StringParmTemplate, "menu": hou.MenuParmTemplate}
            cls = types.get(parm_type.lower())
            if cls is None: return err(f"Unsupported parameter type: {parm_type}")
            label = label or name
            if parm_type.lower() == "menu":
                items = menu or []
                if not items: return err("menu must contain at least one item")
                menu_items = [str(x.get("value", x)) if isinstance(x, dict) else str(x) for x in items]
                menu_labels = [str(x.get("label", x.get("value", x))) if isinstance(x, dict) else str(x) for x in items]
                if isinstance(default, str):
                    if default in menu_items: default_index = menu_items.index(default)
                    elif default in menu_labels: default_index = menu_labels.index(default)
                    else: raise ValueError(f"Menu default must match one of the menu values or labels: {default}")
                else:
                    default_index = int(default)
                    if float(default) != default_index: raise ValueError("Menu default index must be an integer")
                if default_index < 0 or default_index >= len(menu_items):
                    raise ValueError(f"Menu default index must be between 0 and {len(menu_items) - 1}")
                template = cls(name, label, menu_items, menu_labels, default_value=default_index)
            elif parm_type.lower() == "string": template = cls(name, label, 1, default_value=(str(default),))
            elif parm_type.lower() == "toggle": template = cls(name, label, bool(default))
            else:
                value = int(default) if parm_type.lower() == "int" else float(default)
                if minimum is not None and maximum is not None and minimum > maximum:
                    raise ValueError("minimum cannot be greater than maximum")
                template = cls(name, label, 1, default_value=(value,))
                if minimum is not None: template.setMinValue(minimum)
                if maximum is not None: template.setMaxValue(maximum)
            n.addSpareParmTuple(template)
            return ok("Parameter created", {"node_path": n.path(), "name": name, "type": parm_type})
        except Exception as e: return err(str(e))
    add(create_parameter)

    def promote_parameter(source_node_path: str, source_parameter: str, destination_node_path: str,
                          promoted_name: str = "", label: str = "") -> dict:
        """Copy a parameter template to a destination node and link the source to it."""
        try:
            src, p = _parm(source_node_path, source_parameter); dst = _node(destination_node_path)
            template = p.parmTemplate() if hasattr(p, "parmTemplate") else p[0].parmTemplate()
            new_name = promoted_name or template.name()
            template = template.clone(); template.setName(new_name)
            if label: template.setLabel(label)
            dst.addSpareParmTuple(template)
            promoted = dst.parm(new_name) or dst.parmTuple(new_name)
            if promoted is None: raise RuntimeError("Promoted parameter was not created")
            source_items = [p] if hasattr(p, "expression") else list(p)
            target_items = [promoted] if hasattr(promoted, "expression") else list(promoted)
            if len(source_items) != len(target_items): raise ValueError("Promoted parameter component count differs from source")
            links = []
            for source_item, target_item in zip(source_items, target_items):
                source_item.setExpression(f'ch("{target_item.path()}")', language=hou.exprLanguage.Hscript)
                links.append({"source": source_item.path(), "promoted": target_item.path()})
            return ok("Parameter promoted and linked", {"links": links})
        except Exception as e: return err(str(e))
    add(promote_parameter)

    def organize_parameters(node_path: str, folder: str, order: list, labels: dict | None = None,
                            help_text: dict | None = None) -> dict:
        """Organize existing spare parameters into a folder in the requested order."""
        try:
            n = _node(node_path); group = n.parmTemplateGroup(); templates = []
            for name in order:
                t = group.find(name)
                if t is None: return err(f"Parameter template not found: {name}")
                t = t.clone()
                if labels and name in labels: t.setLabel(labels[name])
                if help_text and name in help_text: t.setHelp(help_text[name])
                templates.append(t); group.remove(name)
            folder_t = hou.FolderParmTemplate("morfyai_" + "_".join(folder.split()).lower(), folder)
            for t in templates: folder_t.addParmTemplate(t)
            group.append(folder_t); n.setParmTemplateGroup(group)
            return ok("Parameters organized", {"node_path": n.path(), "folder": folder, "parameters": order})
        except Exception as e: return err(str(e))
    add(organize_parameters)

    def bind_controller_handle(controller_path: str, parameter_path: str, handle_type: str = "transform",
                               axis: str = "x", controller_parameter: str = "") -> dict:
        """Bind a rig channel to a visible controller transform and activate its Houdini xform handle."""
        try:
            c = _node(controller_path); target_node, target = _parm(*parameter_path.rsplit("/", 1)); target = _as_scalar_parm(target)
            if not controller_parameter:
                candidates = {"x": "tx", "y": "ty", "z": "tz", "rx": "rx", "ry": "ry", "rz": "rz"}
                controller_parameter = candidates.get(axis.lower(), axis.lower())
            source = c.parm(controller_parameter)
            if source is None: raise ValueError(f"Controller channel not found: {controller_parameter}")
            if handle_type.lower() not in {"transform", "translate", "rotate", "scale", "parameter"}:
                raise ValueError("Supported handle types: transform, translate, rotate, scale, parameter")
            base_value = float(source.eval())
            target.setExpression(f'ch("{source.path()}") - {base_value:.17g}', language=hou.exprLanguage.Hscript)
            c.setUserData("morfyai_handle_binding:" + target.path(), json.dumps({"source": source.path(), "type": handle_type, "axis": axis, "base_value": base_value}))
            state_id = "morfyai_ctrl_" + "_".join(c.path().strip("/").split("/"))
            class ControllerState:
                def __init__(self, state_name, scene_viewer):
                    self.state_name = state_name
                    self.scene_viewer = scene_viewer
            if state_id not in _REGISTERED_VIEWER_STATES:
                template = hou.ViewerStateTemplate(state_id, "MorfyAI Controller", hou.objNodeTypeCategory())
                template.bindFactory(ControllerState)
                template.bindHandleStatic("xform", "controller_xform", [
                    ("tx", "tx"), ("ty", "ty"), ("tz", "tz"),
                    ("rx", "rx"), ("ry", "ry"), ("rz", "rz"),
                    ("sx", "sx"), ("sy", "sy"), ("sz", "sz"),
                ])
                hou.ui.registerViewerState(template)
                _REGISTERED_VIEWER_STATES.add(state_id)
            viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
            c.setSelected(True, clear_all_selected=True)
            if viewer is not None: viewer.setCurrentState(state_id)
            return ok("Controller channel bound to target parameter", {"controller": c.path(), "source": source.path(),
                "target": target.path(), "handle_type": handle_type, "axis": axis,
                "viewer_state": state_id, "interactive_viewer_handle": True})
        except Exception as e: return err(str(e))
    add(bind_controller_handle)

    def inspect_controller(controller_path: str) -> dict:
        """Inspect controller display channels, spare parameters and registered bindings."""
        try:
            n = _node(controller_path); parms = {}
            for p in n.parms():
                parms[p.name()] = {"value": _safe_value(p.eval), "locked": _safe_value(p.isLocked, False),
                                   "hidden": _safe_value(p.isHidden, False), "active": _safe_value(p.isSelected, None),
                                   "scoped": _safe_value(p.isScoped, None)}
            bindings = {}
            for key, value in n.userDataDict().items():
                if key.startswith("morfyai_handle_binding:"):
                    bindings[key.split(":", 1)[1]] = json.loads(value)
            return ok("Controller inspected", {"path": n.path(), "type": n.type().name(), "color": list(n.color().rgb()),
                "controller": n.userData("morfyai_controller") == "1", "channels": parms, "bindings": bindings})
        except Exception as e: return err(str(e))
    add(inspect_controller)

    # 2. Node and parameter inspection
    def get_parameter_schema(node_path: str = "", node_type: str = "") -> dict:
        """Return Houdini parameter templates, defaults, ranges, menus and tuple components."""
        try:
            if node_path: n = _node(node_path); templates = n.parmTemplateGroup().entries(); path = n.path()
            else:
                if hou is None: raise RuntimeError("Houdini environment unavailable")
                t = None
                for category in hou.nodeTypeCategories().values():
                    try:
                        t = hou.nodeType(category, node_type)
                    except Exception:
                        t = None
                    if t is not None: break
                if t is None: raise ValueError(f"Node type not found: {node_type}")
                templates = t.parmTemplateGroup().entries(); path = node_type
            def walk(items):
                out = []
                for t in items:
                    if isinstance(t, hou.FolderParmTemplate): out.append({"name": t.name(), "label": t.label(), "type": "folder", "children": walk(t.parmTemplates())}); continue
                    row = {"name": t.name(), "label": t.label(), "type": t.type().name(), "default": _safe_value(lambda: t.defaultValue()),
                           "help": _safe_value(t.help, ""), "hidden": _safe_value(t.isHidden, False),
                           "conditions": {(_safe_value(k.name, str(k)) if hasattr(k, "name") else str(k)): str(v)
                                          for k, v in (_safe_value(lambda: t.conditionals(), {}) or {}).items()}}
                    if node_path:
                        parm = n.parm(t.name())
                        if parm is not None:
                            row["locked"] = _safe_value(parm.isLocked, False)
                            row["current_value"] = _safe_value(parm.eval)
                            row["disabled"] = _safe_value(lambda: parm.isDisabled(), False)
                    for key, fn in (("min", getattr(t, "minValue", None)), ("max", getattr(t, "maxValue", None)), ("menu_items", getattr(t, "menuItems", None)), ("menu_labels", getattr(t, "menuLabels", None))):
                        if fn: row[key] = _safe_value(fn)
                    if hasattr(t, "numComponents"): row["components"] = t.numComponents()
                    out.append(row)
                return out
            return ok("Parameter schema retrieved", {"node": path, "parameters": walk(templates)})
        except Exception as e: return err(str(e))
    add(get_parameter_schema)

    def set_parameter_reference(target_node_path: str, target_parameter: str, source_node_path: str,
                                source_parameter: str, language: str = "hscript") -> dict:
        """Set a Houdini expression reference from a destination parameter to a source."""
        try:
            _, dst = _parm(target_node_path, target_parameter); src_node, src = _parm(source_node_path, source_parameter)
            expression = f'ch("{src.path()}")'
            dst.setExpression(expression, language=hou.exprLanguage.Hscript if language.lower() == "hscript" else hou.exprLanguage.Python)
            return ok("Parameter reference set", {"target": dst.path(), "source": src.path(), "expression": expression})
        except Exception as e: return err(str(e))
    add(set_parameter_reference)

    def inspect_parameter_reference(node_path: str, parameter: str) -> dict:
        """Inspect expression and referenced parameter for a Houdini channel."""
        try:
            _, p = _parm(node_path, parameter); p = _as_scalar_parm(p)
            return ok("Parameter reference inspected", {"path": p.path(), "expression": _safe_value(p.expression, ""),
                "expression_language": str(_safe_value(p.expressionLanguage, "")), "referenced_parameter": _safe_value(lambda: p.getReferencedParm().path(), None),
                "value": _safe_value(p.eval)})
        except Exception as e: return err(str(e))
    add(inspect_parameter_reference)

    def manage_subnet_interface(subnet_path: str, inputs: list | None = None, outputs: list | None = None,
                                parameters: list | None = None) -> dict:
        """Create VOP connectors, label SOP subnet inputs, create SOP outputs and add spare parameters."""
        try:
            n = _node(subnet_path); made = {"inputs": [], "outputs": [], "parameters": []}
            category = n.childTypeCategory()
            is_vop = category is not None and category.name().lower() == "vop"
            is_sop = category is not None and category.name().lower() == "sop"
            if inputs and is_vop:
                for i, item in enumerate(inputs):
                    name = item.get("name", f"input{i+1}") if isinstance(item, dict) else str(item)
                    inp = n.createNode("subnetconnector", name)
                    inp.parm("connectorkind").set("input")
                    if isinstance(item, dict) and item.get("label") and inp.parm("parmlabel"):
                        inp.parm("parmlabel").set(item["label"])
                    made["inputs"].append(inp.path())
            elif inputs and is_sop:
                if len(inputs) > 4: raise ValueError("SOP subnets expose four labeled input slots")
                for i, item in enumerate(inputs):
                    label = item.get("label", item.get("name", f"Input {i+1}")) if isinstance(item, dict) else str(item)
                    p = n.parm(f"label{i+1}")
                    if p is None: raise ValueError(f"SOP subnet input label slot {i+1} is unavailable")
                    p.set(str(label)); made["inputs"].append({"index": i, "label": str(label)})
            elif inputs:
                raise ValueError(f"Subnet input management is not supported for category {category.name() if category else 'unknown'}")

            if outputs and is_vop:
                for item in outputs:
                    name = item.get("name", "output") if isinstance(item, dict) else str(item)
                    out = n.createNode("subnetconnector", name); out.parm("connectorkind").set("output")
                    if isinstance(item, dict) and item.get("label") and out.parm("parmlabel"):
                        out.parm("parmlabel").set(item["label"])
                    made["outputs"].append(out.path())
            elif outputs and is_sop:
                for i, item in enumerate(outputs):
                    source_path = item.get("node_path", item.get("source")) if isinstance(item, dict) else None
                    name = item.get("name", f"output{i+1}") if isinstance(item, dict) else str(item)
                    out = n.createNode("output", name)
                    source = _node(source_path) if source_path else None
                    if source is not None: out.setInput(0, source)
                    if out.parm("outputidx"): out.parm("outputidx").set(i)
                    if isinstance(item, dict) and item.get("label"): out.setUserData("morfyai_output_label", str(item["label"]))
                    made["outputs"].append({"path": out.path(), "source": source.path() if source else None, "index": i})
            elif outputs:
                raise ValueError(f"Subnet output management is not supported for category {category.name() if category else 'unknown'}")
            for spec in parameters or []:
                name = spec["name"]; kind = spec.get("type", "float")
                default = spec.get("default", "" if kind == "string" else False if kind == "toggle" else 0)
                created = create_parameter(n.path(), name, spec.get("label", name), kind, default,
                    spec.get("minimum"), spec.get("maximum"), spec.get("menu"))
                if created.get("status") != "success":
                    raise ValueError(created.get("message", f"Could not create interface parameter {name}"))
                made["parameters"].append(name)
            n.layoutChildren()
            return ok("Subnet interface updated", made)
        except Exception as e: return err(str(e))
    add(manage_subnet_interface)

    def get_node_flags(node_path: str) -> dict:
        """Read display, render, bypass and template flags."""
        try:
            n = _node(node_path)
            return ok("Node flags retrieved", {"path": n.path(), "display": _safe_value(lambda: n.isDisplayFlagSet(), None),
                "render": _safe_value(lambda: n.isRenderFlagSet(), None), "bypass": _safe_value(lambda: n.isBypassed(), None),
                "template": _safe_value(lambda: n.isTemplateFlagSet(), None)})
        except Exception as e: return err(str(e))
    add(get_node_flags)

    def set_node_flags(node_path: str, flags: dict) -> dict:
        """Set supported display, render, bypass and template node flags."""
        try:
            n = _node(node_path); methods = {"display": "setDisplayFlag", "render": "setRenderFlag", "bypass": "bypass",
                "template": "setTemplateFlag"}; changed = {}
            for k, v in flags.items():
                fn = getattr(n, methods.get(k, ""), None)
                if not callable(fn): changed[k] = "unsupported"; continue
                fn(bool(v)); changed[k] = bool(v)
            return ok("Node flags updated", changed)
        except Exception as e: return err(str(e))
    add(set_node_flags)

    def inspect_node_cook(node_path: str) -> dict:
        """Inspect node cook state, errors, warnings and cook duration when available."""
        try:
            n = _node(node_path); errors = list(n.errors() or []); warnings = list(n.warnings() or [])
            info = {"path": n.path(), "type": n.type().name(), "cook_status": "error" if errors else ("cooked" if _safe_value(lambda: n.isCooked(), False) else "unknown"),
                "errors": errors, "warnings": warnings, "cook_time": _safe_value(lambda: n.cookTime(), None),
                "time_dependent": _safe_value(lambda: n.isTimeDependent(), None)}
            return ok("Node cook inspected", info)
        except Exception as e: return err(str(e))
    add(inspect_node_cook)

    # 3. Timeline and animation
    def get_timeline() -> dict:
        """Return active frame, FPS, frame range and playback range."""
        try:
            return ok("Timeline retrieved", {"current_frame": hou.frame(), "fps": hou.fps(),
                "frame_range": list(hou.playbar.frameRange()), "playback_range": list(hou.playbar.playbackRange())})
        except Exception as e: return err(str(e))
    add(get_timeline)

    def set_current_frame(frame: float) -> dict:
        """Set Houdini's current frame."""
        try: hou.setFrame(float(frame)); return ok("Current frame set", {"frame": hou.frame()})
        except Exception as e: return err(str(e))
    add(set_current_frame)

    def set_keyframes(node_path: str, parameter: str, keyframes: list, interpolation: str = "bezier") -> dict:
        """Set keyframes as frame/value pairs using the requested interpolation."""
        try:
            _, p = _parm(node_path, parameter); p = _as_scalar_parm(p); keys = []
            modes = {"linear": "linear()", "bezier": "bezier()", "ease": "ease()", "hold": "constant()"}
            for item in keyframes:
                k = hou.Keyframe(); k.setFrame(float(item["frame"])); k.setValue(float(item["value"]))
                interp = modes.get(interpolation.lower())
                if interp is None: raise ValueError(f"Unsupported interpolation: {interpolation}")
                k.setExpression(interp, hou.exprLanguage.Hscript); keys.append(k)
            p.setKeyframes(keys)
            return ok("Keyframes set", {"parameter": p.path(), "count": len(keys), "interpolation": interpolation})
        except Exception as e: return err(str(e))
    add(set_keyframes)

    def get_keyframes(node_path: str, parameter: str) -> dict:
        """Return frame, value, interpolation and tangent data for parameter keys."""
        try:
            _, p = _parm(node_path, parameter); p = _as_scalar_parm(p); out = []
            for k in p.keyframes():
                out.append({"frame": k.frame(), "value": k.value(), "interpolation": _safe_value(k.expression, ""),
                    "in_slope": _safe_value(k.inSlope, None), "out_slope": _safe_value(k.slope, None),
                    "in_acceleration": _safe_value(k.inAccel, None), "out_acceleration": _safe_value(k.accel, None)})
            return ok("Keyframes retrieved", {"parameter": p.path(), "keyframes": out})
        except Exception as e: return err(str(e))
    add(get_keyframes)

    def delete_keyframes(node_path: str, parameter: str, start_frame: float, end_frame: float | None = None) -> dict:
        """Delete keyframes at a frame or inside an inclusive frame range."""
        try:
            _, p = _parm(node_path, parameter); p = _as_scalar_parm(p)
            a = float(start_frame); b = a if end_frame is None else float(end_frame)
            kept = [k for k in p.keyframes() if not a <= k.frame() <= b]; removed = len(p.keyframes()) - len(kept)
            p.deleteAllKeyframes(); p.setKeyframes(kept)
            return ok("Keyframes deleted", {"parameter": p.path(), "removed": removed})
        except Exception as e: return err(str(e))
    add(delete_keyframes)

    def evaluate_parameter(node_path: str, parameter: str, frame: float) -> dict:
        """Evaluate a parameter at a frame without changing the active frame."""
        try:
            _, p = _parm(node_path, parameter); p = _as_scalar_parm(p)
            value = p.evalAtFrame(float(frame))
            return ok("Parameter evaluated", {"parameter": p.path(), "frame": frame, "value": value})
        except Exception as e: return err(str(e))
    add(evaluate_parameter)

    def set_animation_interpolation(node_path: str, parameter: str, start_frame: float | None = None,
                                    end_frame: float | None = None, interpolation: str = "bezier") -> dict:
        """Change interpolation on all keys or keys inside a frame range."""
        try:
            _, p = _parm(node_path, parameter); p = _as_scalar_parm(p)
            interp = {"linear": "linear()", "bezier": "bezier()", "ease": "ease()", "hold": "constant()"}.get(interpolation.lower())
            if interp is None: raise ValueError(f"Unsupported interpolation: {interpolation}")
            keys = p.keyframes(); changed = 0
            for k in keys:
                if start_frame is not None and k.frame() < start_frame: continue
                if end_frame is not None and k.frame() > end_frame: continue
                k.setExpression(interp, hou.exprLanguage.Hscript); changed += 1
            p.setKeyframes(keys)
            return ok("Interpolation updated", {"parameter": p.path(), "changed": changed, "interpolation": interpolation})
        except Exception as e: return err(str(e))
    add(set_animation_interpolation)

    # 4. Geometry and transforms
    def get_geometry_summary(sop_path: str, frame: int | None = None) -> dict:
        """Summarize cooked geometry counts, primitive types, bounds, attributes and groups."""
        old = None
        try:
            geo, old = _geometry(sop_path, frame)
            if geo is None: raise ValueError("Node has no cooked geometry")
            box = geo.boundingBox()
            node = _node(sop_path)
            result = {"path": sop_path, "frame": frame, "points": len(geo.points()), "primitives": len(geo.prims()),
                "vertices": geo.vertexCount(), "primitive_types": sorted({p.type().name() for p in geo.prims()}),
                "bounds": {"min": list(box.minvec()), "max": list(box.maxvec())},
                "attributes": {c: [a.name() for a in getattr(geo, c + "Attribs")()] for c in ("point", "prim", "vertex", "global")},
                "groups": {c: [g.name() for g in getattr(geo, c + "Groups")()] for c in ("point", "prim")},
                "errors": list(node.errors() or []), "warnings": list(node.warnings() or [])}
            return ok("Geometry summary retrieved", result)
        except Exception as e: return err(str(e))
        finally:
            if frame is not None and old is not None: hou.setFrame(old)
    add(get_geometry_summary)

    def list_geometry_attributes(sop_path: str, attribute_class: str = "all", frame: int | None = None) -> dict:
        """List geometry attribute names, data types, tuple sizes and classes."""
        old = None
        try:
            geo, old = _geometry(sop_path, frame); classes = {"point": "pointAttribs", "primitive": "primAttribs", "prim": "primAttribs", "vertex": "vertexAttribs", "detail": "globalAttribs", "global": "globalAttribs"}
            selected = [classes[attribute_class]] if attribute_class in classes else list(dict.fromkeys(classes.values()))
            rows = []
            for fn in selected:
                cls = {"pointAttribs": "point", "primAttribs": "primitive", "vertexAttribs": "vertex", "globalAttribs": "detail"}[fn]
                for a in getattr(geo, fn)(): rows.append({"name": a.name(), "class": cls, "type": a.dataType().name(), "tuple_size": a.size(), "storage": str(a.dataType())})
            return ok("Geometry attributes retrieved", {"path": sop_path, "attributes": rows})
        except Exception as e: return err(str(e))
        finally:
            if frame is not None and old is not None: hou.setFrame(old)
    add(list_geometry_attributes)

    def get_attribute_values(sop_path: str, attribute_class: str, name: str, start: int = 0,
                             count: int = 100, frame: int | None = None) -> dict:
        """Read a bounded range of point, primitive, vertex or detail attribute values."""
        old = None
        try:
            geo, old = _geometry(sop_path, frame); c = attribute_class.lower()
            if c in ("point", "points"): elements = geo.points(); attr = geo.findPointAttrib(name)
            elif c in ("prim", "primitive", "primitives"): elements = geo.prims(); attr = geo.findPrimAttrib(name)
            elif c in ("vertex", "vertices"): elements = [v for prim in geo.prims() for v in prim.vertices()]; attr = geo.findVertexAttrib(name)
            elif c in ("detail", "global"): elements = [geo]; attr = geo.findGlobalAttrib(name)
            else: raise ValueError("attribute_class must be point, primitive, vertex or detail")
            if attr is None: raise ValueError(f"Attribute not found: {name}")
            values = []
            for i, elem in enumerate(elements[start:start + max(0, min(count, 10000))], start=start):
                val = geo.attribValue(attr) if c in ("detail", "global") else elem.attribValue(attr)
                values.append({"index": i, "value": list(val) if hasattr(val, "__iter__") and not isinstance(val, (str, bytes)) else val})
            return ok("Attribute values retrieved", {"name": name, "class": c, "total": len(elements), "values": values})
        except Exception as e: return err(str(e))
        finally:
            if frame is not None and old is not None: hou.setFrame(old)
    add(get_attribute_values)

    def list_geometry_groups(sop_path: str, group_class: str = "all", frame: int | None = None) -> dict:
        """List point and primitive geometry groups and member counts."""
        old = None
        try:
            geo, old = _geometry(sop_path, frame); result = []
            classes = ["point", "primitive"] if group_class == "all" else [group_class]
            for c in classes:
                groups = geo.pointGroups() if c == "point" else geo.primGroups() if c in ("prim", "primitive") else None
                if groups is None: raise ValueError("group_class must be point, primitive or all")
                for g in groups: result.append({"name": g.name(), "class": c, "count": len(g.points() if c == "point" else g.prims())})
            return ok("Geometry groups retrieved", {"groups": result})
        except Exception as e: return err(str(e))
        finally:
            if frame is not None and old is not None: hou.setFrame(old)
    add(list_geometry_groups)

    def inspect_packed_pieces(sop_path: str, piece_attribute: str = "name", frame: int | None = None) -> dict:
        """Inspect packed primitives, identity, transform, pivot and bounds."""
        old = None
        try:
            geo, old = _geometry(sop_path, frame); out = []
            for i, prim in enumerate(geo.prims()):
                if not isinstance(prim, hou.PackedPrim): continue
                name = _safe_value(lambda: prim.stringAttribValue(piece_attribute), None)
                if name is None:
                    a = geo.findPrimAttrib(piece_attribute); name = _safe_value(lambda: prim.attribValue(a), None) if a else None
                if name is None:
                    intrinsics = set(prim.intrinsicNames())
                    for candidate in (piece_attribute, "fragmentname", "packedprimitivename"):
                        if candidate in intrinsics:
                            name = _safe_value(lambda c=candidate: prim.intrinsicValue(c), None)
                            if name is not None: break
                bbox = _safe_value(prim.boundingBox, None)
                transform = _safe_value(lambda: prim.intrinsicValue("packedfulltransform"), None)
                local_transform = _safe_value(lambda: prim.intrinsicValue("packedlocaltransform"), None)
                pivot = _safe_value(lambda: prim.intrinsicValue("pivot"), None)
                matrix = hou.Matrix4(transform) if transform is not None else None
                out.append({"primitive_index": i, "piece": name,
                    "position": list(matrix.extractTranslates()) if matrix else (list(bbox.center()) if bbox else None),
                    "orientation": list(matrix.extractRotates()) if matrix else None,
                    "pivot": list(pivot) if pivot is not None else None,
                    "transform": _matrix_values(transform), "local_transform": _matrix_values(local_transform),
                    "bounds": {"min": list(bbox.minvec()), "max": list(bbox.maxvec())} if bbox else None})
            return ok("Packed pieces inspected", {"path": sop_path, "count": len(out), "pieces": out})
        except Exception as e: return err(str(e))
        finally:
            if frame is not None and old is not None: hou.setFrame(old)
    add(inspect_packed_pieces)

    def compare_geometry_frames(sop_path: str, frames: list, piece_attribute: str = "name") -> dict:
        """Compare packed piece positions and transforms across frames; restore active frame."""
        original = hou.frame() if hou else None; results = []
        try:
            for frame in frames:
                r = inspect_packed_pieces(sop_path, piece_attribute, int(frame))
                if r.get("status") != "success": return r
                results.append({"frame": frame, "pieces": r["data"]["pieces"]})
            return ok("Geometry frames compared", {"path": sop_path, "frames": results})
        except Exception as e: return err(str(e))
        finally:
            if original is not None: hou.setFrame(original)
    add(compare_geometry_frames)

    def inspect_transform(node_path: str, frame: int | None = None, piece_index: int | None = None) -> dict:
        """Inspect local and world node transform or a packed primitive transform."""
        old = None
        try:
            if piece_index is not None:
                geo, old = _geometry(node_path, frame); prim = geo.prim(int(piece_index))
                if not isinstance(prim, hou.PackedPrim): raise ValueError("piece_index must reference a packed primitive")
                return ok("Packed transform inspected", {"path": node_path, "piece_index": piece_index,
                    "transform": _matrix_values(prim.intrinsicValue("packedfulltransform")),
                    "local_transform": _matrix_values(prim.intrinsicValue("packedlocaltransform")),
                    "pivot": _safe_value(lambda: list(prim.intrinsicValue("pivot")), None)})
            n = _node(node_path)
            if frame is not None: old = hou.frame(); hou.setFrame(frame)
            world = _safe_value(lambda: list(n.worldTransform().asTuple()), None)
            local = _safe_value(lambda: list(n.parmTransform().asTuple()), None)
            return ok("Node transform inspected", {"path": n.path(), "world": world, "local": local,
                "pivot": _safe_value(lambda: list(n.parmTuple("p").eval()), None),
                "frame": frame if frame is not None else hou.frame()})
        except Exception as e: return err(str(e))
        finally:
            if frame is not None and old is not None: hou.setFrame(old)
    add(inspect_transform)

    # 5. Visual inspection
    def capture_viewport(width: int = 1280, height: int = 720, frame: int | None = None,
                         camera_path: str = "", shading: str = "") -> dict:
        """Capture the Scene Viewer with optional frame, camera and shading overrides."""
        old = hou.frame() if hou else None; viewport = None; saved_camera = None; saved_shading = None
        try:
            if frame is not None: hou.setFrame(frame)
            viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
            if viewer is None: raise RuntimeError("Scene Viewer is unavailable")
            viewport = viewer.curViewport(); saved_camera = viewport.defaultCamera().stash()
            display = viewport.settings().displaySet(hou.displaySetType.SceneObject)
            saved_shading = display.shadedMode()
            if camera_path: viewport.setCamera(_node(camera_path))
            shade_names = {"wire": "Wire", "smooth": "Smooth", "flat": "Flat", "wire_ghost": "WireGhost",
                           "hidden_line": "HiddenLineInvisible", "smooth_wire": "SmoothWire"}
            if shading:
                shade = shade_names.get(shading.lower())
                if shade is None: raise ValueError(f"Unsupported shading mode: {shading}")
                display.setShadedMode(getattr(hou.glShadingType, shade))
            if frame is not None and hasattr(hou.ui, "triggerUpdate"): hou.ui.triggerUpdate()
            result = _capture(viewport, width, height, "viewport")
            result.update({"camera": camera_path or viewport.cameraPath(), "shading": shading or str(saved_shading),
                           "scope": "Houdini window capture with the Scene Viewer visible"})
            return ok("Viewport captured", result)
        except Exception as e: return err(str(e))
        finally:
            if viewport is not None and saved_camera is not None:
                try: viewport.setDefaultCamera(saved_camera)
                except Exception: pass
            if viewport is not None and saved_shading is not None:
                try: viewport.settings().displaySet(hou.displaySetType.SceneObject).setShadedMode(saved_shading)
                except Exception: pass
            if frame is not None and old is not None: hou.setFrame(old)
    add(capture_viewport)

    def capture_viewport_frames(frames: list, width: int = 1280, height: int = 720,
                                camera_path: str = "", shading: str = "") -> dict:
        """Capture selected Scene Viewer frames and restore frame, camera and shading."""
        old = hou.frame() if hou else None; images = []; viewport = None; saved_camera = None; saved_shading = None
        try:
            viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
            if viewer is None: raise RuntimeError("Scene Viewer is unavailable")
            viewport = viewer.curViewport(); saved_camera = viewport.defaultCamera().stash()
            display = viewport.settings().displaySet(hou.displaySetType.SceneObject); saved_shading = display.shadedMode()
            if camera_path: viewport.setCamera(_node(camera_path))
            shade_names = {"wire": "Wire", "smooth": "Smooth", "flat": "Flat", "wire_ghost": "WireGhost",
                           "hidden_line": "HiddenLineInvisible", "smooth_wire": "SmoothWire"}
            if shading:
                shade = shade_names.get(shading.lower())
                if shade is None: raise ValueError(f"Unsupported shading mode: {shading}")
                display.setShadedMode(getattr(hou.glShadingType, shade))
            for frame in frames:
                hou.setFrame(frame)
                if hasattr(hou.ui, "triggerUpdate"): hou.ui.triggerUpdate()
                shot = _capture(viewport, width, height, f"viewport_f{frame}"); shot["frame"] = frame; images.append(shot)
            return ok("Viewport frames captured", {"frames": images})
        except Exception as e: return err(str(e))
        finally:
            if viewport is not None and saved_camera is not None:
                try: viewport.setDefaultCamera(saved_camera)
                except Exception: pass
            if viewport is not None and saved_shading is not None:
                try: viewport.settings().displaySet(hou.displaySetType.SceneObject).setShadedMode(saved_shading)
                except Exception: pass
            if old is not None: hou.setFrame(old)
    add(capture_viewport_frames)

    def viewport_flipbook(start_frame: int = 1, end_frame: int = 24, width: int = 1280, height: int = 720) -> dict:
        """Render a viewport flipbook and return image file paths."""
        try:
            if hou is None: raise RuntimeError("Houdini environment unavailable")
            viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
            if viewer is None: raise RuntimeError("Scene Viewer is unavailable")
            template = os.path.join(tempfile.gettempdir(), f"morfyai_flipbook_{os.getpid()}.$F4.png")
            settings = viewer.flipbookSettings().stash(); settings.output(template); settings.frameRange((start_frame, end_frame))
            settings.resolution((width, height)); settings.outputToMPlay(False); viewer.flipbook(viewer.curViewport(), settings)
            import glob
            files = sorted(glob.glob(template.replace("$F4", "*")))
            if not files: raise RuntimeError("Flipbook produced no image files")
            return ok("Viewport flipbook rendered", {"frames": [{"frame": start_frame+i, "path": p} for i, p in enumerate(files)], "width": width, "height": height})
        except Exception as e: return err(str(e))
    # The original viewport_flipbook tool is retained in server.py because it
    # publishes registered MCP image resources and honors the user setting.

    def capture_network_editor(network_path: str, node_paths: list | None = None,
                               width: int = 1280, height: int = 720) -> dict:
        """Capture the Network Editor displaying a network and optionally focus listed nodes."""
        try:
            n = _node(network_path); pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
            if pane is None: raise RuntimeError("Network Editor is unavailable")
            pane.setPwd(n)
            if node_paths:
                previous = list(hou.selectedNodes())
                try:
                    for selected in previous: selected.setSelected(False)
                    nodes = [_node(p) for p in node_paths]
                    for item in nodes: item.setSelected(True, clear_all_selected=False)
                    pane.homeToSelection()
                finally:
                    for item in hou.selectedNodes(): item.setSelected(False)
                    for item in previous: item.setSelected(True, clear_all_selected=False)
            result = _capture(pane, width, height, "network")
            result["scope"] = "Houdini window capture with the requested Network Editor visible"
            return ok("Network Editor captured", result)
        except Exception as e: return err(str(e))
    add(capture_network_editor)

    def frame_network_items(network_path: str, node_paths: list) -> dict:
        """Frame specified nodes in the Network Editor without laying out unrelated nodes."""
        try:
            _node(network_path); pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
            if pane is None: raise RuntimeError("Network Editor is unavailable")
            nodes = [_node(p) for p in node_paths]; pane.setPwd(hou.node(network_path))
            previous = list(hou.selectedNodes())
            try:
                for selected in previous: selected.setSelected(False)
                for item in nodes: item.setSelected(True, clear_all_selected=False)
                if nodes: pane.homeToSelection()
            finally:
                for item in hou.selectedNodes(): item.setSelected(False)
                for item in previous: item.setSelected(True, clear_all_selected=False)
            return ok("Network items framed", {"network": network_path, "nodes": [n.path() for n in nodes]})
        except Exception as e: return err(str(e))
    add(frame_network_items)

    # 6. Node layout and network boxes
    def get_node_positions(node_paths: list) -> dict:
        """Read positions for specific nodes."""
        try:
            result = []
            for path in node_paths:
                n = _node(path); p = n.position(); result.append({"path": path, "x": p[0], "y": p[1]})
            return ok("Node positions retrieved", result)
        except Exception as e: return err(str(e))
    add(get_node_positions)

    def set_node_positions(positions: list) -> dict:
        """Set positions on listed nodes only."""
        try:
            result = []
            for item in positions:
                n = _node(item["node_path"]); n.setPosition(hou.Vector2(float(item["x"]), float(item["y"])))
                result.append({"path": n.path(), "x": float(item["x"]), "y": float(item["y"])})
            return ok("Node positions set", result)
        except Exception as e: return err(str(e))
    add(set_node_positions)

    def layout_selected_nodes(node_paths: list, direction: str = "right", spacing: float = 2.0) -> dict:
        """Arrange only selected nodes in a stable line, leaving all others untouched."""
        try:
            nodes = [_node(p) for p in node_paths]
            if not nodes: return err("node_paths is empty")
            origin = nodes[0].position(); step = hou.Vector2(spacing, 0) if direction == "right" else hou.Vector2(0, -spacing) if direction == "down" else hou.Vector2(-spacing, 0) if direction == "left" else hou.Vector2(0, spacing)
            for i, n in enumerate(nodes): n.setPosition(origin + step * i)
            return ok("Selected nodes arranged", [{"path": n.path(), "x": n.position()[0], "y": n.position()[1]} for n in nodes])
        except Exception as e: return err(str(e))
    add(layout_selected_nodes)

    def manage_network_box(parent_path: str, box_name: str, node_paths: list | None = None,
                           remove_node_paths: list | None = None, title: str | None = None,
                           color: list | None = None, fit: bool = True) -> dict:
        """Update a Network Box's members, title, color and fit."""
        try:
            parent = _node(parent_path); box = next((b for b in parent.networkBoxes() if b.name() == box_name), None)
            if box is None: raise ValueError(f"Network Box not found: {box_name}")
            for path in node_paths or []: box.addNode(_node(path))
            for path in remove_node_paths or []:
                n = _node(path)
                if n in box.nodes(): box.removeNode(n)
            if title is not None: box.setComment(title)
            if color is not None: box.setColor(hou.Color(tuple(color[:3])))
            if fit: box.fitAroundContents()
            return ok("Network Box updated", {"name": box.name(), "title": box.comment(), "nodes": [n.path() for n in box.nodes()]})
        except Exception as e: return err(str(e))
    add(manage_network_box)

    def get_network_layout(network_path: str) -> dict:
        """Return child nodes, connections, positions and network boxes for layout verification."""
        try:
            n = _node(network_path); nodes = []
            for child in n.children():
                p = child.position(); nodes.append({"path": child.path(), "type": child.type().name(), "x": p[0], "y": p[1],
                    "inputs": [i.path() if i else None for i in child.inputs()]})
            boxes = []
            for b in n.networkBoxes():
                position = list(b.position()); size = list(b.size())
                boxes.append({"name": b.name(), "title": b.comment(), "nodes": [x.path() for x in b.nodes()],
                    "position": position, "size": size,
                    "bounds": {"min": position, "max": [position[0] + size[0], position[1] + size[1]]}})
            return ok("Network layout retrieved", {"path": n.path(), "nodes": nodes, "boxes": boxes})
        except Exception as e: return err(str(e))
    add(get_network_layout)

    # 7. Undo, save and scene state
    def begin_undo_group(name: str) -> dict:
        """Begin a Houdini undo group that ends with end_undo_group."""
        try:
            group = hou.undos.group(name)
            group.__enter__()
            _ACTIVE_UNDO_GROUPS.append((name, group))
            return ok("Undo group started", {"name": name, "depth": len(_ACTIVE_UNDO_GROUPS)})
        except Exception as e: return err(str(e))
    add(begin_undo_group)

    def end_undo_group(name: str = "") -> dict:
        """End the most recently started Houdini undo group."""
        try:
            if not _ACTIVE_UNDO_GROUPS: return err("No MorfyAI undo group is currently open")
            active_name, group = _ACTIVE_UNDO_GROUPS[-1]
            if name and name != active_name:
                return err(f"The open undo group is '{active_name}', not '{name}'")
            try: group.__exit__(None, None, None)
            finally: _ACTIVE_UNDO_GROUPS.pop()
            return ok("Undo group ended", {"name": active_name, "depth": len(_ACTIVE_UNDO_GROUPS)})
        except Exception as e: return err(str(e))
    add(end_undo_group)

    def undo(steps: int = 1) -> dict:
        """Undo one or more Houdini operations."""
        try:
            done = 0
            for _ in range(max(1, min(int(steps), 100))): hou.undos.performUndo(); done += 1
            return ok("Undo completed", {"steps": done})
        except Exception as e: return err(str(e))
    add(undo)

    def redo(steps: int = 1) -> dict:
        """Redo one or more Houdini operations."""
        try:
            done = 0
            for _ in range(max(1, min(int(steps), 100))): hou.undos.performRedo(); done += 1
            return ok("Redo completed", {"steps": done})
        except Exception as e: return err(str(e))
    add(redo)

    def save_scene_as(path: str) -> dict:
        """Save the current Houdini scene to a separate file path."""
        try:
            hou.hipFile.save(file_name=os.path.abspath(path), save_to_recent_files=False)
            return ok("Scene saved", {"path": os.path.abspath(path), "hip_file": hou.hipFile.path()})
        except Exception as e: return err(str(e))
    add(save_scene_as)

    def get_scene_state() -> dict:
        """Return current scene file, modified status, Houdini version and timeline frame."""
        try:
            return ok("Scene state retrieved", {"file": hou.hipFile.path(), "unsaved_changes": hou.hipFile.hasUnsavedChanges(),
                "houdini_version": hou.applicationVersionString(), "frame": hou.frame(), "fps": hou.fps(),
                "frame_range": list(hou.playbar.frameRange()), "playback_range": list(hou.playbar.playbackRange())})
        except Exception as e: return err(str(e))
    add(get_scene_state)
