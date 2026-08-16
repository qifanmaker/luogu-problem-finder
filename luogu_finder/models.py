"""问题数据模型与 JSON 解析。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .constants import DIFFICULTY_LABELS


@dataclass
class Problem:
    """题库列表中的一道题（problem.list 响应里 problem 对象）。"""

    pid: str
    type: str
    name: str
    difficulty: int
    tags: list[int] = field(default_factory=list)
    totalSubmit: int = 0
    totalAccepted: int = 0
    flag: int = 5
    provider_uid: Optional[int] = None
    provider_name: str = ""

    @property
    def accept_rate(self) -> float:
        """通过率（0~1）。提交数为 0 时视为 0。"""
        if self.totalSubmit <= 0:
            return 0.0
        return self.totalAccepted / self.totalSubmit

    @property
    def difficulty_name(self) -> str:
        return DIFFICULTY_LABELS.get(self.difficulty, f"{self.difficulty}（新档）")

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Problem":
        provider = data.get("provider") or {}
        return cls(
            pid=data.get("pid", ""),
            type=data.get("type", "P"),
            name=data.get("name", ""),
            difficulty=int(data.get("difficulty", 0) or 0),
            tags=list(data.get("tags") or []),
            totalSubmit=int(data.get("totalSubmit", 0) or 0),
            totalAccepted=int(data.get("totalAccepted", 0) or 0),
            flag=int(data.get("flag", 5) or 5),
            provider_uid=provider.get("uid"),
            provider_name=provider.get("name", ""),
        )

    def to_json(self) -> dict[str, Any]:
        """序列化回原始字段形态（供缓存复用）。"""
        return {
            "pid": self.pid,
            "type": self.type,
            "name": self.name,
            "difficulty": self.difficulty,
            "tags": list(self.tags),
            "totalSubmit": self.totalSubmit,
            "totalAccepted": self.totalAccepted,
            "flag": self.flag,
            "provider": (
                {"uid": self.provider_uid, "name": self.provider_name}
                if self.provider_uid is not None
                else {}
            ),
        }

    def __repr__(self) -> str:  # 便于调试
        return f"<Problem {self.pid} {self.name!r} diff={self.difficulty}>"


def parse_problem_list(payload: dict[str, Any]) -> tuple[list[Problem], int, dict]:
    """解析 /problem/list 的 content-only JSON。

    返回 (problems, total_count, filter_echo)。
    """
    data = payload.get("data") or {}
    problems_data = data.get("problems") or {}
    result = problems_data.get("result") or []
    problems = [Problem.from_json(p) for p in result]
    count = int(problems_data.get("count", 0) or 0)
    filter_echo = data.get("filter") or {}
    return problems, count, filter_echo
