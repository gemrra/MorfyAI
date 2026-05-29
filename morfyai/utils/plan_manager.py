# -*- coding: utf-8 -*-
"""
Plan Manager — data model and file management for Plan mode

Responsibilities:
- Plan data CRUD (create / read / update / delete)
- Plan file persistence at cache/plans/plan_{session_id}.json
- Compact Plan context generation (injected into the LLM, minimizing token cost)
- One session has only one active plan; old plans are auto-archived on re-creation
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None


class PlanManager:
    """Plan file manager

    File storage path:
        cache/plans/plan_{session_id}.json

    Plan JSON Schema (enhanced):
        {
            "plan_id": "a1b2c3d4",
            "session_id": "e5f6g7h8",
            "title": "...",
            "overview": "...",
            "complexity": "low|medium|high",
            "estimated_total_operations": 25,
            "phases": [{"name": "Phase 1: ...", "step_ids": ["step-1", "step-2"]}],
            "created_at": "2026-02-26T10:30:00",
            "status": "draft|confirmed|executing|completed|rejected",
            "architecture": {"nodes": [...], "connections": [...], "groups": [...]},
            "steps": [
                {
                    "id": "step-1",
                    "title": "Build base terrain",
                    "description": "Detailed description, including specific paths and parameter values...",
                    "sub_steps": ["Create node", "Set parameters"],
                    "tools": ["create_node", "set_node_parameter"],
                    "depends_on": [],
                    "expected_result": "Verifiable expected outcome",
                    "risk": "low|medium|high",
                    "estimated_operations": 4,
                    "fallback": "Fallback strategy on failure",
                    "notes": "Notes",
                    "status": "pending|running|done|error",
                    "result_summary": null
                }
            ]
        }
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        if cache_dir is None:
            cache_dir = Path(__file__).resolve().parent.parent.parent / "cache"
        self._plans_dir = cache_dir / "plans"
        self._plans_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _plan_path(self, session_id: str) -> Path:
        return self._plans_dir / f"plan_{session_id}.json"

    def _archive_path(self, session_id: str) -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self._plans_dir / f"plan_{session_id}_archived_{ts}.json"

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_plan(self, session_id: str, plan_data: dict) -> dict:
        """Create a new Plan and persist it

        If the session already has an active plan, the old one is auto-archived.

        Args:
            session_id: session ID
            plan_data: data submitted by the AI via the create_plan tool
                must include title, steps; overview is optional

        Returns:
            Complete plan dict (with auto-generated plan_id, created_at, etc.)
        """
        # Archive old plan
        old_path = self._plan_path(session_id)
        if old_path.exists():
            try:
                old_path.rename(self._archive_path(session_id))
            except OSError:
                old_path.unlink(missing_ok=True)

        # Normalize steps (enhanced: supports sub_steps / expected_result / risk / fallback, etc.)
        steps = []
        for i, s in enumerate(plan_data.get("steps", [])):
            step = {
                "id": s.get("id", f"step-{i + 1}"),
                "title": s.get("title", s.get("description", "")),
                "description": s.get("description", ""),
                "sub_steps": s.get("sub_steps", []),
                "tools": s.get("tools", []),
                "depends_on": s.get("depends_on", []),
                "expected_result": s.get("expected_result", ""),
                "risk": s.get("risk", "low"),
                "estimated_operations": s.get("estimated_operations", 1),
                "fallback": s.get("fallback", ""),
                "notes": s.get("notes", ""),
                "status": "pending",
                "result_summary": None,
            }
            steps.append(step)

        plan = {
            "plan_id": str(uuid.uuid4())[:8],
            "session_id": session_id,
            "title": plan_data.get("title", "Untitled Plan"),
            "overview": plan_data.get("overview", ""),
            "complexity": plan_data.get("complexity", "medium"),
            "estimated_total_operations": plan_data.get("estimated_total_operations", sum(
                s.get("estimated_operations", 1) for s in plan_data.get("steps", [])
            )),
            "phases": plan_data.get("phases", []),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "status": "draft",  # draft → confirmed → executing → completed
            "steps": steps,
            "architecture": plan_data.get("architecture", {}),
        }

        self._save(session_id, plan)
        return plan

    def load_plan(self, session_id: str) -> Optional[dict]:
        """Load the active plan for this session

        Returns:
            plan dict, or None if not found
        """
        path = self._plan_path(session_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def update_step(
        self,
        session_id: str,
        step_id: str,
        status: str,
        result_summary: Optional[str] = None,
    ) -> Optional[dict]:
        """Update the status of a single step

        Args:
            session_id: session ID
            step_id: step ID
            status: new status ("running" | "done" | "error")
            result_summary: optional result summary

        Returns:
            Updated plan dict, or None if the plan does not exist
        """
        plan = self.load_plan(session_id)
        if not plan:
            return None

        for step in plan["steps"]:
            if step["id"] == step_id:
                step["status"] = status
                if result_summary is not None:
                    step["result_summary"] = result_summary
                break

        # Check whether everything is done
        all_done = all(s["status"] in ("done", "error") for s in plan["steps"])
        if all_done:
            plan["status"] = "completed"
        elif any(s["status"] == "running" for s in plan["steps"]):
            plan["status"] = "executing"

        self._save(session_id, plan)
        return plan

    def confirm_plan(self, session_id: str) -> Optional[dict]:
        """Set plan status to confirmed"""
        plan = self.load_plan(session_id)
        if plan:
            plan["status"] = "confirmed"
            self._save(session_id, plan)
        return plan

    def reject_plan(self, session_id: str) -> Optional[dict]:
        """Set plan status to rejected"""
        plan = self.load_plan(session_id)
        if plan:
            plan["status"] = "rejected"
            self._save(session_id, plan)
        return plan

    def delete_plan(self, session_id: str):
        """Delete this session's plan file"""
        path = self._plan_path(session_id)
        path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Context injection (compact form)
    # ------------------------------------------------------------------

    def get_plan_for_context(self, session_id: str) -> str:
        """Generate a compact Plan context to inject into the LLM

        Contains only title + current progress + unfinished steps,
        minimizing token cost. Roughly 100-200 tokens.

        Returns:
            Formatted string, or empty string if no plan
        """
        plan = self.load_plan(session_id)
        if not plan or plan.get("status") in ("rejected", "draft"):
            return ""

        steps = plan.get("steps", [])
        if not steps:
            return ""

        done_count = sum(1 for s in steps if s["status"] == "done")
        total = len(steps)

        lines = [f"[Active Plan: {plan.get('title', 'Untitled')}]"]
        lines.append(f"Progress: {done_count}/{total} done")

        # Currently running step
        for s in steps:
            if s["status"] == "running":
                tools_str = ", ".join(s.get("tools", [])) if s.get("tools") else ""
                title = s.get("title", s.get("description", s["id"]))
                line = f'Current: {s["id"]} "{title}"'
                if tools_str:
                    line += f" (tools: {tools_str})"
                expected = s.get("expected_result", "")
                if expected:
                    line += f" | Expected: {expected}"
                fallback = s.get("fallback", "")
                if fallback:
                    line += f" | Fallback: {fallback}"
                lines.append(line)
                # Sub-step hint
                sub = s.get("sub_steps", [])
                if sub:
                    lines.append(f"  Sub-steps: {'; '.join(sub)}")
                break

        # Next pending step
        for s in steps:
            if s["status"] == "pending":
                deps = s.get("depends_on", [])
                title = s.get("title", s.get("description", s["id"]))
                line = f'Next: {s["id"]} "{title}"'
                if deps:
                    line += f" (depends_on: {', '.join(deps)})"
                lines.append(line)
                break

        # Remaining unfinished step count
        remaining = [s for s in steps if s["status"] == "pending"]
        if len(remaining) > 1:
            names = ", ".join(
                f'"{s.get("title", s.get("description", s["id"]))}"'
                for s in remaining[1:]
            )
            lines.append(f"Remaining: {names}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Tool registration info
    # ------------------------------------------------------------------

    @staticmethod
    def get_plan_tools() -> List[dict]:
        """Return the list of tool definitions specific to Plan mode"""
        return [PLAN_TOOL_CREATE, PLAN_TOOL_UPDATE_STEP, PLAN_TOOL_ASK_QUESTION]

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _save(self, session_id: str, plan: dict):
        path = self._plan_path(session_id)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(plan, f, ensure_ascii=False, indent=2)
        except OSError as e:
            _dbg(f"[PlanManager] Save error: {e}")


# ======================================================================
# Plan tool definitions (OpenAI Function Calling format)
# ======================================================================

PLAN_TOOL_CREATE = {
    "type": "function",
    "function": {
        "name": "create_plan",
        "description": (
            "Create a structured, engineering-grade execution plan for the user to review. "
            "The plan is displayed as an interactive card with DAG flow diagram. "
            "The user must confirm before execution begins.\n"
            "CRITICAL REQUIREMENTS:\n"
            "1. Every step MUST have depends_on set (even linear: step-2 depends_on step-1).\n"
            "2. Plans with 3+ steps MUST use phases for logical grouping.\n"
            "3. Each step needs detailed description with specific node paths, param names, values.\n"
            "4. steps.tools must list the exact Houdini tool names to use.\n"
            "5. depends_on drives the DAG layout — without it the flow diagram will be broken."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Plan title (concise, describes the goal)",
                },
                "overview": {
                    "type": "string",
                    "description": "Brief overview of the plan approach",
                },
                "complexity": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Overall complexity assessment",
                },
                "estimated_total_operations": {
                    "type": "integer",
                    "description": "Estimated total number of tool operations across all steps",
                },
                "phases": {
                    "type": "array",
                    "description": "REQUIRED for plans with 3+ steps. Group steps into logical phases. Each phase represents a logical stage (e.g., 'Phase 1: Base Setup'). All step IDs must be covered.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Phase name, e.g. 'Phase 1: Base Geometry'",
                            },
                            "step_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of step IDs belonging to this phase",
                            },
                        },
                        "required": ["name", "step_ids"],
                    },
                },
                "steps": {
                    "type": "array",
                    "description": "Ordered list of execution steps with detailed breakdown",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Unique step ID, e.g. 'step-1'",
                            },
                            "title": {
                                "type": "string",
                                "description": "Short step title for display",
                            },
                            "description": {
                                "type": "string",
                                "description": "Detailed description including specific node paths, parameter names and values",
                            },
                            "sub_steps": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Atomic sub-operations within this step",
                            },
                            "tools": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Houdini tools to use in this step",
                            },
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "REQUIRED: IDs of steps this depends on. Must be set for every step except the first. Linear: [\"step-1\"] for step-2. Parallel branches share common ancestor.",
                            },
                            "expected_result": {
                                "type": "string",
                                "description": "Verifiable expected outcome after this step completes",
                            },
                            "risk": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                                "description": "Risk level of this step",
                            },
                            "estimated_operations": {
                                "type": "integer",
                                "description": "Estimated number of tool operations in this step",
                            },
                            "fallback": {
                                "type": "string",
                                "description": "Fallback strategy if the primary approach fails",
                            },
                            "notes": {
                                "type": "string",
                                "description": "Technical notes or important considerations",
                            },
                        },
                        "required": ["id", "title", "description", "tools", "expected_result"],
                    },
                },
                "architecture": {
                    "type": "object",
                    "description": (
                        "REQUIRED: Describes the target Houdini node network architecture "
                        "that will be built/modified by this plan. This is the design blueprint, "
                        "NOT the execution steps. It shows what the final node graph looks like."
                    ),
                    "properties": {
                        "nodes": {
                            "type": "array",
                            "description": "All Houdini nodes in the target network",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {
                                        "type": "string",
                                        "description": "Unique node identifier (use the actual node name, e.g. 'grid1', 'mountain1')",
                                    },
                                    "label": {
                                        "type": "string",
                                        "description": "Display label (node type or descriptive name, e.g. 'Grid SOP', 'Mountain', 'Scatter')",
                                    },
                                    "type": {
                                        "type": "string",
                                        "enum": ["sop", "obj", "mat", "vop", "rop", "dop", "lop", "cop", "chop", "out", "subnet", "null", "other"],
                                        "description": "Houdini node category for visual styling",
                                    },
                                    "group": {
                                        "type": "string",
                                        "description": "Logical group name for visual grouping (e.g. 'Terrain', 'Scatter System', 'Materials')",
                                    },
                                    "is_new": {
                                        "type": "boolean",
                                        "description": "True if this node will be created by the plan; false if it already exists",
                                    },
                                    "params": {
                                        "type": "string",
                                        "description": "Key parameters to set (brief, e.g. 'Height=2, Noise=Perlin')",
                                    },
                                },
                                "required": ["id", "label", "type"],
                            },
                        },
                        "connections": {
                            "type": "array",
                            "description": "Connections between nodes (output → input)",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "from": {
                                        "type": "string",
                                        "description": "Source node ID",
                                    },
                                    "to": {
                                        "type": "string",
                                        "description": "Destination node ID",
                                    },
                                    "label": {
                                        "type": "string",
                                        "description": "Optional connection label (e.g. input index or semantic label like 'template')",
                                    },
                                },
                                "required": ["from", "to"],
                            },
                        },
                        "groups": {
                            "type": "array",
                            "description": "Visual grouping of nodes into logical sections",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "Group display name (e.g. 'Terrain Generation', 'Scatter System')",
                                    },
                                    "node_ids": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "Node IDs belonging to this group",
                                    },
                                    "color": {
                                        "type": "string",
                                        "description": "Optional hint color for the group (e.g. 'blue', 'green', 'purple')",
                                    },
                                },
                                "required": ["name", "node_ids"],
                            },
                        },
                    },
                    "required": ["nodes", "connections"],
                },
            },
            "required": ["title", "overview", "steps", "architecture"],
        },
    },
}

