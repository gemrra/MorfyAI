# -*- coding: utf-8 -*-
"""HDA Architect skill — wrap a subnet/geo into a Houdini Digital Asset.

This is the "Builder" half of an Architect -> Builder -> Validator flow:
the agent builds an internal node network, then calls this skill to package
it into an HDA and promote chosen parameters to the asset interface, wired
back to the internal nodes with channel references.

Deterministic Python so the packaging is always correct. Everything is
guarded so a parm/type mismatch reports a warning instead of crashing.
"""

SKILL_INFO = {
    "name": "wrap_as_hda",
    "description": (
        "Wrap an existing subnet or geo node into a Houdini Digital Asset (HDA), optionally promoting "
        "internal parameters to the asset interface and linking them with channel references. "
        "Returns the new asset node path and the saved .hda file path. "
        "Use as the packaging step after building a tool's internal network ('make this an HDA', "
        "'turn this into a digital asset', 'create an HDA with controls X, Y')."
    ),
    "parameters": {
        "target_path": {
            "type": "string",
            "description": "Path of the subnet/geo node to convert, e.g. /obj/my_tool",
            "required": True,
        },
        "asset_name": {
            "type": "string",
            "description": "Internal type name for the asset (no spaces), e.g. my_spiral",
            "required": True,
        },
        "asset_label": {
            "type": "string",
            "description": "Human-readable label / description shown in the tab menu",
            "default": "",
        },
        "promote_parms": {
            "type": "string",
            "description": (
                "Comma-separated parameters to expose on the asset interface, each as "
                "'relative_node:parm_name', e.g. 'sphere1:scale, xform1:tx'. The internal parm is "
                "linked to the new top-level parm via ch(). Leave empty to promote nothing."
            ),
            "default": "",
        },
        "save_dir": {
            "type": "string",
            "description": "Directory to save the .hda file. Default: $HOUDINI_USER_PREF_DIR/otls",
            "default": "",
        },
    },
}


def _resolve_save_dir(save_dir):
    import hou  # type: ignore
    import os
    if save_dir:
        d = save_dir
    else:
        # Prefer a scene-local 'hda' folder ($HIP/hda) so test assets don't pile up
        # in the user's global otls library. Fall back to a temp dir if unsaved.
        d = None
        try:
            hip = hou.expandString("$HIP")
            if hip and hip not in (".", ""):
                d = os.path.join(hip, "hda")
        except Exception:
            d = None
        if not d:
            base = hou.getenv("HOUDINI_TEMP_DIR") or hou.expandString("$HOUDINI_TEMP_DIR") or os.path.expanduser("~")
            d = os.path.join(base, "morfyai_hda")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def run(target_path, asset_name, asset_label="", promote_parms="", save_dir=""):
    import hou  # type: ignore
    import os

    # accept comma-separated string (schema) or a list (direct call)
    if isinstance(promote_parms, str):
        promote_parms = [s.strip() for s in promote_parms.split(",") if s.strip()]
    promote_parms = promote_parms or []
    node = hou.node(target_path)
    if node is None:
        return {"success": False, "error": f"target node does not exist: {target_path}"}

    warnings = []
    label = asset_label or asset_name.replace("_", " ").title()
    out_dir = _resolve_save_dir(save_dir)
    hda_file = os.path.join(out_dir, f"{asset_name}.hda")

    # 1. create the digital asset from the node
    try:
        asset = node.createDigitalAsset(
            name=asset_name,
            hda_file_name=hda_file,
            description=label,
            min_num_inputs=0,
            max_num_inputs=4,
            create_backup=True,
            change_node_type=True,
        )
    except Exception as e:
        return {"success": False,
                "error": f"createDigitalAsset failed: {e}",
                "hint": "target must be a subnet-like node; group your nodes into a subnet first"}

    definition = asset.type().definition()
    promoted = []

    # 2. promote parameters and link them back with channel references
    if promote_parms:
        try:
            ptg = asset.parmTemplateGroup()
        except Exception as e:
            ptg = None
            warnings.append(f"could not read parm template group: {e}")

        for spec in promote_parms:
            try:
                if ":" not in spec:
                    warnings.append(f"bad promote spec (need 'node:parm'): {spec}")
                    continue
                rel_node, parm_name = spec.split(":", 1)
                inner = asset.node(rel_node)
                if inner is None:
                    warnings.append(f"inner node not found: {rel_node}")
                    continue
                parm = inner.parm(parm_name) or inner.parmTuple(parm_name)
                if parm is None:
                    warnings.append(f"parm not found: {spec}")
                    continue
                pt = parm.parmTemplate()
                if ptg is not None:
                    ptg.append(pt)
                promoted.append(spec)
            except Exception as e:
                warnings.append(f"promote failed for {spec}: {e}")

        if ptg is not None and promoted:
            try:
                asset.setParmTemplateGroup(ptg)
            except Exception as e:
                warnings.append(f"setParmTemplateGroup failed: {e}")

            # link inner parms to the new top-level parms
            for spec in promoted:
                try:
                    rel_node, parm_name = spec.split(":", 1)
                    inner = asset.node(rel_node)
                    top = asset.parm(parm_name)
                    if inner is None or top is None:
                        continue
                    # path from inner node up to the asset
                    rel = inner.relativePathTo(asset)
                    expr = f'ch("{rel}/{parm_name}")'
                    p = inner.parm(parm_name)
                    if p is not None:
                        p.setExpression(expr)
                except Exception as e:
                    warnings.append(f"channel link failed for {spec}: {e}")

    # 3. save the definition to disk
    saved = True
    try:
        definition.updateFromNode(asset)
        definition.save(hda_file, asset, hou.hdaOptions())
    except Exception as e:
        saved = False
        warnings.append(f"definition save failed (asset still exists in scene): {e}")

    return {
        "success": True,
        "asset_node": asset.path(),
        "asset_type": asset.type().name(),
        "hda_file": hda_file if saved else None,
        "promoted_parms": promoted,
        "saved_to_disk": saved,
        "warnings": warnings,
        "message": (
            f"Wrapped {target_path} into HDA '{asset_name}' "
            f"({len(promoted)} parm(s) promoted)."
            + ("" if saved else " NOTE: not yet saved to disk — see warnings.")
        ),
    }
