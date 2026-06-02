# -*- coding: utf-8 -*-
"""Visual check — give the build/sim a pair of EYES via a cheap vision model.

The main model (e.g. DeepSeek) cannot see images, so a valid-but-wrong result
(an upside-down table, a jelly-looking snow, a floating object) passes the data
checks yet fails on sight. This skill renders the node/viewport to an image and
asks a CHEAP VISION model (Gemini Flash-Lite / GPT-4o-mini via OpenRouter, or
GLM-4V) to describe it and judge correctness — returning a TEXT verdict the main
model can act on. This is a task-typed switch (vision work -> vision model),
not a difficulty-guess auto-switch: the user's main model stays whatever it is.

Read-only (renders + queries a vision model; does not modify the scene).
"""

import os
import json
import base64
import urllib.request
import urllib.error

SKILL_INFO = {
    "name": "visual_check",
    "description": (
        "LOOK at a built/simulated result with a vision model and report whether it looks correct. "
        "Renders the node (or current viewport) to an image and asks a cheap vision model to describe it "
        "and flag defects a data check misses — upside-down, floating, wrong orientation, jelly/melted look, "
        "empty, intersecting. Returns a TEXT verdict. Use after building anything visual, once data checks "
        "pass, as the final confirmation. Needs an OpenRouter/GLM/OpenAI vision key in config."
    ),
    "parameters": {
        "node_path": {
            "type": "string",
            "description": "SOP node to display + render. Empty = render the current viewport as-is.",
            "default": "",
        },
        "question": {
            "type": "string",
            "description": "What to check, e.g. 'Is this a correct upright table with 4 legs on the ground?'",
            "default": "Describe what you see. Does it look like a correct, well-formed result? List any defects (upside-down, floating, wrong orientation, intersecting, empty).",
        },
        "frame": {
            "type": "integer",
            "description": "Frame to render (for sims). Default = current frame.",
            "default": -1,
        },
    },
}

# provider -> (endpoint, config_key_name, default_model)
# Gemini exposes an OpenAI-COMPATIBLE endpoint, so it works the same way (no SDK).
_PROVIDERS = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
               "gemini_api_key", "gemini-2.5-flash"),
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "openrouter_api_key",
                   "google/gemini-2.0-flash-001"),
    "glm": ("https://open.bigmodel.cn/api/paas/v4/chat/completions", "glm_api_key", "glm-4v-flash"),
    "openai": ("https://api.openai.com/v1/chat/completions", "openai_api_key", "gpt-4o-mini"),
}

# auto-pick order when no provider is configured: cheapest/best-fit vision first
_AUTO_ORDER = ("gemini", "openrouter", "openai", "glm")


def _cfg():
    try:
        from shared.common_utils import load_config
        cfg, _ = load_config("ai", dcc_type="houdini")
        return cfg or {}
    except Exception:
        # fallback: parse the flat ini directly
        try:
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            out = {}
            with open(os.path.join(root, "config", "houdini_ai.ini"), encoding="utf-8") as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln or ln.startswith("#"):
                        continue
                    if ":" in ln:
                        k, v = ln.split(":", 1)
                    elif "=" in ln:
                        k, v = ln.split("=", 1)
                    else:
                        continue
                    out[k.strip()] = v.strip()
            return out
        except Exception:
            return {}


def _render(node_path, frame):
    """Render the node/viewport to a temp jpg. Returns (path, info) or (None, error)."""
    import hou  # type: ignore
    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewer is None:
        return None, "no Scene Viewer pane available to render"
    if node_path:
        n = hou.node(node_path)
        if n is None:
            return None, f"node not found: {node_path}"
        try:
            n.setDisplayFlag(True)
        except Exception:
            pass
    if frame is not None and frame >= 0:
        try:
            hou.setFrame(frame)
        except Exception:
            pass
    out_dir = os.path.join(os.path.expanduser("~"), "morfyai_vischeck")
    os.makedirs(out_dir, exist_ok=True)
    cur = int(hou.frame())
    out = os.path.join(out_dir, f"vis.{cur:04d}.jpg")
    try:
        if os.path.exists(out):
            os.remove(out)
    except Exception:
        pass
    vp = viewer.curViewport()

    # Consistent, clear 3/4 view via a temp camera that LOOKS AT the object (a null
    # target — Houdini computes the orientation, so it's always upright, never flipped).
    tmp_cam = None
    tmp_tgt = None
    prev_cam = None
    try:
        prev_cam = vp.camera()
    except Exception:
        prev_cam = None
    try:
        if node_path:
            tnode = hou.node(node_path)
            geo = tnode.geometry() if tnode else None
            if geo is not None and len(geo.points()) > 0:
                bb = geo.boundingBox()
                c = bb.center()
                size = max(bb.sizevec()) or 1.0
                d = size * 2.2 + 1.0
                op = hou.node("/obj")
                tmp_tgt = op.createNode("null", "morfyai_vis_target")
                tmp_tgt.parmTuple("t").set((c[0], c[1], c[2]))
                tmp_cam = op.createNode("cam", "morfyai_vis_cam")
                tmp_cam.parmTuple("t").set((c[0] + d * 0.8, c[1] + d * 0.85, c[2] + d * 0.8))
                tmp_cam.parm("resx").set(640)
                tmp_cam.parm("resy").set(512)
                lap = tmp_cam.parm("lookatpath")
                if lap is not None:
                    lap.set(tmp_tgt.path())
                vp.setCamera(tmp_cam)
    except Exception:
        tmp_cam = None
    if tmp_cam is None:
        try:
            if node_path and hou.node(node_path) and hou.node(node_path).geometry():
                vp.frameBoundingBox(hou.node(node_path).geometry().boundingBox())
            else:
                vp.frameAll()
        except Exception:
            pass

    fs = viewer.flipbookSettings().stash()
    fs.output(os.path.join(out_dir, "vis.$F4.jpg"))
    fs.frameRange((cur, cur))
    fs.resolution((640, 512))
    fs.outputToMPlay(False)
    viewer.flipbook(vp, fs)

    # restore viewport camera + clean up temp nodes
    try:
        if prev_cam is not None:
            vp.setCamera(prev_cam)
    except Exception:
        pass
    for _n in (tmp_cam, tmp_tgt):
        try:
            if _n is not None:
                _n.destroy()
        except Exception:
            pass

    if not os.path.exists(out):
        # find any produced frame
        import glob
        files = sorted(glob.glob(os.path.join(out_dir, "vis.*.jpg")))
        if files:
            out = files[-1]
        else:
            return None, "flipbook produced no image"
    return out, None


