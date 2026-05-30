# -*- coding: utf-8 -*-
"""
Houdini MCP Client
raisefornodeoperation corefeature, support AI Agent  toolcall
"""
from __future__ import annotations

import os
import sys
import re
import time
import json
from typing import Any, Optional, Dict, List, Tuple
from pathlib import Path

try:
    import hou  # type: ignore
except Exception:
    hou = None  # type: ignore

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None


# ============================================================
# Document-search feature has been removed; use web_search to query the official docs.
# ============================================================

# forceusethisplace lib directoryin depend onlibrary
_lib_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'lib')
if os.path.exists(_lib_path):
    # will lib directoryaddto sys.path mostpreviousface, ensurepreferreduse
    if _lib_path in sys.path:
        sys.path.remove(_lib_path)
    sys.path.insert(0, _lib_path)

# importenter requests
try:
    import requests
except ImportError:
    requests = None  # type: ignore

from .settings import read_settings

# importenter RAG searchsystem
try:
    from ..doc_rag import get_doc_rag
    HAS_DOC_RAG = True
except ImportError:
    HAS_DOC_RAG = False
    _dbg("[MCP Client] DocRAG module not found, local doc search disabled")

# importenter Skill system
HAS_SKILLS = False
_list_skills = None   # type: ignore
_run_skill = None     # type: ignore
try:
    from ...skills import list_skills as _list_skills, run_skill as _run_skill
    HAS_SKILLS = True
except (ImportError, ValueError, SystemError):
    pass

if not HAS_SKILLS:
    try:
        import importlib
        _skills_mod = importlib.import_module('morfyai.skills')
        _list_skills = _skills_mod.list_skills
        _run_skill = _skills_mod.run_skill
        HAS_SKILLS = True
    except Exception:
        pass

if not HAS_SKILLS:
    # lasttry: based onfile pathdirectlyimportenter
    try:
        import importlib.util
        _skills_init = Path(__file__).parent.parent.parent / 'skills' / '__init__.py'
        if _skills_init.exists():
            _spec = importlib.util.spec_from_file_location('houdini_skills', str(_skills_init))
            _skills_mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_skills_mod)
            _list_skills = _skills_mod.list_skills
            _run_skill = _skills_mod.run_skill
            HAS_SKILLS = True
    except Exception:
        pass

if not HAS_SKILLS:
    _dbg("[MCP Client] Skill system not loaded, run_skill/list_skills unavailable")


