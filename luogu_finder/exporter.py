"""题号导出：逗号连接、每 N 个换行分段。"""

from __future__ import annotations

from typing import Sequence

from .constants import DEFAULT_SEP, DEFAULT_SPLIT


def format_pids(
    pids: Sequence[str],
    sep: str = DEFAULT_SEP,
    split: int = DEFAULT_SPLIT,
) -> str:
    """把题号序列格式化为「逗号连接、每 split 个换行」的文本。

    split <= 0 表示不分段（单行）。
    """
    if split and split > 0:
        lines = []
        for i in range(0, len(pids), split):
            lines.append(sep.join(pids[i : i + split]))
        return "\n".join(lines)
    return sep.join(pids)


def pids_to_text(
    problems,
    sep: str = DEFAULT_SEP,
    split: int = DEFAULT_SPLIT,
) -> str:
    """从 Problem 对象序列提取题号并格式化（导出/复制共用）。"""
    return format_pids([p.pid for p in problems], sep=sep, split=split)
