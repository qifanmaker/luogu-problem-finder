"""本地 SQLite 缓存：题目池 + 查询签名缓存。

- problems 表：全量题目 JSON 池，跨查询复用，避免重复拉取。
- queries  表：查询签名 → 结果题号列表 + 时间戳，命中且在 TTL 内则直接复用。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "cache.db"


class ProblemCache:
    def __init__(self, db_path: Path = DEFAULT_DB) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), timeout=30)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS problems ("
            "pid TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS queries ("
            "sig TEXT PRIMARY KEY, created REAL NOT NULL, pids TEXT NOT NULL)"
        )
        self._conn.commit()

    # ---------- problems 池 ----------

    def get_problems(self, pids: list[str]) -> dict[str, dict]:
        """按 pid 批量读取题目 JSON，返回 {pid: data}。"""
        if not pids:
            return {}
        with self._lock:
            rows = self._conn.execute(
                "SELECT pid, data FROM problems WHERE pid IN (%s)"
                % ",".join("?" * len(pids)),
                pids,
            ).fetchall()
        return {pid: json.loads(data) for pid, data in rows}

    def save_problems(self, problems: list[dict]) -> None:
        """upsert 一批题目 JSON（按 pid 去重）。"""
        if not problems:
            return
        rows = [(p["pid"], json.dumps(p, ensure_ascii=False)) for p in problems]
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO problems (pid, data) VALUES (?, ?)", rows
            )
            self._conn.commit()

    def total_problems(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM problems").fetchone()
        return row[0]

    # ---------- 查询缓存 ----------

    def get_query(self, sig: str, ttl_hours: float) -> Optional[list[str]]:
        """命中且未过期则返回题号列表，否则 None。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT created, pids FROM queries WHERE sig = ?", (sig,)
            ).fetchone()
        if not row:
            return None
        created, pids_json = row
        if time.time() - created > ttl_hours * 3600:
            return None
        return json.loads(pids_json)

    def save_query(self, sig: str, pids: list[str]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO queries (sig, created, pids) VALUES (?, ?, ?)",
                (sig, time.time(), json.dumps(pids, ensure_ascii=False)),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
