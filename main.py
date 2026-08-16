#!/usr/bin/env python3
"""洛谷题库筛选工具 —— 命令行入口。

示例：
    python main.py --tag 动态规划 --difficulty 3-5 --year 2010-2020 --accepted-gt 1000
    python main.py --tag 字符串,动态规划 --tag 图论 --top 10 --export out.txt
    python main.py --list-tags
    python main.py --gui
"""

from __future__ import annotations

import argparse
import sys

from luogu_finder import __version__
from luogu_finder.cache import ProblemCache
from luogu_finder.client import LuoguClient, LuoguBlockedError
from luogu_finder.constants import (
    DEFAULT_DELAY,
    DEFAULT_SEP,
    DEFAULT_SPLIT,
    DEFAULT_TTL_HOURS,
    DIFFICULTY_LABELS,
    PROBLEM_TYPES,
)
from luogu_finder.exporter import format_pids
from luogu_finder.filters import QuerySpec, FilterRunner
from luogu_finder.models import Problem
from luogu_finder.tags import get_store, TAG_TYPE_NAMES


def setup_console() -> None:
    """Windows 控制台默认非 UTF-8，强制用 UTF-8 输出避免乱码/报错。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001 无关紧要
                pass


def _parse_int_range(text: str, name: str) -> list[int]:
    """解析 '3-5' 或 '3,5' 为整数列表。"""
    text = text.strip()
    try:
        if "-" in text:
            a, b = text.split("-", 1)
            lo, hi = int(a.strip()), int(b.strip())
            if lo > hi:
                lo, hi = hi, lo
            return list(range(lo, hi + 1))
        return [int(x.strip()) for x in text.split(",") if x.strip()]
    except ValueError as e:
        raise ValueError(f"{name} 参数无法解析: {text!r}") from e


def build_spec(args: argparse.Namespace) -> QuerySpec:
    store = get_store()
    tag_groups: list[list[int]] = []
    for group_text in args.tag or []:
        tokens = [t.strip() for t in group_text.split(",") if t.strip()]
        if tokens:
            tag_groups.append(store.resolve_tag_ids(tokens))
    if args.special:
        tokens = [t.strip() for t in args.special.split(",") if t.strip()]
        if tokens:
            # 特殊题目作为独立 AND 组（与 --tag 的组是 AND 关系）
            tag_groups.append(store.resolve_tag_ids(tokens))

    if args.difficulty:
        diff = _parse_int_range(args.difficulty, "难度")
        bad = [d for d in diff if not 1 <= d <= 8]
        if bad:
            raise ValueError(f"难度取值需在 1-8 之间，收到: {bad}")
    else:
        diff = []

    if args.top is not None and not 0 < args.top <= 100:
        raise ValueError("--top 需在 (0, 100] 内")

    spec = QuerySpec(
        tag_groups=tag_groups,
        difficulty=diff,
        type=args.type,
        keyword=args.keyword or "",
        content=args.content,
        accepted_gt=args.accepted_gt,
        accepted_lt=args.accepted_lt,
        top_percent=args.top,
        sort_by=args.sort,
        order=args.order,
        limit=args.limit,
    )
    if args.year:
        spec.year_ids = store.year_ids_from_text(args.year)
    return spec


def algorithm_tags_text(problem: Problem) -> str:
    """展示算法标签（type=2），多标签用 / 连接。"""
    store = get_store()
    names = [
        store.display_name(tid)
        for tid in problem.tags
        if store.by_id.get(tid, {}).get("type") == 2
    ]
    return "/".join(names) if names else "—"


def _truncate(text: str, width: int) -> str:
    if width <= 0 or len(text) <= width:
        return text
    return text[: max(0, width - 1)] + "…"


def print_table(problems: list[Problem]) -> None:
    if not problems:
        print("（无符合条件的题目）")
        return
    headers = ["题号", "题目名称", "算法标签", "难度", "通过率", "通过/提交"]
    rows = []
    for p in problems:
        rows.append([
            p.pid,
            p.name,
            algorithm_tags_text(p),
            p.difficulty_name,
            f"{p.accept_rate:.1%}",
            f"{p.totalAccepted}/{p.totalSubmit}",
        ])
    # 标签列上限 40 字符，其余列按内容自适应
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    widths[2] = min(widths[2], 40)
    widths[1] = min(widths[1], 34)
    fmt = "  ".join("{" + str(i) + ":<" + str(w) + "}" for i, w in enumerate(widths))
    print(fmt.format(*headers))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        for i, cell in enumerate(row):
            row[i] = _truncate(cell, widths[i])
        print(fmt.format(*row))


def cmd_list_tags() -> int:
    store = get_store()
    print("=== 算法标签（type=2，共 %d 个）===" % len(store.algorithm_tags()))
    for root in store.algorithm_roots():
        children = store.children_of(root["id"])
        names = [c["name"] for c in children]
        suffix = f"（含 {', '.join(names)}）" if names else ""
        print(f"  {root['id']:>5}  {root['name']}{suffix}")
    print()
    print("=== 年份标签（type=4）===")
    lo, hi = store.year_minmax()
    print(f"  范围 {lo}~{hi}，--year 传区间如 {lo}-2020")
    print()
    print("=== 难度（1-8）===")
    for d, name in DIFFICULTY_LABELS.items():
        if d >= 1:
            print(f"  {d}: {name}")
    print()
    print("=== 特殊题目（type=5）===")
    for t in store.special_tags():
        print(f"  {t['id']:>5}  {t['name']}")
    print()
    print("=== 题目类型 ===")
    print("  " + " / ".join(PROBLEM_TYPES) + "（当前题库仅 P、B 有题）")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    try:
        spec = build_spec(args)
    except ValueError as e:
        print(f"参数错误：{e}", file=sys.stderr)
        return 2
    cache = ProblemCache()

    est_info = {"printed": False}

    def on_progress(page: int, total: int) -> None:
        if not est_info["printed"]:
            est_info["printed"] = True
            secs = total * args.delay * 1.0  # 抖动中值
            print(f"共 {total} 页，预计约 {secs:.0f} 秒（间隔 {args.delay}s，可 Ctrl+C 取消）")
        if args.quiet:
            return
        print(f"\r  拉取中 {page}/{total} 页", end="", flush=True)
        if page >= total:
            print()

    client = LuoguClient(
        delay=args.delay,
        on_progress=on_progress,
        log=(lambda m: None if args.quiet else print(f"  {m}")),
    )
    runner = FilterRunner(
        client, cache,
        refresh=args.refresh, ttl_hours=args.ttl,
        on_status=lambda s: None if args.quiet else print(f"[{s}]"),
    )
    try:
        problems = runner.run(spec)
    except LuoguBlockedError as e:
        print(f"\n错误：{e}", file=sys.stderr)
        return 2
    finally:
        cache.close()

    print()
    print_table(problems)

    # 导出
    if args.export is not None or args.print_pids:
        text = format_pids([p.pid for p in problems], sep=args.sep, split=args.split)
        if args.export and args.export != "-":
            with open(args.export, "w", encoding="utf-8") as f:
                f.write(text + "\n")
            print(f"\n已导出 {len(problems)} 个题号到 {args.export}")
        else:
            print()
            print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    setup_console()
    ap = argparse.ArgumentParser(
        prog="luogu-finder",
        description="洛谷题库筛选工具（零依赖，跨平台）",
        epilog=(
            "示例:\n"
            "  python main.py --tag 动态规划 --difficulty 3-5 --year 2010-2020 --accepted-gt 1000\n"
            "  python main.py --tag 字符串,动态规划 --tag 图论 --top 10 --export out.txt\n"
            "  python main.py --gui"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    g = ap.add_argument_group("筛选条件")
    g.add_argument("--tag", action="append", metavar="标签[,标签…]",
                   help="算法标签（可多次；每次=一个AND组，组内逗号=OR；支持名称或ID）")
    g.add_argument("--special", metavar="标签[,标签…]",
                   help="特殊题目标签（交互题/提交答案/Special Judge/O2优化/通信题），"
                        "作为独立 AND 组，如 --special 交互题,O2优化")
    g.add_argument("--year", metavar="A-B|A,B", help="年份区间(如 2010-2020)或集合(如 2010,2015)")
    g.add_argument("--difficulty", metavar="A-B|A,B", help="难度区间(如 3-5)或集合，1-8")
    g.add_argument("--type", choices=PROBLEM_TYPES, help="题目类型（缺省=全部）")
    g.add_argument("--keyword", metavar="词", help="关键词模糊搜索（标题/内容/标签）")
    g.add_argument("--content", action="store_true", help="开启全文搜索模式")
    g.add_argument("--accepted-gt", type=int, metavar="N", help="通过数 > N")
    g.add_argument("--accepted-lt", type=int, metavar="N", help="通过数 < N")
    g.add_argument("--top", type=float, metavar="X", help="候选集按通过数取前 X%%")

    g = ap.add_argument_group("输出")
    g.add_argument("--sort", choices=["accepted", "rate", "difficulty", "pid", "name"],
                   default="accepted", help="排序字段（默认按通过数）")
    g.add_argument("--order", choices=["asc", "desc"], default="desc")
    g.add_argument("--limit", type=int, metavar="N", help="最多输出 N 条")
    g.add_argument("--export", nargs="?", const="-", metavar="文件", default=None,
                   help="导出题号到文件（缺省值 '-' 打印到屏幕）")
    g.add_argument("--print-pids", action="store_true", help="把题号打印到屏幕（便于复制）")
    g.add_argument("--sep", default=DEFAULT_SEP, help=f"段内分隔符（默认 {DEFAULT_SEP!r}）")
    g.add_argument("--split", type=int, default=DEFAULT_SPLIT,
                   help=f"每 N 个题号换行分段（默认 {DEFAULT_SPLIT}；0=不分段）")
    g.add_argument("--quiet", action="store_true", help="抑制进度输出")

    g = ap.add_argument_group("网络与缓存")
    g.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                   help=f"请求间隔秒（默认 {DEFAULT_DELAY}，实际带随机抖动，调大可降低风控风险）")
    g.add_argument("--refresh", action="store_true", help="忽略缓存强制重抓")
    g.add_argument("--ttl", type=float, default=DEFAULT_TTL_HOURS,
                   help=f"缓存有效期小时（默认 {DEFAULT_TTL_HOURS}）")

    g = ap.add_argument_group("其他")
    g.add_argument("--list-tags", action="store_true", help="列出可用标签/年份/难度")
    g.add_argument("--gui", action="store_true", help="启动图形界面")

    args = ap.parse_args(argv)

    if args.gui:
        from luogu_finder.gui import run_gui
        return run_gui()
    if args.list_tags:
        return cmd_list_tags()

    # 没有筛选条件时给出提示
    if not (args.tag or args.special or args.year or args.difficulty or args.type
            or args.keyword or args.accepted_gt is not None or args.accepted_lt is not None
            or args.top):
        print("未提供任何筛选条件，将拉取全库（17285 题）。可加 --limit 限制输出。")
        if input("确认继续？[y/N] ").strip().lower() != "y":
            return 0
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
