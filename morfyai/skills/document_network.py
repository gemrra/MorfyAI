# -*- coding: utf-8 -*-
"""Documentation Generator skill.

Produces handoff-ready Markdown documentation for a node network: purpose,
node inventory, data flow, key parameters, attributes, errors/warnings, and
pitfalls. Read-only — never modifies the scene.
"""

SKILL_INFO = {
    "name": "document_network",
    "description": (
        "Generate handoff-ready Markdown documentation for a node network: node inventory, data flow, "
        "inputs/outputs, key (non-default) parameters, geometry attributes, and any errors/warnings. "
        "Read-only. Use when the user asks to document / write notes / explain a network for handoff."
    ),
    "parameters": {
        "network_path": {
            "type": "string",
            "description": "Network/container path to document, e.g. /obj/geo1",
            "required": True,
        },
        "include_params": {
            "type": "boolean",
            "description": "Include each node's non-default parameter values",
            "default": True,
        },
    },
}


def _non_default_parms(node, limit=12):
    out = []
    try:
        for p in node.parms():
            try:
                if p.isAtDefault():
                    continue
                tpl = p.parmTemplate()
                # skip pure UI / folder controls
                val = p.eval()
                out.append((p.name(), val))
                if len(out) >= limit:
                    break
            except Exception:
                continue
    except Exception:
        pass
    return out


def _attribs(node):
    info = {}
    try:
        geo = node.geometry()
        if geo is None:
            return info
        info["point"] = [a.name() for a in geo.pointAttribs()]
        info["prim"] = [a.name() for a in geo.primAttribs()]
        info["vertex"] = [a.name() for a in geo.vertexAttribs()]
        info["detail"] = [a.name() for a in geo.globalAttribs()]
    except Exception:
        pass
    return info


def run(network_path, include_params=True):
    import hou  # type: ignore

    net = hou.node(network_path)
    if net is None:
        return {"success": False, "error": f"network does not exist: {network_path}"}

    children = list(net.children())
    lines = []
    lines.append(f"# {net.name()} — Network Documentation")
    lines.append("")
    lines.append(f"- **Path:** `{net.path()}`")
    lines.append(f"- **Type:** `{net.type().name()}`")
    lines.append(f"- **Node count:** {len(children)}")

    display = next((c for c in children if c.isDisplayFlagSet()), None)
    if display is not None:
        lines.append(f"- **Display node:** `{display.name()}`")
    lines.append("")

    # data-flow chain (follow inputs from the display node back to sources)
    if display is not None:
        chain = []
        cur, seen = display, set()
        while cur is not None and cur.path() not in seen:
            seen.add(cur.path())
            chain.append(cur.name())
            ins = [i for i in cur.inputs() if i]
            cur = ins[0] if ins else None
        if len(chain) > 1:
            lines.append("## Data Flow")
            lines.append("")
            lines.append("`" + "` → `".join(reversed(chain)) + "`")
            lines.append("")

    # node inventory
    lines.append("## Nodes")
    lines.append("")
    error_nodes = []
    for c in children:
        in_names = [i.name() for i in c.inputs() if i]
        out_n = len([o for o in c.outputs() if o])
        flags = []
        if c.isDisplayFlagSet():
            flags.append("display")
        try:
            if hasattr(c, "isBypassed") and c.isBypassed():
                flags.append("bypassed")
        except Exception:
            pass
        flag_str = f" _({', '.join(flags)})_" if flags else ""
        lines.append(f"### `{c.name()}` — `{c.type().name()}`{flag_str}")
        lines.append(f"- inputs: {in_names or '—'} · outputs: {out_n}")

        try:
            errs = c.errors() or []
            warns = c.warnings() or []
        except Exception:
            errs, warns = [], []
        if errs:
            error_nodes.append(c.name())
            lines.append(f"- ⚠️ **errors:** {'; '.join(errs)[:300]}")
        if warns:
            lines.append(f"- warnings: {'; '.join(warns)[:200]}")

        if include_params:
            nd = _non_default_parms(c)
            if nd:
                pretty = ", ".join(f"`{n}`={v}" for n, v in nd)
                lines.append(f"- key params: {pretty}")

        attribs = _attribs(c)
        if attribs and any(attribs.values()):
            parts = [f"{k}: {', '.join(v)}" for k, v in attribs.items() if v]
            if parts:
                lines.append(f"- attributes — {' | '.join(parts)}")
        lines.append("")

    # pitfalls summary
    lines.append("## Pitfalls / Notes")
    lines.append("")
    if error_nodes:
        lines.append(f"- Nodes with errors that need attention: {', '.join(error_nodes)}")
    if display is None:
        lines.append("- No display flag set — output node is ambiguous.")
    if not error_nodes and display is not None:
        lines.append("- No errors detected; network cooks to the display node.")
    lines.append("")

    doc = "\n".join(lines)
    return {
        "success": True,
        "network": net.path(),
        "node_count": len(children),
        "error_nodes": error_nodes,
        "documentation": doc,
        "message": f"Generated documentation for {net.path()} ({len(children)} nodes).",
    }