PLAN_TOOL_UPDATE_STEP = {
    "type": "function",
    "function": {
        "name": "update_plan_step",
        "description": (
            "Update the status of a plan step. Call this BEFORE starting a step "
            "(status='running') and AFTER completing it (status='done' or 'error'). "
            "This keeps the plan UI in sync with progress."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "step_id": {
                    "type": "string",
                    "description": "The step ID to update, e.g. 'step-1'",
                },
                "status": {
                    "type": "string",
                    "enum": ["running", "done", "error"],
                    "description": "New status for the step",
                },
                "result_summary": {
                    "type": "string",
                    "description": "Brief summary of what was done (for 'done') or what went wrong (for 'error')",
                },
            },
            "required": ["step_id", "status"],
        },
    },
}


PLAN_TOOL_ASK_QUESTION = {
    "type": "function",
    "function": {
        "name": "ask_question",
        "description": (
            "Ask the user clarifying questions before creating the plan. "
            "Use this when information is insufficient, ambiguous, or when multiple "
            "significantly different implementation approaches exist. "
            "Ask at most 1-2 key questions per call. Do not over-ask."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "description": "List of questions to ask (max 2)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Unique question ID, e.g. 'q1'",
                            },
                            "prompt": {
                                "type": "string",
                                "description": "The question text to display",
                            },
                            "options": {
                                "type": "array",
                                "description": "Selectable options for this question",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {
                                            "type": "string",
                                            "description": "Option ID",
                                        },
                                        "label": {
                                            "type": "string",
                                            "description": "Option display text",
                                        },
                                    },
                                    "required": ["id", "label"],
                                },
                            },
                            "allow_multiple": {
                                "type": "boolean",
                                "description": "If true, user can select multiple options (checkbox). Default false (radio).",
                            },
                            "allow_free_text": {
                                "type": "boolean",
                                "description": "If true, show a free text input for custom answer. Default false.",
                            },
                        },
                        "required": ["id", "prompt", "options"],
                    },
                },
            },
            "required": ["questions"],
        },
    },
}


# ======================================================================
# Singleton
# ======================================================================

_instance: Optional[PlanManager] = None


def get_plan_manager(cache_dir: Optional[Path] = None) -> PlanManager:
    """Get the PlanManager singleton"""
    global _instance
    if _instance is None:
        _instance = PlanManager(cache_dir)
    return _instance
