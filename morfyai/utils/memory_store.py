# -*- coding: utf-8 -*-
"""
three-tier memory store module (Memory Store)

use SQLite + thisplace Embedding realnow: 
- Episodic Memory  (episodic memory: concrete experience)
- Semantic Memory  (abstract knowledge: reflectiongeneratedexperiencerule)
- Procedural Memory (strategic memory: problem-solving recipe)

vector retrievaluse numpy cosine similarity (memory entrythroughcommon <10000 item, noneeds FAISS) . 
"""

import json
import math
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None

import numpy as np

from .embedding import get_embedder, LocalEmbedder, EMBEDDING_DIM

# ============================================================
# datalibrarypath
# ============================================================

_DB_DIR = Path(__file__).parent.parent.parent / "cache" / "memory"
_DB_PATH = _DB_DIR / "agent_memory.db"

# ============================================================
# dataclass
# ============================================================

@dataclass
class EpisodicRecord:
    """episodic memory record"""
    id: str = ""
    timestamp: float = 0.0
    session_id: str = ""
    task_description: str = ""
    actions: List[dict] = field(default_factory=list)     # toolcallordercolumn
    result_summary: str = ""
    success: bool = True
    error_count: int = 0
    retry_count: int = 0
    reward_score: float = 0.0
    embedding: Optional[np.ndarray] = None
    importance: float = 1.0
    tags: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.timestamp == 0.0:
            self.timestamp = time.time()


# Usage-category constants
MEMORY_CATEGORIES = (
    "preference",     # day-to-day preferences (code style, output language, format)
    "command",        # build commands (compile, test, deploy, etc.)
    "debug",          # debug patterns (debug approach and path)
    "pitfall",        # pitfall log (special limits and gotchas)
    "workflow",       # workflow patterns (node wiring, operation sequence)
    "knowledge",      # technical knowledge (node usage, VEX syntax)
    "user_profile",   # user profile (work domain, skill level)
    "general",        # other generic experience
)

# Abstraction-level constants (6 tiers)
ABSTRACTION_LEVELS = {
    0: "core_identity",   # core identity: user identity, core preferences, language habits (very few, highly refined)
    1: "core_preference",  # core preferences: code style, format preferences, interaction habits
    2: "experience_rule",  # experience rules: reusable experience, best practices, debug approaches
    3: "workflow_pattern",  # workflow patterns: concrete workflows, command sequences, node wiring
    4: "specific_case",    # concrete cases: specific-task success/failure records, pitfall details
    5: "raw_detail",       # raw details: conversation snippets, parameter details, ephemeral records
}


@dataclass
class SemanticRecord:
    """abstract knowledgerecord"""
    id: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    rule: str = ""
    source_episodes: List[str] = field(default_factory=list)
    confidence: float = 0.5
    activation_count: int = 0
    embedding: Optional[np.ndarray] = None
    category: str = "general"  # preference / command / debug / pitfall / workflow / knowledge / user_profile / general
    abstraction_level: int = 2  # 0-5, default 2 (experiencerule) , see ABSTRACTION_LEVELS

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        now = time.time()
        if self.created_at == 0.0:
            self.created_at = now
        if self.updated_at == 0.0:
            self.updated_at = now


@dataclass
class ProceduralRecord:
    """strategic memory record"""
    id: str = ""
    strategy_name: str = ""
    description: str = ""
    priority: float = 0.5
    success_rate: float = 0.5
    usage_count: int = 0
    last_used: float = 0.0
    embedding: Optional[np.ndarray] = None
    conditions: List[str] = field(default_factory=list)   # suitusecondition

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.last_used == 0.0:
            self.last_used = time.time()


# ============================================================
# Memory Store coreclass
# ============================================================

