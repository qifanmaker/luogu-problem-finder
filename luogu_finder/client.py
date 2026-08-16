"""洛谷 HTTP 客户端：反爬处理 + 限速 + 重试 + 风控识别。

关键点（实测，2026-08-16）：
- 首次请求会被 302 重定向到同一 URL 并下发 C3VK cookie，必须带 cookie 重试。
- 想要纯 JSON 响应，必须带请求头 `x-lentille-request: content-only`。
- 题库列表 / 题目详情均为公开数据，无需登录。
"""

from __future__ import annotations

import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

from .constants import (
    DEFAULT_DELAY,
    DELAY_JITTER,
    MAX_RETRIES,
    PER_PAGE,
    RETRY_BACKOFF,
    UA,
)

BASE = "https://www.luogu.com.cn"


class LuoguBlockedError(Exception):
    """疑似触发洛谷风控（连续失败/403/验证码特征），应停止并提示用户。"""


class _CookieJar:
    """极简 cookie 管理：从 Set-Cookie 提取并回带。"""

    def __init__(self) -> None:
        self.cookies: dict[str, str] = {}

    def extract(self, headers: Any) -> None:
        values = headers.get_all("Set-Cookie") if hasattr(headers, "get_all") else []
        for h in values or []:
            for part in h.split(";"):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    self.cookies[k] = v

    def header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁用自动重定向，手动处理（302 会回到同一 URL，自动跟随会死循环）。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None

    def http_error_302(self, req, fp, code, msg, headers):  # noqa: ANN001
        return fp

    http_error_301 = http_error_307 = http_error_308 = http_error_302


class LuoguClient:
    """带反爬、限速、重试的洛谷请求客户端。

    on_progress 回调用于 CLI/GUI 展示进度，签名为 callable(current_page, total_pages)。
    """

    def __init__(
        self,
        delay: float = DEFAULT_DELAY,
        on_progress: Optional[Callable[[int, int], None]] = None,
        log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.delay = delay
        self.on_progress = on_progress
        self.log = log or (lambda _msg: None)
        self._jar = _CookieJar()
        self._opener = urllib.request.build_opener(_NoRedirect)
        self._cancel = threading.Event()
        self._next_at = 0.0  # 下一次允许发起请求的时间点（节流）

    # ---------- 公开接口 ----------

    def cancel(self) -> None:
        """请求取消（GUI 用）。"""
        self._cancel.set()

    def fetch_json(self, path: str, params: Optional[dict] = None) -> dict:
        """GET 请求并返回解析后的 JSON（content-only）。"""
        self._throttle()
        url = self._build_url(path, params)
        for attempt in range(MAX_RETRIES + 1):
            if self._cancel.is_set():
                raise LuoguBlockedError("已取消")
            try:
                resp = self._request_once(url)
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
                if resp.status == 302:
                    # 反爬 cookie 流程：拿到 C3VK 后重试同一 URL
                    resp.read()
                    continue
                resp.read()
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    raise LuoguBlockedError(
                        "收到 403，疑似触发洛谷风控，请增大请求间隔(--delay)后重试"
                    ) from e
                self.log(f"HTTP {e.code}，重试…")
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                self.log(f"网络错误({e})，重试…")
            except json.JSONDecodeError as e:
                self.log(f"响应解析失败，重试… ({e})")
            # 指数退避
            backoff = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
            self._sleep(backoff)
        raise LuoguBlockedError(
            "多次请求失败，疑似触发洛谷风控，请增大请求间隔(--delay)后重试"
        )

    def fetch_problem_pages(
        self,
        params: dict,
        progress_interval: int = 5,
    ) -> tuple[list[dict], int]:
        """分页拉取 /problem/list 全部结果。

        params: 不含 page 的查询参数。
        返回 (problems_json_list, total_count)。
        响应自带 count，据此计算总页数逐页拉取。
        """
        # 先取第 1 页拿总数
        first = self.fetch_json("/problem/list", {**params, "page": 1})
        data = first.get("data") or {}
        probs = data.get("problems") or {}
        count = int(probs.get("count", 0) or 0)
        result = list(probs.get("result") or [])
        seen = {p["pid"] for p in result}
        total_pages = max(1, (count + PER_PAGE - 1) // PER_PAGE)

        if self.on_progress:
            self.on_progress(1, total_pages)

        for page in range(2, total_pages + 1):
            if self._cancel.is_set():
                raise LuoguBlockedError("已取消")
            resp = self.fetch_json("/problem/list", {**params, "page": page})
            data = resp.get("data") or {}
            probs = data.get("problems") or {}
            items = list(probs.get("result") or [])
            new_items = [p for p in items if p["pid"] not in seen]
            if not new_items:
                # 越界页会被 clamp 到最后一页，出现重复即已拉完
                break
            result.extend(new_items)
            seen.update(p["pid"] for p in new_items)
            if self.on_progress:
                self.on_progress(page, total_pages)
        return result, count

    # ---------- 内部实现 ----------

    def _build_url(self, path: str, params: Optional[dict]) -> str:
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return url

    def _request_once(self, url: str):
        req = urllib.request.Request(url)
        req.add_header("User-Agent", UA)
        req.add_header("Referer", BASE + "/problem/list")
        req.add_header("x-lentille-request", "content-only")
        if self._jar.cookies:
            req.add_header("Cookie", self._jar.header())
        resp = self._opener.open(req, timeout=30)
        self._jar.extract(resp.headers)
        return resp

    def _throttle(self) -> None:
        """限速：每次请求后，下一次最早在 delay * jitter 秒后发起。"""
        if self.delay <= 0:
            return
        now = time.monotonic()
        if self._next_at > now:
            self._sleep(self._next_at - now)
        self._next_at = time.monotonic() + self.delay * random.uniform(*DELAY_JITTER)

    def _sleep(self, seconds: float) -> None:
        """可中断的 sleep（取消时立即退出）。"""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self._cancel.is_set():
                return
            time.sleep(min(0.05, max(0.0, end - time.monotonic())))
