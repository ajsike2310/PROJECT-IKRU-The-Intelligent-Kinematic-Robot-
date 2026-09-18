"""
===============================================================================
PROJECT IKRU — SQLite Persistent Memory Store
===============================================================================
Stores chronological chat history, session metadata, and structured user facts
in a local SQLite database for exact recall and persistent identity across
restarts.
===============================================================================
"""

import os
import sqlite3
import threading
from datetime import datetime


class SQLiteStore:
    """
    SQLite-backed relational storage for IKRU's episodic memory:
    - Full chronological chat message log (user + assistant).
    - Structured user facts table (name, preferences, settings).
    - Session tracking with timestamps.
    """

    def __init__(self, db_path="data/memory/ikru_history.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()
        self.session_id = self._create_session()

    def _get_conn(self):
        """Creates a new connection per call (thread-safe)."""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        """Creates tables if they don't exist."""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                        title TEXT
                    );

                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id INTEGER NOT NULL,
                        timestamp TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        visual_context TEXT,
                        tools_used TEXT,
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                    );

                    CREATE TABLE IF NOT EXISTS user_facts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        category TEXT NOT NULL DEFAULT 'general',
                        fact TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                        confidence REAL DEFAULT 1.0
                    );

                    CREATE INDEX IF NOT EXISTS idx_messages_session
                        ON messages(session_id, timestamp);
                    CREATE INDEX IF NOT EXISTS idx_facts_category
                        ON user_facts(category);
                """)
                conn.commit()
            finally:
                conn.close()

    def _create_session(self):
        """Starts a new conversation session."""
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "INSERT INTO sessions (title) VALUES (?)",
                    (f"Session {datetime.now().strftime('%Y-%m-%d %H:%M')}",)
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    # ================================================================
    # MESSAGE HISTORY
    # ================================================================

    def save_message(self, role, content, visual_context=None, tools_used=None):
        """Records a single chat message (user or assistant)."""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO messages (session_id, role, content, visual_context, tools_used) VALUES (?, ?, ?, ?, ?)",
                    (self.session_id, role, content, visual_context, tools_used)
                )
                conn.commit()
            finally:
                conn.close()

    def get_recent_messages(self, limit=20):
        """Returns the most recent messages across all sessions."""
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    "SELECT role, content, timestamp, visual_context FROM messages ORDER BY id DESC LIMIT ?",
                    (limit,)
                ).fetchall()
                return [dict(r) for r in reversed(rows)]
            finally:
                conn.close()

    def get_session_messages(self, session_id=None, limit=50):
        """Returns messages from a specific session (defaults to current)."""
        sid = session_id or self.session_id
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    "SELECT role, content, timestamp FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                    (sid, limit)
                ).fetchall()
                return [dict(r) for r in reversed(rows)]
            finally:
                conn.close()

    def get_message_count(self):
        """Returns total number of stored messages."""
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute("SELECT COUNT(*) as cnt FROM messages").fetchone()
                return row["cnt"]
            finally:
                conn.close()

    # ================================================================
    # USER FACTS
    # ================================================================

    def save_fact(self, fact, category="general", confidence=1.0):
        """
        Stores a user fact (e.g., 'User's name is Abhi').
        Uses INSERT OR REPLACE to update existing facts by unique text.
        """
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT INTO user_facts (category, fact, confidence)
                       VALUES (?, ?, ?)
                       ON CONFLICT(fact) DO UPDATE SET
                           confidence = excluded.confidence,
                           created_at = datetime('now', 'localtime')""",
                    (category, fact, confidence)
                )
                conn.commit()
            finally:
                conn.close()

    def get_all_facts(self):
        """Returns all stored user facts."""
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    "SELECT category, fact, created_at, confidence FROM user_facts ORDER BY created_at DESC"
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_facts_by_category(self, category):
        """Returns facts filtered by category."""
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    "SELECT fact, created_at, confidence FROM user_facts WHERE category = ? ORDER BY created_at DESC",
                    (category,)
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    # ================================================================
    # MAINTENANCE
    # ================================================================

    def clear_all(self):
        """Wipes all memory data (messages, facts, sessions)."""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.executescript("""
                    DELETE FROM messages;
                    DELETE FROM user_facts;
                    DELETE FROM sessions;
                """)
                conn.commit()
            finally:
                conn.close()
        self.session_id = self._create_session()

    def get_stats(self):
        """Returns memory statistics."""
        with self._lock:
            conn = self._get_conn()
            try:
                msg_count = conn.execute("SELECT COUNT(*) as c FROM messages").fetchone()["c"]
                fact_count = conn.execute("SELECT COUNT(*) as c FROM user_facts").fetchone()["c"]
                session_count = conn.execute("SELECT COUNT(*) as c FROM sessions").fetchone()["c"]
                return {
                    "messages": msg_count,
                    "facts": fact_count,
                    "sessions": session_count,
                    "current_session": self.session_id
                }
            finally:
                conn.close()
