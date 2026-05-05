"""
Storage - Persistenza SQLite per commenti e run history.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path


class Storage:
    def __init__(self, db_path: str = "monitor.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS comments (
                    id TEXT PRIMARY KEY,
                    platform TEXT,
                    profile TEXT,
                    author TEXT,
                    text TEXT,
                    timestamp TEXT,
                    severity INTEGER,
                    category TEXT,
                    confidence REAL,
                    keywords TEXT,
                    llm_used INTEGER,
                    reason TEXT,
                    screenshot TEXT,
                    target_url TEXT,
                    created_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT,
                    finished_at TEXT,
                    targets_count INTEGER,
                    comments_scraped INTEGER,
                    negatives_found INTEGER,
                    stats_json TEXT
                )
            """)
            conn.commit()

    def save_comment(self, comment: dict):
        clf = comment.get("classification", {})
        uid = f"{comment.get('platform')}_{comment.get('id', '')}"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO comments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                uid,
                comment.get("platform", ""),
                comment.get("profile", ""),
                comment.get("author", ""),
                comment.get("text", ""),
                str(comment.get("timestamp", "")),
                clf.get("severity", 0),
                clf.get("category", ""),
                clf.get("confidence", 0),
                json.dumps(clf.get("matched_keywords", [])),
                1 if clf.get("llm_used") else 0,
                clf.get("reason", ""),
                comment.get("screenshot", ""),
                comment.get("target_url", ""),
                datetime.now().isoformat(),
            ))
            conn.commit()

    def get_all_negatives(self, min_severity: int = 1) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM comments WHERE severity >= ? ORDER BY severity DESC",
                (min_severity,)
            ).fetchall()
        return [dict(r) for r in rows]

    def save_run(self, stats: dict, targets_count: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO runs (started_at,finished_at,targets_count,comments_scraped,negatives_found,stats_json) VALUES (?,?,?,?,?,?)",
                (
                    stats.get("started_at", ""),
                    stats.get("finished_at", ""),
                    targets_count,
                    stats.get("total_comments_scraped", 0),
                    stats.get("negative_comments_found", 0),
                    json.dumps(stats),
                )
            )
            conn.commit()