class HoudiniMCP:
    """Houdini nodeoperationclientend
    
    raisefornodenetwork read, create, modify, deleteetc.operation. 
    setcountas AI Agent  toolexecuteafterend. 
    """
    
    # Class-level cache (shared across instances, loaded once)
    _node_types_cache: Optional[Dict[str, List[str]]] = None  # {category: [type_names]}
    _node_types_cache_time: float = 0  # cachewhenbetween
    _common_node_inputs_cache: Dict[str, str] = {}  # commonnodeinputinfocache
    _ats_cache: Dict[str, Dict[str, Any]] = {}  # ATScache: {node_type_key: ats_data}

    # perfMon performanceanalyze: currentactive  profile object
    _active_perf_profile: Any = None

    # throughusetoolresultpaginatecache: key = "tool_name:unique_key" → completetext
    _tool_page_cache: Dict[str, str] = {}
    _TOOL_PAGE_LINES = 50  # eachpagerowcount

    def __init__(self):
        import threading
        self._stop_event: Optional[threading.Event] = None

    def set_stop_event(self, event):
        """setstopevent (from AIClient passenter, used fordetectuserinbreak)
        
        in execute_python / execute_shell inviacheckthiseventcomesupportuserinbreak. 
        """
        self._stop_event = event

    @classmethod
    def _paginate_tool_result(cls, text: str, cache_key: str, tool_hint: str,
                              page: int = 1, page_lines: int = 0) -> str:
        """throughusetoolresultpaginate
        
        Args:
            text: complete textresult
            cache_key: cachekey (such as "get_node_parameters:/obj/geo1/box1")
            tool_hint: pagination tool-call hint for the AI (e.g., 'get_node_parameters(node_path="/obj/geo1/box1", page=2)')
            page: pagecode (from 1 start)
            page_lines: eachpagerowcount, 0 tableshowusedefault
        """
        if not page_lines:
            page_lines = cls._TOOL_PAGE_LINES

        cls._tool_page_cache[cache_key] = text

        lines = text.split('\n')
        total_lines = len(lines)
        total_pages = max(1, (total_lines + page_lines - 1) // page_lines)

        page = max(1, min(page, total_pages))

        start = (page - 1) * page_lines
        end = min(start + page_lines, total_lines)
        page_text = '\n'.join(lines[start:end])

        if total_pages == 1:
            return page_text

        header = f"[Page {page}/{total_pages}/{total_lines} lines]\n\n"

        if page < total_pages:
            # will page_hint in pagecodereplaceswapasbelowonepage
            next_page = page + 1
            footer = f"\n\n[Page {page}/{total_pages}]  — more content; call {tool_hint.replace(f'page={page}', f'page={next_page}')} for next page"
        else:
            footer = f"\n\n[Page {page}/{total_pages} - last page]"

        return header + page_text + footer

    # ========================================
    # networkstructureread (lightweight, onlyreturntopologyinfo)
    # ========================================
    
    def get_network_structure(self, network_path: Optional[str] = None) -> Tuple[bool, Dict[str, Any]]:
        """getnodenetwork topologystructure (nodename, type, connectrelation)
        
        thisisonelightweightoperation, notreadparameterDetails. 
        
        Args:
            network_path: network path, such as '/obj/geo1'. None thenusecurrentnetwork. 
        
        Returns:
            (success, data) itsin data packagecontaining:
            {
                "network_path": str,
                "network_type": str,
                "nodes": [
                    {
                        "name": str,
                        "path": str,
                        "type": str,
                        "type_label": str,
                        "is_displayed": bool,
                        "has_errors": bool,
                        "position": [x, y]
                    }
                ],
                "connections": [
                    {
                        "from": str,  # Source nodepath
                        "to": str,    # Target nodepath
                        "input_index": int,
                        "input_label": str  # inputportname (such ashas)
                    }
                ]
            }
        """
        if hou is None:
            return False, {"error": "Houdini API (hou module) not detected"}
        
        # getnetworknode
        if network_path:
            network = hou.node(network_path)
            if network is None:
                return False, {"error": f"Network not found: {network_path}"}
        else:
            network = self._current_network()
            if network is None:
                return False, {"error": "Current network not found — please open the network editor"}
        
        nodes_data = []
        connections_data = []
        
        try:
            children = network.children()
            
            for node in children:
                try:
                    node_type = node.type()
                    category = node_type.category().name() if node_type else "Unknown"
                    type_name = node_type.name() if node_type else "unknown"
                    
                    # getposition
                    pos = node.position()
                    position = [pos[0], pos[1]] if pos else [0, 0]
                    
                    # checkwhetherhaserror
                    has_errors = False
                    try:
                        errors = node.errors()
                        has_errors = bool(errors)
                    except Exception:
                        pass
                    
                    node_info = {
                        "name": node.name(),
                        "path": node.path(),
                        "type": f"{category.lower()}/{type_name}",
                        "type_label": node_type.description() if node_type else "",
                        "is_displayed": node.isDisplayFlagSet() if hasattr(node, 'isDisplayFlagSet') else False,
                        "has_errors": has_errors,
                        "position": position
                    }
                    
                    # detect wrangle typenode, extract VEX code
                    _wrangle_keywords = ('wrangle', 'snippet', 'vopnet')
                    if any(kw in type_name.lower() for kw in _wrangle_keywords):
                        try:
                            snippet = node.parm("snippet")
                            if snippet:
                                code = snippet.eval()
                                if code and code.strip():
                                    node_info["vex_code"] = code.strip()
                        except Exception:
                            pass
                    # alsodetect python scriptnode
                    if 'python' in type_name.lower():
                        try:
                            for pname in ("python", "code", "script"):
                                parm = node.parm(pname)
                                if parm:
                                    code = parm.eval()
                                    if code and code.strip():
                                        node_info["python_code"] = code.strip()
                                        break
                        except Exception:
                            pass
                    
                    nodes_data.append(node_info)
                    
                    # collectsetconnectrelation (containinginputportname)
                    for input_idx, input_node in enumerate(node.inputs()):
                        if input_node is not None:
                            conn_info = {
                                "from": input_node.path(),
                                "to": node.path(),
                                "input_index": input_idx,
                            }
                            # trygetinputportlabel
                            try:
                                input_label = node_type.inputLabel(input_idx)
                                if input_label:
                                    conn_info["input_label"] = input_label
                            except Exception:
                                pass
                            connections_data.append(conn_info)
                except Exception:
                    continue
            
            # collectset NetworkBox info
            boxed_node_paths = set()
            boxes_data = []
            try:
                for box in network.networkBoxes():
                    box_nodes = box.nodes()
                    box_node_paths = [n.path() for n in box_nodes]
                    boxed_node_paths.update(box_node_paths)
                    boxes_data.append({
                        "name": box.name(),
                        "comment": box.comment() or "",
                        "node_count": len(box_nodes),
                        "nodes": box_node_paths,
                    })
            except Exception:
                pass  # networkBoxes() mayinsomenetworktypebelowunavailable

            return True, {
                "network_path": network.path(),
                "network_type": network.type().name() if network.type() else "unknown",
                "node_count": len(nodes_data),
                "nodes": nodes_data,
                "connections": connections_data,
                "network_boxes": boxes_data,
                "boxed_node_paths": list(boxed_node_paths),
            }
        except Exception as e:
            return False, {"error": f"Failed to read network structure: {str(e)}"}

    def get_network_structure_text(self, network_path: Optional[str] = None,
                                   box_name: Optional[str] = None) -> Tuple[bool, str]:
        """Get a textual description of a node network (suitable for AI consumption).

        Three modes:
        1. No box_name AND the network has NetworkBox(es) → overview mode (boxes collapsed; saves tokens)
        2. box_name supplied → drill-down mode (only expand and show nodes inside that box)
        3. no box_name andnetworkno NetworkBox → passstatsallexpandmode
        """
        ok, data = self.get_network_structure(network_path)
        if not ok:
            return False, data.get("error", "Unknown error")
        
        boxes = data.get("network_boxes", [])
        boxed_paths = set(data.get("boxed_node_paths", []))

        # ── Drill-down mode: only expand and show nodes inside the specified box ──
        if box_name:
            target = next((b for b in boxes if b["name"] == box_name), None)
            if not target:
                available = ", ".join(b["name"] for b in boxes) if boxes else "(none)"
                return False, f"NetworkBox not found: {box_name}. Available boxes: {available}"
            
            target_paths = set(target["nodes"])
            box_nodes = [n for n in data["nodes"] if n["path"] in target_paths]
            box_conns = [c for c in data["connections"]
                         if c["from"] in target_paths and c["to"] in target_paths]
            # box withexternal crossgroupconnect
            cross_conns = [c for c in data["connections"]
                           if (c["from"] in target_paths) != (c["to"] in target_paths)]
            
            lines = [
                f"## NetworkBox details: {box_name}",
                f"Comment: {target['comment'] or '(none)'}",
                f"Node count: {target['node_count']}",
                "", "### Nodes:"
            ]
            wrangle_details = []
            self._format_node_list(box_nodes, lines, wrangle_details)
            
            if box_conns:
                lines.append("")
                lines.append("### Internal connections:")
                for conn in box_conns:
                    lines.append(self._format_connection(conn))
            
            if cross_conns:
                lines.append("")
                lines.append("### Cross-group connections (to other boxes / ungrouped):")
                for conn in cross_conns:
                    lines.append(self._format_connection(conn))
            
            if wrangle_details:
                lines.append("")
                lines.append("### Inline node code:")
                for detail in wrangle_details:
                    lines.append(detail)
            
            return True, "\n".join(lines)

        # ── Overview mode: collapse NetworkBox display (core token-saving logic) ──
        if boxes:
            unboxed_nodes = [n for n in data["nodes"] if n["path"] not in boxed_paths]
            
            lines = [
                f"## Network structure: {data['network_path']}",
                f"Network type: {data['network_type']}",
                f"Total nodes: {data['node_count']}",
                f"NetworkBox groups: {len(boxes)} (containing {len(boxed_paths)} nodes)",
                "",
                "### NetworkBox overview:"
            ]
            for b in boxes:
                # statistics box withinnodetypesummary (fetchprevious 3  types)
                box_paths_set = set(b["nodes"])
                type_counts: Dict[str, int] = {}
                for n in data["nodes"]:
                    if n["path"] in box_paths_set:
                        short_type = n["type"].split("/")[-1] if "/" in n["type"] else n["type"]
                        type_counts[short_type] = type_counts.get(short_type, 0) + 1
                top_types = sorted(type_counts.items(), key=lambda x: -x[1])[:3]
                types_str = ", ".join(f"{t}×{c}" for t, c in top_types)
                if len(type_counts) > 3:
                    types_str += f" plus {len(type_counts)} types"
                
                lines.append(f"📦 **{b['name']}**: {b['comment'] or '(no comment)'} — {b['node_count']} nodes [{types_str}]")
            
            lines.append(f"\n💡 Use get_network_structure(box_name=\"box_name\") to view detailed nodes for a group")
            
            if unboxed_nodes:
                lines.append(f"\n### Ungrouped nodes ({len(unboxed_nodes)}):")
                wrangle_details = []
                self._format_node_list(unboxed_nodes, lines, wrangle_details)
                if wrangle_details:
                    lines.append("")
                    lines.append("### Ungrouped node inline code:")
                    for detail in wrangle_details:
                        lines.append(detail)
            
            # crossgroupconnect: twoendnotinsameone box in connect
            cross_conns = []
            # build node_path → box_name mapping
            path_to_box: Dict[str, str] = {}
            for b in boxes:
                for np in b["nodes"]:
                    path_to_box[np] = b["name"]
            for conn in data["connections"]:
                src_box = path_to_box.get(conn["from"], "__unboxed__")
                dst_box = path_to_box.get(conn["to"], "__unboxed__")
                if src_box != dst_box:
                    cross_conns.append(conn)
            
            if cross_conns:
                lines.append("")
                lines.append("### Cross-group connections:")
                for conn in cross_conns:
                    from_name = conn['from'].split('/')[-1]
                    to_name = conn['to'].split('/')[-1]
                    src_box = path_to_box.get(conn["from"], "ungrouped")
                    dst_box = path_to_box.get(conn["to"], "ungrouped")
                    idx = conn['input_index']
                    label = conn.get('input_label', '')
                    port_str = f"{label}({idx})" if label else str(idx)
                    lines.append(f"- [{src_box}] {from_name} → {to_name}[{port_str}] [{dst_box}]")
            
            return True, "\n".join(lines)

        # ── passstatsmode: no NetworkBox, allpartexpand (compatible witholdrowas) ──
        lines = [
            f"## Network structure: {data['network_path']}",
            f"Network type: {data['network_type']}",
            f"Node count: {data['node_count']}",
            "",
            "### Nodes:"
        ]
        
        wrangle_details = []
        self._format_node_list(data['nodes'], lines, wrangle_details)
        
        if data['connections']:
            lines.append("")
            lines.append("### Connections:")
            for conn in data['connections']:
                lines.append(self._format_connection(conn))
        
        if wrangle_details:
            lines.append("")
            lines.append("### Inline node code:")
            for detail in wrangle_details:
                lines.append(detail)
        
        return True, "\n".join(lines)

    @staticmethod
    def _format_node_list(nodes: List[Dict], lines: List[str], wrangle_details: List[str]):
        """formatizationnodelistto lines, collectsetcodeDetailsto wrangle_details"""
        for node in nodes:
            status = []
            if node.get('is_displayed'):
                status.append("display")
            if node.get('has_errors'):
                status.append("error")
            status_str = f" [{', '.join(status)}]" if status else ""
            
            has_code = ""
            if node.get('vex_code'):
                has_code = " [contains VEX]"
            elif node.get('python_code'):
                has_code = " [contains Python]"
            
            lines.append(f"- `{node['name']}` ({node['type']}){status_str}{has_code}")
            
            if node.get('vex_code'):
                code = node['vex_code']
                code_lines = code.split('\n')
                if len(code_lines) > 30:
                    code = '\n'.join(code_lines[:30]) + f'\n// ... of {len(code_lines)} lines, truncated'
                wrangle_details.append(
                    f"#### `{node['name']}` VEX code:\n```vex\n{code}\n```"
                )
            elif node.get('python_code'):
                code = node['python_code']
                code_lines = code.split('\n')
                if len(code_lines) > 30:
                    code = '\n'.join(code_lines[:30]) + f'\n# ... of {len(code_lines)} lines, truncated'
                wrangle_details.append(
                    f"#### `{node['name']}` Python code:\n```python\n{code}\n```"
                )

    @staticmethod
    def _format_connection(conn: Dict[str, Any], prefix: str = "- ") -> str:
        """formatizationsingleitemconnectinfo, packagecontaininginputportname (such ashas)"""
        from_name = conn['from'].split('/')[-1]
        to_name = conn['to'].split('/')[-1]
        idx = conn['input_index']
        label = conn.get('input_label', '')
        if label:
            port_str = f"{label}({idx})"
        else:
            port_str = str(idx)
        return f"{prefix}{from_name} → {to_name}[{port_str}]"

    # ========================================
    # ATS (Abstract Type System) build
    # ========================================
    
    def _build_ats(self, node_type: Any) -> Dict[str, Any]:
        """buildnodetype ATS (abstracttypesystem)
        
        Args:
            node_type: Houdininodetypeobject
            
        Returns:
            ATSdatadict, packagecontainingparametertemplate, defaultetc.info
        """
        if hou is None or node_type is None:
            return {}
        
        # generatecachekey
        type_key = f"{node_type.category().name().lower()}/{node_type.name()}"
        
        # checkcache
        if type_key in HoudiniMCP._ats_cache:
            return HoudiniMCP._ats_cache[type_key]
        
        try:
            # getparametertemplate
            parm_template_group = node_type.parmTemplateGroup()
            ats_data = {
                "type": type_key,
                "type_label": node_type.description() if hasattr(node_type, 'description') else "",
                "input_count": {
                    "min": node_type.minNumInputs() if hasattr(node_type, 'minNumInputs') else 0,
                    "max": node_type.maxNumInputs() if hasattr(node_type, 'maxNumInputs') else 0,
                },
                "output_count": {
                    "min": node_type.minNumOutputs() if hasattr(node_type, 'minNumOutputs') else 0,
                    "max": node_type.maxNumOutputs() if hasattr(node_type, 'maxNumOutputs') else 0,
                },
                "parameters": {}
            }
            
            # extractparametertemplateinfo (onlypackagecontainingparametername, type, default)
            if parm_template_group:
                for parm_template in parm_template_group.parmTemplates():
                    try:
                        parm_name = parm_template.name()
                        parm_type = parm_template.type().name() if hasattr(parm_template, 'type') else "unknown"
                        
                        # getdefault
                        default_value = None
                        if hasattr(parm_template, 'defaultValue'):
                            try:
                                default_value = parm_template.defaultValue()
                                # formatizationfloat
                                if isinstance(default_value, float):
                                    default_value = round(default_value, 6)
                                elif isinstance(default_value, tuple):
                                    default_value = tuple(round(v, 6) if isinstance(v, float) else v for v in default_value)
                            except Exception:
                                pass
                        
                        # onlysavekeyinfo
                        ats_data["parameters"][parm_name] = {
                            "type": parm_type,
                            "default_value": default_value,
                            "is_hidden": parm_template.isHidden() if hasattr(parm_template, 'isHidden') else False,
                        }
                    except Exception:
                        continue
            
            # cacheATSdata
            HoudiniMCP._ats_cache[type_key] = ats_data
            return ats_data
            
        except Exception:
            return {}
    
    # ========================================
    # nodeDetailsread (optimizationizationversion: firstbuildATS, againreadpartpartcontext)
    # ========================================
    
    def get_node_details(self, node_path: str) -> Tuple[bool, Dict[str, Any]]:
        """getspecifiednode detailfineinfo (optimizationizationversion: firstbuildATS, againreadpartpartcontext)
        
        flow: 
        1. firstbuildATS (nodetype abstractinfo, packageincludeparametertemplate, defaultetc.)
        2. needleforspecialfixednodeonlyreadpartpartcontext (notdefaultparameter, error, connectetc.)
        
        Args:
            node_path: nodecompletepath
        
        Returns:
            (success, data) itsin data packagecontaining:
            {
                "name": str,
                "path": str,
                "type": str,
                "type_label": str,
                "comment": str,
                "flags": {...},
                "errors": [...],
                "inputs": [...],
                "outputs": [...],
                "parameters": {...},  # onlypackagecontainingnotdefaultparameter
                "ats": {...}  # ATSinfo (options, used forreference)
            }
        """
        if hou is None:
            return False, {"error": "Houdini API not detected"}
        
        node = hou.node(node_path)
        if node is None:
            return False, {"error": f"Not foundNode: {node_path}"}
        
        try:
            node_type = node.type()
            category = node_type.category().name() if node_type else "Unknown"
            type_name = node_type.name() if node_type else "unknown"
            type_key = f"{category.lower()}/{type_name}"
            
            # firststep: buildATS (nodetype abstractinfo)
            ats_data = self._build_ats(node_type)
            
            # secondstep: readnodespecialfixedcontext (onlyreadpartpartinfo)
            # basethisinfo
            data = {
                "name": node.name(),
                "path": node.path(),
                "type": type_key,
                "type_label": node_type.description() if node_type else "",
                "comment": node.comment().strip() if node.comment() else "",
            }
            
            # statusinfo
            data["flags"] = {
                "display": node.isDisplayFlagSet() if hasattr(node, 'isDisplayFlagSet') else False,
                "render": node.isRenderFlagSet() if hasattr(node, 'isRenderFlagSet') else False,
                "bypass": node.isBypassed() if hasattr(node, 'isBypassed') else False,
                "locked": node.isLocked() if hasattr(node, 'isLocked') else False,
            }
            
            # errorinfo (reneed, mustread)
            errors = []
            try:
                errs = node.errors()
                if errs:
                    errors = list(errs)
            except Exception:
                pass
            data["errors"] = errors
            
            # inputoutputconnect (reneed, mustread)
            inputs = []
            for i, inp in enumerate(node.inputs()):
                if inp is not None:
                    inputs.append({"index": i, "node": inp.path()})
            data["inputs"] = inputs
            
            outputs = []
            for out in node.outputs():
                outputs.append(out.path())
            data["outputs"] = outputs
            
            # onlyreadnotdefaultparameter (partpartcontext)
            params = {}
            for parm in node.parms():
                try:
                    if parm.isHidden() or parm.isDisabled():
                        continue
                    
                    parm_name = parm.name()
                    
                    # checkwhetherasdefault
                    is_default = False
                    try:
                        is_default = parm.isAtDefault()
                    except Exception:
                        # ifnomethoddecidebreak, thenreadcurrentvalue
                        pass
                    
                    # onlysavenotdefaultparameter
                    if not is_default:
                        value = parm.eval()
                        
                        # formatizationfloat
                        if isinstance(value, float):
                            value = round(value, 6)
                        elif isinstance(value, tuple):
                            value = tuple(round(v, 6) if isinstance(v, float) else v for v in value)
                        
                        params[parm_name] = {
                            "value": value,
                            "is_default": False
                        }
                except Exception:
                    continue
            
            data["parameters"] = params
            
            # options: addATSreference (used forreference, butnotpackagecontaininginmainneeddatain)
            # ifneedscompleteATSinfo, canvia get_node_type_ats singleindependentget
            
            return True, data
        except Exception as e:
            return False, {"error": f"Failed to read node details: {str(e)}"}

    def get_node_details_text(self, node_path: str) -> Tuple[bool, str]:
        """getnodeDetails textdescription (optimizationizationversion: onlydisplaypartpartcontext)"""
        ok, data = self.get_node_details(node_path)
        if not ok:
            return False, data.get("error", "Unknown error")
        
        lines = [
            f"## Node: {data['name']}",
            f"Path: {data['path']}",
            f"type: {data['type']} ({data['type_label']})",
        ]
        
        if data['comment']:
            lines.append(f"Note: {data['comment']}")
        
        # status
        flags = data['flags']
        status = []
        if flags['display']:
            status.append("display")
        if flags['render']:
            status.append("render")
        if flags['bypass']:
            status.append("bypassed")
        if flags['locked']:
            status.append("locked")
        if status:
            lines.append(f"Status: {', '.join(status)}")
        
        # error (reneedcontext)
        if data['errors']:
            lines.append("")
            lines.append("### Errors:")
            for err in data['errors']:
                lines.append(f"- {err}")
        
        # connect (reneedcontext)
        if data['inputs']:
            lines.append("")
            lines.append("### Input connections:")
            for inp in data['inputs']:
                lines.append(f"- [{inp['index']}] ← {inp['node']}")
        
        if data['outputs']:
            lines.append("")
            lines.append("### Output connections:")
            for out in data['outputs']:
                lines.append(f"- → {out}")
        
        # notdefaultparameter (partpartcontext, alreadyoptimizationization)
        lines.append("")
        lines.append("### Parameters (non-default):")
        if data['parameters']:
            for name, info in data['parameters'].items():
                value = info['value']
                if isinstance(value, tuple):
                    value_str = "(" + ", ".join(str(v) for v in value) + ")"
                else:
                    value_str = str(value)
                lines.append(f"- {name} = {value_str}")
        else:
            lines.append("(all parameters are default)")
        
        return True, "\n".join(lines)
    
    def get_node_type_ats(self, node_type: str, category: str = "sop") -> Tuple[bool, Dict[str, Any]]:
        """getnodetype ATS (abstracttypesystem)info
        
        Args:
            node_type: nodetypename, such as 'box', 'scatter'
            category: nodecategory, default 'sop'
        
        Returns:
            (success, ats_data) ATSdatapackagecontainingparametertemplate, defaultetc.info
        """
        if hou is None:
            return False, {"error": "Houdini API not detected"}
        
        try:
            # getnodetypeobject
            categories = hou.nodeTypeCategories()
            cat_obj = categories.get(category.capitalize()) or categories.get(category.upper())
            if not cat_obj:
                return False, {"error": f"Category not found: {category}"}
            
            node_type_obj = None
            type_lower = node_type.lower()
            for name, nt in cat_obj.nodeTypes().items():
                if name.lower() == type_lower or name.lower().endswith(f"::{type_lower}"):
                    node_type_obj = nt
                    break
            
            if not node_type_obj:
                return False, {"error": f"Node type not found: {node_type}"}
            
            # buildATS
            ats_data = self._build_ats(node_type_obj)
            if not ats_data:
                return False, {"error": "Failed to build ATS"}
            
            return True, ats_data
            
        except Exception as e:
            return False, {"error": f"Failed to fetch ATS: {str(e)}"}

    # ========================================
    # errorandwarningcheck
    # ========================================
    
    def check_node_errors(self, node_path: Optional[str] = None) -> Tuple[bool, Dict[str, Any]]:
        """checknodeornetworkin errorandwarning
        
        Args:
            node_path: Node path. ifisnetwork path, checkitsbelowallnode. ifas None, checkcurrentnetwork. 
        
        Returns:
            (success, data) itsin data packagecontaining errors and warnings list
        """
        if hou is None:
            return False, {"error": "Houdini API not detected"}
        
        try:
            # certainfixedneedcheck node
            if node_path:
                target = hou.node(node_path)
                if target is None:
                    return False, {"error": f"Not foundNode: {node_path}"}
            else:
                # getcurrentnetwork
                try:
                    pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
                    target = pane.pwd() if pane else hou.node('/obj')
                except Exception:
                    target = hou.node('/obj')
            
            results = {
                "checked_path": target.path(),
                "total_nodes": 0,
                "error_count": 0,
                "warning_count": 0,
                "errors": [],
                "warnings": []
            }
            
            # ifiscontain node, checkallsubnode
            if hasattr(target, 'children') and target.children():
                nodes_to_check = target.allSubChildren() if hasattr(target, 'allSubChildren') else target.children()
            else:
                nodes_to_check = [target]
            
            results["total_nodes"] = len(nodes_to_check)
            
            for node in nodes_to_check:
                try:
                    # checkerror
                    errors = node.errors() if hasattr(node, 'errors') else []
                    for err in errors:
                        results["errors"].append({
                            "node_path": node.path(),
                            "node_name": node.name(),
                            "node_type": node.type().name() if node.type() else "unknown",
                            "message": str(err)
                        })
                        results["error_count"] += 1
                    
                    # checkwarning
                    warnings = node.warnings() if hasattr(node, 'warnings') else []
                    for warn in warnings:
                        results["warnings"].append({
                            "node_path": node.path(),
                            "node_name": node.name(),
                            "node_type": node.type().name() if node.type() else "unknown",
                            "message": str(warn)
                        })
                        results["warning_count"] += 1
                        
                except Exception:
                    continue
            
            return True, results
            
        except Exception as e:
            return False, {"error": f"Failed to check errors: {str(e)}"}
    
    def check_node_errors_text(self, node_path: Optional[str] = None) -> Tuple[bool, str]:
        """geterrorcheck textdescription"""
        ok, data = self.check_node_errors(node_path)
        if not ok:
            return False, data.get("error", "Unknown error")
        
        lines = [
            f"## Error check report",
            f"Checked Path: {data['checked_path']}",
            f"Checked nodes: {data['total_nodes']}",
            f"Errors: {data['error_count']}",
            f"Warning count: {data['warning_count']}",
        ]
        
        if data['errors']:
            lines.append("")
            lines.append("### Errors:")
            for err in data['errors']:
                lines.append(f"- **{err['node_name']}** ({err['node_type']}): {err['message']}")
        
        if data['warnings']:
            lines.append("")
            lines.append("### Warnings:")
            for warn in data['warnings']:
                lines.append(f"- **{warn['node_name']}** ({warn['node_type']}): {warn['message']}")
        
        if not data['errors'] and not data['warnings']:
            lines.append("")
            lines.append("**No errors or warnings.**")
        
        return True, "\n".join(lines)

    # ========================================
    # selectednodeoperation
    # ========================================
    
    def describe_selection(self, limit: int = 3, include_all_params: bool = False) -> Tuple[bool, str]:
        """readselectednode info"""
        if hou is None:
            return False, "Houdini API not detected"
        
        nodes = hou.selectedNodes()
        if not nodes:
            return False, "No nodes selected"
        
        lines: List[str] = []
        for node in nodes[:limit]:
            ok, text = self.get_node_details_text(node.path())
            if ok:
                lines.append(text)
                lines.append("")
        
        if len(nodes) > limit:
            lines.append(f"(showing first {limit} nodes, total selected {len(nodes)})")
        
        return True, "\n".join(lines)

    # ========================================
    # nodesearch (usecache)
    # ========================================
    
    def _get_node_types_index(self) -> Dict[str, List[Tuple[str, str, str]]]:
        """getnodetypeindex (withcache)
        
        return: {category_lower: [(type_name, description, full_path), ...]}
        """
        import time as _time
        cache_duration = 300  # 5-minute cache
        
        if (HoudiniMCP._node_types_cache is not None and 
            _time.time() - HoudiniMCP._node_types_cache_time < cache_duration):
            return HoudiniMCP._node_types_cache
        
        if hou is None:
            return {}
        
        index: Dict[str, List[Tuple[str, str, str]]] = {}
        try:
            for cat_name, cat in hou.nodeTypeCategories().items():
                cat_lower = cat_name.lower()
                index[cat_lower] = []
                for type_name, node_type in cat.nodeTypes().items():
                    try:
                        desc = node_type.description()
                        index[cat_lower].append((type_name, desc, f"{cat_lower}/{type_name}"))
                    except Exception:
                        continue
            
            HoudiniMCP._node_types_cache = index
            HoudiniMCP._node_types_cache_time = _time.time()
        except Exception:
            pass
        
        return index
    
    def search_nodes(self, keyword: str, limit: int = 12) -> Tuple[bool, str]:
        """searchnodetype (usecache)"""
        if hou is None:
            return False, "Houdini API not detected"
        if not keyword:
            return False, "Please enter a keyword"
        
        kw = keyword.lower()
        matches: List[str] = []
        
        # usecache nodetypeindex
        index = self._get_node_types_index()
        for cat_name, types in index.items():
            for type_name, desc, full_path in types:
                if kw in full_path.lower() or kw in desc.lower():
                    matches.append(f"- `{full_path}` — {desc}")
        
        if not matches:
            return False, f"No match found containing '{keyword}' node types"
        
        if len(matches) > limit:
            extra = len(matches) - limit
            matches = matches[:limit] + [f"… {extra} more"]
        
        return True, "\n".join(matches)

    def semantic_search_nodes(self, description: str, category: str = "sop") -> Tuple[bool, str]:
        """semanticsearchnode - viaselfthenlanguagedescriptionfindtomergesuit node
        
        built-incommonusenode semanticmapping
        """
        if hou is None:
            return False, "Houdini API not detected"
        
        # Semantic mapping: description keyword -> node type list
        # Format: "keyword": ["node1", "node2", ...]
        semantic_map = {
            # Point operations
            "scatter": ["scatter", "pointsfromvolume"],
            "random point": ["scatter", "add"],
            "delete point": ["blast", "delete"],
            "merge point": ["fuse"],
            "point cloud": ["scatter"],

            # Copy operations
            "copy to point": ["copytopoints"],
            "instance": ["copytopoints"],
            "clone": ["copytopoints"],
            "copy object": ["copytopoints"],

            # Deform operations
            "noise": ["mountain", "attribnoise"],
            "deform": ["transform", "bend", "twist"],
            "smooth": ["smooth", "relax"],
            "extrude": ["polyextrude"],
            "subdivide": ["subdivide", "remesh"],

            # Geometry creation
            "box": ["box"],
            "sphere": ["sphere"],
            "tube": ["tube"],
            "cylinder": ["tube"],
            "grid": ["grid"],
            "plane": ["grid"],
            "curve": ["curve", "line"],

            # ⭐ Terrain-related (common request; detailed mapping)
            "terrain": ["grid", "mountain"],     # terrain = grid + mountain
            "ground": ["grid"],
            "mountain": ["mountain"],
            "hills": ["mountain"],
            "heightfield": ["heightfield"],

            # Attribute operations
            "set attribute": ["attribwrangle"],
            "color": ["color", "attribwrangle"],
            "normal": ["normal"],
            "UV": ["uvproject", "uvunwrap"],

            # Connect operations
            "merge": ["merge"],
            "split": ["split", "blast"],
            "boolean": ["boolean"],

            # Simulation-related
            "rigid body": ["rbdmaterialfracture"],
            "fracture": ["voronoifracture"],
            "fluid": ["flip", "pyro"],
            "cloth": ["vellum"],
            "hair": ["hairgen"],
        }
        
        desc_lower = description.lower()
        results = []
        scores = {}
        
        # matchsemanticmapping
        for keywords, nodes in semantic_map.items():
            if any(k in desc_lower for k in keywords.split()):
                for node in nodes:
                    if node not in scores:
                        scores[node] = 0
                    scores[node] += 1
        
        # getmatch nodeDetails
        cat_filter = category.lower() if category != "all" else None
        
        for node_name in sorted(scores.keys(), key=lambda x: -scores[x])[:10]:
            for cat_name, cat in hou.nodeTypeCategories().items():
                if cat_filter and cat_name.lower() != cat_filter:
                    continue
                for type_name, node_type in cat.nodeTypes().items():
                    if node_name in type_name.lower():
                        desc = node_type.description()
                        results.append(f"- `{cat_name.lower()}/{type_name}` — {desc}")
                        break
        
        # ifsemanticmatchnotfindto, trydirectlykeywordsearch
        if not results:
            for cat_name, cat in hou.nodeTypeCategories().items():
                if cat_filter and cat_name.lower() != cat_filter:
                    continue
                for type_name, node_type in cat.nodeTypes().items():
                    desc = node_type.description().lower()
                    if any(w in desc or w in type_name.lower() for w in desc_lower.split()):
                        results.append(f"- `{cat_name.lower()}/{type_name}` — {node_type.description()}")
                        if len(results) >= 10:
                            break
                if len(results) >= 10:
                    break
        
        if results:
            result_text = f"based on '{description}' findtoor lessnode:\n" + "\n".join(results[:10])
            return True, result_text
        
        return False, f"No match for '{description}'  node"

    def list_children(self, network_path: Optional[str] = None, 
                      recursive: bool = False, 
                      show_flags: bool = True) -> Tuple[bool, str]:
        """columnoutsubnode"""
        if hou is None:
            return False, "Houdini API not detected"
        
        if network_path:
            network = hou.node(network_path)
            if not network:
                return False, f"Network not found: {network_path}"
        else:
            network = self._current_network()
            if not network:
                return False, "Current network not found"
        
        def format_node(node, indent=0):
            prefix = "  " * indent
            flags = ""
            if show_flags:
                parts = []
                if hasattr(node, 'isDisplayFlagSet') and node.isDisplayFlagSet():
                    parts.append("[disp]")
                if hasattr(node, 'isRenderFlagSet') and node.isRenderFlagSet():
                    parts.append("🎬")
                if hasattr(node, 'isBypassed') and node.isBypassed():
                    parts.append("⏸")
                if parts:
                    flags = f" [{' '.join(parts)}]"
            
            node_type = node.type().name() if node.type() else "unknown"
            return f"{prefix}- {node.name()} ({node_type}){flags}"
        
        lines = [f"## {network.path()}"]
        
        def list_nodes(parent, indent=0):
            for child in parent.children():
                lines.append(format_node(child, indent))
                if recursive and hasattr(child, 'children') and child.children():
                    list_nodes(child, indent + 1)
        
        list_nodes(network)
        
        if len(lines) == 1:
            lines.append(" (emptynetwork)")
        
        return True, "\n".join(lines)

    def get_geometry_info(self, node_path: str, output_index: int = 0) -> Tuple[bool, str]:
        """getgeometryinfo"""
        if hou is None:
            return False, "Houdini API not detected"
        
        node = hou.node(node_path)
        if not node:
            return False, f"Not foundNode: {node_path}"
        
        try:
            geo = node.geometry()
            if not geo:
                return False, f"node {node_path} has no geometry output"
            
            info = {
                "pointcount": geo.intrinsicValue("pointcount"),
                "vertexcount": geo.intrinsicValue("vertexcount"),
                "diagrammetadatacount": geo.intrinsicValue("primitivecount"),
            }
            
            # pointattributes
            point_attrs = [f"{a.name()} ({a.dataType().name()})" for a in geo.pointAttribs()]
            # vertexattributes
            vertex_attrs = [f"{a.name()} ({a.dataType().name()})" for a in geo.vertexAttribs()]
            # diagrammetadataattributes
            prim_attrs = [f"{a.name()} ({a.dataType().name()})" for a in geo.primAttribs()]
            # globalattributes
            detail_attrs = [f"{a.name()} ({a.dataType().name()})" for a in geo.globalAttribs()]
            
            lines = [
                f"## geometryinfo: {node_path}",
                f"- Points: {info['pointcount']}",
                f"- topPoints: {info['vertexcount']}",
                f"- diagrammetadatacount: {info['diagrammetadatacount']}",
                "",
                "### attributes",
            ]
            
            if point_attrs:
                lines.append(f"pointattributes: {', '.join(point_attrs)}")
            if vertex_attrs:
                lines.append(f"vertexattributes: {', '.join(vertex_attrs)}")
            if prim_attrs:
                lines.append(f"diagrammetadataattributes: {', '.join(prim_attrs)}")
            if detail_attrs:
                lines.append(f"globalattributes: {', '.join(detail_attrs)}")
            
            if not any([point_attrs, vertex_attrs, prim_attrs, detail_attrs]):
                lines.append(" (nocustomattributes)")
            
            return True, "\n".join(lines)
        except Exception as e:
            return False, f"Failed to fetch geometry info: {str(e)}"

    def set_display_flag(self, node_path: str, display: bool = True, 
                         render: bool = True) -> Tuple[bool, str]:
        """setdisplay/renderflag"""
        if hou is None:
            return False, "Houdini API not detected"
        
        node = hou.node(node_path)
        if not node:
            return False, f"Not foundNode: {node_path}"
        
        try:
            if display and hasattr(node, 'setDisplayFlag'):
                node.setDisplayFlag(True)
            if render and hasattr(node, 'setRenderFlag'):
                node.setRenderFlag(True)
            
            flags = []
            if display:
                flags.append("display")
            if render:
                flags.append("render")
            
            return True, f"Set {node.name()} as{'/'.join(flags)}node"
        except Exception as e:
            return False, f"Failed to set flag: {str(e)}"

    def copy_node(self, source_path: str, dest_network: Optional[str] = None,
                  new_name: Optional[str] = None) -> Tuple[bool, str]:
        """copynode"""
        if hou is None:
            return False, "Houdini API not detected"
        
        source = hou.node(source_path)
        if not source:
            return False, f"Not foundSource node: {source_path}"
        
        if dest_network:
            dest = hou.node(dest_network)
            if not dest:
                return False, f"Not foundtargetnetwork: {dest_network}"
        else:
            dest = source.parent()
        
        try:
            new_node = hou.copyNodesTo([source], dest)[0]
            if new_name:
                new_node.setName(new_name)
            new_node.moveToGoodPosition()
            return True, f"alreadycopynodeto: {new_node.path()}"
        except Exception as e:
            return False, f"copyFailed: {str(e)}"

    def batch_set_parameters(self, node_paths: List[str], param_name: str, 
                             value: Any) -> Tuple[bool, str]:
        """batchsetparameter"""
        if hou is None:
            return False, "Houdini API not detected"
        
        success = []
        failed = []
        
        for path in node_paths:
            node = hou.node(path)
            if not node:
                failed.append(f"{path}: Not found")
                continue
            
            parm = node.parm(param_name)
            if not parm:
                parm_tuple = node.parmTuple(param_name)
                if parm_tuple and isinstance(value, (list, tuple)):
                    try:
                        parm_tuple.set(value)
                        success.append(node.name())
                    except Exception as e:
                        failed.append(f"{node.name()}: {e}")
                else:
                    failed.append(f"{node.name()}: noparameter {param_name}")
                continue
            
            try:
                parm.set(value)
                success.append(node.name())
            except Exception as e:
                failed.append(f"{node.name()}: {e}")
        
        msg = f"modifySuccess: {len(success)} nodes"
        if failed:
            msg += f"\nFailed: {'; '.join(failed)}"
        
        return len(success) > 0, msg

    def find_nodes_by_param(self, param_name: str, value: Any = None,
                            network_path: Optional[str] = None,
                            recursive: bool = True) -> Tuple[bool, str]:
        """byparametervaluesearchnode"""
        if hou is None:
            return False, "Houdini API not detected"
        
        if network_path:
            network = hou.node(network_path)
            if not network:
                return False, f"Network not found: {network_path}"
        else:
            network = self._current_network() or hou.node('/obj')
        
        results = []
        
        def search_in(parent):
            for node in parent.children():
                parm = node.parm(param_name)
                if parm:
                    parm_value = parm.eval()
                    if value is None or str(parm_value) == str(value):
                        results.append(f"- {node.path()}: {param_name}={parm_value}")
                if recursive and hasattr(node, 'children'):
                    search_in(node)
        
        search_in(network)
        
        if results:
            header = f"findto {len(results)} nodespackagecontainingparameter '{param_name}'"
            if value is not None:
                header += f" = {value}"
            return True, header + ":\n" + "\n".join(results[:50])
        
        return False, f"No match found containingparameter '{param_name}'  node"

    def save_hip(self, file_path: Optional[str] = None) -> Tuple[bool, str]:
        """save HIP file"""
        if hou is None:
            return False, "Houdini API not detected"
        
        try:
            if file_path:
                hou.hipFile.save(file_path)
                return True, f"Savedto: {file_path}"
            else:
                hou.hipFile.save()
                return True, f"Saved: {hou.hipFile.path()}"
        except Exception as e:
            return False, f"saveFailed: {str(e)}"

    def undo_redo(self, action: str) -> Tuple[bool, str]:
        """undo/redo"""
        if hou is None:
            return False, "Houdini API not detected"
        
        try:
            if action == "undo":
                hou.undos.performUndo()
                return True, "Undone"
            elif action == "redo":
                hou.undos.performRedo()
                return True, "alreadyredo"
            else:
                return False, f"notknowoperation: {action}"
        except Exception as e:
            return False, f"operationFailed: {str(e)}"

    def search_documentation(self, node_type: str, category: str = "sop") -> Tuple[bool, str]:
        """querynodedocument"""
        if requests is None:
            return False, "requests modulenotinstall"
        
        base_url = "https://www.sidefx.com/docs/houdini/nodes"
        doc_node_type = node_type.replace("::", "--")
        doc_url = f"{base_url}/{category}/{doc_node_type}.html"
        
        settings = read_settings()
        tries = max(1, settings.request_retries + 1)
        
        for _ in range(tries):
            try:
                response = requests.get(doc_url, timeout=settings.request_timeout)
                if response.status_code == 404:
                    return False, f"Not founddocument: {category}/{node_type}"
                response.raise_for_status()
                
                content = response.text
                title_match = re.search(r'<title>(.*?)</title>', content, re.IGNORECASE)
                title = title_match.group(1) if title_match else f"{node_type} node"
                
                summary = ""
                summary_match = re.search(r'<div[^>]*class="[^"]*summary[^"]*"[^>]*>(.*?)</div>', content, re.DOTALL | re.IGNORECASE)
                if summary_match:
                    summary = re.sub(r'<[^>]+>', '', summary_match.group(1)).strip()
                
                result = f"## {title}\n\n**documentlink**: {doc_url}\n\n"
                if summary:
                    result += f"**description**: {summary}\n"
                
                return True, result
            except Exception as e:
                time.sleep(settings.request_backoff)
        
        return False, f"queryFailed: {doc_url}"

    # ========================================
    # Wrangle nodecreate (VEX preferred)
    # ========================================
    
    def create_wrangle_node(self, vex_code: str, 
                            wrangle_type: str = "attribwrangle",
                            node_name: Optional[str] = None,
                            run_over: str = "Points",
                            parent_path: Optional[str] = None) -> Tuple[bool, str]:
        """create Wrangle nodeandset VEX code
        
        thisisresolvedecidegeometryprocessissue firstselectway. 
        
        Args:
            vex_code: VEX code
            wrangle_type: Wrangle type, default attribwrangle
            node_name: nodename (options)
            run_over: runmode (Points/Vertices/Primitives/Detail)
            parent_path: parentnetwork path (options)
        
        Returns:
            (success, message)
        """
        if hou is None:
            return False, "Houdini API not detected"
        
        if not vex_code or not vex_code.strip():
            return False, "VEX codeis empty"
        
        # getparentnetwork
        if parent_path:
            network = hou.node(parent_path)
            if network is None:
                return False, f"Not foundparentnetwork: {parent_path}"
        else:
            network = self._current_network()
            if network is None:
                return False, "Current network not found"
        
        # verify wrangle type
        valid_types = ["attribwrangle", "pointwrangle", "primitivewrangle", 
                       "volumewrangle", "vertexwrangle"]
        if wrangle_type not in valid_types:
            wrangle_type = "attribwrangle"
        
        # ensureincorrect networklayerlevel
        network = self._ensure_target_network(network, self._category_from_hint("sop"))
        
        # createnode
        safe_name = self._sanitize_node_name(node_name)
        
        try:
            # based ondocument, use force_valid_node_name=True autoprocessinvalidnodename
            new_node = network.createNode(
                wrangle_type,
                safe_name,
                run_init_scripts=True,
                load_contents=True,
                exact_type_name=False,  # allowfuzzymatch
                force_valid_node_name=True  # autocleanupinvalidnodename
            )
        except Exception as exc:
            return False, f"create Wrangle nodeFailed: {exc}"
        
        # set VEX code
        try:
            # largemulticount Wrangle node codeparameternameis "snippet"
            snippet_parm = new_node.parm("snippet")
            if snippet_parm:
                snippet_parm.set(vex_code)
            else:
                # somenodemayuse "code" or "vexcode"
                for parm_name in ["code", "vexcode", "vex_code"]:
                    parm = new_node.parm(parm_name)
                    if parm:
                        parm.set(vex_code)
                        break
        except Exception as exc:
            return False, f"set VEX codeFailed: {exc}"
        
        # setrunmode (with Houdini Attrib Wrangle parm("class") menusingleconsistent: 0=Detail, 1=Primitives, 2=Points, 3=Vertices, 4=Numbers)
        run_over_map = {
            "Detail": 0,
            "Primitives": 1,
            "Points": 2,
            "Vertices": 3,
            "Numbers": 4,
        }
        run_over_value = run_over_map.get(run_over, 2)  # default Points
        
        try:
            class_parm = new_node.parm("class")
            if class_parm:
                class_parm.set(run_over_value)
        except Exception:
            pass  # some wrangle typemaynotclass parameter
        
        # layoutandselect
        new_node.moveToGoodPosition()
        new_node.setSelected(True, clear_all_selected=True)
        
        try:
            new_node.setDisplayFlag(True)
            new_node.setRenderFlag(True)
        except Exception:
            pass
        
        try:
            editor = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.NetworkEditor)
            if editor:
                editor.homeToSelection()
        except Exception:
            pass
        
        # checkwhetherhascompileerror
        errors = []
        try:
            node_errors = new_node.errors()
            if node_errors:
                errors = list(node_errors)
        except Exception:
            pass
        
        if errors:
            return True, f"Created Wrangle Node: {new_node.path()}\nVEX compilewarning: {'; '.join(errors)}"
        
        return True, f"Created Wrangle Node: {new_node.path()}"

    # ========================================
    # nodecreate
    # ========================================
    
    def create_node(self, type_hint: str, node_name: Optional[str] = None, 
                    parameters: Optional[Dict[str, Any]] = None,
                    parent_path: Optional[str] = None) -> Tuple[bool, str]:
        """createsinglenode"""
        if hou is None:
            return False, "Houdini API not detected"
        
        # getparentnetwork
        if parent_path:
            network = hou.node(parent_path)
            if network is None:
                return False, f"Not foundparentnetwork: {parent_path}"
        else:
            network = self._current_network()
            if network is None:
                # tryusedefaultnetwork
                try:
                    network = hou.node('/obj')
                    if network is None:
                        return False, "Current network not found, andnomethodaccessdefaultnetwork /obj. pleaseensureHoudinialreadycorrectstart, orinnetworkedit inopenonenetwork. "
                except Exception:
                    return False, "Current network not found, andnomethodaccessdefaultnetwork. pleaseensureHoudinialreadycorrectstart, orinnetworkedit inopenonenetwork. "
        
        if not type_hint:
            return False, "notraisefornodetype"
        
        # based ondocument, createNode candirectlyprocessnodetypematch, noneedspre-firstparse
        # butIsneedsensurenetworktypecorrect
        desired_cat = self._desired_category_from_hint(type_hint, network)
        if desired_cat is None:
            # If unable to recognize category, try to infer from node type (common SOP nodes)
            common_sop_nodes = ['box', 'sphere', 'grid', 'tube', 'line', 'circle', 'noise', 'mountain', 
                              'scatter', 'copytopoints', 'attribwrangle', 'pointwrangle', 'primitivewrangle',
                              'delete', 'blast', 'fuse', 'transform', 'subdivide', 'remesh']
            if type_hint.lower() in common_sop_nodes:
                # thisisoneSOPnode, needsSOPnetwork
                desired_cat = hou.sopNodeTypeCategory()
            else:
                # ifnomethodrecognizecategory, tryusecurrentnetwork category
                desired_cat = network.childTypeCategory() if network else None
                if desired_cat is None:
                    return False, f"nomethodrecognizenodecategory: {type_hint}"
        
        # ensuretargetnetworktypecorrect (willautocreatecontain )
        network = self._ensure_target_network(network, desired_cat)
        if network is None:
            return False, f"nomethodgetorcreatetargetnetwork: {type_hint}"
        
        # cleanupnodename (butkeeporiginalvalueused forerrorHint)
        safe_name = self._sanitize_node_name(node_name)
        
        # based ondocument, createNode supportor lessparameter: 
        # createNode(node_type_name, node_name=None, run_init_scripts=True, 
        #            load_contents=True, exact_type_name=False, force_valid_node_name=False)
        # 
        # Isuse force_valid_node_name=True let Houdini autoprocessinvalidnodename
        # use exact_type_name=False (default)let Houdini enterrowfuzzymatch
        
        try:
            # directlyuse createNode, letitselfselfprocesstypematch
            # if node_name invalid, force_valid_node_name=True willautocleanup
            new_node = network.createNode(
                type_hint,  # directlypassoriginaltypename, let Houdini processmatch
                safe_name,  # ifas None, Houdini willautogeneratename
                run_init_scripts=True,
                load_contents=True,
                exact_type_name=False,  # allowfuzzymatch
                force_valid_node_name=True  # autocleanupinvalidnodename
            )
        except hou.OperationFailed as exc:
            # raiseformoredetailfine errorinfo
            error_detail = str(exc)
            current_cat = network.childTypeCategory() if network else None
            cat_name = current_cat.name().lower() if current_cat else "unknown"
            network_path = network.path() if network else "unknown"
            
            # tryraiseforSuggestion
            suggestions = []
            try:
                if current_cat:
                    node_types = list(current_cat.nodeTypes().keys())
                    hint_lower = type_hint.lower()
                    for nt in node_types:
                        if hint_lower in nt.lower() or nt.lower() in hint_lower:
                            suggestions.append(nt)
                            if len(suggestions) >= 5:
                                break
            except Exception:
                pass
            
            error_msg = f"createnodeFailed: {type_hint}\n"
            error_msg += f"errorDetails: {error_detail}\n"
            error_msg += f"currentnetwork: {network_path} (category: {cat_name})"
            if suggestions:
                error_msg += f"\nSuggestion Node type: {', '.join(suggestions[:5])}"
            return False, error_msg
        except Exception as exc:
            import traceback
            error_detail = str(exc)
            network_path = network.path() if network else "unknown" if network else "None"
            error_msg = f"createnodeFailed: {type_hint}\n"
            error_msg += f"error: {error_detail}\n"
            error_msg += f"network: {network_path}"
            # onlyindebugwhenoutputcompletetraceback
            if "DEBUG" in os.environ:
                error_msg += f"\n{traceback.format_exc()}"
            return False, error_msg
        
        # setparameter
        if parameters and isinstance(parameters, dict):
            for parm_name, parm_value in parameters.items():
                parm = new_node.parm(parm_name)
                if parm is None:
                    parm_tuple = new_node.parmTuple(parm_name)
                    if parm_tuple and isinstance(parm_value, (list, tuple)):
                        try:
                            parm_tuple.set(parm_value)
                        except Exception:
                            pass
                    continue
                try:
                    parm.set(parm_value)
                except Exception:
                    continue
        
        new_node.moveToGoodPosition()
        new_node.setSelected(True, clear_all_selected=True)
        
        try:
            editor = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.NetworkEditor)
            if editor:
                editor.homeToSelection()
        except Exception:
            pass
        
        # returnNode path + diff info (let AI resolvechangeization)
        node_path = new_node.path()
        diff_parts = [f"✓{node_path}"]
        try:
            parent = new_node.parent()
            if parent:
                siblings = len(parent.children())
                diff_parts.append(f"(parentnetwork: {parent.path()}, subsectionPoints: {siblings})")
            # inputconnectinfo
            inputs = new_node.inputs()
            if inputs:
                connected = [n.path() for n in inputs if n is not None]
                if connected:
                    diff_parts.append(f"Inputs: {', '.join(connected)}")
        except Exception:
            pass
        return True, ' '.join(diff_parts)

    def create_network(self, plan: Dict[str, Any]) -> Tuple[bool, str]:
        """batchcreatenodenetwork"""
        if hou is None:
            return False, "Houdini API not detected"
        
        network = self._current_network()
        if network is None:
            return False, "Current network not found"
        
        node_specs = plan.get("nodes") if isinstance(plan, dict) else None
        if not node_specs:
            return False, "missing nodes field"
        
        created: Dict[str, Any] = {}
        creation_order: List[str] = []
        messages: List[str] = []
        
        try:
            # detectwhetherneedsautocreatecontain 
            current_cat = network.childTypeCategory()
            current_cat_name = current_cat.name().lower() if current_cat else ""
            
            has_sop_node = any(
                isinstance(spec, dict) and 
                str(spec.get("type", "")).lower().startswith("sop/")
                for spec in node_specs
            )
            
            if has_sop_node and current_cat_name.startswith("object"):
                try:
                    # based ondocument, directlyuse createNode, letitselfselfprocessmatch
                    auto_container = network.createNode(
                        "geo",
                        None,  # let Houdini autogeneratename
                        run_init_scripts=True,
                        load_contents=True,
                        exact_type_name=False,
                        force_valid_node_name=True
                    )
                    auto_container.moveToGoodPosition()
                    messages.append(f"autocreatecontain : {auto_container.name()}")
                    network = auto_container
                except Exception as exc:
                    messages.append(f"createcontain Failed: {exc}")
            
            # createnode
            for idx, spec in enumerate(node_specs):
                if not isinstance(spec, dict):
                    continue
                
                node_id = spec.get("id") or spec.get("name") or f"node_{idx+1}"
                type_hint = spec.get("type") or spec.get("node_type")
                
                if not type_hint:
                    messages.append(f"[{node_id}] missing type")
                    continue
                
                # based ondocument, createNode candirectlyprocessnodetypematch
                desired_cat = self._desired_category_from_hint(type_hint, network)
                if desired_cat is None:
                    # ifnomethodrecognizecategory, tryusecurrentnetwork category
                    desired_cat = network.childTypeCategory() if network else None
                    if desired_cat is None:
                        messages.append(f"[{node_id}] nomethodrecognizecategory: {type_hint}")
                        continue
                
                network = self._ensure_target_network(network, desired_cat)
                
                node_name = spec.get("name")
                safe_name = self._sanitize_node_name(node_name)
                
                # directlyuse createNode, letitselfselfprocesstypematch
                try:
                    new_node = network.createNode(
                        type_hint,  # directlypassoriginaltypename
                        safe_name,
                        run_init_scripts=True,
                        load_contents=True,
                        exact_type_name=False,  # allowfuzzymatch
                        force_valid_node_name=True  # autocleanupinvalidnodename
                    )
                except hou.OperationFailed as exc:
                    messages.append(f"[{node_id}] createFailed: {type_hint} - {exc}")
                    continue
                except Exception as exc:
                    messages.append(f"[{node_id}] createFailed: {exc}")
                    continue
                
                # setparameter
                params = spec.get("parameters") or spec.get("parms", {})
                if isinstance(params, dict):
                    for parm_name, parm_value in params.items():
                        parm = new_node.parm(parm_name)
                        if parm is None:
                            continue
                        try:
                            parm.set(parm_value)
                        except Exception:
                            pass
                
                created[node_id] = new_node
                creation_order.append(node_id)
            
            # Connect
            connections = plan.get("connections", [])
            for conn in connections:
                if not isinstance(conn, dict):
                    continue
                
                src_id = conn.get("from") or conn.get("src")
                dst_id = conn.get("to") or conn.get("dst")
                input_index = int(conn.get("input", 0))
                
                src_node = created.get(src_id)
                dst_node = created.get(dst_id)
                
                if src_node and dst_node:
                    try:
                        dst_node.setInput(input_index, src_node)
                    except Exception as exc:
                        messages.append(f"connectFailed {src_id}->{dst_id}: {exc}")
            
            # autolayout
            if created:
                network.layoutChildren()
                if creation_order:
                    last_node = created[creation_order[-1]]
                    last_node.setSelected(True, clear_all_selected=True)
                    try:
                        last_node.setDisplayFlag(True)
                        last_node.setRenderFlag(True)
                    except Exception:
                        pass
            
            summary = ", ".join(created[nid].path() for nid in creation_order if nid in created)
            if created:
                msg = f"Created {len(created)} nodes: {summary}"
                if messages:
                    msg += f"\nnote: {'; '.join(messages)}"
                return True, msg
            
            return False, "notcreateanynode"
        except Exception as exc:
            # Rollback: delete the created node to keep the scene clean
            if created:
                _dbg(f"[MCP Client] Network creation error, rolling back {len(created)} created node(s)...")
                for nid in reversed(creation_order):
                    try:
                        node = created.get(nid)
                        if node and node.path():
                            node.destroy()
                    except Exception:
                        pass
            return False, f"createnetworkFailed (alreadybackscroll): {exc}"

    # ========================================
    # nodeconnect
    # ========================================
    
    def connect_nodes(self, output_node_path: str, input_node_path: str, 
                      input_index: int = 0) -> Tuple[bool, str]:
        """connecttwonode"""
        if hou is None:
            return False, "Houdini API not detected"
        
        out_node = hou.node(output_node_path)
        if out_node is None:
            return False, f"Not foundoutputNode: {output_node_path}"
        
        in_node = hou.node(input_node_path)
        if in_node is None:
            return False, f"Not foundinputNode: {input_node_path}"
        
        try:
            in_node.setInput(int(input_index), out_node, 0)
            return True, f"alreadyconnect: {output_node_path} → {input_node_path}[{input_index}]"
        except Exception as exc:
            return False, f"connectFailed: {exc}"

    # ========================================
    # parameterset
    # ========================================
    
    def set_parameter(self, node_path: str, param_name: str, value: Any) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """setNode parameters (setpreviousautosnapshotoldvalue, supportundo)
        
        Returns:
            (success, message, undo_snapshot)
            undo_snapshot packagecontaining node_path, param_name, old_value, new_value
        """
        if hou is None:
            return False, "Houdini API not detected", None
        
        node = hou.node(node_path)
        if node is None:
            return False, f"Not foundNode: {node_path}", None
        
        # trygetparameter
        parm = node.parm(param_name)
        if parm is None:
            # tryastupleparameter
            parm_tuple = node.parmTuple(param_name)
            if parm_tuple is None:
                # List similar parameter names to help the AI self-correct
                try:
                    all_parms = [p.name() for p in node.parms()]
                    hint_lower = param_name.lower()
                    similar = [p for p in all_parms if hint_lower in p.lower() or p.lower() in hint_lower][:8]
                    err = f"node {node_path} does not existparameter '{param_name}'"
                    if similar:
                        err += f"\nsimilarparameter: {', '.join(similar)}"
                    else:
                        # columnoutprevious 15 parameterforreference
                        sample = all_parms[:15]
                        err += f"\nthisnodecanuseparameter(previous15): {', '.join(sample)}"
                        if len(all_parms) > 15:
                            err += f" ... of {len(all_parms)} "
                except Exception:
                    err = f"Not foundparameter: {param_name}"
                return False, err, None
            
            if isinstance(value, (list, tuple)):
                try:
                    # snapshotoldvalue (tupleparameter)
                    old_value = list(parm_tuple.eval())
                    parm_tuple.set(value)
                    new_value = list(parm_tuple.eval())
                    snapshot = {
                        "node_path": node_path,
                        "param_name": param_name,
                        "old_value": old_value,
                        "new_value": new_value,
                        "is_tuple": True,
                    }
                    return True, f"Set {node_path} {param_name}: {old_value} → {new_value}", snapshot
                except Exception as exc:
                    return False, f"setFailed: {exc}", None
            else:
                return False, f"parameter {param_name} needslistortuplevalue", None
        
        try:
            # snapshotoldvalue (markerquantityparameter)
            try:
                old_expr = parm.expression()
                old_lang = str(parm.expressionLanguage())
                old_value = {"expr": old_expr, "lang": old_lang}
            except Exception:
                old_value = parm.eval()
            
            parm.set(value)
            actual_value = parm.eval()
            snapshot = {
                "node_path": node_path,
                "param_name": param_name,
                "old_value": old_value,
                "new_value": actual_value,
                "is_tuple": False,
            }
            return True, f"Set {node_path} {param_name}: {old_value} → {actual_value}", snapshot
        except Exception as exc:
            return False, f"setFailed: {exc}", None

    # ========================================
    # nodedelete
    # ========================================
    
    @staticmethod
    def _snapshot_node(node, _depth: int = 0) -> Optional[Dict[str, Any]]:
        """indeleteprevioussnapshotnodestatus (used forundorebuild)
        
        ★ recursivesnapshot: autosaveallsubnodetree, ensuredeleteparentnodeaftercancompleterestore. 
        
        Args:
            node: needsnapshot  Houdini node
            _depth: recursivedepth (withinpartuse, preventnolimitrecursive)
        
        Returns:
            Snapshot dict containing all info needed to rebuild the node and its full subtree; None on failure.
        """
        if _depth > 20:  # Prevent deeply nested structures from causing a stack overflow
            return None
        try:
            node_type = node.type()
            parent = node.parent()
            if not node_type or not parent:
                return None
            
            # basethisinfo
            snapshot: Dict[str, Any] = {
                "parent_path": parent.path(),
                "node_type": node_type.name(),
                "node_name": node.name(),
                "position": [node.position()[0], node.position()[1]],
            }
            
            # notdefaultparametervalue
            params = {}
            try:
                for parm in node.parms():
                    try:
                        # skiplocked/notcanwriteparameter
                        if parm.isLocked():
                            continue
                        # onlysavewithdefaultdifferent parameter
                        default = parm.parmTemplate().defaultValue()
                        current = parm.eval()
                        # tableexpressionpreferredsave
                        try:
                            expr = parm.expression()
                            if expr:
                                params[parm.name()] = {"expr": expr, "lang": str(parm.expressionLanguage())}
                                continue
                        except Exception:
                            pass
                        # Use float tolerance when comparing floats
                        if isinstance(current, float) and isinstance(default, (float, int)):
                            if abs(current - float(default)) > 1e-9:
                                params[parm.name()] = current
                        elif current != default:
                            params[parm.name()] = current
                    except Exception:
                        continue
            except Exception:
                pass
            snapshot["params"] = params
            
            # inputconnect
            input_connections = []
            try:
                for i, conn in enumerate(node.inputs()):
                    if conn is not None:
                        input_connections.append({
                            "input_index": i,
                            "source_path": conn.path(),
                        })
            except Exception:
                pass
            snapshot["input_connections"] = input_connections
            
            # outputconnect
            output_connections = []
            try:
                for conn in node.outputConnections():
                    output_connections.append({
                        "output_index": conn.outputIndex(),
                        "dest_path": conn.outputNode().path() if conn.outputNode() else "",
                        "dest_input_index": conn.inputIndex(),
                    })
            except Exception:
                pass
            snapshot["output_connections"] = output_connections
            
            # flagbit
            try:
                snapshot["display_flag"] = node.isDisplayFlagSet() if hasattr(node, 'isDisplayFlagSet') else False
                snapshot["render_flag"] = node.isRenderFlagSet() if hasattr(node, 'isRenderFlagSet') else False
            except Exception:
                snapshot["display_flag"] = False
                snapshot["render_flag"] = False
            
            # ★ recursivesnapshotsubnodetree — ensuredeleteparentnodeaftercancompleterestoresubnode
            children_snapshots = []
            try:
                children = node.children()
                if children:
                    for child in children:
                        try:
                            child_snap = HoudiniMCP._snapshot_node(child, _depth + 1)
                            if child_snap:
                                children_snapshots.append(child_snap)
                        except Exception:
                            continue
            except Exception:
                pass
            if children_snapshots:
                snapshot["children"] = children_snapshots
            
            # ★ Snapshot connections between sub-nodes (sibling-node connections)
            # externalconnectalreadyineachsubnode  input_connections / output_connections inrecord, 
            # butrestorewhensubnodeisone by onecreate , withinpartconnectneedsinallsubnodecreatefinishfinishaftersingleindependentrestore. 
            internal_connections = []
            try:
                if children:
                    child_paths = set(c.path() for c in children)
                    for child in children:
                        try:
                            for i, inp in enumerate(child.inputs()):
                                if inp is not None and inp.path() in child_paths:
                                    internal_connections.append({
                                        "src_name": inp.name(),
                                        "dest_name": child.name(),
                                        "dest_input": i,
                                    })
                        except Exception:
                            continue
            except Exception:
                pass
            if internal_connections:
                snapshot["internal_connections"] = internal_connections
            
            return snapshot
        except Exception:
            return None

    def delete_node_by_path(self, node_path: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """bypathdeletenode (deletepreviousautosnapshot, supportundorebuild)
        
        Returns:
            (success, message, undo_snapshot)
        """
        if hou is None:
            return False, "Houdini API not detected", None
        
        node = hou.node(node_path)
        if node is None:
            return False, f"Not foundNode: {node_path}", None
        
        try:
            # deleteprevioussnapshot (used forundo)
            snapshot = self._snapshot_node(node)
            
            full_path = node.path()
            name = node.name()
            parent = node.parent()
            parent_path = parent.path() if parent else ""
            
            # collectsetconnectinfo (deleteprevious)
            input_nodes = [n.path() for n in node.inputs() if n is not None] if node.inputs() else []
            output_conns = []
            try:
                for conn in node.outputConnections():
                    out_node = conn.outputNode()
                    if out_node:
                        output_conns.append(out_node.path())
            except Exception:
                pass
            
            node.destroy()
            
            # returncompletepath + diff info
            diff_parts = [f"DeletedNode: {full_path}"]
            if parent_path:
                try:
                    remaining = len(hou.node(parent_path).children()) if hou.node(parent_path) else 0
                    diff_parts.append(f"(parentnetwork: {parent_path}, remainingsubNode: {remaining})")
                except Exception:
                    diff_parts.append(f"(parentnetwork: {parent_path})")
            if input_nodes:
                diff_parts.append(f"originalInputs: {', '.join(input_nodes)}")
            if output_conns:
                diff_parts.append(f"originaloutputto: {', '.join(output_conns[:3])}")
            
            return True, ' '.join(diff_parts), snapshot
        except Exception as exc:
            return False, f"deleteFailed: {exc}", None

    def delete_selected(self) -> Tuple[bool, str]:
        """deleteselected node"""
        if hou is None:
            return False, "Houdini API not detected"
        
        nodes = list(hou.selectedNodes())
        if not nodes:
            return False, "nothasselected node"
        
        paths = [n.path() for n in nodes]
        for n in nodes:
            try:
                n.destroy()
            except Exception:
                pass
        
        return True, f"Deleted {len(paths)} nodes"

    # ========================================
    # Python code execution (Cursor terminal-like)
    # ========================================
    
    class _ExecInterrupt(Exception):
        """Exception thrown when execute_python times out or the user stops it (to interrupt)."""
        pass

    def execute_python(self, code: str, timeout: int = 30) -> Tuple[bool, Dict[str, Any]]:
        """in Houdini Python environmentinexecutecode
        
        Cursor-terminal-like feature; can execute arbitrary Python code.
        
        Args:
            code: needexecute  Python code
            timeout: timeoutwhenbetween (second)
        
        Returns:
            (success, result) itsin result packagecontaining:
            {
                "output": str,      # outputcontent
                "return_value": Any, # lastonetableexpression Return value
                "error": str,       # errorinfo (ifhas)
                "execution_time": float  # executewhenbetween (second)
            }
        
        safenote: 
        - This feature allows executing arbitrary code; use with care
        - dangerousoperation (such asdeletefile)needsuserconfirm
        
        ★ timeoutprotect (v1.4.5): 
        use sys.settrace ineachrow Python codeexecutepreviouschecktimeoutandstopflag. 
        On timeout or user-stop, raises _ExecInterrupt to interrupt code execution and prevent main-thread deadlock.
        Note: cannot interrupt blocking calls inside C extensions (e.g., hou.node.cook),
        butcanin C callreturnafter belowonerow Python codeplaceinbreak. 
        """
        if hou is None:
            return False, {"error": "Houdini API not detected"}
        
        if not code or not code.strip():
            return False, {"error": "codeis empty"}
        
        import io
        import sys
        import traceback
        import threading
        
        start_time = time.time()
        _stop_event = self._stop_event  # cachereference
        _deadline = start_time + max(timeout, 5)  # at least 5 second
        _check_interval = 0.5  # Check every 0.5s (avoid being too aggressive)
        _last_check = [start_time]  # uselistso thatinclosepackageinmodify
        
        def _trace_timeout(frame, event, arg):
            """sys.settrace callback: eachrowcodeexecutepreviouschecktimeoutandstopflag"""
            now = time.time()
            # Lower check frequency: skip if elapsed since last check is below _check_interval
            if now - _last_check[0] < _check_interval:
                return _trace_timeout
            _last_check[0] = now
            # checkstopflag
            if _stop_event and _stop_event.is_set():
                raise HoudiniMCP._ExecInterrupt("userstoppedexecute")
            # checktimeout
            if now > _deadline:
                raise HoudiniMCP._ExecInterrupt(
                    f"codeExecution timed out ({timeout}s), alreadyinbreak. "
                    f"such asneedsmorelongwhenbetween, pleaseaddadd timeout parameter. "
                )
            return _trace_timeout
        
        # Capture output
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        old_trace = sys.gettrace()
        captured_output = io.StringIO()
        captured_error = io.StringIO()
        
        result = {
            "output": "",
            "return_value": None,
            "error": "",
            "execution_time": 0.0
        }
        
        try:
            sys.stdout = captured_output
            sys.stderr = captured_error
            
            # accuratebackupexecuteenvironment
            exec_globals = {
                'hou': hou,
                '__builtins__': __builtins__,
            }
            exec_locals = {}
            
            # ★ installtimeout trace
            sys.settrace(_trace_timeout)
            
            # tryastableexpressionrequestvalue (returnlastonevalue)
            try:
                # firsttry eval (singletableexpression)
                return_value = eval(code.strip(), exec_globals, exec_locals)
                result["return_value"] = self._safe_repr(return_value)
            except SyntaxError:
                # nosingletableexpression, use exec execute
                exec(code, exec_globals, exec_locals)
                
                # Try to fetch the last assigned value
                if exec_locals:
                    last_var = list(exec_locals.keys())[-1]
                    if not last_var.startswith('_'):
                        result["return_value"] = self._safe_repr(exec_locals[last_var])
            
            result["output"] = captured_output.getvalue()
            
            # check stderr
            stderr_content = captured_error.getvalue()
            if stderr_content:
                result["output"] += f"\n[stderr]\n{stderr_content}"
            
            result["execution_time"] = time.time() - start_time
            return True, result
        
        except HoudiniMCP._ExecInterrupt as e:
            result["error"] = str(e)
            result["output"] = captured_output.getvalue()
            result["execution_time"] = time.time() - start_time
            return False, result
            
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            result["output"] = captured_output.getvalue()
            result["execution_time"] = time.time() - start_time
            return False, result
            
        finally:
            # ★ Must restore the original trace; otherwise it impacts subsequent Python execution
            sys.settrace(old_trace)
            sys.stdout = old_stdout
            sys.stderr = old_stderr
    
    def _safe_repr(self, value: Any, max_length: int = 1000) -> str:
        """safeplacegetobject stringtableshow"""
        try:
            # processcommontype
            if value is None:
                return "None"
            if isinstance(value, (int, float, bool)):
                return str(value)
            if isinstance(value, str):
                if len(value) > max_length:
                    return repr(value[:max_length] + "...")
                return repr(value)
            if isinstance(value, (list, tuple)):
                if len(value) > 10:
                    items = [self._safe_repr(v, 100) for v in value[:10]]
                    return f"[{', '.join(items)}, ... ({len(value)} items total)]"
                items = [self._safe_repr(v, 100) for v in value]
                return f"[{', '.join(items)}]"
            if isinstance(value, dict):
                if len(value) > 10:
                    items = [f"{k}: {self._safe_repr(v, 100)}" for k, v in list(value.items())[:10]]
                    return f"{{{', '.join(items)}, ... ({len(value)} items total)}}"
                items = [f"{k}: {self._safe_repr(v, 100)}" for k, v in value.items()]
                return f"{{{', '.join(items)}}}"
            
            # Houdini object
            if hou and hasattr(value, 'path'):
                return f"<{type(value).__name__}: {value.path()}>"
            if hou and hasattr(value, 'name'):
                return f"<{type(value).__name__}: {value.name()}>"
            
            # default
            s = repr(value)
            if len(s) > max_length:
                return s[:max_length] + "..."
            return s
        except Exception:
            return f"<{type(value).__name__}>"

    # ========================================
    # toolpartdispatchprocess  (eachtoolonemethod)
    # ========================================

    def _tool_create_wrangle_node(self, args: Dict[str, Any]) -> Dict[str, Any]:
        vex_code = args.get("vex_code", "")
        if not vex_code:
            return {"success": False, "error": "missing vex_code parameter"}
        ok, msg = self.create_wrangle_node(
            vex_code, args.get("wrangle_type", "attribwrangle"),
            args.get("node_name"), args.get("run_over", "Points"),
            args.get("parent_path"))
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_get_network_structure(self, args: Dict[str, Any]) -> Dict[str, Any]:
        network_path = args.get("network_path")
        box_name = args.get("box_name")  # NetworkBox drill-down parameter
        page = int(args.get("page", 1))

        # Pagination fast path (box_name also participates in the cache key)
        cache_suffix = f":{box_name}" if box_name else ""
        cache_key = f"get_network_structure:{network_path or '_current'}{cache_suffix}"
        if page > 1 and cache_key in self._tool_page_cache:
            np_arg = f'network_path="{network_path}", ' if network_path else ''
            bx_arg = f'box_name="{box_name}", ' if box_name else ''
            hint = f'get_network_structure({np_arg}{bx_arg}page={page})'
            return {"success": True, "result": self._paginate_tool_result(
                self._tool_page_cache[cache_key], cache_key, hint, page)}

        ok, data = self.get_network_structure(network_path)
        if ok:
            _, text = self.get_network_structure_text(network_path, box_name=box_name)
            np_arg = f'network_path="{network_path}", ' if network_path else ''
            bx_arg = f'box_name="{box_name}", ' if box_name else ''
            hint = f'get_network_structure({np_arg}{bx_arg}page={page})'
            return {"success": True, "result": self._paginate_tool_result(
                text, cache_key, hint, page)}
        return {"success": False, "error": data.get("error", "Unknown error")}

    def _tool_get_node_parameters(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """getnode allcanuseparameter (name, type, default, currentvalue), supportpaginate"""
        node_path = args.get("node_path", "")
        if not node_path:
            return {"success": False, "error": "missing node_path parameter"}
        page = int(args.get("page", 1))

        if hou is None:
            return {"success": False, "error": "Houdini API not detected"}

        # paginatefastpath: cacheinalreadyhascompleteresult
        cache_key = f"get_node_parameters:{node_path}"
        if page > 1 and cache_key in self._tool_page_cache:
            hint = f'get_node_parameters(node_path="{node_path}", page={page})'
            return {"success": True, "result": self._paginate_tool_result(
                self._tool_page_cache[cache_key], cache_key, hint, page)}

        node = hou.node(node_path)
        if node is None:
            return {"success": False, "error": f"Not foundNode: {node_path}"}

        try:
            node_type = node.type()
            type_key = f"{node_type.category().name().lower()}/{node_type.name()}"
            lines = [
                f"## {node.name()} ({node.path()})",
                f"type: {type_key} ({node_type.description()})",
            ]

            # ★ Node overview (merged from the original get_node_details feature) ★
            # statusflag
            flags = []
            if hasattr(node, 'isDisplayFlagSet') and node.isDisplayFlagSet():
                flags.append('display')
            if hasattr(node, 'isRenderFlagSet') and node.isRenderFlagSet():
                flags.append('render')
            if hasattr(node, 'isBypassed') and node.isBypassed():
                flags.append('bypass')
            if hasattr(node, 'isLocked') and node.isLocked():
                flags.append('locked')
            if flags:
                lines.append(f"flag: {', '.join(flags)}")

            # errorinfo
            try:
                errs = node.errors()
                if errs:
                    lines.append(f"⚠ error: {'; '.join(errs[:3])}")
            except Exception:
                pass

            # inputconnect
            inputs = []
            for i, inp in enumerate(node.inputs()):
                if inp is not None:
                    inputs.append(f"[{i}]{inp.path()}")
            if inputs:
                lines.append(f"Inputs: {', '.join(inputs)}")

            # outputconnect
            outputs = [o.path() for o in node.outputs()] if node.outputs() else []
            if outputs:
                lines.append(f"Outputs: {', '.join(outputs[:5])}")

            lines.append("")  # emptyrowpartinterval

            # traverseallparametertemplate (completelist)
            parm_group = node_type.parmTemplateGroup()
            if not parm_group:
                lines.append("(noparameter)")
                return {"success": True, "result": "\n".join(lines)}

            count = 0
            for pt in parm_group.parmTemplates():
                try:
                    if pt.isHidden():
                        continue
                    name = pt.name()
                    ptype = pt.type().name() if hasattr(pt, 'type') else "?"
                    label = pt.label() if hasattr(pt, 'label') else ""

                    # getdefault
                    default = None
                    try:
                        default = pt.defaultValue()
                        if isinstance(default, float):
                            default = round(default, 4)
                        elif isinstance(default, tuple):
                            default = tuple(round(v, 4) if isinstance(v, float) else v for v in default)
                    except Exception:
                        pass

                    # getcurrentvalue
                    current = None
                    try:
                        parm = node.parm(name)
                        if parm:
                            current = parm.eval()
                            if isinstance(current, float):
                                current = round(current, 4)
                            elif isinstance(current, tuple):
                                current = tuple(round(v, 4) if isinstance(v, float) else v for v in current)
                    except Exception:
                        pass

                    # menusingleoptions (ifhas)
                    menu_items = ""
                    if ptype == "Menu" and hasattr(pt, 'menuItems'):
                        try:
                            items = pt.menuItems()
                            labels = pt.menuLabels() if hasattr(pt, 'menuLabels') else items
                            if items and len(items) <= 10:
                                pairs = [f"{it}({lb})" if lb != it else it
                                         for it, lb in zip(items, labels)]
                                menu_items = f" options=[{', '.join(pairs)}]"
                            elif items:
                                menu_items = f" options=[{', '.join(items[:8])}...]"
                        except Exception:
                            pass

                    is_default = (current == default) if current is not None and default is not None else None
                    marker = "" if is_default else " *"  # * marknotdefault

                    lines.append(
                        f"- {name} ({ptype}, {label}): "
                        f"default={default}, current={current}{marker}{menu_items}"
                    )
                    count += 1
                except Exception:
                    continue

            lines.insert(2, f"parameterCount: {count}")
            full_text = "\n".join(lines)

            # paginatereturn
            hint = f'get_node_parameters(node_path="{node_path}", page={page})'
            return {"success": True, "result": self._paginate_tool_result(
                full_text, cache_key, hint, page)}

        except Exception as e:
            return {"success": False, "error": f"getparameterFailed: {str(e)}"}

    def _tool_set_node_parameter(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = args.get("node_path", "")
        param_name = args.get("param_name", "")
        value = args.get("value")
        missing = []
        if not node_path:
            missing.append("node_path(Node path)")
        if not param_name:
            missing.append("param_name(parametername)")
        if missing:
            return {"success": False, "error": f"missingmustneedparameter: {', '.join(missing)}"}
        ok, msg, snapshot = self.set_parameter(node_path, param_name, value)
        result = {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}
        if ok and snapshot:
            # ★ parameterpreviousaftervalueconsistentwhennotgenerate checkpoint, avoiddisplaynointentmeaning "modify"
            old_v = snapshot.get("old_value")
            new_v = snapshot.get("new_value")
            if old_v != new_v:
                result["_undo_snapshot"] = snapshot  # for UI undouse, notwillsendgive AI
        return result

    def _tool_create_node(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_type = args.get("node_type", "")
        if not node_type:
            return {"success": False, "error": "missing node_type parameter"}
        ok, msg = self.create_node(
            node_type, args.get("node_name"),
            args.get("parameters"), args.get("parent_path"))
        if ok:
            return {"success": True, "result": msg, "error": ""}
        error_msg = msg if msg else f"createnodeFailed: {node_type}"
        _dbg(f"[MCP Client] create_node failed: {error_msg[:200]}")
        return {"success": False, "result": "", "error": error_msg}

    def _tool_create_nodes_batch(self, args: Dict[str, Any]) -> Dict[str, Any]:
        nodes = args.get("nodes", [])
        if not nodes:
            return {"success": False, "error": "missing nodes parameter"}
        plan = {"nodes": nodes, "connections": args.get("connections", [])}
        ok, msg = self.create_network(plan)
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_connect_nodes(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from_path = args.get("from_path", "")
        to_path = args.get("to_path", "")
        missing = []
        if not from_path:
            missing.append("from_path (upstream node path)")
        if not to_path:
            missing.append("to_path (downstream node path)")
        if missing:
            return {"success": False, "error": f"missingmustneedparameter: {', '.join(missing)}"}
        ok, msg = self.connect_nodes(from_path, to_path, args.get("input_index", 0))
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_delete_node(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = args.get("node_path", "")
        if not node_path:
            return {"success": False, "error": "missing node_path parameter"}
        ok, msg, snapshot = self.delete_node_by_path(node_path)
        result = {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}
        if ok and snapshot:
            result["_undo_snapshot"] = snapshot  # for UI undouse, notwillsendgive AI
        return result

    def _tool_search_node_types(self, args: Dict[str, Any]) -> Dict[str, Any]:
        keyword = args.get("keyword", "")
        if not keyword:
            return {"success": False, "error": "missing keyword parameter"}
        ok, msg = self.search_nodes(keyword, args.get("limit", 10))
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_semantic_search_nodes(self, args: Dict[str, Any]) -> Dict[str, Any]:
        description = args.get("description", "")
        if not description:
            return {"success": False, "error": "missing description parameter"}
        ok, msg = self.semantic_search_nodes(description, args.get("category", "sop"))
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_list_children(self, args: Dict[str, Any]) -> Dict[str, Any]:
        network_path = args.get("network_path")
        recursive = args.get("recursive", False)
        page = int(args.get("page", 1))

        # paginatefastpath
        cache_key = f"list_children:{network_path or '_current'}:r={recursive}"
        if page > 1 and cache_key in self._tool_page_cache:
            np_arg = f'network_path="{network_path}", ' if network_path else ''
            hint = f'list_children({np_arg}recursive={recursive}, page={page})'
            return {"success": True, "result": self._paginate_tool_result(
                self._tool_page_cache[cache_key], cache_key, hint, page)}

        ok, msg = self.list_children(network_path, recursive, args.get("show_flags", True))
        if not ok:
            return {"success": False, "error": msg}

        np_arg = f'network_path="{network_path}", ' if network_path else ''
        hint = f'list_children({np_arg}recursive={recursive}, page={page})'
        return {"success": True, "result": self._paginate_tool_result(
            msg, cache_key, hint, page)}

    def _tool_get_geometry_info(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = args.get("node_path", "")
        if not node_path:
            return {"success": False, "error": "missing node_path parameter"}
        ok, msg = self.get_geometry_info(node_path, args.get("output_index", 0))
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_read_selection(self, args: Dict[str, Any]) -> Dict[str, Any]:
        include_params = args.get("include_params", True)
        include_geometry = args.get("include_geometry", False)
        ok, msg = self.describe_selection(limit=5, include_all_params=include_params)
        if ok and include_geometry and hou:
            nodes = hou.selectedNodes()
            for node in nodes[:3]:
                geo_ok, geo_msg = self.get_geometry_info(node.path())
                if geo_ok:
                    msg += f"\n\n{geo_msg}"
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_set_display_flag(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = args.get("node_path", "")
        if not node_path:
            return {"success": False, "error": "missing node_path parameter"}
        ok, msg = self.set_display_flag(
            node_path, args.get("display", True), args.get("render", True))
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_copy_node(self, args: Dict[str, Any]) -> Dict[str, Any]:
        source_path = args.get("source_path", "")
        if not source_path:
            return {"success": False, "error": "missing source_path parameter"}
        ok, msg = self.copy_node(
            source_path, args.get("dest_network"), args.get("new_name"))
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_batch_set_parameters(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_paths = args.get("node_paths", [])
        param_name = args.get("param_name", "")
        missing = []
        if not node_paths:
            missing.append("node_paths(Node pathlist)")
        if not param_name:
            missing.append("param_name(parametername)")
        if missing:
            return {"success": False, "error": f"missingmustneedparameter: {', '.join(missing)}"}
        ok, msg = self.batch_set_parameters(node_paths, param_name, args.get("value"))
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_find_nodes_by_param(self, args: Dict[str, Any]) -> Dict[str, Any]:
        param_name = args.get("param_name", "")
        if not param_name:
            return {"success": False, "error": "missing param_name parameter"}
        ok, msg = self.find_nodes_by_param(
            param_name, args.get("value"),
            args.get("network_path"), args.get("recursive", True))
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_save_hip(self, args: Dict[str, Any]) -> Dict[str, Any]:
        ok, msg = self.save_hip(args.get("file_path"))
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_undo_redo(self, args: Dict[str, Any]) -> Dict[str, Any]:
        action = args.get("action", "")
        if not action:
            return {"success": False, "error": "missing action parameter"}
        ok, msg = self.undo_redo(action)
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_execute_python(self, args: Dict[str, Any]) -> Dict[str, Any]:
        code = args.get("code", "")
        if not code:
            return {"success": False, "error": "missing code parameter"}
        page = int(args.get("page", 1))

        # paginatefastpath (onlyforSuccess outputcache)
        # use code   hash ascachekey, avoid key passedlong
        import hashlib
        code_hash = hashlib.md5(code.encode()).hexdigest()[:12]
        cache_key = f"execute_python:{code_hash}"
        if page > 1 and cache_key in self._tool_page_cache:
            hint = f'execute_python(code="...sameon...", page={page})'
            return {"success": True, "result": self._paginate_tool_result(
                self._tool_page_cache[cache_key], cache_key, hint, page)}

        # safecheck: detectdangerousoperation
        security_msg = self._check_code_security(code)
        if security_msg:
            return {"success": False, "error": security_msg}
        timeout = int(args.get("timeout", 30))
        ok, result = self.execute_python(code, timeout=timeout)
        if ok:
            output_parts = []
            if result.get("output"):
                output_parts.append(f"Outputs:\n{result['output']}")
            if result.get("return_value") is not None:
                output_parts.append(f"Return value: {result['return_value']}")
            output_parts.append(f"Execution time: {result['execution_time']:.3f}s")
            full_text = "\n".join(output_parts)

            hint = f'execute_python(code="...sameon...", page={page})'
            return {"success": True, "result": self._paginate_tool_result(
                full_text, cache_key, hint, page)}
        # Failed: packagecontainingpartpartoutput (ifhas)+ completeerror + executewhenbetween
        error_parts = []
        partial_output = result.get("output", "")
        if partial_output:
            error_parts.append(f"[partpartoutput]\n{partial_output}")
        error_parts.append(result.get("error", "Execution failed"))
        error_parts.append(f"Execution time: {result.get('execution_time', 0):.3f}s")
        return {"success": False, "error": "\n".join(error_parts), "result": partial_output}

    # ========================================
    # System shell sandboxed execution
    # ========================================

    # Shell commandblacknamesingle (positivethen, ignorelargesmallwrite)
    _SHELL_DANGEROUS_PATTERNS = [
        # file/directorybatchdelete
        (r'\brm\s+.*-r', "disallowrecursivedelete (rm -r)"),
        (r'\brm\s+.*-f', "disallowforcedelete (rm -f)"),
        (r'\brmdir\s+/s', "disallowrecursivedeletedirectory (rmdir /s)"),
        (r'\bdel\s+/s', "disallowrecursivedelete (del /s)"),
        (r'\bdel\s+/q', "disallowsilentdelete (del /q)"),
        (r'\brd\s+/s', "disallowrecursivedelete (rd /s)"),
        # formatization
        (r'\bformat\s+[a-zA-Z]:', "disallowformatizationdisk"),
        # registertable
        (r'\breg\s+(delete|add)', "disallowmodifyregistertable"),
        # Shutdown / restart
        (r'\bshutdown\b', "Shutdown disallowed"),
        (r'\breboot\b', "disallowrestart"),
        # permissionlimitraiserise
        (r'\brunas\b', "disallow runas raisepermission"),
        (r'\bsudo\b', "disallow sudo raisepermission"),
        # networkconfig
        (r'\bnetsh\b', "disallowmodifynetworkconfig"),
        # processinject
        (r'\btaskkill\s+/f', "disallowforceendprocess"),
        # dangerous PowerShell
        (r'Remove-Item\s+.*-Recurse', "disallow PowerShell recursivedelete"),
        (r'Invoke-Expression', "disallow Invoke-Expression"),
        (r'\biex\b', "disallow iex (Invoke-Expression alias)"),
        # diskoperation
        (r'\bdiskpart\b', "disallow diskpart"),
        # fork bomb
        (r'%0\|%0', "disallow fork bomb"),
        (r':\(\)\{.*\}', "disallow fork bomb"),
    ]

    # Allowed command prefixes (whitelist, coarse-grained; commands not on the list can still run, only the blacklist intercepts)
    # thiswhitenamesingleonlyused forlogHint
    _SHELL_COMMON_COMMANDS = frozenset({
        'pip', 'python', 'git', 'dir', 'ls', 'cd', 'echo', 'type', 'cat',
        'where', 'which', 'whoami', 'hostname', 'ipconfig', 'ifconfig',
        'curl', 'wget', 'ffmpeg', 'ffprobe', 'magick', 'convert',
        'hython', 'hbatch', 'mantra', 'hcmd',
        'node', 'npm', 'npx', 'conda', 'env', 'set', 'tree',
        'find', 'grep', 'rg', 'awk', 'sed', 'head', 'tail', 'wc',
        'mkdir', 'copy', 'cp', 'move', 'mv', 'ren', 'rename',
        'tar', 'zip', 'unzip', '7z',
    })

    def _check_shell_security(self, command: str) -> Optional[str]:
        """check Shell commandwhetherpackagecontainingdangerousoperation"""
        for pattern, msg in self._SHELL_DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return f"Blocked by safety filter: {msg}\nCommand: {command}\nIf you really need to run this, do it manually in a system terminal."
        return None

    def _tool_execute_shell(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a command in the system shell (sandboxed environment).

        ★ v1.4.4 improved: use Popen + poll instead of subprocess.run
        - Support user interruption of running commands via the Stop button
        - Correctly kill the entire process tree on Windows (not just the cmd.exe parent)
        - Prevent pipe-buffer-full deadlock (use communicate chunk-read)
        """
        import subprocess
        import hashlib

        command = args.get("command", "").strip()
        if not command:
            return {"success": False, "error": "missing command parameter"}

        page = int(args.get("page", 1))
        timeout = min(int(args.get("timeout", 30)), 120)  # max 120 second

        # paginatefastpath
        cmd_hash = hashlib.md5(command.encode()).hexdigest()[:12]
        cache_key = f"shell:{cmd_hash}"
        if page > 1 and cache_key in self._tool_page_cache:
            hint = f'execute_shell(command="...sameon...", page={page})'
            return {"success": True, "result": self._paginate_tool_result(
                self._tool_page_cache[cache_key], cache_key, hint, page)}

        # safecheck
        security_msg = self._check_shell_security(command)
        if security_msg:
            return {"success": False, "error": security_msg}

        # working directory
        cwd = args.get("cwd", "")
        if not cwd:
            # Default: project root directory
            cwd = str(Path(__file__).parent.parent.parent.parent)
        if not os.path.isdir(cwd):
            return {"success": False, "error": f"working directorydoes not exist: {cwd}"}

        # ★ getstopeventreference (from AIClient passenter, used fordetectuserinbreak)
        stop_event = getattr(self, '_stop_event', None)

        start_time = time.time()
        proc = None
        try:
            # startsubprocess (notblock)
            popen_kwargs = dict(
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
            )
            if sys.platform == 'win32':
                popen_kwargs.update(
                    encoding='utf-8',
                    errors='replace',
                    env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                popen_kwargs.update(text=True)
            
            proc = subprocess.Popen(command, **popen_kwargs)
            
            # ★ Poll-wait: every 0.5s check stop flag and timeout
            deadline = start_time + timeout
            while proc.poll() is None:
                # checkuserinbreak
                if stop_event and stop_event.is_set():
                    self._kill_process_tree(proc)
                    elapsed = time.time() - start_time
                    return {"success": False, "error": f"commandisuserinbreak\ncommand: {command}\nalreadyrun: {elapsed:.1f}s"}
                
                # checktimeout
                if time.time() > deadline:
                    self._kill_process_tree(proc)
                    elapsed = time.time() - start_time
                    return {"success": False, "error": f"commandtimeout ({timeout}s limit)\ncommand: {command}\nconsumewhen: {elapsed:.2f}s"}
                
                # Brief sleep to avoid CPU spin
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass
            
            # processalreadyend, readoutput
            stdout, stderr = proc.communicate(timeout=5)
            elapsed = time.time() - start_time

            # Assemble output
            parts = []
            if stdout:
                parts.append(stdout.rstrip())
            if stderr:
                parts.append(f"[stderr]\n{stderr.rstrip()}")
            parts.append(f"[Exit code: {proc.returncode}, consumewhen: {elapsed:.2f}s]")
            full_text = "\n".join(parts)

            success = proc.returncode == 0
            hint = f'execute_shell(command="...sameon...", page={page})'
            return {"success": success, "result": self._paginate_tool_result(
                full_text, cache_key, hint, page)}

        except Exception as e:
            if proc and proc.poll() is None:
                self._kill_process_tree(proc)
            return {"success": False, "error": f"Shell Execution failed: {e}"}

    @staticmethod
    def _kill_process_tree(proc):
        """killdeadprocessanditsallsubprocess
        
        Windows onuse taskkill /F /T killdeadwholeprocesstree, 
        avoidonlykill cmd.exe andsubprocessresumeruncauseshangstart. 
        """
        import subprocess as _sp
        try:
            if sys.platform == 'win32':
                # /F = force  /T = killdeadwholeprocesstree  /PID = process ID
                _sp.run(
                    f'taskkill /F /T /PID {proc.pid}',
                    shell=True,
                    capture_output=True,
                    timeout=5,
                    creationflags=_sp.CREATE_NO_WINDOW,
                )
            else:
                import signal
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # ========================================
    # nodelayouttool
    # ========================================

    def _tool_layout_nodes(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """layoutnode — multistrategyautowholemanagenodeposition"""
        from . import hou_core

        parent_path = args.get("network_path", "") or args.get("parent_path", "")
        if not parent_path:
            net = self._current_network()
            if net is not None:
                parent_path = net.path()

        node_paths = args.get("node_paths", None)
        if isinstance(node_paths, str):
            node_paths = [p.strip() for p in node_paths.split(",") if p.strip()]
        if node_paths is not None and len(node_paths) == 0:
            node_paths = None

        method = args.get("method", "auto")
        spacing = float(args.get("spacing", 1.0))

        ok, msg, positions = hou_core.layout_nodes(
            parent_path=parent_path,
            node_paths=node_paths,
            method=method,
            spacing=spacing,
        )
        if ok:
            # buildcanread positionsummary
            lines = [msg]
            if positions and len(positions) <= 20:
                lines.append("nodeposition:")
                for p in positions:
                    lines.append(f"  {p['path']}: ({p['x']}, {p['y']})")
            elif positions:
                lines.append(f"(of {len(positions)} nodes, onlydisplayprevious 10 )")
                for p in positions[:10]:
                    lines.append(f"  {p['path']}: ({p['x']}, {p['y']})")
            return {"success": True, "result": "\n".join(lines)}
        return {"success": False, "error": msg}

    def _tool_get_node_positions(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """getnodepositioninfo"""
        from . import hou_core

        parent_path = args.get("network_path", "") or args.get("parent_path", "")
        if not parent_path:
            net = self._current_network()
            if net is not None:
                parent_path = net.path()

        node_paths = args.get("node_paths", None)
        if isinstance(node_paths, str):
            node_paths = [p.strip() for p in node_paths.split(",") if p.strip()]
        if node_paths is not None and len(node_paths) == 0:
            node_paths = None

        ok, msg, positions = hou_core.get_node_positions(
            parent_path=parent_path,
            node_paths=node_paths,
        )
        if ok:
            lines = [msg]
            for p in positions:
                lines.append(f"  {p['path']} ({p['type']}): ({p['x']}, {p['y']})")
            return {"success": True, "result": "\n".join(lines)}
        return {"success": False, "error": msg}

    # ========================================
    # NetworkBox operation
    # ========================================

    def _tool_create_network_box(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """create NetworkBox andoptionsplacewillnodeaddenteritsin"""
        from . import hou_core

        parent_path = args.get("parent_path", "")
        if not parent_path:
            # defaultusecurrentnetwork
            net = self._current_network()
            if net is None:
                return {"success": False, "error": "Current network not found, pleasespecified parent_path"}
            parent_path = net.path()

        name = args.get("name", "")
        comment = args.get("comment", "")
        color_preset = args.get("color_preset", "")
        node_paths = args.get("node_paths", [])
        if isinstance(node_paths, str):
            node_paths = [p.strip() for p in node_paths.split(",") if p.strip()]

        ok, msg, box = hou_core.create_network_box(
            parent_path, name, comment, color_preset, node_paths
        )
        if ok:
            result_data = {"box_name": box.name() if box else name, "message": msg}
            return {"success": True, "result": msg}
        return {"success": False, "error": msg}

    def _tool_add_nodes_to_box(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """willnodeaddtoalreadyhas  NetworkBox"""
        from . import hou_core

        parent_path = args.get("parent_path", "")
        if not parent_path:
            net = self._current_network()
            if net is None:
                return {"success": False, "error": "Current network not found, pleasespecified parent_path"}
            parent_path = net.path()

        box_name = args.get("box_name", "")
        if not box_name:
            return {"success": False, "error": "missing box_name parameter"}

        node_paths = args.get("node_paths", [])
        if isinstance(node_paths, str):
            node_paths = [p.strip() for p in node_paths.split(",") if p.strip()]
        if not node_paths:
            return {"success": False, "error": "missing node_paths parameter"}

        auto_fit = args.get("auto_fit", True)
        ok, msg = hou_core.add_nodes_to_box(parent_path, box_name, node_paths, auto_fit)
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_list_network_boxes(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List all NetworkBoxes in the network and their contents."""
        from . import hou_core

        parent_path = args.get("parent_path", "")
        if not parent_path:
            net = self._current_network()
            if net is None:
                return {"success": False, "error": "Current network not found, pleasespecified parent_path"}
            parent_path = net.path()

        ok, msg, boxes_info = hou_core.list_network_boxes(parent_path)
        if ok:
            if not boxes_info:
                return {"success": True, "result": f"{parent_path} innotNetworkBox"}
            lines = [f"{parent_path} in{len(boxes_info)}  NetworkBox:\n"]
            for box in boxes_info:
                status = "📦" if not box["minimized"] else "📦(collapse)"
                lines.append(f"{status} {box['name']}: {box['comment'] or '(no comment)'}")
                lines.append(f"   packagecontaining {box['node_count']} nodes: {', '.join(box['nodes'][:10])}")
                if box['node_count'] > 10:
                    lines.append(f"   ...andadditionally {box['node_count'] - 10} nodes")
            return {"success": True, "result": "\n".join(lines)}
        return {"success": False, "error": msg}

    # ========================================
    # Skill system
    # ========================================

    def _tool_list_skills(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """columnoutallavailable skills"""
        if not HAS_SKILLS or _list_skills is None:
            return {"success": False, "error": "Skill systemnotload"}
        try:
            skills = _list_skills()
            if not skills:
                return {"success": True, "result": "currentnothascanuse  Skill. "}
            lines = [f"available skills ({len(skills)}):\n"]
            for s in skills:
                lines.append(f"### {s['name']}")
                lines.append(f"  {s.get('description', '')}")
                params = s.get('parameters', {})
                if params:
                    lines.append("  parameter:")
                    for pname, pinfo in params.items():
                        req = " (required)" if pinfo.get('required') else ""
                        lines.append(f"    - {pname}: {pinfo.get('description', '')}{req}")
                lines.append("")
            return {"success": True, "result": "\n".join(lines)}
        except Exception as e:
            return {"success": False, "error": f"columnout Skill Failed: {e}"}

    def _tool_run_skill(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """executespecified Skill"""
        if not HAS_SKILLS or _run_skill is None:
            return {"success": False, "error": "Skill systemnotload"}

        skill_name = args.get("skill_name", "")
        if not skill_name:
            return {"success": False, "error": "missing skill_name parameter"}

        params = args.get("params", {})
        if not isinstance(params, dict):
            try:
                params = json.loads(str(params))
            except Exception:
                return {"success": False, "error": "params mustis JSON object"}

        try:
            result = _run_skill(skill_name, params)
            if "error" in result:
                return {"success": False, "error": result["error"]}

            # formatizationoutput
            import json as _json
            formatted = _json.dumps(result, ensure_ascii=False, indent=2)
            return {"success": True, "result": formatted}
        except Exception as e:
            import traceback
            return {"success": False, "error": f"Skill executeException: {e}\n{traceback.format_exc()[:500]}"}

    def _tool_check_errors(self, args: Dict[str, Any]) -> Dict[str, Any]:
        ok, text = self.check_node_errors_text(args.get("node_path"))
        return {"success": ok, "result": text if ok else "", "error": "" if ok else text}

    def _tool_search_local_doc(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not HAS_DOC_RAG:
            return {"success": False, "error": "DocIndex modulenotload"}
        query = args.get("query", "")
        if not query:
            return {"success": False, "error": "missing query parameter"}
        try:
            index = get_doc_rag()
            results = index.search(query, top_k=min(args.get("top_k", 5), 10))
            if not results:
                return {"success": True, "result": f"Not foundwith '{query}' related document"}
            parts = [f"findto {len(results)} relateditemitem:\n"]
            for idx, r in enumerate(results, 1):
                parts.append(f"{idx}. [{r['type'].upper()}] {r['name']} (score={r['score']:.1f})")
                parts.append(f"   {r['snippet']}\n")
            return {"success": True, "result": "\n".join(parts)}
        except Exception as e:
            import traceback
            return {"success": False, "error": f"documentsearchFailed: {e}\n{traceback.format_exc()}"}

    def _tool_get_houdini_node_doc(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_type = args.get("node_type", "")
        if not node_type:
            return {"success": False, "error": "missing node_type parameter"}
        page = int(args.get("page", 1))
        ok, doc_text = self._get_houdini_local_doc(node_type, args.get("category", "sop"), page)
        return {"success": ok, "result": doc_text if ok else "", "error": "" if ok else doc_text}

    def _tool_get_node_inputs(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_type = args.get("node_type", "")
        if not node_type:
            return {"success": False, "error": "missing node_type parameter"}
        ok, info = self.get_node_input_info(node_type, args.get("category", "sop"))
        return {"success": ok, "result": info if ok else "", "error": "" if ok else info}

    # ========================================
    # performanceanalyze (perfMon) tool
    # ========================================

    def _tool_perf_start_profile(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """start hou.perfMon performance profile"""
        if hou is None:
            return {"success": False, "error": "Houdini environmentunavailable"}

        title = args.get("title", "AI Performance Analysis")
        force_cook_node = args.get("force_cook_node", "")

        # ifalreadyhasactive profile, firststopold
        if self._active_perf_profile is not None:
            try:
                self._active_perf_profile.stop()
            except Exception:
                pass
            self._active_perf_profile = None

        try:
            profile = hou.perfMon.startProfile(title)
            self._active_perf_profile = profile
        except Exception as e:
            return {"success": False, "error": f"start perfMon profile Failed: {e}"}

        result_msg = f"alreadystartperformance profile: {title}"

        # options: startafterstandi.e.force cook specifiednode
        if force_cook_node:
            node = hou.node(force_cook_node)
            if node:
                try:
                    node.cook(force=True)
                    result_msg += f"\nalreadyforce cook Node: {force_cook_node}"
                except Exception as e:
                    result_msg += f"\nforce cook {force_cook_node} Failed: {e}"
            else:
                result_msg += f"\nwarning: node {force_cook_node} does not exist, skip cook"

        result_msg += "\nHint: after running the operations, call perf_stop_and_report to fetch the analysis report."
        return {"success": True, "result": result_msg}

    def _tool_perf_stop_and_report(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Stop the perfMon profile and return the analysis report."""
        if hou is None:
            return {"success": False, "error": "Houdini environmentunavailable"}

        if self._active_perf_profile is None:
            return {"success": False, "error": "nothasactive performance profile. pleasefirstcall perf_start_profile start. "}

        save_path = args.get("save_path", "")

        profile = self._active_perf_profile
        self._active_perf_profile = None

        try:
            profile.stop()
        except Exception as e:
            return {"success": False, "error": f"stop profile Failed: {e}"}

        # getstatisticsdata
        stats_data = None
        try:
            stats_data = profile.stats()
        except Exception as e:
            return {"success": False, "error": f"get profile statisticsdataFailed: {e}"}

        # options: savetodisk
        save_msg = ""
        if save_path:
            try:
                hou.perfMon.saveProfile(profile, save_path)
                save_msg = f"\nSaved profile to: {save_path}"
            except Exception as e:
                save_msg = f"\nsave profile Failed: {e}"

        # parsestatisticsdata, extractkeyrefermarker
        report_parts = ["=== Performance analysis report ==="]

        if isinstance(stats_data, dict):
            # tryextract cook eventstatistics
            cook_stats = stats_data.get("cookStats", stats_data.get("cook_stats", {}))
            script_stats = stats_data.get("scriptStats", stats_data.get("script_stats", {}))
            memory_stats = stats_data.get("memoryStats", stats_data.get("memory_stats", {}))

            if cook_stats:
                report_parts.append("\n--- Cook statistics ---")
                # parsenode cook whenbetween
                node_times = []
                if isinstance(cook_stats, dict):
                    for key, val in cook_stats.items():
                        if isinstance(val, dict):
                            t = val.get("time", val.get("selfTime", 0))
                            node_times.append((key, t))
                        elif isinstance(val, (int, float)):
                            node_times.append((key, val))
                node_times.sort(key=lambda x: x[1], reverse=True)
                for name, t in node_times[:15]:
                    report_parts.append(f"  {name}: {t:.2f}ms")
                if len(node_times) > 15:
                    report_parts.append(f"  ... still{len(node_times) - 15} itemitem")

            if script_stats:
                report_parts.append("\n--- scriptstatistics ---")
                if isinstance(script_stats, dict):
                    for key, val in list(script_stats.items())[:10]:
                        report_parts.append(f"  {key}: {val}")

            if memory_stats:
                report_parts.append("\n--- withinsavestatistics ---")
                if isinstance(memory_stats, dict):
                    for key, val in list(memory_stats.items())[:10]:
                        report_parts.append(f"  {key}: {val}")

            if not cook_stats and not script_stats and not memory_stats:
                # statisticsformatnotknow, outputoriginaldata summary
                import json as _json
                raw = _json.dumps(stats_data, indent=2, default=str, ensure_ascii=False)
                if len(raw) > 2000:
                    raw = raw[:2000] + "\n... (truncated)"
                report_parts.append("\n--- originalstatisticsdata ---")
                report_parts.append(raw)
        elif isinstance(stats_data, str):
            report_parts.append(stats_data[:3000])
        else:
            report_parts.append(f"statisticsdatatype: {type(stats_data).__name__}")
            report_parts.append(str(stats_data)[:3000])

        if save_msg:
            report_parts.append(save_msg)

        full_report = "\n".join(report_parts)

        # usepaginatereturn
        page = int(args.get("page", 1))
        cache_key = "perf_stop_and_report:latest"
        hint = f'perf_stop_and_report(page={page})'
        return {"success": True, "result": self._paginate_tool_result(
            full_report, cache_key, hint, page)}

    # ========================================
    # toolpartdispatchtable & usemethodHint & safecheck
    # ========================================

    # Tool-usage hints: when a parameter is missing or a call errors out, attach the correct calling pattern
    _TOOL_USAGE: Dict[str, str] = {
        "get_network_structure": 'get_network_structure(network_path="/obj/geo1", page=1)',
        "get_node_parameters": 'get_node_parameters(node_path="/obj/geo1/box1", page=1)',
        "set_node_parameter": 'set_node_parameter(node_path="/obj/geo1/box1", param_name="sizex", value=2.0)',
        "create_node": 'create_node(parent_path="/obj/geo1", node_type="box", node_name="box1")',
        "create_nodes_batch": 'create_nodes_batch(parent_path="/obj/geo1", nodes=[{"type":"box","name":"box1"},...])',
        "create_wrangle_node": 'create_wrangle_node(parent_path="/obj/geo1", code="@P.y += 1;", name="my_wrangle")',
        "connect_nodes": 'connect_nodes(from_path="/obj/geo1/box1", to_path="/obj/geo1/merge1", input_index=0)',
        "delete_node": 'delete_node(node_path="/obj/geo1/box1")',
        "search_node_types": 'search_node_types(keyword="scatter", category="sop")',
        "semantic_search_nodes": 'semantic_search_nodes(query="random scatter points", category="sop")',
        "list_children": 'list_children(path="/obj/geo1", page=1)',
        "read_selection": 'read_selection()',
        "set_display_flag": 'set_display_flag(node_path="/obj/geo1/box1")',
        "copy_node": 'copy_node(source_path="/obj/geo1/box1", dest_parent="/obj/geo1", new_name="box1_copy")',
        "batch_set_parameters": 'batch_set_parameters(node_path="/obj/geo1/box1", parameters={"sizex":2,"sizey":3})',
        "find_nodes_by_param": 'find_nodes_by_param(network_path="/obj/geo1", param_name="file", param_value="*.bgeo")',
        "save_hip": 'save_hip(file_path="C:/path/to/file.hip")',
        "undo_redo": 'undo_redo(action="undo")',
        "execute_python": 'execute_python(code="import hou; print(hou.node(\\"/obj\\").children())")',
        "execute_shell": 'execute_shell(command="pip list", cwd="C:/project", timeout=30)',
        "check_errors": 'check_errors(node_path="/obj/geo1/box1")',
        "search_local_doc": 'search_local_doc(keyword="scatter")',
        "get_houdini_node_doc": 'get_houdini_node_doc(node_type="scatter", page=1)',
        "get_node_inputs": 'get_node_inputs(node_type="copytopoints", category="sop")',
        "run_skill": 'run_skill(skill_name="analyze_geometry_attribs", params={"node_path":"/obj/geo1/box1"})',
        "list_skills": 'list_skills()',
        # nodelayout
        "layout_nodes": 'layout_nodes(network_path="/obj/geo1", method="auto")',
        "get_node_positions": 'get_node_positions(network_path="/obj/geo1")',
        # NetworkBox
        "create_network_box": 'create_network_box(parent_path="/obj/geo1", name="input_stage", comment="datainput", color_preset="input", node_paths=["/obj/geo1/box1"])',
        "add_nodes_to_box": 'add_nodes_to_box(parent_path="/obj/geo1", box_name="input_stage", node_paths=["/obj/geo1/box1"])',
        "list_network_boxes": 'list_network_boxes(parent_path="/obj/geo1")',
        # PerfMon performanceanalyze
        "perf_start_profile": 'perf_start_profile(title="Cook Analysis", force_cook_node="/obj/geo1/output0")',
        "perf_stop_and_report": 'perf_stop_and_report(save_path="C:/tmp/profile.hperf")',
    }

    # toolname -> processmethodname mappingtable
    _TOOL_DISPATCH: Dict[str, str] = {
        "create_wrangle_node": "_tool_create_wrangle_node",
        "get_network_structure": "_tool_get_network_structure",
        "get_node_parameters": "_tool_get_node_parameters",
        "set_node_parameter": "_tool_set_node_parameter",
        "create_node": "_tool_create_node",
        "create_nodes_batch": "_tool_create_nodes_batch",
        "connect_nodes": "_tool_connect_nodes",
        "delete_node": "_tool_delete_node",
        "search_node_types": "_tool_search_node_types",
        "semantic_search_nodes": "_tool_semantic_search_nodes",
        "list_children": "_tool_list_children",
        # "get_geometry_info" alreadyremove, by skill replacement for
        "read_selection": "_tool_read_selection",
        "set_display_flag": "_tool_set_display_flag",
        "copy_node": "_tool_copy_node",
        "batch_set_parameters": "_tool_batch_set_parameters",
        "find_nodes_by_param": "_tool_find_nodes_by_param",
        "save_hip": "_tool_save_hip",
        "undo_redo": "_tool_undo_redo",
        "execute_python": "_tool_execute_python",
        "execute_shell": "_tool_execute_shell",
        "check_errors": "_tool_check_errors",
        "search_local_doc": "_tool_search_local_doc",
        "get_houdini_node_doc": "_tool_get_houdini_node_doc",
        "get_node_inputs": "_tool_get_node_inputs",
        "run_skill": "_tool_run_skill",
        "list_skills": "_tool_list_skills",
        # nodelayout
        "layout_nodes": "_tool_layout_nodes",
        "get_node_positions": "_tool_get_node_positions",
        # NetworkBox
        "create_network_box": "_tool_create_network_box",
        "add_nodes_to_box": "_tool_add_nodes_to_box",
        "list_network_boxes": "_tool_list_network_boxes",
        # PerfMon performanceanalyze
        "perf_start_profile": "_tool_perf_start_profile",
        "perf_stop_and_report": "_tool_perf_stop_and_report",
        # long-termmemorymainmovesearch
        "search_memory": "_tool_search_memory",
        # viewportscreenshot
        "capture_viewport": "_tool_capture_viewport",
    }

    # Python codesafeblacknamesingle
    _DANGEROUS_PATTERNS = [
        (r'\bos\.remove\b', "disallowuse os.remove deletefile"),
        (r'\bos\.rmdir\b', "disallowuse os.rmdir deletedirectory"),
        (r'\bshutil\.rmtree\b', "disallowuse shutil.rmtree recursivedelete"),
        (r'\bos\.system\b', "disallowuse os.system executesystemcommand"),
        (r'\bsubprocess\b', "disallowuse subprocess executeexternalprocess"),
        (r'\b__import__\b', "disallowuse __import__ movestateimportenter"),
        (r'\bopen\s*\([^)]*["\']w["\']', "disallowbywritemodeopenfile (canusereadmode)"),
        (r'\bhou\.exit\b', "disallowuse hou.exit exit Houdini"),
        (r'\bhou\.hipFile\.clear\b', "disallowuse hou.hipFile.clear clearemptyscene"),
    ]

    def _check_code_security(self, code: str) -> Optional[str]:
        """checkcodewhetherpackagecontainingdangerousoperation, returnwarningmessageor None"""
        for pattern, msg in self._DANGEROUS_PATTERNS:
            if re.search(pattern, code):
                return f"⛔ safeinterceptcut: {msg}\nsuch ascertainneedsexecute, pleasein Houdini Python Shell inmanualrun. "
        return None

    # When these tools error out, hint the AI to look up docs first before retrying — don't blind-retry
    _DOC_CHECK_TOOLS: frozenset = frozenset({
        'create_node',
        'create_nodes_batch',
        'create_wrangle_node',
        'set_node_parameter',
        'batch_set_parameters',
        'connect_nodes',
    })

    def _append_usage_hint(self, tool_name: str, error_msg: str) -> str:
        """inerrormessageendattachtool correctcallway, andlook updocument Suggestion"""
        parts = [error_msg]

        usage = self._TOOL_USAGE.get(tool_name)
        if usage:
            parts.append(f"Correct usage: {usage}")

        # node-create / parameter-set tool errors → strongly suggest looking up docs before retrying
        if tool_name in self._DOC_CHECK_TOOLS:
            parts.append(
                "⚠️ Do not blind-retry! First confirm the correct information via the methods below, then re-call:\n"
                "  1. search_node_types(keyword=\"...\") — searchcorrect nodetypename\n"
                "  2. get_houdini_node_doc(node_type=\"...\") — look upthisnode parameterdocument\n"
                "  3. get_node_parameters(node_path=\"...\") — viewalreadyhasnode actualparameternameandcurrentvalue\n"
                "confirmnodetypename, parametername, parametervaluetypenoerrorafter, againrenewcallthistool. "
            )

        return "\n\n".join(parts)

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """executetoolcall - AI Agent  statsonetoolenterport (based onpartdispatchtable)
        
        Args:
            tool_name: toolname
            arguments: toolparameter
        
        Returns:
            {"success": bool, "result": str, "error": str}
        """
        _dbg(f"[MCP Client] Executing tool: {tool_name}, args: {list(arguments.keys())}")
        
        # ★ Hook: on_before_tool — lets plugins intercept / audit / modify arguments
        try:
            from ..hooks import get_hook_manager as _ghm
            _hm = _ghm()
            _hm.fire('on_before_tool', tool_name=tool_name, args=arguments)
        except Exception:
            pass
        
        handler_name = self._TOOL_DISPATCH.get(tool_name)
        
        # ★ ifwithinpartpartdispatchtableindoes not exist, tryexternaltool (HookManager + ToolRegistry)
        if handler_name is None:
            try:
                from ..hooks import get_hook_manager as _ghm
                _hm = _ghm()
                if _hm.has_external_tool(tool_name):
                    result = _hm.execute_external_tool(tool_name, arguments)
                    # ★ Hook: on_after_tool
                    try:
                        _hm.fire('on_after_tool', tool_name=tool_name, args=arguments, result=result)
                    except Exception:
                        pass
                    return result
            except Exception:
                pass
            # ★ try ToolRegistry (Skill toolby skill: prefixregister)
            try:
                from ..tool_registry import get_tool_registry
                _reg = get_tool_registry()
                if _reg.has_tool(tool_name):
                    _handler = _reg.get_handler(tool_name)
                    if _handler:
                        result = _handler(arguments)
                        if not isinstance(result, dict):
                            result = {"success": True, "result": str(result)}
                        try:
                            _ghm_inst = _ghm()
                            _ghm_inst.fire('on_after_tool', tool_name=tool_name, args=arguments, result=result)
                        except Exception:
                            pass
                        return result
            except Exception:
                pass
            return self._tool_unknown(tool_name)
        
        handler = getattr(self, handler_name, None)
        if handler is None:
            return {"success": False, "error": f"toolprocess Not implemented: {handler_name}"}
        
        try:
            result = handler(arguments)
            # toolreturnFailedwhen, autoattachusemethodHint
            if not result.get("success") and result.get("error"):
                result["error"] = self._append_usage_hint(tool_name, result["error"])
            # ★ Hook: on_after_tool — notifyplugintoolexecuteDone
            try:
                from ..hooks import get_hook_manager as _ghm
                _ghm().fire('on_after_tool', tool_name=tool_name, args=arguments, result=result)
            except Exception:
                pass
            return result
        except Exception as e:
            import traceback
            _dbg(f"[MCP Client] Tool execution error: {traceback.format_exc()}")
            err = f"tool {tool_name} executeException: {str(e)}"
            return {"success": False, "error": self._append_usage_hint(tool_name, err)}

    # ========================================
    # long-termmemorymainmovesearch
    # ========================================

    def _tool_search_memory(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """searchlong-termmemorylibrary — crosslayerlevel chunk search"""
        query = args.get("query", "")
        _dbg(f"[search_memory] Received search request: query={query!r}, args={args}")
        # ★ Defensive guard: if the global memory toggle is off, return an empty result directly,
        #   so the agent can't bypass the tool filter (e.g., cached old schema) to read memory.
        try:
            from morfyai.qt_compat import QSettings
            _s = QSettings("MorfyAI", "Settings")
            _enabled = _s.value("memory_enabled", False)
            if isinstance(_enabled, str):
                _enabled = _enabled.lower() == 'true'
            if not bool(_enabled):
                return {
                    "success": True,
                    "count": 0,
                    "memories": [],
                    "message": "long-termmemorysystemcurrentdisabled (useralreadyinsetinclose). ",
                }
        except Exception:
            pass
        if not query:
            return {"success": False, "error": "query parametercannotis empty"}

        category = args.get("category")
        top_k = min(max(args.get("top_k", 5), 1), 10)

        try:
            from ..memory_store import get_memory_store, ABSTRACTION_LEVELS
            store = get_memory_store()
            total = store.count_semantic()
            _dbg(f"[search_memory] Memory store has {total} semantic record(s)")

            results = store.search_all_levels(
                query=query,
                category=category,
                top_k=top_k,
                min_confidence=0.1,
            )
            _dbg(f"[search_memory] Results: {len(results)}")

            if not results:
                return {
                    "success": True,
                    "count": 0,
                    "memories": [],
                    "message": f"Not foundrelatedmemory (libraryinof {total} itemsemanticmemory, min_confidence=0.1)",
                }

            memories = []
            for rec, score in results:
                level_name = ABSTRACTION_LEVELS.get(rec.abstraction_level, "unknown")
                memories.append({
                    "rule": rec.rule,
                    "category": rec.category,
                    "abstraction_level": rec.abstraction_level,
                    "level_name": level_name,
                    "confidence": round(rec.confidence, 2),
                    "relevance": round(score, 3),
                    "activation_count": rec.activation_count,
                })

            # updateactivatecountcount
            for rec, _ in results:
                try:
                    store.increment_semantic_activation(rec.id)
                except Exception:
                    pass

            return {
                "success": True,
                "count": len(memories),
                "query": query,
                "category_filter": category,
                "memories": memories,
            }

        except Exception as e:
            return {"success": False, "error": f"memorysearchFailed: {str(e)}"}

    # ========================================
    # viewportscreenshot
    # ========================================

    def _tool_capture_viewport(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Capture the current Houdini 3D viewport snapshot; returns a base64-encoded image.
        
        use flipbook mechanismcutfetchcurrentframe singleframeimage, for AI visualanalyzenoderunresult. 
        ★ mustinmainthreadexecute (involveand hou UI operation). 
        """
        if hou is None:
            return {"success": False, "error": "Houdini environmentunavailable"}
        
        width = args.get("width", 960)
        height = args.get("height", 540)
        output_path = args.get("output_path", "")
        # Cap resolution range
        width = max(160, min(width, 1920))
        height = max(120, min(height, 1080))
        
        try:
            import tempfile
            import base64
            
            # get Scene Viewer
            viewer = None
            try:
                desktop = hou.ui.curDesktop()
                if desktop:
                    viewer = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
            except Exception:
                pass
            
            if viewer is None:
                try:
                    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
                except Exception:
                    pass
            
            if viewer is None:
                return {"success": False, "error": "findnotto Scene Viewer panel, pleaseensurehasopen  3D viewport"}
            
            # getcurrentframe
            current_frame = int(hou.frame())
            
            # generatetemporarywhenfile path
            tmp_dir = tempfile.gettempdir()
            tmp_file = os.path.join(tmp_dir, f"houdini_viewport_{int(time.time() * 1000)}.jpg")
            
            # use flipbook cutfetchsingleframe
            try:
                flip_settings = viewer.flipbookSettings().stash()
                flip_settings.output(tmp_file)
                flip_settings.frameRange((current_frame, current_frame))
                flip_settings.resolution((width, height))
                flip_settings.outputToMPlay(False)
                
                # executesingleframescreenshot
                viewport = viewer.curViewport()
                viewer.flipbook(viewport, flip_settings)
            except Exception as e:
                # some Houdini versionmaynot supported flipbook API
                return {"success": False, "error": f"Flipbook screenshotFailed: {e}"}
            
            # readgeneratedimage
            if not os.path.exists(tmp_file):
                # flipbook mayuseframenumberasfilenamesuffix
                import glob
                pattern = tmp_file.replace('.jpg', '*.jpg')
                candidates = sorted(glob.glob(pattern))
                if candidates:
                    tmp_file = candidates[0]
                else:
                    return {"success": False, "error": "screenshotfilenotgenerate, pleasecheckviewportstatus"}
            
            # Read and encode
            with open(tmp_file, 'rb') as f:
                img_bytes = f.read()
            
            if len(img_bytes) == 0:
                return {"success": False, "error": "screenshotfileis empty"}
            
            b64_data = base64.b64encode(img_bytes).decode('utf-8')
            
            # cleanuptemporarywhenfile
            try:
                os.remove(tmp_file)
            except Exception:
                pass
            
            # getviewportinfo
            viewport_name = ""
            try:
                viewport_name = viewer.curViewport().name()
            except Exception:
                pass
            
            cam_info = ""
            try:
                vp = viewer.curViewport()
                cam = vp.camera()
                if cam:
                    cam_info = f", camera={cam.path()}"
            except Exception:
                pass
            
            size_kb = len(img_bytes) / 1024
            
            result_msg = (
                f"alreadycutfetchviewportsnapshot: {width}x{height}, frame={current_frame}, "
                f"viewport={viewport_name}{cam_info}, "
                f"size={size_kb:.1f}KB"
            )
            
            # ifspecified output_path, savetofile
            if output_path:
                try:
                    # support $HIP plus  Houdini variableexpand
                    expanded_path = hou.text.expandString(output_path) if hasattr(hou, 'text') else output_path
                    save_dir = os.path.dirname(expanded_path)
                    if save_dir and not os.path.exists(save_dir):
                        os.makedirs(save_dir, exist_ok=True)
                    with open(expanded_path, 'wb') as f:
                        f.write(img_bytes)
                    result_msg += f"\nscreenshotSavedto: {expanded_path}"
                except Exception as e:
                    result_msg += f"\nsaveto {output_path} Failed: {e}"
            
            return {
                "success": True,
                "result": result_msg,
                # ★ specialfield: packagecontaining base64 imagedata, 
                # agent_loop_stream indetecttothisfieldwillwillimageinjectmessage
                "_viewport_image": b64_data,
                "_image_media_type": "image/jpeg",
            }
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "error": f"viewportscreenshotFailed: {str(e)}"}

    def _tool_unknown(self, tool_name: str) -> Dict[str, Any]:
        """processnotknowtoolname, raiseforSuggestion"""
        available = list(self._TOOL_DISPATCH.keys())
        error_msg = f"tooldoes not exist: {tool_name}"
        similar = [t for t in available
                   if tool_name.lower() in t.lower() or t.lower() in tool_name.lower()]
        if similar:
            error_msg += f"\nSuggestion tool: {', '.join(similar[:3])}"
        else:
            error_msg += f"\ncanusetool: {', '.join(available[:8])}..."
        error_msg += f"\npleaseusecorrect toolname, don'tduplicatecalldoes not exist tool. "
        return {"success": False, "error": error_msg}


    # ========================================
    # withinparthelpermethod
    # ========================================
    
    def _current_network(self) -> Any:
        """getcurrentnetworkedit in network
        
        preferredlevel: currentedit  > /obj/geo1 > /obj
        Prints a warning when using the fallback path.
        """
        try:
            editor = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.NetworkEditor)
            if editor:
                network = editor.pwd()
                if network:
                    return network
            # fall backto /obj/geo1
            try:
                geo1 = hou.node('/obj/geo1')
                if geo1:
                    _dbg("[MCP Client] ⚠️ No active network editor found, falling back to /obj/geo1")
                    return geo1
            except Exception:
                pass
            # fall backto /obj
            try:
                obj = hou.node('/obj')
                if obj:
                    _dbg("[MCP Client] ⚠️ No active network editor found, falling back to /obj")
                    return obj
            except Exception:
                pass
            return None
        except Exception as e:
            _dbg(f"[MCP Client] _current_network error: {e}")
            try:
                geo1 = hou.node('/obj/geo1')
                if geo1:
                    return geo1
            except Exception:
                pass
            try:
                return hou.node('/obj')
            except Exception:
                return None

    def _category_from_hint(self, prefix: str) -> Any:
        """fromprefixgetcategory"""
        try:
            prefix_lower = (prefix or '').strip().lower()
            for name, category in hou.nodeTypeCategories().items():
                if name.lower() == prefix_lower:
                    return category
        except Exception:
            pass
        return None

    def _desired_category_from_hint(self, type_hint: str, network: Any) -> Any:
        """fromtypeHintgetexpected category"""
        try:
            if "/" in (type_hint or ''):
                prefix = type_hint.split("/", 1)[0]
                return self._category_from_hint(prefix) or (network.childTypeCategory() if network else None)
            
            # If there's no prefix, try to infer category from the node name (common SOP nodes)
            hint_lower = (type_hint or '').lower().strip()
            common_sop_nodes = {
                'box', 'sphere', 'grid', 'tube', 'line', 'circle', 'font', 'curve',
                'noise', 'mountain', 'attribnoise', 'scatter', 'copytopoints', 
                'attribwrangle', 'pointwrangle', 'primitivewrangle', 'volumewrangle',
                'delete', 'blast', 'fuse', 'transform', 'subdivide', 'remesh',
                'polyextrude', 'smooth', 'relax', 'bend', 'twist', 'mountain',
                'add', 'merge', 'connect', 'group', 'partition'
            }
            if hint_lower in common_sop_nodes:
                # thisisoneSOPnode
                return hou.sopNodeTypeCategory()
            
            # defaultusecurrentnetwork category
            return network.childTypeCategory() if network else None
        except Exception:
            return None

    def _ensure_target_network(self, network: Any, desired_category: Any) -> Any:
        """ensuretargetnetworktypecorrect"""
        if network is None or desired_category is None:
            return network
            
        try:
            current_cat = network.childTypeCategory() if network else None
            if current_cat is None:
                return network
                
            # ifcategorymatch, directlyreturn
            if current_cat == desired_category:
                return network
            
            current_name = (current_cat.name().lower() if current_cat else "")
            desired_name = (desired_category.name().lower() if desired_category else "")
            
            if current_name == desired_name:
                return network
            
            # ifin obj layerlevelbutneedscreate sop node, autocreate geo contain 
            if current_name.startswith("object") and desired_name.startswith("sop"):
                try:
                    _dbg(f"[MCP Client] Auto-creating geo container, from {current_name} to {desired_name}")
                    # based ondocument, directlyuse createNode, letitselfselfprocessmatch
                    container = network.createNode(
                        "geo",
                        None,  # let Houdini autogeneratename
                        run_init_scripts=True,
                        load_contents=True,
                        exact_type_name=False,
                        force_valid_node_name=True
                    )
                    if container:
                        container.moveToGoodPosition()
                        _dbg(f"[MCP Client] Created geo container: {container.path()}")
                        return container
                    else:
                        _dbg(f"[MCP Client] Failed to create geo container: returned None")
                        return network
                except Exception as e:
                    _dbg(f"[MCP Client] Create geo container error: {e}")
                    import traceback
                    traceback.print_exc()
                    return network
        except Exception as e:
            _dbg(f"[MCP Client] _ensure_target_network error: {e}")
            import traceback
            traceback.print_exc()
        return network

    def _sanitize_node_name(self, name: Optional[str]) -> Optional[str]:
        """cleanupnodename"""
        if not name:
            return None
        cleaned = str(name).strip()
        if not cleaned:
            return None
        cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", cleaned)
        cleaned = cleaned.strip("_") or None
        return cleaned

    # ========================================
    # Houdini thisplacehelpdocumentquery
    # ========================================
    
    # Houdini nodeTypeCategories()   key with AI passenter  category mapping
    _CATEGORY_MAP: Dict[str, str] = {
        "sop": "Sop", "obj": "Object", "dop": "Dop", "vop": "Vop",
        "cop": "Cop2", "cop2": "Cop2", "rop": "Driver", "driver": "Driver",
        "chop": "Chop", "shop": "Shop", "lop": "Lop", "top": "Top",
    }

    def _get_houdini_local_doc(self, node_type: str, category: str = "sop", page: int = 1) -> Tuple[bool, str]:
        """getnodedocument (multiredowngradestrategy, supportpaginate)

        preferredlevel: 
        1. paginatecache (beforealreadyget documentdirectlypaginatereturn)
        2. Houdini thisplacehelpservice  (http://127.0.0.1:{port})
        3. SideFX inlinedocument (https://www.sidefx.com/docs/houdini/)
        4. hou.NodeType.description() + parameterlist asmostlowlimitdegree document

        Args:
            node_type: nodetypename
            category: nodecategory
            page: pagecode (from 1 start), greater than 1 whenpreferredfromcacheread

        Returns:
            (success, doc_text)
        """
        if hou is None:
            return False, "Houdini API not detected"

        type_name_lower = node_type.lower().strip()

        # ---------- paginatefastpath: cacheinalreadyhascompletedocument ----------
        cache_key = f"{category}/{node_type}".lower()
        if page > 1 and cache_key in self._doc_page_cache:
            return True, self._paginate_doc(self._doc_page_cache[cache_key], node_type, category, page)

        # ---------- lookupnodetypeobject ----------
        node_type_obj = None
        try:
            categories = hou.nodeTypeCategories()
            hou_cat_name = self._CATEGORY_MAP.get(category.lower(), category.capitalize())
            cat_obj = categories.get(hou_cat_name)
            # iffinecertainmatchFailed, traverseallpartclass
            if cat_obj is None:
                for cname, cobj in categories.items():
                    if cname.lower() == category.lower():
                        cat_obj = cobj
                        break

            if cat_obj:
                for name, nt in cat_obj.nodeTypes().items():
                    name_low = name.lower()
                    if name_low == type_name_lower or name_low.endswith(f"::{type_name_lower}"):
                        node_type_obj = nt
                        break
            # ifspecifiedcategoryNot found, searchallpartcategory
            if node_type_obj is None:
                for cname, cobj in categories.items():
                    for name, nt in cobj.nodeTypes().items():
                        name_low = name.lower()
                        if name_low == type_name_lower or name_low.endswith(f"::{type_name_lower}"):
                            node_type_obj = nt
                            # update category asactualfindto 
                            for k, v in self._CATEGORY_MAP.items():
                                if v == cname:
                                    category = k
                                    break
                            break
                    if node_type_obj:
                        break
        except Exception as e:
            _dbg(f"[MCP] Node type lookup failed: {e}")

        # ---------- strategy 1: thisplacehelpservice  ----------
        local_result = self._fetch_local_help(node_type, category, node_type_obj, page)
        if local_result is not None:
            return True, local_result

        # ---------- strategy 2: SideFX inlinedocument ----------
        online_result = self._fetch_online_help(node_type, category, page)
        if online_result is not None:
            return True, online_result

        # ---------- strategy 3: from hou.NodeType extractbasethisinfo ----------
        if node_type_obj is not None:
            return self._extract_type_info(node_type_obj, node_type)

        return False, f"findnottonodetype '{node_type}'  document. pleaseuse search_node_types confirmcorrect nodename. "

    # ---- helpdocument submethod ----

    def _html_to_text(self, html: str) -> str:
        """will HTML convertascanreadpuretext"""
        try:
            from bs4 import BeautifulSoup as BS
            soup = BS(html, 'html.parser')
            # removenotneeds partpart
            for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer']):
                tag.decompose()
            text = soup.get_text(separator='\n', strip=True)
        except Exception:
            # no bs4 whenusepositivethen
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<nav[^>]*>.*?</nav>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<header[^>]*>.*?</header>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<footer[^>]*>.*?</footer>', '', text, flags=re.DOTALL | re.IGNORECASE)
            # blocklevellabelswaprow
            text = re.sub(r'<(?:br|p|div|h[1-6]|li|tr)[^>]*>', '\n', text, flags=re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
        # cleanupmultiremainingemptyrow
        lines = [l.strip() for l in text.split('\n')]
        lines = [l for l in lines if l]
        text = '\n'.join(lines)
        return text

    # documentpaginatecache: key = "category/node_type" → completepuretext
    _doc_page_cache: Dict[str, str] = {}
    _DOC_PAGE_SIZE = 2500  # eachpagecharactercount

    def _paginate_doc(self, text: str, node_type: str, category: str, page: int = 1) -> str:
        """willdocumentbypagereturn, supportpaginateviewcompletecontent
        
        Args:
            text: complete puretextdocument
            node_type: nodetypename
            category: nodecategory
            page: pagecode (from 1 start)
        """
        cache_key = f"{category}/{node_type}".lower()
        self._doc_page_cache[cache_key] = text

        total_chars = len(text)
        page_size = self._DOC_PAGE_SIZE
        total_pages = max(1, (total_chars + page_size - 1) // page_size)

        # limitpagecoderange
        page = max(1, min(page, total_pages))

        start = (page - 1) * page_size
        end = min(start + page_size, total_chars)
        page_text = text[start:end]

        header = f"[{node_type} nodedocument] (Page {page}/{total_pages}/{total_chars} character)\n\n"

        if total_pages == 1:
            return header + page_text
        
        if page < total_pages:
            footer = f"\n\n[Page {page}/{total_pages}]  — more content; call get_houdini_node_doc(node_type=\"{node_type}\", category=\"{category}\", page={page + 1}) for next page"
        else:
            footer = f"\n\n[Page {page}/{total_pages} - last page]"
        
        return header + page_text + footer

    def _fetch_local_help(self, node_type: str, category: str, node_type_obj, page: int = 1) -> Optional[str]:
        """from Houdini thisplacehelpservice getdocument"""
        # firstcheckpaginatecache (avoidduplicaterequest)
        cache_key = f"{category}/{node_type}".lower()
        if cache_key in self._doc_page_cache and page > 1:
            return self._paginate_doc(self._doc_page_cache[cache_key], node_type, category, page)

        if not requests:
            return None
        settings = read_settings()
        help_port = getattr(settings, "help_server_port", 48626)
        help_server = f"http://127.0.0.1:{help_port}"

        # build URL (preferred helpUrl, otherwiseusestandardpath)
        url_path = f"/nodes/{category.lower()}/{node_type.lower()}"
        if node_type_obj:
            try:
                help_url = node_type_obj.helpUrl()
                if help_url and not help_url.startswith(('http://', 'https://')):
                    url_path = help_url
            except Exception:
                pass
        full_url = f"{help_server}{url_path}"

        try:
            response = requests.get(full_url, timeout=5)
            if response.status_code == 200:
                text = self._html_to_text(response.text)
                if text and len(text) > 50:
                    return self._paginate_doc(text, node_type, category, page)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            pass  # thisplaceservice unavailable, downgradetoinline
        except Exception as e:
            _dbg(f"[MCP] Local help fetch failed: {e}")
        return None

    def _fetch_online_help(self, node_type: str, category: str, page: int = 1) -> Optional[str]:
        """from SideFX inlinedocumentget"""
        # firstcheckpaginatecache
        cache_key = f"{category}/{node_type}".lower()
        if cache_key in self._doc_page_cache and page > 1:
            return self._paginate_doc(self._doc_page_cache[cache_key], node_type, category, page)

        if not requests:
            return None
        base_url = "https://www.sidefx.com/docs/houdini/"
        full_url = f"{base_url}nodes/{category.lower()}/{node_type.lower()}.html"
        try:
            response = requests.get(full_url, timeout=8)
            if response.status_code == 200:
                text = self._html_to_text(response.text)
                if text and len(text) > 50:
                    return self._paginate_doc(text, node_type, category, page)
        except Exception:
            pass
        return None

    def _extract_type_info(self, node_type_obj, node_type: str) -> Tuple[bool, str]:
        """from hou.NodeType objectextractbasethisdocumentinfo (lastdowngrade)"""
        try:
            label = node_type_obj.description() or node_type
            # inputinfo
            inputs = []
            try:
                input_labels = node_type_obj.inputLabels()
                for i, lbl in enumerate(input_labels):
                    inputs.append(f"  input {i}: {lbl}")
            except Exception:
                pass
            # parametersummary (previous 20)
            parms = []
            try:
                parm_templates = node_type_obj.parmTemplates()
                for pt in parm_templates[:20]:
                    parms.append(f"  {pt.name()}: {pt.label()} ({pt.type().name()})")
            except Exception:
                pass

            doc = [f"[{node_type} nodebasethisinfo]", f"name: {label}"]
            if inputs:
                doc.append("inputport:\n" + '\n'.join(inputs))
            if parms:
                doc.append(f"parameter (previous{min(20, len(parms))}):\n" + '\n'.join(parms))
            return True, '\n'.join(doc)
        except Exception as e:
            return False, f"extractnodeinfoFailed: {e}"
    
    # Common node-input descriptions (loaded from an external JSON; avoids hard-coding)
    # ========================================
    _COMMON_NODE_INPUTS: Dict[str, str] = {}

    @classmethod
    def _load_common_node_inputs(cls) -> Dict[str, str]:
        """Lazy-load common node-input info from node_inputs.json."""
        if cls._COMMON_NODE_INPUTS:
            return cls._COMMON_NODE_INPUTS
        json_path = os.path.join(os.path.dirname(__file__), 'node_inputs.json')
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                cls._COMMON_NODE_INPUTS = json.load(f)
            _dbg(f"[MCP Client] Loaded {len(cls._COMMON_NODE_INPUTS)} node input definition(s)")
        except FileNotFoundError:
            _dbg(f"[MCP Client] ⚠️ node_inputs.json not found: {json_path}")
        except Exception as e:
            _dbg(f"[MCP Client] ⚠️ Load node_inputs.json failed: {e}")
        return cls._COMMON_NODE_INPUTS

    def get_node_input_info(self, node_type: str, category: str = "sop") -> Tuple[bool, str]:
        """getnode inputportinfo (usecache, reneed: help AI manageresolveinputorderorder)
        
        Args:
            node_type: nodetypename
            category: nodecategory
        
        Returns:
            (success, info) inputportinfo
        """
        type_lower = node_type.lower()
        cache_key = f"{category}/{type_lower}"
        
        # Check common-node cache (lazy-loaded from JSON)
        common_inputs = self._load_common_node_inputs()
        if type_lower in common_inputs:
            return True, common_inputs[type_lower]
        
        # checkmovestatecache
        if cache_key in HoudiniMCP._common_node_inputs_cache:
            return True, HoudiniMCP._common_node_inputs_cache[cache_key]
        
        if hou is None:
            return False, "Houdini API not detected"
        
        try:
            # getnodetype
            categories = hou.nodeTypeCategories()
            cat_obj = categories.get(category.capitalize()) or categories.get(category.upper())
            if not cat_obj:
                return False, f"Category not found: {category}"
            
            node_type_obj = None
            for name, nt in cat_obj.nodeTypes().items():
                if name.lower() == type_lower or name.lower().endswith(f"::{type_lower}"):
                    node_type_obj = nt
                    break
            
            if not node_type_obj:
                return False, f"Node type not found: {node_type}"
            
            # getinputinfo
            max_inputs = node_type_obj.maxNumInputs()
            min_inputs = node_type_obj.minNumInputs()
            
            info_lines = [
                f"Node: {node_type} ({node_type_obj.description()})",
                f"inputportCount: {min_inputs}-{max_inputs}",
                "",
                "inputportDetails:"
            ]
            
            for i in range(min(max_inputs, 6)):
                try:
                    label = node_type_obj.inputLabel(i)
                    required = i < min_inputs
                    req_str = "mustneeds" if required else "options"
                    info_lines.append(f"  [{i}] {label} ({req_str})")
                except Exception:
                    info_lines.append(f"  [{i}] Input {i}")
            
            result = "\n".join(info_lines)
            
            # cacheresult
            HoudiniMCP._common_node_inputs_cache[cache_key] = result
            
            return True, result
            
        except Exception as e:
            return False, f"getinputinfoFailed: {str(e)}"