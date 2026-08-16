"""标签/年份/难度 名称 ↔ ID 映射。

数据源：data/tags.json（由 /_lfe/tags/zh-CN 抓取，含标签层级与类型）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TAGS_FILE = DATA_DIR / "tags.json"

# 标签类型（type 字段含义）
TAG_TYPE_NAMES = {
    1: "区域",
    2: "算法",
    3: "来源",
    4: "时间/年份",
    5: "特殊题目",
    6: "其他",
}


class TagStore:
    """标签仓库：名称/ID 双向解析、年份范围展开、算法根分类。"""

    def __init__(self, tags_file: Path = TAGS_FILE) -> None:
        raw = json.loads(tags_file.read_text(encoding="utf-8"))
        self.tags = raw.get("tags") or []
        # 清洗 BOM / 首尾空白（源数据里个别标签名带 ﻿）
        for t in self.tags:
            t["name"] = t.get("name", "").lstrip("﻿​").strip()
        self.by_id: dict[int, dict] = {}
        self.by_name: dict[str, list[dict]] = {}
        for t in self.tags:
            self.by_id[t["id"]] = t
            self.by_name.setdefault(t["name"], []).append(t)
        self._year_tags = sorted(
            (t for t in self.tags
             if t.get("type") == 4 and t["name"].isdigit()),
            key=lambda t: int(t["name"]),
        )

    # ---------- 解析 ----------

    def resolve_tag_ids(self, tokens: list[str]) -> list[int]:
        """把标签名或 ID 解析成 ID 列表。未知项抛 ValueError 并给出提示。

        匹配优先级：
          1. ID
          2. 名称精确匹配（忽略大小写/全角空格）
          3. 唯一子串匹配（如 "动态规划" → "动态规划 DP"）；有多个候选时报错提示。
        """
        ids: list[int] = []
        unknown: list[str] = []
        for tok in tokens:
            tok = tok.strip()
            if not tok:
                continue
            if tok.isdigit():
                tid = int(tok)
                if tid in self.by_id:
                    ids.append(tid)
                else:
                    unknown.append(tok)
                continue

            # 精确匹配
            matches = self.by_name.get(tok)
            if not matches:
                # 忽略全角空格，做大小写不敏感精确匹配
                norm = tok.replace("　", " ")
                for name, cands in self.by_name.items():
                    if name.replace("　", " ").lower() == norm.lower():
                        matches = cands
                        break
            if matches:
                ids.append(matches[0]["id"])
                continue

            # 子串匹配（大小写不敏感）：优先「前缀 + 尾部为 ASCII 后缀」的最短命中
            # （如 "动态规划" → "动态规划 DP"），避免误匹配 "动态规划优化"。
            sub = [t for t in self.tags if tok.lower() in t["name"].lower()]
            if sub:
                def _rank(t: dict) -> tuple:
                    name = t["name"]
                    lower = name.lower()
                    is_prefix = lower.startswith(tok.lower())
                    rest = name[len(tok):] if is_prefix else name
                    ascii_rest = bool(rest) and all(ord(c) < 128 for c in rest)
                    return (not (is_prefix and ascii_rest), len(name))
                sub.sort(key=_rank)
                if _rank(sub[0]) != _rank(sub[1] if len(sub) > 1 else sub[0]):
                    ids.append(sub[0]["id"])
                    continue
                raise ValueError(
                    f"标签「{tok}」匹配到多个："
                    + "、".join(sorted(t["name"] for t in sub))
                    + "，请用完整名称或标签 ID"
                )
            unknown.append(tok)

        if unknown:
            raise ValueError(
                "未知标签: " + "、".join(unknown)
                + "（可用 --list-tags 查看全部标签名）"
            )
        return ids

    def year_range_ids(self, start: int, end: int) -> list[int]:
        """返回 [start, end] 区间内存在的年份标签 ID（升序）。"""
        return [
            t["id"] for t in self._year_tags
            if start <= int(t["name"]) <= end
        ]

    def year_ids_from_text(self, text: str) -> list[int]:
        """解析年份参数：'2010-2020'（区间）或 '2010,2015'（集合）。

        只保留标签库中存在数字年份；不存在时抛 ValueError。
        """
        text = text.strip()
        if not text:
            return []
        if "-" in text:
            a, b = text.split("-", 1)
            try:
                start, end = int(a.strip()), int(b.strip())
            except ValueError as e:
                raise ValueError(f"年份参数无法解析: {text!r}") from e
            if start > end:
                start, end = end, start
            ids = self.year_range_ids(start, end)
            if not ids:
                raise ValueError(f"年份范围 {text} 内没有任何已收录年份标签")
            return ids
        try:
            years = [int(x.strip()) for x in text.split(",") if x.strip()]
        except ValueError as e:
            raise ValueError(f"年份参数无法解析: {text!r}") from e
        ids = [tid for y in years for tid in ([self.year_name_to_id(y)] if self.year_name_to_id(y) else [])]
        missing = [y for y in years if self.year_name_to_id(y) is None]
        if missing:
            raise ValueError(f"标签库中没有这些年份: {missing}")
        return ids

    def year_id_to_name(self, tid: int) -> Optional[str]:
        t = self.by_id.get(tid)
        return t["name"] if t and t.get("type") == 4 else None

    def year_name_to_id(self, year: int) -> Optional[int]:
        for t in self._year_tags:
            if int(t["name"]) == year:
                return t["id"]
        return None

    # ---------- 展示 ----------

    def algorithm_roots(self) -> list[dict]:
        """算法类型(type=2)的根分类（parent 为 null）。"""
        return [t for t in self.tags if t.get("type") == 2 and t.get("parent") is None]

    def children_of(self, tid: int) -> list[dict]:
        return [t for t in self.tags if t.get("parent") == tid]

    def algorithm_tags(self) -> list[dict]:
        return [t for t in self.tags if t.get("type") == 2]

    def special_tags(self) -> list[dict]:
        """特殊题目标签（type=5）：交互题/提交答案/Special Judge/O2优化/通信题。"""
        return [t for t in self.tags if t.get("type") == 5]

    def display_name(self, tid: int) -> str:
        t = self.by_id.get(tid)
        return t["name"] if t else f"#{tid}"

    def year_minmax(self) -> tuple[int, int]:
        if not self._year_tags:
            return (0, 0)
        return (int(self._year_tags[0]["name"]), int(self._year_tags[-1]["name"]))


# 模块级单例（延迟加载）
_STORE: Optional[TagStore] = None


def get_store() -> TagStore:
    global _STORE
    if _STORE is None:
        _STORE = TagStore()
    return _STORE
