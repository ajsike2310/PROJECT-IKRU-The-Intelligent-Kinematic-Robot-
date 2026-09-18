"""
===============================================================================
PROJECT IKRU — Qdrant Vector Memory Store
===============================================================================
Provides semantic long-term memory using Qdrant's embedded local storage and
FastEmbed for CPU-based text embeddings. Enables associative recall: given a
new query, retrieves the most semantically similar past memories.
===============================================================================
"""

import os
import uuid
import threading
from datetime import datetime


class QdrantMemory:
    """
    Qdrant-backed vector store for IKRU's semantic long-term memory.
    Runs in local embedded file mode (no Docker/server required).
    Uses fastembed (BAAI/bge-small-en-v1.5, 384-dim) for text embeddings.
    """

    COLLECTION_NAME = "ikru_longterm_memory"
    EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
    VECTOR_DIM = 384

    def __init__(self, storage_path="data/memory/qdrant"):
        self.storage_path = storage_path
        os.makedirs(storage_path, exist_ok=True)
        self._lock = threading.Lock()
        self._client = None
        self._embedder = None
        self._ready = False
        self._init_thread = threading.Thread(target=self._lazy_init, daemon=True)
        self._init_thread.start()

    def _lazy_init(self):
        """Initializes Qdrant client and fastembed model in background."""
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            self._client = QdrantClient(path=self.storage_path)

            # Create collection if it doesn't exist
            collections = [c.name for c in self._client.get_collections().collections]
            if self.COLLECTION_NAME not in collections:
                self._client.create_collection(
                    collection_name=self.COLLECTION_NAME,
                    vectors_config=VectorParams(
                        size=self.VECTOR_DIM,
                        distance=Distance.COSINE
                    )
                )
                print(f"[Memory] Created Qdrant collection: {self.COLLECTION_NAME}")

            # Initialize fastembed model
            from fastembed import TextEmbedding
            self._embedder = TextEmbedding(model_name=self.EMBEDDING_MODEL)

            self._ready = True
            count = self._client.count(self.COLLECTION_NAME).count
            print(f"[Memory] Qdrant vector memory ready ({count} memories indexed)")

        except Exception as e:
            print(f"[Memory] Warning: Qdrant initialization failed: {e}")
            self._ready = False

    def _wait_ready(self, timeout=30):
        """Waits for background initialization to finish."""
        self._init_thread.join(timeout=timeout)
        return self._ready

    def _embed(self, text):
        """Generates embedding vector for a text string."""
        if not self._embedder:
            return None
        embeddings = list(self._embedder.embed([text]))
        if embeddings:
            return embeddings[0].tolist()
        return None

    # ================================================================
    # MEMORY STORAGE
    # ================================================================

    def add_memory(self, text, metadata=None):
        """
        Stores a text memory with its vector embedding in Qdrant.
        
        Args:
            text: The text content to remember.
            metadata: Optional dict with keys like 'role', 'type', 'timestamp'.
        """
        if not self._wait_ready():
            return False

        vector = self._embed(text)
        if not vector:
            return False

        if metadata is None:
            metadata = {}

        payload = {
            "text": text,
            "timestamp": metadata.get("timestamp", datetime.now().isoformat()),
            "role": metadata.get("role", "unknown"),
            "type": metadata.get("type", "conversation"),
            **{k: v for k, v in metadata.items() if k not in ("text", "timestamp", "role", "type")}
        }

        point_id = str(uuid.uuid4())

        with self._lock:
            try:
                from qdrant_client.models import PointStruct
                self._client.upsert(
                    collection_name=self.COLLECTION_NAME,
                    points=[
                        PointStruct(
                            id=point_id,
                            vector=vector,
                            payload=payload
                        )
                    ]
                )
                return True
            except Exception as e:
                print(f"[Memory] Error storing vector memory: {e}")
                return False

    # ================================================================
    # SEMANTIC RECALL
    # ================================================================

    def search_memories(self, query, top_k=3, score_threshold=0.55):
        """
        Retrieves the most semantically similar memories to the query.

        Args:
            query: The search query text.
            top_k: Maximum number of results.
            score_threshold: Minimum cosine similarity score (0.0 to 1.0).

        Returns:
            List of dicts with 'text', 'score', 'timestamp', 'role', 'type'.
        """
        if not self._wait_ready():
            return []

        vector = self._embed(query)
        if not vector:
            return []

        with self._lock:
            try:
                results = self._client.query_points(
                    collection_name=self.COLLECTION_NAME,
                    query=vector,
                    limit=top_k,
                    score_threshold=score_threshold
                ).points

                memories = []
                for r in results:
                    memories.append({
                        "text": r.payload.get("text", ""),
                        "score": r.score,
                        "timestamp": r.payload.get("timestamp", ""),
                        "role": r.payload.get("role", ""),
                        "type": r.payload.get("type", "")
                    })
                return memories

            except Exception as e:
                print(f"[Memory] Error searching vector memory: {e}")
                return []

    # ================================================================
    # MAINTENANCE
    # ================================================================

    def get_count(self):
        """Returns the total number of indexed memories."""
        if not self._wait_ready():
            return 0
        try:
            return self._client.count(self.COLLECTION_NAME).count
        except Exception:
            return 0

    def clear_all(self):
        """Deletes and recreates the vector collection."""
        if not self._wait_ready():
            return
        with self._lock:
            try:
                from qdrant_client.models import Distance, VectorParams
                self._client.delete_collection(self.COLLECTION_NAME)
                self._client.create_collection(
                    collection_name=self.COLLECTION_NAME,
                    vectors_config=VectorParams(
                        size=self.VECTOR_DIM,
                        distance=Distance.COSINE
                    )
                )
                print("[Memory] Vector memory cleared and recreated.")
            except Exception as e:
                print(f"[Memory] Error clearing vector memory: {e}")
