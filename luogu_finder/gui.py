"""洛谷题库筛选工具 —— tkinter 图形界面（跨平台，零依赖）。

后台线程拉取数据，queue + after 回主线程更新进度与结果，界面不卡顿。
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .cache import ProblemCache
from .client import LuoguClient, LuoguBlockedError
from .constants import DEFAULT_DELAY, DEFAULT_SEP, DEFAULT_SPLIT
from .exporter import pids_to_text
from .filters import QuerySpec, FilterRunner
from .models import Problem
from .tags import get_store

COLUMNS = [
    ("pid", "题号", 70),
    ("name", "题目名称", 240),
    ("tags", "算法标签", 220),
    ("difficulty", "难度", 110),
    ("rate", "通过率", 70),
    ("stat", "通过/提交", 120),
]

CHECK_ON = "☑ "
CHECK_OFF = "☐ "


class LuoguGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("洛谷题库筛选工具")
        root.geometry("1080x740")
        root.minsize(900, 600)

        self.store = get_store()
        self.problems: list[Problem] = []
        self.selected_tags: set[int] = set()      # 勾选的算法标签 ID（OR 组）
        self.special_vars: dict[int, tk.BooleanVar] = {}  # 特殊题目标签勾选
        self.tag_item: dict[int, str] = {}        # tag id -> tree item id
        self._queue: queue.Queue = queue.Queue()
        self._client: LuoguClient | None = None
        self._worker: threading.Thread | None = None
        self._cancelled = False

        self._build_widgets()

    # ---------- 界面构建 ----------

    def _build_widgets(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self._paned = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        self._paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # 左侧：筛选条件
        left = ttk.Frame(self._paned, width=340)
        self._paned.add(left, weight=0)

        # 按钮框最先 pack 且钉在底部，保证始终可见（不被上方的可伸缩区域挤掉）
        btns = ttk.Frame(left)
        btns.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        self.btn_start = ttk.Button(btns, text="开始筛选", command=self.on_start)
        self.btn_start.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.btn_cancel = ttk.Button(btns, text="取消", command=self.on_cancel, state=tk.DISABLED)
        self.btn_cancel.pack(side=tk.LEFT, padx=(6, 0))

        cond = ttk.LabelFrame(left, text="筛选条件", padding=8)
        cond.pack(side=tk.TOP, fill=tk.X)
        self._build_condition_panel(cond)

        specialbox = ttk.LabelFrame(left, text="特殊题目", padding=6)
        specialbox.pack(side=tk.TOP, fill=tk.X, pady=(8, 0))
        self._build_special_panel(specialbox)

        tagbox = ttk.LabelFrame(left, text="算法标签（勾选父类自动包含子类）", padding=6)
        tagbox.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(8, 0))
        self._build_tag_panel(tagbox)

        # 右侧：结果
        right = ttk.Frame(self._paned)
        self._paned.add(right, weight=1)
        self._build_result_panel(right)

        # ttk.Panedwindow 对 weight=0 的窗格会给最小宽度（此处实测会压到 1px），
        # 布局稳定后用 sashpos 强制设定左栏宽度。
        self.root.after(50, lambda: self._paned.sashpos(0, 340))

    def _build_condition_panel(self, parent: ttk.Frame) -> None:
        grid = ttk.Frame(parent)
        grid.pack(fill=tk.X)

        def row(y: int, label: str, widget: ttk.Widget, col: int = 1) -> None:
            ttk.Label(grid, text=label).grid(row=y, column=0, sticky="e", padx=(0, 6), pady=3)
            widget.grid(row=y, column=col, columnspan=3, sticky="we", pady=3)
            grid.columnconfigure(1, weight=1)

        self.var_type = tk.StringVar(value="全部")
        self.cmb_type = ttk.Combobox(grid, textvariable=self.var_type, width=10,
                                     values=["全部", "P", "B"], state="readonly")
        row(0, "类型", self.cmb_type, col=1)

        self.var_keyword = tk.StringVar()
        row(1, "关键词", ttk.Entry(grid, textvariable=self.var_keyword))

        # 难度区间
        self.var_diff_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(grid, text="难度", variable=self.var_diff_on).grid(
            row=2, column=0, sticky="e", padx=(0, 6), pady=3)
        self.spn_diff_min = ttk.Spinbox(grid, from_=1, to=8, width=5)
        self.spn_diff_min.set(1)
        ttk.Label(grid, text="—").grid(row=2, column=2, pady=3)
        self.spn_diff_max = ttk.Spinbox(grid, from_=1, to=8, width=5)
        self.spn_diff_max.set(8)
        self.spn_diff_min.grid(row=2, column=1, sticky="e")
        self.spn_diff_max.grid(row=2, column=3, sticky="w")

        # 年份区间
        lo, hi = self.store.year_minmax()
        self.var_year_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(grid, text="年份", variable=self.var_year_on).grid(
            row=3, column=0, sticky="e", padx=(0, 6), pady=3)
        self.spn_year_min = ttk.Spinbox(grid, from_=lo, to=hi, width=6)
        self.spn_year_min.set(lo)
        ttk.Label(grid, text="—").grid(row=3, column=2, pady=3)
        self.spn_year_max = ttk.Spinbox(grid, from_=lo, to=hi, width=6)
        self.spn_year_max.set(hi)
        self.spn_year_min.grid(row=3, column=1, sticky="e")
        self.spn_year_max.grid(row=3, column=3, sticky="w")

        # 通过数区间
        self.var_ac_gt = tk.StringVar()
        ttk.Label(grid, text="通过数").grid(row=4, column=0, sticky="e", padx=(0, 6), pady=3)
        ttk.Entry(grid, textvariable=self.var_ac_gt, width=8).grid(row=4, column=1, sticky="e")
        ttk.Label(grid, text="<").grid(row=4, column=2, pady=3)
        self.var_ac_lt = tk.StringVar()
        ttk.Entry(grid, textvariable=self.var_ac_lt, width=8).grid(row=4, column=3, sticky="w")

        # 前 x%
        self.var_top = tk.StringVar()
        ttk.Label(grid, text="前x%").grid(row=5, column=0, sticky="e", padx=(0, 6), pady=3)
        ttk.Entry(grid, textvariable=self.var_top, width=10).grid(row=5, column=1, columnspan=3, sticky="w")

        # 排序
        self.var_sort = tk.StringVar(value="accepted")
        self.cmb_sort = ttk.Combobox(grid, textvariable=self.var_sort, width=10,
                                     values=["accepted", "rate", "difficulty", "pid", "name"],
                                     state="readonly")
        row(6, "排序", self.cmb_sort, col=1)
        self.var_order = tk.StringVar(value="desc")
        ttk.Combobox(grid, textvariable=self.var_order, width=6,
                     values=["desc", "asc"], state="readonly").grid(
            row=6, column=3, sticky="w")

        # 限制条数
        self.var_limit = tk.StringVar()
        ttk.Label(grid, text="最多N条").grid(row=7, column=0, sticky="e", padx=(0, 6), pady=3)
        ttk.Entry(grid, textvariable=self.var_limit, width=10).grid(row=7, column=1, columnspan=3, sticky="w")

        # 请求间隔 / 分段
        self.var_delay = tk.StringVar(value=str(DEFAULT_DELAY))
        ttk.Label(grid, text="间隔(s)").grid(row=8, column=0, sticky="e", padx=(0, 6), pady=3)
        ttk.Entry(grid, textvariable=self.var_delay, width=8).grid(row=8, column=1, sticky="e")
        self.var_split = tk.StringVar(value=str(DEFAULT_SPLIT))
        ttk.Label(grid, text="每行N个").grid(row=8, column=2, pady=3)
        ttk.Entry(grid, textvariable=self.var_split, width=8).grid(row=8, column=3, sticky="w")

    def _build_special_panel(self, parent: ttk.Frame) -> None:
        """特殊题目标签（type=5）勾选区，作为独立 AND 组。"""
        for i, tag in enumerate(self.store.special_tags()):
            var = tk.BooleanVar(value=False)
            self.special_vars[tag["id"]] = var
            ttk.Checkbutton(parent, text=tag["name"], variable=var).grid(
                row=i // 3, column=i % 3, sticky="w", padx=4, pady=1)
        if self.store.special_tags():
            ttk.Label(parent, text="（与算法标签为 AND 关系）",
                      foreground="#888").grid(row=2, column=0, columnspan=3, sticky="w", padx=4)

    def _build_tag_panel(self, parent: ttk.Frame) -> None:
        self.tag_tree = ttk.Treeview(parent, show="tree", height=9)
        vs = ttk.Scrollbar(parent, orient="vertical", command=self.tag_tree.yview)
        hs = ttk.Scrollbar(parent, orient="horizontal", command=self.tag_tree.xview)
        self.tag_tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tag_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vs.pack(side=tk.RIGHT, fill=tk.Y)
        hs.pack(side=tk.BOTTOM, fill=tk.X)
        self.tag_tree.bind("<Button-1>", self._on_tag_click)

        for root_tag in self.store.algorithm_roots():
            parent_id = self._insert_tag(self.tag_tree, "", root_tag)
            for child in self.store.children_of(root_tag["id"]):
                self._insert_tag(self.tag_tree, parent_id, child)

        hint = ttk.Label(parent, text="提示：点击文字切换勾选；勾选父类=包含其全部子类（OR）",
                         foreground="#888")
        hint.pack(side=tk.BOTTOM, fill=tk.X)

    def _insert_tag(self, tree: ttk.Treeview, parent: str, tag: dict) -> str:
        item = tree.insert(parent, "end", text=CHECK_OFF + tag["name"], open=False)
        self.tag_item[tag["id"]] = item
        return item

    def _on_tag_click(self, event: tk.Event) -> None:
        item = self.tag_tree.identify_row(event.y)
        if not item:
            return
        # 找到该 item 对应的 tag id
        for tid, it in self.tag_item.items():
            if it == item:
                self._toggle_tag(tid)
                break

    def _toggle_tag(self, tid: int) -> None:
        store = self.store
        tag = store.by_id.get(tid)
        if not tag:
            return
        ids = self._tag_effective_ids(tid)
        toggling = tid not in self.selected_tags
        if toggling:
            self.selected_tags.update(ids)
        else:
            self.selected_tags.difference_update(ids)
        for i in ids:
            self._refresh_tag_text(i)

    def _tag_effective_ids(self, tid: int) -> set[int]:
        """勾选父类时含全部子类。"""
        store = self.store
        ids = {tid}
        stack = list(store.children_of(tid))
        while stack:
            t = stack.pop()
            ids.add(t["id"])
            stack.extend(store.children_of(t["id"]))
        return ids

    def _refresh_tag_text(self, tid: int) -> None:
        item = self.tag_item.get(tid)
        if not item:
            return
        store = self.store
        mark = CHECK_ON if tid in self.selected_tags else CHECK_OFF
        self.tag_tree.item(item, text=mark + store.by_id[tid]["name"])

    # ---------- 结果面板 ----------

    def _build_result_panel(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent)
        top.pack(fill=tk.BOTH, expand=True)

        self.result_tree = ttk.Treeview(top, columns=[c[0] for c in COLUMNS], show="headings")
        for key, text, width in COLUMNS:
            self.result_tree.heading(key, text=text)
            self.result_tree.column(key, width=width, anchor="w")
        vs = ttk.Scrollbar(top, orient="vertical", command=self.result_tree.yview)
        hs = ttk.Scrollbar(top, orient="horizontal", command=self.result_tree.xview)
        self.result_tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.result_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vs.pack(side=tk.RIGHT, fill=tk.Y)
        hs.pack(side=tk.BOTTOM, fill=tk.X)

        # 操作按钮
        btns = ttk.Frame(parent)
        btns.pack(fill=tk.X, pady=(6, 0))
        self.btn_copy = ttk.Button(btns, text="复制编号", command=self.on_copy, state=tk.DISABLED)
        self.btn_copy.pack(side=tk.LEFT)
        self.btn_export = ttk.Button(btns, text="导出编号到文件", command=self.on_export, state=tk.DISABLED)
        self.btn_export.pack(side=tk.LEFT, padx=(6, 0))
        self.lbl_status = ttk.Label(btns, text="就绪", foreground="#888")
        self.lbl_status.pack(side=tk.RIGHT)

        self.progress = ttk.Progressbar(parent, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(6, 0))

    # ---------- 动作 ----------

    def _read_spec(self) -> QuerySpec:
        spec = QuerySpec()

        kw = self.var_keyword.get().strip()
        if kw:
            spec.keyword = kw

        t = self.var_type.get()
        if t in ("P", "B"):
            spec.type = t

        if self.var_diff_on.get():
            try:
                lo = int(self.spn_diff_min.get())
                hi = int(self.spn_diff_max.get())
            except ValueError:
                raise ValueError("难度必须是数字")
            if lo > hi:
                lo, hi = hi, lo
            spec.difficulty = list(range(lo, hi + 1))

        if self.var_year_on.get():
            lo = int(self.spn_year_min.get())
            hi = int(self.spn_year_max.get())
            spec.year_ids = self.store.year_range_ids(lo, hi)

        if self.selected_tags:
            spec.tag_groups.append(sorted(self.selected_tags))
        special = [tid for tid, var in self.special_vars.items() if var.get()]
        if special:
            spec.tag_groups.append(sorted(special))  # 特殊题目为独立 AND 组

        if self.var_ac_gt.get().strip():
            spec.accepted_gt = int(self.var_ac_gt.get().strip())
        if self.var_ac_lt.get().strip():
            spec.accepted_lt = int(self.var_ac_lt.get().strip())

        if self.var_top.get().strip():
            v = float(self.var_top.get().strip())
            if not 0 < v <= 100:
                raise ValueError("前x% 需在 (0,100] 内")
            spec.top_percent = v

        spec.sort_by = self.var_sort.get()
        spec.order = self.var_order.get()

        if self.var_limit.get().strip():
            spec.limit = int(self.var_limit.get().strip())

        return spec

    def on_start(self) -> None:
        try:
            spec = self._read_spec()
            delay = float(self.var_delay.get().strip() or DEFAULT_DELAY)
        except ValueError as e:
            messagebox.showerror("参数错误", str(e))
            return

        self._set_running(True)
        self.problems = []
        self._clear_result()
        self._cancelled = False

        def worker() -> None:
            try:
                client = LuoguClient(delay=delay, on_progress=self._on_progress)
                self._client = client
                cache = ProblemCache()
                runner = FilterRunner(client, cache, on_status=self._on_status)
                try:
                    result = runner.run(spec)
                    self._queue.put(("done", result))
                finally:
                    cache.close()
            except LuoguBlockedError as e:
                if not self._cancelled:
                    self._queue.put(("error", str(e)))
            except Exception as e:  # noqa: BLE001 兜底
                self._queue.put(("error", f"{type(e).__name__}: {e}"))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()
        self.root.after(100, self._poll_queue)

    def _on_progress(self, page: int, total: int) -> None:
        self._queue.put(("progress", (page, total)))

    def _on_status(self, msg: str) -> None:
        self._queue.put(("status", msg))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "progress":
                    page, total = payload
                    self.progress.configure(maximum=max(total, 1), value=page)
                    self.lbl_status.configure(text=f"拉取中 {page}/{total} 页")
                elif kind == "status":
                    self.lbl_status.configure(text=payload)
                elif kind == "done":
                    self.problems = payload
                    self._fill_result(payload)
                    self.lbl_status.configure(text=f"完成：{len(payload)} 题")
                    self._set_running(False)
                elif kind == "error":
                    messagebox.showerror("错误", payload)
                    self.lbl_status.configure(text="出错")
                    self._set_running(False)
        except queue.Empty:
            pass
        # worker 把结果入队后才退出；只要线程还在或队列还有消息就继续轮询，
        # 避免 "done" 在 worker 退出瞬间被漏掉。
        if self._worker is not None and (
            self._worker.is_alive() or not self._queue.empty()
        ):
            self.root.after(100, self._poll_queue)

    def on_cancel(self) -> None:
        self._cancelled = True
        if self._client:
            self._client.cancel()
        self.lbl_status.configure(text="已取消")
        self._set_running(False)

    def _fill_result(self, problems: list[Problem]) -> None:
        self._clear_result()
        store = self.store
        for p in problems:
            tag_names = "/".join(
                store.display_name(t) for t in p.tags
                if store.by_id.get(t, {}).get("type") == 2
            ) or "—"
            self.result_tree.insert("", "end", values=(
                p.pid, p.name, tag_names, p.difficulty_name,
                f"{p.accept_rate:.1%}", f"{p.totalAccepted}/{p.totalSubmit}",
            ))
        state = tk.NORMAL if problems else tk.DISABLED
        self.btn_copy.configure(state=state)
        self.btn_export.configure(state=state)

    def _clear_result(self) -> None:
        self.result_tree.delete(*self.result_tree.get_children())

    def _set_running(self, running: bool) -> None:
        self.btn_start.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.btn_cancel.configure(state=tk.NORMAL if running else tk.DISABLED)

    def _export_text(self) -> str:
        try:
            split = int(self.var_split.get().strip() or DEFAULT_SPLIT)
        except ValueError:
            split = DEFAULT_SPLIT
        return pids_to_text(self.problems, sep=DEFAULT_SEP, split=split)

    def on_copy(self) -> None:
        if not self.problems:
            return
        text = self._export_text()
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.lbl_status.configure(text=f"已复制 {len(self.problems)} 个题号")

    def on_export(self) -> None:
        if not self.problems:
            return
        path = filedialog.asksaveasfilename(
            title="导出题号", defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(self._export_text() + "\n")
        self.lbl_status.configure(text=f"已导出到 {path}")


def run_gui() -> int:
    root = tk.Tk()
    LuoguGui(root)
    root.mainloop()
    return 0
