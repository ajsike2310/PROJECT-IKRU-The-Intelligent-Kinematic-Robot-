"""
===============================================================================
PROJECT IKRU — Memory Manager (Orchestrator)
===============================================================================
Coordinates SQLite (relational history) and Qdrant (semantic vectors) into a
unified memory interface. Handles context assembly, automatic fact extraction,
and background indexing.
===============================================================================
"""

import re
import json
import threading
from datetime import datetime
from .database import SQLiteStore
from .vector_store import QdrantMemory


# Heuristic patterns for automatic fact extraction from user messages
# Tuple format: (regex_pattern, category, template, case_sensitive)
# case_sensitive=True means match against original text (for names)
FACT_PATTERNS = [
    # Name detection — trigger words case-insensitive, but name must be Capitalized
    (r"(?i:my name is|i'm called|call me)\s+([A-Z][a-z]+)(?:\s+([A-Z][a-z]+))?\b", "personal", "User's name is {0}", True),
    # Age
    (r"i(?:'| a)?m\s+(\d{1,3})\s+years?\s+old", "personal", "User is {0} years old", False),
    # Location
    (r"i\s+live\s+in\s+(.+?)(?:\.|,|$)", "personal", "User lives in {0}", False),
    (r"i(?:'| a)?m\s+from\s+(.+?)(?:\.|,|$)", "personal", "User is from {0}", False),
    # Preferences — stop at 'and', punctuation, or end
    (r"(?:i (?:really )?(?:love|like|enjoy|prefer|adore))\s+(\w+(?:\s+\w+){0,2}?)(?:\s+and\s+|\.|!|,|$)", "preference", "User likes {0}", False),
    (r"(?:i (?:really )?(?:hate|dislike|don't like|can't stand))\s+(\w+(?:\s+\w+){0,2}?)(?:\s+and\s+|\.|!|,|$)", "preference", "User dislikes {0}", False),
    # Favorite X is Y — capture single word value
    (r"my (?:fav(?:ou?rite)?|preferred)\s+(\w+)\s+is\s+(\w+)\b", "preference", "User's favorite {0} is {1}", False),
    # Occupation / Role
    (r"i(?:'| a)?m\s+a\s+(student|teacher|engineer|developer|designer|doctor|artist|musician|writer|scientist|researcher|programmer)\b", "personal", "User is a {0}", False),
    (r"i\s+(?:work|study)\s+(?:as|at|in)\s+(.+?)(?:\.|,|$)", "personal", "User works/studies in {0}", False),
    # Pets
    (r"(?:i have|my)\s+(?:a\s+)?(\w+)\s+(?:named?|called)\s+(\w+)", "personal", "User has a {0} named {1}", False),
    # Explicit remember requests
    (r"(?:remember|note|keep in mind|don't forget)\s+(?:that\s+)?(.+?)(?:\.|!|$)", "general", "{0}", False),
]


