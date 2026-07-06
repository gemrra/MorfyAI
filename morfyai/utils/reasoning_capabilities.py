# -*- coding: utf-8 -*-
"""
Per-model reasoning/thinking capability detection.

Mirrors the approach OpenCode uses via models.dev: each model is auto-detected
by name and matched to the SET of effort levels it actually supports — not a
single fixed Low/Medium/High for everyone. GLM-5.2 gets a wider dial
(low/medium/high/max/extra); MiMo V2.5 gets a narrower one (low/medium); a
model with no reasoning control at all still gets a safe low/medium/high
default rather than being disabled, since Effort is a UX-level speed/quality
dial (like OpenCode's Default/Low/.../Max or Claude's Faster<->Smarter), not
literally "does the API accept a reasoning_effort param".

We also track *how* each family's levels actually reach the API:
  - "effort":       sent as the API's own `reasoning_effort` string.
                     OpenAI o-series / gpt-5.x.
  - "budget_tokens": sent as a numeric thinking-token budget.
                     Anthropic Claude / Gemini extended thinking.
  - "boolean":       the API only takes thinking on/off — every level except
                     the lowest just enables it, no distinct per-level effect.
                     DeepSeek-V4/R1, GLM, MiMo, Kimi K2, MiniMax-M, Qwen3, Grok.
  - "none":          no reasoning capability; the level is UI-only and never
                     reaches the API.
This is all still a best-effort local table (same as the context/vision/price
guesses in ai_client.AIClient._FAMILY_CAPS) — none of these obscure/aggregator
-routed models have a confirmed live models.dev-style spec, so treat the
*wire* behavior as approximate even though the *level set shown* is precise
to the example the user asked for.
"""

import re

# (pattern, kind, [levels in order, lowest first])
_FAMILY_LEVELS = [
    (re.compile(r'\bo1\b|\bo3\b|\bo4\b|gpt-5', re.I), "effort", ["low", "medium", "high"]),
    (re.compile(r'claude', re.I), "budget_tokens", ["low", "medium", "high", "max"]),
    (re.compile(r'gemini', re.I), "budget_tokens", ["low", "medium", "high"]),
    (re.compile(r'glm-?5', re.I), "boolean", ["low", "medium", "high", "max", "extra"]),
    (re.compile(r'glm-?4\.?7', re.I), "boolean", ["low", "medium"]),
    (re.compile(r'deepseek-v4|deepseek-r1|deepseek-reasoner', re.I), "boolean", ["low", "medium", "high"]),
    (re.compile(r'minimax-m', re.I), "boolean", ["low", "medium", "high"]),
    (re.compile(r'mimo', re.I), "boolean", ["low", "medium"]),
    (re.compile(r'kimi-k2', re.I), "boolean", ["low", "medium"]),
    (re.compile(r'qwen3', re.I), "boolean", ["low", "medium", "high"]),
    (re.compile(r'grok', re.I), "boolean", ["low", "medium", "high"]),
]
_DEFAULT_KIND = "none"
_DEFAULT_LEVELS = ["low", "medium", "high"]

# level -> Anthropic/Gemini thinking.budget_tokens (extra tiers beyond the
# original 3 fall back to "high"'s budget if not listed).
BUDGET_TOKENS_BY_LEVEL = {"low": 2000, "medium": 6000, "high": 10000, "max": 24000}


def get_reasoning_capability(model, provider=""):
    """Classify a model's reasoning control. Returns a dict:
        {"kind": "effort"|"budget_tokens"|"boolean"|"none",
         "options": [str, ...]}   # UI-selectable effort levels, always non-empty
    """
    model = model or ""
    for pattern, kind, levels in _FAMILY_LEVELS:
        if pattern.search(model):
            return {"kind": kind, "options": levels}
    return {"kind": _DEFAULT_KIND, "options": _DEFAULT_LEVELS}


def resolve_reasoning_effort(model, provider, level):
    """Given a UI level (one of get_reasoning_capability's options), return
    the (enable_thinking, reasoning_effort) pair to actually send for this
    specific model — None for reasoning_effort means "don't send that
    parameter at all"."""
    cap = get_reasoning_capability(model, provider)
    levels = cap["options"]
    level = (level or "medium").lower()
    if level not in levels:
        level = levels[min(1, len(levels) - 1)]  # nearest sane default

    if cap["kind"] == "none":
        return False, None
    if cap["kind"] == "boolean":
        return level != levels[0], None
    # "effort" / "budget_tokens": thinking is always engaged, only depth varies
    return True, level
