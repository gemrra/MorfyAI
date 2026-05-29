# -*- coding: utf-8 -*-
"""
Growth Tracker + Personality Profile

Core formula: Growth(t) = -d(Error)/dt
Long-term decrease in prediction error = growth

Tracked metrics (rolling-window statistics):
- error_rate:        recent N-task error rate trend
- success_rate:      success rate trend
- avg_tool_calls:    average tool-call count trend (down = more efficient)
- avg_retries:       average retry count trend
- skill_confidence:  per-domain skill confidence

Personality = the long-term cumulative result of strategy reinforcement
"""

import json
import math
import time
from collections import deque
from dataclasses import dataclass, field, asdict

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None
from pathlib import Path
from typing import Any, Dict, List, Optional

from .memory_store import MemoryStore, get_memory_store

# ============================================================
# Persistence path
# ============================================================

_GROWTH_FILE = Path(__file__).parent.parent.parent / "cache" / "memory" / "growth_profile.json"

# ============================================================
# Rolling window size
# ============================================================

WINDOW_SIZE = 30  # rolling window of recent N tasks


@dataclass
class TaskMetric:
    """Metric data for a single task"""
    timestamp: float = 0.0
    success: bool = True
    error_count: int = 0
    retry_count: int = 0
    tool_call_count: int = 0
    reward: float = 0.0
    tags: List[str] = field(default_factory=list)