class MemoryManager:
    """
    Unified memory orchestrator combining SQLite and Qdrant for IKRU.
    
    Provides:
    - Automatic conversation persistence (SQLite).
    - Semantic long-term recall via vector search (Qdrant).
    - Automatic user fact extraction from conversation.
    - Context assembly for LLM prompt injection.
    """

    def __init__(self, db_path="data/memory/ikru_history.db", qdrant_path="data/memory/qdrant"):
        self.db = SQLiteStore(db_path=db_path)
        self.vector = QdrantMemory(storage_path=qdrant_path)
        print("[Memory] MemoryManager initialized (SQLite + Qdrant)")

    # ================================================================
    # CONVERSATION RECORDING
    # ================================================================

    def record_user_message(self, content, visual_context=None):
        """Records a user message to SQLite and indexes it in Qdrant."""
        self.db.save_message(
            role="user",
            content=content,
            visual_context=visual_context
        )

        # Background vector indexing (non-blocking)
        threading.Thread(
            target=self._index_memory,
            args=(content, "user", "conversation"),
            daemon=True
        ).start()

        # Background fact extraction
        threading.Thread(
            target=self._extract_facts,
            args=(content,),
            daemon=True
        ).start()

    def record_assistant_message(self, content, tools_used=None):
        """Records an assistant response to SQLite and indexes it in Qdrant."""
        tools_str = json.dumps(tools_used) if tools_used else None
        self.db.save_message(
            role="assistant",
            content=content,
            tools_used=tools_str
        )

        # Background vector indexing
        threading.Thread(
            target=self._index_memory,
            args=(content, "assistant", "conversation"),
            daemon=True
        ).start()

    def _index_memory(self, text, role, memory_type):
        """Indexes a text into Qdrant vector store (waits for Qdrant readiness)."""
        if len(text.strip()) < 10:
            return
        # Wait for Qdrant lazy init to finish before indexing
        if not self.vector._wait_ready(timeout=120):
            return
        self.vector.add_memory(text, metadata={
            "role": role,
            "type": memory_type,
            "timestamp": datetime.now().isoformat()
        })

    # ================================================================
    # AUTOMATIC FACT EXTRACTION
    # ================================================================

    def _extract_facts(self, user_text):
        """Scans user text for identity/preference facts and stores them."""
        original_text = user_text.strip()
        text_lower = original_text.lower()
        for pattern, category, template, case_sensitive in FACT_PATTERNS:
            # Use original text for case-sensitive patterns (name detection)
            search_text = original_text if case_sensitive else text_lower
            flags = 0 if case_sensitive else re.IGNORECASE
            match = re.search(pattern, search_text, flags)
            if match:
                groups = [g for g in match.groups() if g is not None]
                if not groups:
                    continue
                # Capitalize names properly
                if category == "personal" and "name" in template.lower():
                    groups = [g.title() for g in groups]
                    # Join first + last name if both captured
                    if len(groups) == 2:
                        fact = f"User's name is {groups[0]} {groups[1]}".strip()
                    else:
                        fact = template.format(*groups).strip()
                else:
                    fact = template.format(*groups).strip()
                if len(fact) > 5:
                    self.db.save_fact(fact=fact, category=category)
                    # Also index fact as a high-value vector memory
                    self.vector.add_memory(
                        f"[User Fact] {fact}",
                        metadata={"role": "system", "type": "fact"}
                    )
                    print(f"[Memory] Extracted fact: {fact}")

    def save_explicit_fact(self, fact, category="general"):
        """Manually stores a fact about the user."""
        self.db.save_fact(fact=fact, category=category)
        self.vector.add_memory(
            f"[User Fact] {fact}",
            metadata={"role": "system", "type": "fact"}
        )

    # ================================================================
    # CONTEXT ASSEMBLY (FOR LLM PROMPT INJECTION)
    # ================================================================

    def build_memory_context(self, user_query, top_k=3, score_threshold=0.55):
        """
        Assembles an augmented memory context string for LLM injection.
        
        Retrieves:
        1. Semantically similar past memories from Qdrant.
        2. All stored user facts from SQLite.
        
        Returns:
            str: Formatted memory context block, or empty string if no memories.
        """
        context_parts = []

        # 1. Semantic recall from Qdrant
        recalled = self.vector.search_memories(
            query=user_query,
            top_k=top_k,
            score_threshold=score_threshold
        )

        if recalled:
            memory_lines = []
            for mem in recalled:
                ts = mem.get("timestamp", "")
                text = mem.get("text", "")
                score = mem.get("score", 0)
                # Format timestamp as relative if possible
                try:
                    dt = datetime.fromisoformat(ts)
                    delta = datetime.now() - dt
                    if delta.days == 0:
                        time_label = "Earlier today"
                    elif delta.days == 1:
                        time_label = "Yesterday"
                    elif delta.days < 7:
                        time_label = f"{delta.days} days ago"
                    else:
                        time_label = dt.strftime("%b %d")
                except Exception:
                    time_label = "Previously"
                memory_lines.append(f"  - ({time_label}, relevance {score:.0%}): {text}")

            context_parts.append(
                "[Recalled Long-Term Memories:\n" +
                "\n".join(memory_lines) +
                "]"
            )

        # 2. Structured user facts from SQLite
        facts = self.db.get_all_facts()
        if facts:
            fact_lines = [f"  - {f['fact']}" for f in facts[:10]]
            context_parts.append(
                "[Known User Facts:\n" +
                "\n".join(fact_lines) +
                "]"
            )

        if context_parts:
            return "\n".join(context_parts)

        return ""

    # ================================================================
    # DIAGNOSTICS & MAINTENANCE
    # ================================================================

    def get_stats(self):
        """Returns combined memory statistics."""
        db_stats = self.db.get_stats()
        vector_count = self.vector.get_count()
        return {
            **db_stats,
            "vector_memories": vector_count
        }

    def clear_all(self):
        """Wipes all memory (SQLite + Qdrant)."""
        self.db.clear_all()
        self.vector.clear_all()
        print("[Memory] All memory cleared.")
