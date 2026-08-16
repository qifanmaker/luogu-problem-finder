# LuoguProblemFinder

跨平台（Windows/macOS/Linux）洛谷题库筛选工具，**零第三方依赖**（纯标准库）。

## 运行

```bash
python main.py --tag 动态规划 --difficulty 3-5 --year 2010-2020 --top 10
python main.py --gui                 # tkinter 图形界面
python main.py --list-tags           # 查看可用标签/年份/难度
```

## 关键约束（用户强调）

- **严禁触发洛谷风控**：默认串行请求 + 随机抖动限速（delay 0.8s × 0.5~1.5），
  等效 ~0.7 req/s。不要为了提高速度随意加并发。见 `client.py::_throttle`。
- 自动处理洛谷 302 + `C3VK` cookie 反爬；用 `x-lentille-request: content-only` 头拿 JSON。

## 洛谷 API 要点（实测，完整版见 docs/luogu-api.md）

- `GET /problem/list` + 头 `x-lentille-request: content-only` → 纯 JSON。
- 查询参数：`tag`（`|` 组间 AND、组内 `,` 的 OR）、`difficulty`（`|` 并集，`0`=不过滤）、
  `type`（P/B）、`keyword`、`page`（每页 50）。
- 服务端**不支持按通过数排序/过滤**，通过数筛选必须本地计算（先拉全候选集）。
- 标签表在 `data/tags.json`；难度 1-8（2026 新命名，见 constants.py）。

## 架构

- `luogu_finder/client.py` 网络层（反爬/限速/重试/风控识别）
- `luogu_finder/filters.py` 查询构建 + 本地筛选（通过数绝对值/前x%）
- `luogu_finder/cache.py` SQLite 缓存（data/cache.db，题目池 + 查询签名）
- `luogu_finder/gui.py` tkinter 界面；`main.py` CLI
