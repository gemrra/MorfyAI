# -*- coding: utf-8 -*-
"""
Reward Engine

After each task completes, compute a reward score that drives memory
reinforcement/decay. Inspired by the human dopamine system:
- Success -> reinforce
- Failure -> decay
- Mistake then correction -> extra reinforcement (the brain is especially
  sensitive to error correction)
- Time decay -> old memories fade naturally
"""

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .memory_store import MemoryStore, EpisodicRecord, get_memory_store

# ============================================================
# Reward weight configuration
# ============================================================

@dataclass
class RewardWeights:
    """Weights used for reward calculation"""
    success: float = 0.4        # task success weight
    efficiency: float = 0.25    # efficiency weight
    novelty: float = 0.15       # novelty weight
    error_penalty: float = 0.2  # error-penalty weight


# ============================================================
# Reward engine
# ============================================================

class RewardEngine:
    """Compute task reward score and update memory importance"""

    def __init__(self, store: Optional[MemoryStore] = None, weights: Optional[RewardWeights] = None):
        self.store = store or get_memory_store()
        self.weights = weights or RewardWeights()
        # Importance update thresholds
        self.strengthen_threshold = 0.6   # reward > this -> reinforce
        self.weaken_threshold = 0.3       # reward < this -> decay
        # Reinforcement / decay factors
        self.strengthen_factor = 1.2
        self.weaken_factor = 0.8
        self.error_correction_factor = 1.5  # extra reinforcement after correcting an error

    # ==========================================================
    # Core: compute Reward Score
    # ==========================================================

    def calculate_reward(
        self,
        success: bool,
        error_count: int = 0,
        retry_count: int = 0,
        tool_call_count: int = 0,
        had_error_correction: bool = False,
        task_embedding=None,
    ) -> float:
        """Compute the reward score for a task (0~1)

        Args:
            success: whether the task completed successfully
            error_count: number of errors
            retry_count: number of retries
            tool_call_count: total number of tool calls
            had_error_correction: whether an "error -> correction -> success" cycle occurred
            task_embedding: task embedding (used to compute novelty)

        Returns:
            reward score (0~1)
        """
        w = self.weights

        # 1. Success score
        success_score = 1.0 if success else 0.0

        # 2. Efficiency score (inverse of tool calls and retries — fewer is more efficient)
        if tool_call_count <= 0:
            tool_call_count = 1
        efficiency_score = 1.0 / (1.0 + 0.1 * tool_call_count + 0.3 * retry_count)

        # 3. Novelty score (inverse of the max similarity against existing memories)
        novelty_score = self._calculate_novelty(task_embedding)

        # 4. Error penalty
        error_penalty = min(1.0, error_count * 0.2)

        # Weighted combination
        reward = (
            w.success * success_score
            + w.efficiency * efficiency_score
            + w.novelty * novelty_score
            - w.error_penalty * error_penalty
        )

        # Bonus for correcting an earlier error
        if had_error_correction and success:
            reward = min(1.0, reward * 1.2)

        # Clip to [0, 1]
        reward = max(0.0, min(1.0, reward))

        return reward

    def _calculate_novelty(self, task_embedding) -> float:
        """Compute the novelty of a task

        Inverse of the maximum similarity against the most recent N memories.
        New task -> high novelty -> higher reward.
        """
        if task_embedding is None:
            return 0.5  # default to medium novelty

        recent = self.store.get_recent_episodic(limit=20)
        if not recent:
            return 1.0  # no historical memory -> fully novel

        max_sim = 0.0
        from .embedding import get_embedder
        embedder = get_embedder()
        for ep in recent:
            if ep.embedding is not None:
                sim = embedder.cosine_similarity(task_embedding, ep.embedding)
                max_sim = max(max_sim, sim)

        # Novelty = 1 - max similarity
        return max(0.0, 1.0 - max_sim)

    # ==========================================================
    # Memory importance updates
    # ==========================================================

    def update_importance(self, record: EpisodicRecord, reward: float) -> float:
        """Update memory importance based on the reward

        Args:
            record: episodic memory record
            reward: previously computed reward score

        Returns:
            Updated importance value
        """
        importance = record.importance

        # Reinforce / decay based on reward
        if reward >= self.strengthen_threshold:
            importance *= self.strengthen_factor
        elif reward < self.weaken_threshold:
            importance *= self.weaken_factor

        # Extra reinforcement after error correction
        if "error_correction" in record.tags:
            importance *= self.error_correction_factor

        # Upper / lower bounds
        importance = max(0.01, min(5.0, importance))

        # Write back to the database
        self.store.update_episodic_reward(record.id, reward, importance)

        return importance

    # ==========================================================
    # Global time decay
    # ==========================================================

    def apply_time_decay(self, lambda_decay: float = 0.01):
        """Apply time decay to all episodic memories

        importance *= exp(-lambda * days_since_creation)
        """
        self.store.decay_importance(lambda_decay)

    # ==========================================================
    # Full post-task processing
    # ==========================================================

    def process_task_completion(
        self,
        episodic_record: EpisodicRecord,
        tool_call_count: int = 0,
    ) -> Dict:
        """Full post-task reward processing pipeline

        Args:
            episodic_record: episodic memory created for the task; reward not yet computed
            tool_call_count: total tool call count

        Returns:
            Processing result dict
        """
        # Detect whether an error-correction sequence occurred
        had_error_correction = "error_correction" in episodic_record.tags

        # Compute reward
        reward = self.calculate_reward(
            success=episodic_record.success,
            error_count=episodic_record.error_count,
            retry_count=episodic_record.retry_count,
            tool_call_count=tool_call_count,
            had_error_correction=had_error_correction,
            task_embedding=episodic_record.embedding,
        )

        # Update importance
        new_importance = self.update_importance(episodic_record, reward)

        # Periodic global decay (runs every 10 tasks)
        total = self.store.count_episodic()
        if total % 10 == 0:
            self.apply_time_decay()

        return {
            "reward": reward,
            "importance": new_importance,
            "had_error_correction": had_error_correction,
            "total_episodes": total,
        }


# ============================================================
# Global singleton
# ============================================================

_engine_instance: Optional[RewardEngine] = None

def get_reward_engine() -> RewardEngine:
    """Get the global RewardEngine instance"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = RewardEngine()
    return _engine_instance
