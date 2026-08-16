"""筛选逻辑：base 查询参数构建 + 本地筛选（通过数绝对值/前x%）+ 排序。

数据管道：
  QuerySpec ─► 服务端查询参数（type/keyword/tag组/年份组/difficulty）
            ─► 分页拉全候选集（经 cache）
            ─► 本地筛选（accepted_gt/lt、top_percent）
            ─► 排序 + limit
"""

from __future__ import annotations

import math
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable, Optional

from .cache import ProblemCache
from .client import LuoguClient
from .models import Problem, parse_problem_list

SORT_KEYS = {
    "pid": lambda p: p.pid,
    "name": lambda p: p.name,
    "difficulty": lambda p: p.difficulty,
    "accepted": lambda p: p.totalAccepted,
    "rate": lambda p: p.accept_rate,
}


@dataclass
class QuerySpec:
    """一次完整的筛选请求（CLI/GUI 解析后的结果）。"""

    tag_groups: list[list[int]] = field(default_factory=list)  # 组内 OR，组间 AND
    year_ids: list[int] = field(default_factory=list)          # 年份标签 ID（OR 组）
    difficulty: list[int] = field(default_factory=list)        # OR 集合
    type: Optional[str] = None
    keyword: str = ""
    content: bool = False
    accepted_gt: Optional[int] = None
    accepted_lt: Optional[int] = None
    top_percent: Optional[float] = None                        # 候选集按通过数取前 x%
    sort_by: str = "accepted"
    order: str = "desc"
    limit: Optional[int] = None

    # 构造服务端查询参数（不含 page）
    def to_query_params(self) -> dict:
        params: dict = {}
        # tag：组间 |（AND），组内 ,（OR）；年份单独成组，与算法标签组 AND
        tag_groups = [list(g) for g in self.tag_groups if g]
        if self.year_ids:
            tag_groups.append(list(self.year_ids))
        if tag_groups:
            params["tag"] = "|".join(",".join(map(str, g)) for g in tag_groups)
        if self.difficulty:
            params["difficulty"] = "|".join(map(str, sorted(self.difficulty)))
        if self.type:
            params["type"] = self.type
        if self.keyword:
            params["keyword"] = self.keyword
        if self.content:
            params["content"] = "true"
        return params

    # 服务端查询签名：决定「要拉哪些题」，本地筛选条件不影响网络请求
    def server_signature(self) -> str:
        return urllib.parse.urlencode(sorted(self.to_query_params().items()))


class FilterRunner:
    """把 QuerySpec 变成结果列表。"""

    def __init__(
        self,
        client: LuoguClient,
        cache: ProblemCache,
        refresh: bool = False,
        ttl_hours: float = 24.0,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.client = client
        self.cache = cache
        self.refresh = refresh
        self.ttl_hours = ttl_hours
        self.on_status = on_status or (lambda _s: None)

    def run(self, spec: QuerySpec) -> list[Problem]:
        params = spec.to_query_params()
        sig = spec.server_signature()

        # 1) 服务端查询命中缓存 → 从题目池读取，本地筛选照常应用
        if not self.refresh:
            cached_pids = self.cache.get_query(sig, self.ttl_hours)
            if cached_pids is not None:
                pool = self.cache.get_problems(cached_pids)
                problems = [Problem.from_json(pool[pid]) for pid in cached_pids if pid in pool]
                if problems or not cached_pids:
                    self.on_status(f"命中缓存（{len(problems)} 题）")
                    return self._finalize(problems, spec)

        # 2) 拉取全部候选集
        self.on_status("正在拉取题库（首次或缓存过期，请耐心等待）…")
        raw_problems, _total = self.client.fetch_problem_pages(params)
        problems = [Problem.from_json(p) for p in raw_problems]

        # 3) 写入缓存
        self.cache.save_problems(raw_problems)
        self.cache.save_query(sig, [p.pid for p in problems])
        self.on_status(f"已拉取 {len(problems)} 题并写入缓存")
        return self._finalize(problems, spec)

    def _finalize(self, problems: list[Problem], spec: QuerySpec) -> list[Problem]:
        """本地筛选 + 排序 + limit。"""
        # 通过数绝对值
        if spec.accepted_gt is not None:
            problems = [p for p in problems if p.totalAccepted > spec.accepted_gt]
        if spec.accepted_lt is not None:
            problems = [p for p in problems if p.totalAccepted < spec.accepted_lt]

        # 前 x%：按通过数降序取前 ceil(N * x%)（基准 = 本地筛选后的候选集）
        if spec.top_percent is not None and 0 < spec.top_percent < 100:
            ranked = sorted(problems, key=lambda p: p.totalAccepted, reverse=True)
            k = math.ceil(len(ranked) * spec.top_percent / 100.0)
            problems = ranked[:k]
        elif spec.top_percent is not None:
            # 100 或 0：0 保留原序（不筛），100 全保留
            pass

        # 排序
        key = SORT_KEYS.get(spec.sort_by, SORT_KEYS["accepted"])
        problems.sort(key=key, reverse=(spec.order == "desc"))

        # limit
        if spec.limit is not None and spec.limit > 0:
            problems = problems[: spec.limit]
        return problems