def run(node_path="", question="", frame=-1, provider="", model=""):
    cfg = _cfg()
    provider = (provider or cfg.get("vision_provider", "") or "").strip().lower()
    # auto-pick the first provider that actually has a key, if none specified
    if provider not in _PROVIDERS:
        provider = ""
        for p in _AUTO_ORDER:
            if (cfg.get(_PROVIDERS[p][1], "") or "").strip():
                provider = p
                break
        if not provider:
            return {"success": False,
                    "error": "no vision API key found. Add one in MorfyAI Settings — e.g. a Gemini key "
                             "(gemini_api_key) from aistudio.google.com, or OpenRouter/OpenAI. "
                             f"Providers: {list(_PROVIDERS)}."}
    url, key_name, default_model = _PROVIDERS[provider]
    api_key = (cfg.get(key_name, "") or "").strip()
    if not api_key:
        return {"success": False,
                "error": f"no vision API key for provider '{provider}' (config '{key_name}' is empty)."}
    model = (model or cfg.get("vision_model", "") or default_model).strip()
    q = question or SKILL_INFO["parameters"]["question"]["default"]

    # 1. render
    img_path, err = _render(node_path, frame)
    if err:
        return {"success": False, "error": err}

    # 2. encode
    try:
        with open(img_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
    except Exception as e:
        return {"success": False, "error": f"could not read render: {e}"}

    # 3. ask the vision model
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": (
                "You are a STRICT visual QA inspector for 3D/Houdini results. Be critical and literal — "
                "do NOT rubber-stamp. Examine spatial relationships carefully before approving:\n"
                "- Is each part where it belongs? (e.g. table/chair LEGS must be BELOW the top and reach "
                "down to the ground — legs sticking UP above the surface means it is UPSIDE-DOWN = wrong.)\n"
                "- Does it rest ON the ground, or float above / sink through it?\n"
                "- Right orientation, proportions, count? Any intersecting/melted/empty parts?\n"
                "Answer concisely: (1) what it appears to be, (2) does it match the intent, (3) concrete "
                "defects. A plausible label is NOT enough — verify the geometry is actually arranged "
                "correctly. End with exactly 'VERDICT: OK' or 'VERDICT: NEEDS FIX - <reason>'.")},
            {"role": "user", "content": [
                {"type": "text", "text": q},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ]},
        ],
        "temperature": 0.0,
        # gemini-2.5-flash is a THINKING model — it spends tokens reasoning before the
        # visible answer, so give generous headroom or the verdict gets truncated.
        "max_tokens": 1500,
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://morfyai.local"
        headers["X-Title"] = "MorfyAI"
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        r = urllib.request.urlopen(req, timeout=90)
        data = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        return {"success": False, "error": f"vision API HTTP {e.code}: {body}",
                "hint": "Check the model slug (vision_model) is valid for this provider."}
    except Exception as e:
        return {"success": False, "error": f"vision API call failed: {e}"}

    try:
        verdict = data["choices"][0]["message"]["content"]
    except Exception:
        verdict = json.dumps(data)[:500]

    return {
        "success": True,
        "provider": provider,
        "model": model,
        "image": img_path,
        "verdict": verdict,
        "looks_ok": ("VERDICT: OK" in (verdict or "").upper()),
        "message": "Vision model reviewed the render. Act on the verdict; if NEEDS FIX, address the defect and re-check.",
    }