@dataclass
class PersonalityTraits:
    """Personality traits (accumulated from long-term reward bias)"""
    efficiency_bias: float = 0.0     # >0 calm/rational, <0 exploratory/creative
    risk_tolerance: float = 0.5      # high = bold attempts, low = conservative/stable
    verbosity: float = 0.5           # preference for reply verbosity
    proactivity: float = 0.5         # proactively suggest vs. only answer the question

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "PersonalityTraits":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class GrowthTracker:
    """Growth tracker + personality formation

    Records per-task metrics, computes trends, and forms personality traits.
    """

    def __init__(self, store: Optional[MemoryStore] = None):
        self.store = store or get_memory_store()

        # Rolling window
        self._metrics: deque = deque(maxlen=WINDOW_SIZE * 2)  # keep 2x to compute trend

        # Skill confidence
        self._skill_confidence: Dict[str, float] = {
            "vex": 0.5,
            "node_creation": 0.5,
            "terrain": 0.5,
            "copernicus": 0.5,
            "general": 0.5,
        }

        # Personality traits
        self.personality = PersonalityTraits()

        # Total task counter
        self._total_tasks: int = 0

        # Load persisted data
        self._load()

    # ==========================================================
    # Record task metrics
    # ==========================================================

    def record_task(self, metric: TaskMetric):
        """Record the metric data of a single task"""
        if metric.timestamp == 0.0:
            metric.timestamp = time.time()

        self._metrics.append(metric)
        self._total_tasks += 1

        # Update skill confidence
        self._update_skill_confidence(metric)

        # Update personality
        self._update_personality(metric)

        # Auto save
        self._save()

    # ==========================================================
    # Trend computation
    # ==========================================================

    def get_growth_metrics(self) -> Dict:
        """Get growth metrics

        Returns:
            {
                "error_rate": float,           # current error rate
                "error_rate_trend": float,      # error-rate trend (negative = improving)
                "success_rate": float,          # current success rate
                "success_rate_trend": float,    # success-rate trend (positive = improving)
                "avg_tool_calls": float,        # average tool-call count
                "avg_retries": float,           # average retry count
                "growth_score": float,          # composite growth score
                "total_tasks": int,             # total task count
            }
        """
        if not self._metrics:
            return {
                "error_rate": 0.0,
                "error_rate_trend": 0.0,
                "success_rate": 1.0,
                "success_rate_trend": 0.0,
                "avg_tool_calls": 0.0,
                "avg_retries": 0.0,
                "growth_score": 0.0,
                "total_tasks": self._total_tasks,
            }

        metrics = list(self._metrics)
        n = len(metrics)
        half = n // 2

        # Current window (later half)
        recent = metrics[half:] if half > 0 else metrics
        # Historical window (earlier half)
        older = metrics[:half] if half > 0 else []

        # Current metrics
        error_rate = sum(1 for m in recent if m.error_count > 0) / max(len(recent), 1)
        success_rate = sum(1 for m in recent if m.success) / max(len(recent), 1)
        avg_tool_calls = sum(m.tool_call_count for m in recent) / max(len(recent), 1)
        avg_retries = sum(m.retry_count for m in recent) / max(len(recent), 1)

        # Trend (compared to older window)
        if older:
            old_error_rate = sum(1 for m in older if m.error_count > 0) / max(len(older), 1)
            old_success_rate = sum(1 for m in older if m.success) / max(len(older), 1)
            error_rate_trend = error_rate - old_error_rate   # negative = improving
            success_rate_trend = success_rate - old_success_rate  # positive = improving
        else:
            error_rate_trend = 0.0
            success_rate_trend = 0.0

        # Composite growth score = -d(Error)/dt (simplified)
        growth_score = -error_rate_trend + success_rate_trend

        return {
            "error_rate": round(error_rate, 3),
            "error_rate_trend": round(error_rate_trend, 3),
            "success_rate": round(success_rate, 3),
            "success_rate_trend": round(success_rate_trend, 3),
            "avg_tool_calls": round(avg_tool_calls, 1),
            "avg_retries": round(avg_retries, 1),
            "growth_score": round(growth_score, 3),
            "total_tasks": self._total_tasks,
        }

    # ==========================================================
    # Skill confidence
    # ==========================================================

    def _update_skill_confidence(self, metric: TaskMetric):
        """Update skill confidence based on task tags"""
        alpha = 0.1  # learning rate

        # Determine affected skill domains from tags
        skill_map = {
            "vex_related": "vex",
            "node_creation": "node_creation",
            "terrain_related": "terrain",
            "copernicus_related": "copernicus",
        }

        affected_skills = set()
        for tag in metric.tags:
            skill = skill_map.get(tag)
            if skill:
                affected_skills.add(skill)

        # Always update "general"
        affected_skills.add("general")

        for skill in affected_skills:
            current = self._skill_confidence.get(skill, 0.5)
            target = 1.0 if metric.success else 0.0
            # Moving average
            new_val = (1 - alpha) * current + alpha * target
            self._skill_confidence[skill] = round(max(0.0, min(1.0, new_val)), 3)

    def update_skill_confidence_batch(self, updates: Dict[str, float]):
        """Batch update skill confidence (from LLM reflection)"""
        for skill, confidence in updates.items():
            # Weighted average with current value (avoid large one-shot LLM changes)
            current = self._skill_confidence.get(skill, 0.5)
            blended = 0.7 * current + 0.3 * confidence
            self._skill_confidence[skill] = round(max(0.0, min(1.0, blended)), 3)
        self._save()

    def get_skill_confidence(self) -> Dict[str, float]:
        """Get all skill confidences"""
        return dict(self._skill_confidence)

    # ==========================================================
    # Personality formation
    # ==========================================================

    def _update_personality(self, metric: TaskMetric):
        """Gradually form personality based on task results

        Personality = long-term cumulative result of strategy reinforcement
        """
        alpha = 0.05  # personality change rate (slow, accumulates over time)

        # Efficiency bias
        if metric.success and metric.tool_call_count <= 3:
            # Efficient success -> increase efficiency bias
            self.personality.efficiency_bias += alpha
        elif not metric.success and metric.retry_count > 2:
            # Many failed retries -> decrease efficiency bias (needs more exploration)
            self.personality.efficiency_bias -= alpha

        # Risk tolerance
        if "error_correction" in metric.tags:
            # Mistake then correction -> raise risk tolerance
            self.personality.risk_tolerance = min(1.0, self.personality.risk_tolerance + alpha)
        elif "unresolved_error" in metric.tags:
            # Unresolved error -> lower risk tolerance
            self.personality.risk_tolerance = max(0.0, self.personality.risk_tolerance - alpha)

        # Proactivity
        if "complex_task" in metric.tags and metric.success:
            # Complex task success -> raise proactivity
            self.personality.proactivity = min(1.0, self.personality.proactivity + alpha * 0.5)

        # Clamp range
        self.personality.efficiency_bias = max(-1.0, min(1.0, self.personality.efficiency_bias))

    def get_personality(self) -> PersonalityTraits:
        """Get current personality traits"""
        return self.personality

    def get_personality_description(self) -> str:
        """Generate a personality description text (for injection into the system prompt)"""
        p = self.personality
        skills = self._skill_confidence

        # Efficiency-bias description
        if p.efficiency_bias > 0.3:
            style = "efficiency-first, prefers concise direct solutions"
        elif p.efficiency_bias < -0.3:
            style = "exploratory and creative, tries multiple approaches"
        else:
            style = "balanced style, balances efficiency and exploration"

        # Risk description
        if p.risk_tolerance > 0.7:
            risk = "high risk tolerance"
        elif p.risk_tolerance < 0.3:
            risk = "low risk tolerance, conservative"
        else:
            risk = "medium risk tolerance"

        # Skills description
        skill_parts = []
        for skill_name, conf in sorted(skills.items(), key=lambda x: -x[1]):
            if conf > 0.1:
                skill_parts.append(f"{skill_name}: {conf:.2f}")
        skills_text = ", ".join(skill_parts) if skill_parts else "no data yet"

        return (
            f"[Self-Awareness] Current style preference: {style}, {risk}.\n"
            f"Skill confidence: {skills_text}"
        )

    # ==========================================================
    # Persistence
    # ==========================================================

    def _save(self):
        """Save growth data to file"""
        try:
            _GROWTH_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "total_tasks": self._total_tasks,
                "skill_confidence": self._skill_confidence,
                "personality": self.personality.to_dict(),
                "metrics": [
                    {
                        "timestamp": m.timestamp,
                        "success": m.success,
                        "error_count": m.error_count,
                        "retry_count": m.retry_count,
                        "tool_call_count": m.tool_call_count,
                        "reward": m.reward,
                        "tags": m.tags,
                    }
                    for m in self._metrics
                ],
            }
            with open(_GROWTH_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            _dbg(f"[GrowthTracker] Save failed: {e}")

    def _load(self):
        """Load growth data from file"""
        if not _GROWTH_FILE.exists():
            return
        try:
            with open(_GROWTH_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._total_tasks = data.get("total_tasks", 0)
            self._skill_confidence.update(data.get("skill_confidence", {}))
            self.personality = PersonalityTraits.from_dict(data.get("personality", {}))

            for m_data in data.get("metrics", []):
                self._metrics.append(TaskMetric(
                    timestamp=m_data.get("timestamp", 0),
                    success=m_data.get("success", True),
                    error_count=m_data.get("error_count", 0),
                    retry_count=m_data.get("retry_count", 0),
                    tool_call_count=m_data.get("tool_call_count", 0),
                    reward=m_data.get("reward", 0),
                    tags=m_data.get("tags", []),
                ))

            _dbg(f"[GrowthTracker] Loaded growth data: {self._total_tasks} tasks, "
                  f"personality={self.personality.to_dict()}")
        except Exception as e:
            _dbg(f"[GrowthTracker] Load failed: {e}")

    # ==========================================================
    # Composite report
    # ==========================================================

    def get_full_report(self) -> Dict:
        """Get the full growth report"""
        return {
            "growth_metrics": self.get_growth_metrics(),
            "skill_confidence": self.get_skill_confidence(),
            "personality": self.personality.to_dict(),
            "personality_description": self.get_personality_description(),
        }


# ============================================================
# Global singleton
# ============================================================

_tracker_instance: Optional[GrowthTracker] = None

def get_growth_tracker() -> GrowthTracker:
    """Get the global GrowthTracker instance"""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = GrowthTracker()
    return _tracker_instance