class MemoryStore:
    """three-tier memory SQLite savestore + Embedding vector retrieval"""

    def __init__(self, db_path: Optional[Path] = None, embedder: Optional[LocalEmbedder] = None):
        self.db_path = db_path or _DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder or get_embedder()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    # ==========================================================
    # datalibraryinitialization
    # ==========================================================

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS episodic_memory (
                id TEXT PRIMARY KEY,
                timestamp REAL,
                session_id TEXT,
                task_description TEXT,
                actions TEXT,
                result_summary TEXT,
                success INTEGER,
                error_count INTEGER,
                retry_count INTEGER,
                reward_score REAL,
                embedding BLOB,
                importance REAL,
                tags TEXT
            );

            CREATE TABLE IF NOT EXISTS semantic_memory (
                id TEXT PRIMARY KEY,
                created_at REAL,
                updated_at REAL,
                rule TEXT,
                source_episodes TEXT,
                confidence REAL,
                activation_count INTEGER,
                embedding BLOB,
                category TEXT
            );

            CREATE TABLE IF NOT EXISTS procedural_memory (
                id TEXT PRIMARY KEY,
                strategy_name TEXT,
                description TEXT,
                priority REAL,
                success_rate REAL,
                usage_count INTEGER,
                last_used REAL,
                embedding BLOB,
                conditions TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_episodic_session ON episodic_memory(session_id);
            CREATE INDEX IF NOT EXISTS idx_episodic_timestamp ON episodic_memory(timestamp);
            CREATE INDEX IF NOT EXISTS idx_episodic_importance ON episodic_memory(importance);
            CREATE INDEX IF NOT EXISTS idx_semantic_category ON semantic_memory(category);
            CREATE INDEX IF NOT EXISTS idx_semantic_confidence ON semantic_memory(confidence);
            CREATE INDEX IF NOT EXISTS idx_procedural_priority ON procedural_memory(priority);
        """)
        conn.commit()
        # ── DB migration: add abstraction_level column (compatible witholddatalibrary)  ──
        self._migrate_add_abstraction_level(conn)

    @staticmethod
    def _migrate_add_abstraction_level(conn: sqlite3.Connection):
        """as semantic_memory tableadd abstraction_level column (compatible withold DB) """
        try:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(semantic_memory)").fetchall()]
            if "abstraction_level" not in cols:
                conn.execute("ALTER TABLE semantic_memory ADD COLUMN abstraction_level INTEGER DEFAULT 2")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_semantic_abstraction ON semantic_memory(abstraction_level)")
                conn.commit()
                _dbg("[MemoryStore] Migration: added abstraction_level column")
        except Exception as e:
            _dbg(f"[MemoryStore] Migration failed (non-fatal): {e}")

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ==========================================================
    # Episodic Memory CRUD
    # ==========================================================

    def add_episodic(self, record: EpisodicRecord) -> str:
        """writeoneitemepisodic memory"""
        # autocompute embedding
        if record.embedding is None:
            text = f"{record.task_description} {record.result_summary}"
            record.embedding = self.embedder.encode(text)

        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO episodic_memory
               (id, timestamp, session_id, task_description, actions,
                result_summary, success, error_count, retry_count,
                reward_score, embedding, importance, tags)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                record.id,
                record.timestamp,
                record.session_id,
                record.task_description,
                json.dumps(record.actions, ensure_ascii=False),
                record.result_summary,
                1 if record.success else 0,
                record.error_count,
                record.retry_count,
                record.reward_score,
                self.embedder.to_bytes(record.embedding),
                record.importance,
                json.dumps(record.tags, ensure_ascii=False),
            ),
        )
        conn.commit()
        return record.id

    def get_episodic(self, record_id: str) -> Optional[EpisodicRecord]:
        """based on ID getepisodic memory"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM episodic_memory WHERE id=?", (record_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_episodic(row)

    def get_recent_episodic(self, limit: int = 20) -> List[EpisodicRecord]:
        """getrecent episodic memory"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM episodic_memory ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [self._row_to_episodic(r) for r in rows]

    def search_episodic(self, query: str, top_k: int = 5, min_importance: float = 0.1) -> List[Tuple[EpisodicRecord, float]]:
        """vector retrievalepisodic memory

        Returns:
            [(record, similarity_score), ...] bysimilardegreelowerorder
        """
        query_vec = self.embedder.encode(query)
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM episodic_memory WHERE importance >= ? ORDER BY importance DESC",
            (min_importance,)
        ).fetchall()

        if not rows:
            return []

        results = []
        for row in rows:
            rec = self._row_to_episodic(row)
            if rec.embedding is not None:
                sim = self.embedder.cosine_similarity(query_vec, rec.embedding)
                # comprehensivemergepart = similardegree * importance permissionre
                combined = sim * (0.5 + 0.5 * min(rec.importance, 2.0))
                results.append((rec, combined))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def update_episodic_importance(self, record_id: str, new_importance: float):
        """updateepisodic memory reneeddegree"""
        conn = self._get_conn()
        conn.execute(
            "UPDATE episodic_memory SET importance=? WHERE id=?",
            (new_importance, record_id)
        )
        conn.commit()

    def update_episodic_reward(self, record_id: str, reward_score: float, importance: float):
        """updateepisodic memory  reward and importance"""
        conn = self._get_conn()
        conn.execute(
            "UPDATE episodic_memory SET reward_score=?, importance=? WHERE id=?",
            (reward_score, importance, record_id)
        )
        conn.commit()

    def update_episodic_tags(self, record_id: str, tags: List[str]):
        """updateepisodic memory  tags"""
        conn = self._get_conn()
        conn.execute(
            "UPDATE episodic_memory SET tags=? WHERE id=?",
            (json.dumps(tags, ensure_ascii=False), record_id)
        )
        conn.commit()

    def count_episodic(self) -> int:
        """statisticsepisodic memorytotal"""
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) FROM episodic_memory").fetchone()[0]

    def get_episodic_by_session(self, session_id: str) -> List[EpisodicRecord]:
        """getsome session  allepisodic memory"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM episodic_memory WHERE session_id=? ORDER BY timestamp ASC",
            (session_id,)
        ).fetchall()
        return [self._row_to_episodic(r) for r in rows]

    def delete_episodic(self, record_id: str) -> bool:
        """deleteoneitemepisodic memory"""
        conn = self._get_conn()
        cur = conn.execute("DELETE FROM episodic_memory WHERE id=?", (record_id,))
        conn.commit()
        return cur.rowcount > 0

    # ==========================================================
    # Semantic Memory CRUD
    # ==========================================================

    def add_semantic(self, record: SemanticRecord) -> str:
        """writeoneitemabstract knowledge"""
        if record.embedding is None:
            record.embedding = self.embedder.encode(record.rule)

        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO semantic_memory
               (id, created_at, updated_at, rule, source_episodes,
                confidence, activation_count, embedding, category, abstraction_level)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                record.id,
                record.created_at,
                record.updated_at,
                record.rule,
                json.dumps(record.source_episodes, ensure_ascii=False),
                record.confidence,
                record.activation_count,
                self.embedder.to_bytes(record.embedding),
                record.category,
                record.abstraction_level,
            ),
        )
        conn.commit()
        return record.id

    def get_semantic(self, record_id: str) -> Optional[SemanticRecord]:
        """based on ID getabstract knowledge"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM semantic_memory WHERE id=?", (record_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_semantic(row)

    def search_semantic(self, query: str, top_k: int = 5, min_confidence: float = 0.2) -> List[Tuple[SemanticRecord, float]]:
        """vector retrievalabstract knowledge"""
        query_vec = self.embedder.encode(query)
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM semantic_memory WHERE confidence >= ?",
            (min_confidence,)
        ).fetchall()

        if not rows:
            return []

        results = []
        for row in rows:
            rec = self._row_to_semantic(row)
            if rec.embedding is not None:
                sim = self.embedder.cosine_similarity(query_vec, rec.embedding)
                combined = sim * (0.5 + 0.5 * rec.confidence)
                results.append((rec, combined))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def get_all_semantic(self, category: Optional[str] = None) -> List[SemanticRecord]:
        """getallabstract knowledge (canbypartclassfilter) """
        conn = self._get_conn()
        if category:
            rows = conn.execute(
                "SELECT * FROM semantic_memory WHERE category=? ORDER BY confidence DESC",
                (category,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM semantic_memory ORDER BY confidence DESC"
            ).fetchall()
        return [self._row_to_semantic(r) for r in rows]

    def increment_semantic_activation(self, record_id: str):
        """addaddabstract knowledge activatetimecount"""
        conn = self._get_conn()
        conn.execute(
            "UPDATE semantic_memory SET activation_count = activation_count + 1, updated_at=? WHERE id=?",
            (time.time(), record_id)
        )
        conn.commit()

    def update_semantic_confidence(self, record_id: str, confidence: float):
        """updateabstract knowledge placeinfodegree"""
        conn = self._get_conn()
        conn.execute(
            "UPDATE semantic_memory SET confidence=?, updated_at=? WHERE id=?",
            (confidence, time.time(), record_id)
        )
        conn.commit()

    def find_duplicate_semantic(self, rule_text: str, threshold: float = 0.85) -> Optional[SemanticRecord]:
        """lookupwhetheralreadysaveinheightsimilar rule (goreuse) """
        results = self.search_semantic(rule_text, top_k=1, min_confidence=0.0)
        if results and results[0][1] >= threshold:
            return results[0][0]
        return None

    def delete_semantic(self, record_id: str):
        """deletespecifiedsemanticmemory"""
        conn = self._get_conn()
        conn.execute("DELETE FROM semantic_memory WHERE id=?", (record_id,))
        conn.commit()

    def count_semantic(self) -> int:
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) FROM semantic_memory").fetchone()[0]

    # ==========================================================
    # partlayermemorysearch (6 layerabstraction level) 
    # ==========================================================

    def get_core_memories(self, max_count: int = 5) -> List[SemanticRecord]:
        """get level=0 corememory, by confidence lowerorder, at most max_count item"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM semantic_memory WHERE abstraction_level = 0 ORDER BY confidence DESC LIMIT ?",
            (max_count,)
        ).fetchall()
        return [self._row_to_semantic(r) for r in rows]

    def search_by_level(
        self, query: str, level: int, top_k: int = 3,
        min_confidence: float = 0.2, threshold: float = 0.25,
    ) -> List[Tuple[SemanticRecord, float]]:
        """byspecifiedlayerlevelsearchmemory chunk

        Args:
            query: searchquery
            level: abstraction level (0-5)
            top_k: returnitemcountonlimit
            min_confidence: mostlowplaceinfodegreefilter
            threshold: mostlowsimilardegreethresholdvalue (willbased on embedding afterendautoscale) 

        Returns:
            [(record, similarity_score), ...] bycomprehensivemergepartlowerorder
        """
        query_vec = self.embedder.encode(query)
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM semantic_memory WHERE abstraction_level = ? AND confidence >= ?",
            (level, min_confidence)
        ).fetchall()

        if not rows:
            return []

        # ★ Fallback embedding (n-gram hash) has cosine-similarity values roughly in 0~0.4,
        #   far lower than sentence-transformers (0~1.0). Dynamically scale the threshold to match.
        effective_threshold = threshold
        if not self.embedder.is_semantic:
            effective_threshold = threshold * 0.2  # 0.25 → 0.05, 0.15 → 0.03

        results = []
        for row in rows:
            rec = self._row_to_semantic(row)
            if rec.embedding is not None:
                sim = self.embedder.cosine_similarity(query_vec, rec.embedding)
                if sim >= effective_threshold:
                    combined = sim * (0.5 + 0.5 * rec.confidence)
                    results.append((rec, combined))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def search_all_levels(
        self, query: str, category: Optional[str] = None,
        top_k: int = 5, min_confidence: float = 0.1,
    ) -> List[Tuple[SemanticRecord, float]]:
        """crosslayerlevelsearch (for search_memory tooluse) , canby category filter

        Args:
            query: searchquery
            category: usage-category filter (optional)
            top_k: returnitemcountonlimit
            min_confidence: mostlowplaceinfodegreefilter

        Returns:
            [(record, similarity_score), ...] bycomprehensivemergepartlowerorder
        """
        query_vec = self.embedder.encode(query)
        conn = self._get_conn()
        if category:
            rows = conn.execute(
                "SELECT * FROM semantic_memory WHERE category = ? AND confidence >= ?",
                (category, min_confidence)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM semantic_memory WHERE confidence >= ?",
                (min_confidence,)
            ).fetchall()

        if not rows:
            return []

        results = []
        for row in rows:
            rec = self._row_to_semantic(row)
            if rec.embedding is not None:
                sim = self.embedder.cosine_similarity(query_vec, rec.embedding)
                combined = sim * (0.5 + 0.5 * rec.confidence)
                results.append((rec, combined))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    # ==========================================================
    # Procedural Memory CRUD
    # ==========================================================

    def add_procedural(self, record: ProceduralRecord) -> str:
        """writeoneitemstrategic memory"""
        if record.embedding is None:
            text = f"{record.strategy_name}: {record.description}"
            record.embedding = self.embedder.encode(text)

        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO procedural_memory
               (id, strategy_name, description, priority, success_rate,
                usage_count, last_used, embedding, conditions)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                record.id,
                record.strategy_name,
                record.description,
                record.priority,
                record.success_rate,
                record.usage_count,
                record.last_used,
                self.embedder.to_bytes(record.embedding),
                json.dumps(record.conditions, ensure_ascii=False),
            ),
        )
        conn.commit()
        return record.id

    def get_procedural(self, record_id: str) -> Optional[ProceduralRecord]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM procedural_memory WHERE id=?", (record_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_procedural(row)

    def search_procedural(self, query: str, top_k: int = 3) -> List[Tuple[ProceduralRecord, float]]:
        """vector retrievalstrategic memory"""
        query_vec = self.embedder.encode(query)
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM procedural_memory ORDER BY priority DESC"
        ).fetchall()

        if not rows:
            return []

        results = []
        for row in rows:
            rec = self._row_to_procedural(row)
            if rec.embedding is not None:
                sim = self.embedder.cosine_similarity(query_vec, rec.embedding)
                combined = sim * (0.3 + 0.7 * rec.priority)
                results.append((rec, combined))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def get_all_procedural(self) -> List[ProceduralRecord]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM procedural_memory ORDER BY priority DESC"
        ).fetchall()
        return [self._row_to_procedural(r) for r in rows]

    def update_procedural_usage(self, record_id: str, success: bool):
        """updatestrategyusestatistics"""
        conn = self._get_conn()
        rec = self.get_procedural(record_id)
        if not rec:
            return
        rec.usage_count += 1
        rec.last_used = time.time()
        # Update success rate (sliding average)
        alpha = min(0.3, 1.0 / rec.usage_count)
        rec.success_rate = (1 - alpha) * rec.success_rate + alpha * (1.0 if success else 0.0)
        conn.execute(
            "UPDATE procedural_memory SET usage_count=?, last_used=?, success_rate=? WHERE id=?",
            (rec.usage_count, rec.last_used, rec.success_rate, record_id)
        )
        conn.commit()

    def update_procedural_priority(self, record_id: str, priority_delta: float):
        """adjustwholestrategypreferredlevel"""
        conn = self._get_conn()
        conn.execute(
            "UPDATE procedural_memory SET priority = MIN(1.0, MAX(0.0, priority + ?)) WHERE id=?",
            (priority_delta, record_id)
        )
        conn.commit()

    def count_procedural(self) -> int:
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) FROM procedural_memory").fetchone()[0]

    def delete_procedural(self, record_id: str) -> bool:
        """deleteoneitemstrategic memory"""
        conn = self._get_conn()
        cur = conn.execute("DELETE FROM procedural_memory WHERE id=?", (record_id,))
        conn.commit()
        return cur.rowcount > 0

    def get_procedural_by_name(self, name: str) -> Optional[ProceduralRecord]:
        """bystrategynamelookup"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM procedural_memory WHERE strategy_name=?", (name,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_procedural(row)

    # ==========================================================
    # Global importance decay
    # ==========================================================

    def decay_importance(self, lambda_decay: float = 0.01):
        """Apply time-based decay to every episodic memory.

        importance *= exp(-lambda * days_since_creation)
        """
        conn = self._get_conn()
        now = time.time()
        rows = conn.execute("SELECT id, timestamp, importance FROM episodic_memory").fetchall()
        for row_id, ts, imp in rows:
            days = (now - ts) / 86400.0
            new_imp = imp * math.exp(-lambda_decay * days)
            new_imp = max(new_imp, 0.01)  # don't go all the way to zero
            if abs(new_imp - imp) > 0.001:
                conn.execute(
                    "UPDATE episodic_memory SET importance=? WHERE id=?",
                    (new_imp, row_id)
                )
        conn.commit()

    # ==========================================================
    # statisticsinfo
    # ==========================================================

    def get_stats(self) -> Dict:
        """getmemorylibrarystatisticsinfo"""
        return {
            "episodic_count": self.count_episodic(),
            "semantic_count": self.count_semantic(),
            "procedural_count": self.count_procedural(),
            "backend": self.embedder._backend,
            "embedding_dim": self.embedder.dim,
        }

    # ==========================================================
    # withinparttoolmethod
    # ==========================================================

    def _row_to_episodic(self, row) -> EpisodicRecord:
        return EpisodicRecord(
            id=row[0],
            timestamp=row[1],
            session_id=row[2],
            task_description=row[3],
            actions=json.loads(row[4]) if row[4] else [],
            result_summary=row[5],
            success=bool(row[6]),
            error_count=row[7],
            retry_count=row[8],
            reward_score=row[9],
            embedding=self.embedder.from_bytes(row[10]) if row[10] else None,
            importance=row[11],
            tags=json.loads(row[12]) if row[12] else [],
        )

    def _row_to_semantic(self, row) -> SemanticRecord:
        return SemanticRecord(
            id=row[0],
            created_at=row[1],
            updated_at=row[2],
            rule=row[3],
            source_episodes=json.loads(row[4]) if row[4] else [],
            confidence=row[5],
            activation_count=row[6],
            embedding=self.embedder.from_bytes(row[7]) if row[7] else None,
            category=row[8],
            abstraction_level=row[9] if len(row) > 9 and row[9] is not None else 2,
        )

    def _row_to_procedural(self, row) -> ProceduralRecord:
        return ProceduralRecord(
            id=row[0],
            strategy_name=row[1],
            description=row[2],
            priority=row[3],
            success_rate=row[4],
            usage_count=row[5],
            last_used=row[6],
            embedding=self.embedder.from_bytes(row[7]) if row[7] else None,
            conditions=json.loads(row[8]) if row[8] else [],
        )

    # ==========================================================
    # initializationdefaultstrategy
    # ==========================================================

    def seed_default_strategies(self):
        """writedefaultstrategy (first timerunwhencall) """
        if self.count_procedural() > 0:
            return  # alreadyhasstrategy, skip

        defaults = [
            ProceduralRecord(
                strategy_name="decompose_complex_task",
                description="complexissueshouldthispartresolveasmultisubstep, one by onestepexecute",
                priority=0.7,
                conditions=["task_complexity > high", "tool_calls > 5"],
            ),
            ProceduralRecord(
                strategy_name="clarify_ambiguous_task",
                description="For ambiguous tasks, ask clarifying questions first; avoid blind execution.",
                priority=0.6,
                conditions=["task_clarity < low", "missing_parameters"],
            ),
            ProceduralRecord(
                strategy_name="multi_path_reasoning",
                description="For high-risk tasks, reason along multiple paths, compare alternatives, then pick the best.",
                priority=0.5,
                conditions=["risk_level > high", "irreversible_action"],
            ),
            ProceduralRecord(
                strategy_name="verify_before_modify",
                description="modifynodeorfileprevious, firstquerynowhasstructureconfirmstate",
                priority=0.65,
                conditions=["action_type == modify", "target_unknown"],
            ),
            ProceduralRecord(
                strategy_name="error_recovery",
                description="On error, analyze the error info and try an alternative approach instead of repeating the same operation.",
                priority=0.7,
                conditions=["error_occurred", "retry_count > 1"],
            ),
        ]

        for s in defaults:
            self.add_procedural(s)

        _dbg(f"[MemoryStore] Wrote {len(defaults)} default strategy(ies)")


# ============================================================
# globalsingleexample
# ============================================================

_store_instance: Optional[MemoryStore] = None

def get_memory_store() -> MemoryStore:
    """getglobal MemoryStore instance"""
    global _store_instance
    if _store_instance is None:
        _store_instance = MemoryStore()
        _store_instance.seed_default_strategies()
    return _store_instance
