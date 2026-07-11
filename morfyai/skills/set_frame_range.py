# -*- coding: utf-8 -*-
"""Set the scene's global start/end frame range (and optionally fps).

Mutating — changes global playback range.
"""

SKILL_INFO = {
    "name": "set_frame_range",
    "description": (
        "Set the scene's global frame range (start/end) and current playback range in the timeline. "
        "Optionally set fps too. Use before a simulation or animation that needs a specific length."
    ),
    "parameters": {
        "start": {"type": "integer", "description": "Start frame.", "required": True},
        "end": {"type": "integer", "description": "End frame.", "required": True},
        "fps": {"type": "number", "description": "Frames per second. Leave 0 to keep current fps.", "default": 0},
    },
}


def run(start=1, end=100, fps=0):
    import hou  # type: ignore

    start, end = int(start), int(end)
    if end < start:
        return {"success": False, "error": f"end ({end}) must be >= start ({start})"}

    try:
        hou.playbar.setFrameRange(start, end)
        hou.playbar.setPlaybackRange(start, end)
    except Exception as e:
        return {"success": False, "error": f"could not set frame range: {e}"}

    fps_set = None
    if fps and float(fps) > 0:
        try:
            hou.setFps(float(fps))
            fps_set = float(fps)
        except Exception:
            pass

    return {
        "success": True,
        "start": start,
        "end": end,
        "fps": fps_set or hou.fps(),
        "verdict": f"Frame range set to {start}-{end}" + (f" @ {fps_set}fps." if fps_set else "."),
    }
