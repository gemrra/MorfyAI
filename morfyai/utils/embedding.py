# -*- coding: utf-8 -*-
"""
Local Embedding wrapper module

Uses sentence-transformers' all-MiniLM-L6-v2 model to generate text vectors.
Prefers ONNX Runtime inference (lightweight), falls back to PyTorch.
Supports batch encoding, caching, and a fallback (TF-IDF style hash vectors)
when no model is available.

Vector dimension: 384 (all-MiniLM-L6-v2)
"""

import os
import hashlib
import numpy as np
from pathlib import Path
from typing import List, Optional, Union

# Route diagnostic prints to in-app Debug Console
try:
    from morfyai.utils.debug_log import log as _dbg
except Exception:
    _dbg = lambda *a, **kw: None

# ============================================================
# Constants
# ============================================================

# Default model name (HuggingFace hub)
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
# Vector dimension
EMBEDDING_DIM = 384
# Model cache directory
_MODEL_CACHE_DIR = Path(__file__).parent.parent.parent / "cache" / "memory" / "embeddings"

# ============================================================
# Global singleton
# ============================================================
_embedder_instance = None


class LocalEmbedder:
    """Local text Embedding encoder

    Load priority:
    1. sentence-transformers (best quality)
    2. Pure fallback: pseudo-vectors based on character n-grams
       (zero dependencies, limited quality but usable)
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, cache_dir: Optional[Path] = None):
        self.model_name = model_name
        self.cache_dir = cache_dir or _MODEL_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.dim = EMBEDDING_DIM
        self._model = None
        self._backend = "none"  # "sentence-transformers" | "fallback"
        self._encode_cache = {}  # small in-memory cache: hash -> vector
        self._max_cache = 2000

        self._try_load_model()

    # ==========================================================
    # Model loading
    # ==========================================================

    def _try_load_model(self):
        """Try to load the sentence-transformers model"""
        # 1. sentence-transformers
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(
                self.model_name,
                cache_folder=str(self.cache_dir),
            )
            self._backend = "sentence-transformers"
            self.dim = self._model.get_sentence_embedding_dimension()
            _dbg(f"[Embedding] Loaded: {self.model_name} (dim={self.dim}, backend=sentence-transformers)")
            return
        except ImportError:
            _dbg("[Embedding] sentence-transformers not installed")
        except Exception as e:
            _dbg(f"[Embedding] sentence-transformers load failed: {e}")

        # 2. Fallback: character n-gram pseudo-vectors
        self._backend = "fallback"
        self.dim = EMBEDDING_DIM
        _dbg(f"[Embedding] Using fallback mode (n-gram hash, dim={self.dim})")

    @property
    def is_semantic(self) -> bool:
        """Whether a true semantic model is in use (not fallback)"""
        return self._backend == "sentence-transformers"

    # ==========================================================
    # Encoding interface
    # ==========================================================

    def encode(self, text: str) -> np.ndarray:
        """Encode a single text into a vector

        Args:
            text: input text

        Returns:
            Normalized float32 vector, shape=(dim,)
        """
        if not text or not text.strip():
            return np.zeros(self.dim, dtype=np.float32)

        # In-memory cache
        cache_key = hashlib.md5(text.encode('utf-8', errors='ignore')).hexdigest()
        if cache_key in self._encode_cache:
            return self._encode_cache[cache_key]

        if self._backend == "sentence-transformers":
            vec = self._encode_st(text)
        else:
            vec = self._encode_fallback(text)

        # Normalize
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        vec = vec.astype(np.float32)

        # Write to cache (LRU-style size limit)
        if len(self._encode_cache) >= self._max_cache:
            # Drop the earliest 20%
            keys = list(self._encode_cache.keys())
            for k in keys[:len(keys) // 5]:
                del self._encode_cache[k]
        self._encode_cache[cache_key] = vec

        return vec

    def encode_batch(self, texts: List[str]) -> np.ndarray:
        """Batch encoding

        Args:
            texts: list of texts

        Returns:
            Normalized vector matrix of shape=(len(texts), dim)
        """
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)

        if self._backend == "sentence-transformers":
            return self._encode_batch_st(texts)

        # Fallback: encode one by one
        vecs = [self.encode(t) for t in texts]
        return np.array(vecs, dtype=np.float32)

    # ==========================================================
    # sentence-transformers encoding
    # ==========================================================

    def _encode_st(self, text: str) -> np.ndarray:
        """Encode a single text using sentence-transformers"""
        vec = self._model.encode(text, show_progress_bar=False, normalize_embeddings=True)
        return np.array(vec, dtype=np.float32)

    def _encode_batch_st(self, texts: List[str]) -> np.ndarray:
        """Batch encode using sentence-transformers"""
        vecs = self._model.encode(texts, show_progress_bar=False,
                                  normalize_embeddings=True, batch_size=32)
        return np.array(vecs, dtype=np.float32)

    # ==========================================================
    # Fallback: pseudo-vectors based on character n-grams
    # ==========================================================

    def _encode_fallback(self, text: str) -> np.ndarray:
        """Hash vector based on character 3-grams

        Not a true semantic vector, but captures lexical overlap.
        Acceptable quality for keyword-matching scenarios.
        """
        vec = np.zeros(self.dim, dtype=np.float32)
        text_lower = text.lower().strip()
        if not text_lower:
            return vec

        # Character 3-grams
        for i in range(len(text_lower) - 2):
            ngram = text_lower[i:i+3]
            # Deterministic hash -> vector position
            h = int(hashlib.md5(ngram.encode()).hexdigest(), 16)
            idx = h % self.dim
            vec[idx] += 1.0

        # Word-level unigrams (weighted higher)
        words = text_lower.split()
        for w in words:
            if len(w) >= 2:
                h = int(hashlib.md5(w.encode()).hexdigest(), 16)
                idx = h % self.dim
                vec[idx] += 2.0

        return vec

    # ==========================================================
    # Similarity computation
    # ==========================================================

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors

        Equivalent to dot product when vectors are normalized.
        """
        if a is None or b is None:
            return 0.0
        dot = np.dot(a, b)
        return float(np.clip(dot, -1.0, 1.0))

    @staticmethod
    def batch_cosine_similarity(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
        """Compute cosine similarity between query and each row of the matrix

        Args:
            query: shape=(dim,) query vector (normalized)
            matrix: shape=(n, dim) candidate vector matrix (normalized)

        Returns:
            shape=(n,) similarity array
        """
        if query is None or matrix is None or len(matrix) == 0:
            return np.array([], dtype=np.float32)
        scores = matrix @ query
        return np.clip(scores, -1.0, 1.0)

    # ==========================================================
    # Serialization helpers
    # ==========================================================

    @staticmethod
    def to_bytes(vec: np.ndarray) -> bytes:
        """Serialize a vector to bytes (for storing in SQLite BLOB)"""
        return vec.astype(np.float32).tobytes()

    @staticmethod
    def from_bytes(data: bytes, dim: int = EMBEDDING_DIM) -> np.ndarray:
        """Deserialize bytes back to a vector"""
        if not data:
            return np.zeros(dim, dtype=np.float32)
        return np.frombuffer(data, dtype=np.float32).copy()


# ============================================================
# Global singleton
# ============================================================

def get_embedder(model_name: str = DEFAULT_MODEL) -> LocalEmbedder:
    """Get the global Embedding encoder instance (singleton)"""
    global _embedder_instance
    if _embedder_instance is None:
        _embedder_instance = LocalEmbedder(model_name)
    return _embedder_instance
