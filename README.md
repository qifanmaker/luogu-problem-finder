# 洛谷题库筛选工具

跨平台（Windows / macOS / Linux）Python 工具，从洛谷题库按多种条件筛题，
返回题号 / 名称 / 算法标签 / 难度 / 通过率，并可把题号批量导出/复制。

**零第三方依赖**，只用 Python 标准库。

## 快速开始

```bash
# 查看可用标签 / 年份 / 难度
python main.py --list-tags

# 按标签 + 难度区间 + 年份区间筛选，按通过数取前 10%
python main.py --tag 动态规划 --difficulty 3-5 --year 2010-2020 --top 10

# 通过数绝对值筛选
python main.py --tag 图论 --accepted-gt 1000 --limit 50

# 多标签：逗号=OR，多次 --tag=AND
python main.py --tag 字符串,动态规划 --tag 图论

# 导出题号到文件（逗号连接，每 50 个换行）
python main.py --tag 动态规划 --export result.txt --split 50

# 图形界面
python main.py --gui
```

## 筛选条件

| 参数 | 说明 |
|---|---|
| `--tag 标签[,标签…]` | 算法标签，可多次；每次=一个 AND 组，组内逗号=OR |
| `--special 标签[,标签…]` | 特殊题目标签（交互题/提交答案/Special Judge/O2优化/通信题），独立 AND 组 |
| `--year 2010-2020` | 年份区间，或 `2010,2015` 集合 |
| `--difficulty 3-5` | 难度区间（1-8），或 `3,5` |
| `--type P\|B` | 题目类型（缺省=全部） |
| `--keyword 词` | 关键词模糊搜索 |
| `--accepted-gt N` / `--accepted-lt N` | 通过数量绝对值 |
| `--top X` | 对筛选后候选集按通过数量取前 X% |
| `--sort accepted\|rate\|difficulty\|pid\|name` | 排序字段 |
| `--order asc\|desc` | 排序方向 |
| `--limit N` | 最多输出 N 条 |

## 导出 / 复制

- `--export 文件`：题号写文件。
- `--print-pids`：题号打印到屏幕（便于复制）。
- `--sep` 段内分隔符（默认 `,`），`--split N` 每 N 个换行（默认 50，`0`=单行）。

## 网络与限速（反检测）

- 自动处理洛谷 302 + `C3VK` cookie 反爬；带 `x-lentille-request: content-only` 头拿 JSON。
- **串行请求**，每次间隔 `--delay`（默认 0.8s）× 随机抖动 0.5~1.5，
  等效约 0.7 请求/秒，不会触发风控。
- 网络/5xx 自动指数退避重试；疑似风控时**停止**并提示，不盲目重试。
- 首次拉取某组筛选条件较慢（全库约 346 页 / 数分钟），之后命中本地缓存秒回。

## 缓存

- SQLite（`data/cache.db`）：题目池 + 查询签名缓存。
- 默认有效期 24 小时，`--ttl 小时` 可调；`--refresh` 强制重抓。
- 重叠筛选复用已缓存题目，避免重复请求。

## 图形界面

`python main.py --gui` 打开 tkinter 界面：
- 条件面板：类型 / 关键词 / 难度区间 / 年份区间 / 通过数区间 / 前x% / 排序 / 条数。
- **特殊题目**勾选区：交互题 / 提交答案 / Special Judge / O2优化 / 通信题（与算法标签为 AND）。
- 算法标签树：按根分类分组，**勾选父类自动包含其全部子类**（OR）。
- 结果表格、进度条、取消；「复制编号」「导出到文件」。
- 若 Linux 报缺 `tkinter`，需 `sudo apt install python3-tk`（Windows/macOS 自带）。

## 项目结构

```
main.py                 命令行入口
luogu_finder/
  client.py              HTTP + 反爬 + 限速 + 重试 + 风控识别
  models.py              Problem 数据模型
  tags.py                标签/年份 名称↔ID 映射
  filters.py             服务端查询构建 + 本地筛选（绝对值/百分比）+ 排序
  cache.py               SQLite 缓存
  exporter.py            题号导出/复制格式
  gui.py                 tkinter 界面
  constants.py           难度标签/类型/默认参数
data/tags.json           标签表（/_lfe/tags/zh-CN 抓取）
docs/luogu-api.md        接口调研笔记（实测，含反爬细节）
```

## 说明与限制

- 通过数量前 x% 基于**筛选后候选集**，需先拉取该候选集全部题目（本地排序）。
- `keyword` 为洛谷模糊全文检索（命中标题/内容/标签），结果上限约 1000。
- 年份筛选使用题目的「来源年份」标签；无年份标签的题不会被年份条件命中。
- 难度 0（暂无评定）不能作为筛选条件，且不参与难度区间。
