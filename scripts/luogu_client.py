#!/usr/bin/env python3
"""洛谷题库 API 参考客户端（实测版，2026-08-16）。

用法:
    python3 scripts/luogu_client.py --page 1
    python3 scripts/luogu_client.py --keyword 动态规划 --difficulty "4|5" --type P
    python3 scripts/luogu_client.py --problem P1000

关键点:
    - 必须携带 cookie jar 跟随 302 反爬重定向
    - 必须带 x-lentille-request: content-only 头才能拿纯 JSON
    - difficulty 多选用 | 分隔; tag 用 | 分隔组(AND)、组内 , (OR)
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request

BASE = "https://www.luogu.com.cn/problem/list"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 用于携带/跟随 C3VK 反爬 cookie
class _CookieJar:
    def __init__(self):
        self.cookies = {}

    def extract(self, resp):
        for h in resp.headers.get_all("Set-Cookie") or []:
            for part in h.split(";"):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    self.cookies[k] = v

    def header(self):
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁用自动重定向，手动处理（避免 302 回到同 URL 造成死循环）。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

    def http_error_302(self, req, fp, code, msg, headers):
        return fp

    http_error_301 = http_error_307 = http_error_308 = http_error_302


def fetch(path, params=None, with_content_only=True):
    jar = _CookieJar()
    url = BASE if path == "/problem/list" else f"https://www.luogu.com.cn{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    opener = urllib.request.build_opener(_NoRedirect)
    for _ in range(5):
        req = urllib.request.Request(url)
        req.add_header("User-Agent", UA)
        req.add_header("Referer", "https://www.luogu.com.cn/problem/list")
        if with_content_only:
            req.add_header("x-lentille-request", "content-only")
        if jar.cookies:
            req.add_header("Cookie", jar.header())
        resp = opener.open(req, timeout=30)
        jar.extract(resp)
        if resp.status == 200:
            return json.loads(resp.read().decode("utf-8"))
        if resp.status == 302:  # 反爬：拿到 C3VK cookie 后重试同 URL
            resp.read()
            continue
        resp.read()
    raise RuntimeError("failed to fetch")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--keyword", default="")
    ap.add_argument("--difficulty", default="")
    ap.add_argument("--tag", default="")
    ap.add_argument("--type", default="")
    ap.add_argument("--content", action="store_true", help="全文搜索")
    ap.add_argument("--orderBy", default="")
    ap.add_argument("--order", default="")
    ap.add_argument("--problem", default="", help="查题目详情，如 P1000")
    args = ap.parse_args()

    if args.problem:
        d = fetch(f"/problem/{args.problem}")
        p = d["data"]["problem"]
        print(f"#{p['pid']} [{p['type']}] {p['name']}  难度={p['difficulty']} "
              f"提交={p['totalSubmit']} 通过={p['totalAccepted']}")
        print("标签:", p["tags"])
        print("描述:", p["contenu"]["description"][:200])
        return

    params = {"page": args.page}
    if args.keyword:
        params["keyword"] = args.keyword
    if args.difficulty:
        params["difficulty"] = args.difficulty
    if args.tag:
        params["tag"] = args.tag
    if args.type:
        params["type"] = args.type
    if args.content:
        params["content"] = "true"
    if args.orderBy:
        params["orderBy"] = args.orderBy
    if args.order:
        params["order"] = args.order

    d = fetch("/problem/list", params)
    probs = d["data"]["problems"]
    print(f"共 {probs['count']} 题 | 第 {args.page} 页 {len(probs['result'])} 题")
    for p in probs["result"]:
        print(f"  {p['pid']:<7} [{'P' if p['type']=='P' else 'B'}] 难度{p['difficulty']} "
              f"通过率 {p['totalAccepted']/max(p['totalSubmit'],1):6.2%}  {p['name']}")


if __name__ == "__main__":
    main()
