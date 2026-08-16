# 洛谷题库接口调研笔记（2026-08-16 实测）

> 基于对 `https://www.luogu.com.cn/problem/list` 的实测逆向，参考
> [0f-0b/luogu-api-docs](https://github.com/0f-0b/luogu-api-docs)（部分已过时，以本文实测为准）。

## 0. 反爬 / 前置要求

- 首次访问 `/problem/list` 会 302 重定向到同 URL，并下发 `C3VK` cookie。
  **必须用 cookie jar（`-c`/`-b`）且跟随重定向**，之后才能拿到 200。
- 建议带 `Referer: https://www.luogu.com.cn/problem/list`。
- UA 建议用真实浏览器 UA（文档说不能以 `mozilla/` 开头、不能含 `python-requests`，
  但实测以 `Mozilla/5.0` 开头的 UA 也可用 —— 该限制可能已放宽）。
- 题库列表 / 题目详情均为**公开数据**，不需要登录（响应中 `user` 字段为 `null`）。

## 1. 关键机制：`x-lentille-request: content-only`

洛谷现在用新前端框架（内部代号 lentille / columba）。旧文档里的 `_contentOnly` 参数
**已失效**（实测 GET 加 `_contentOnly=1` 仍返回完整 HTML，不是 JSON）。

**正确做法**：GET 请求时带请求头

```
x-lentille-request: content-only
```

即可拿到纯 JSON（与页面内嵌 JSON 结构一致，见 §2）。

页面本身是 SSR，完整 HTML 内嵌 JSON 于：

```html
<script id="lentille-context" type="application/json"> {...} </script>
```

## 2. 题库列表接口

```
GET https://www.luogu.com.cn/problem/list
Header: x-lentille-request: content-only
```

### 查询参数（均可选）

| 参数 | 说明 | 备注 |
|---|---|---|
| `page` | 页码，从 1 起，每页 50 条 | 超出范围会被 clamp 到最后一页 |
| `keyword` | 标题搜索关键词 | |
| `content=true` | 全文搜索（标题+题目内容） | 全库命中会封顶在约 1000 条 |
| `difficulty` | 难度筛选 | **多选用 `|` 分隔**（OR/并集），如 `1|2|3`；`0` 等价于不过滤；`,` 分隔**不生效**（只取第一个值） |
| `tag` | 标签筛选 | `|` 分隔各组 = **组间 AND**；组内用 `,` = **组内 OR**。例：`tag=1,2|3` = (tag1 或 tag2) 且 tag3 |
| `type` | 题目类型 | `P`=普通题(16125)，`B`=入门题(1160)，缺省/`luogu`=全部(17285) |
| `orderBy` | 排序字段 | **仅 `pid` 和 `difficulty` 有效**；其他值返回 400 `Invalid orderBy`（`accepted`/`submit`/`rand` 等都不行） |
| `order` | `asc` / `desc` | 默认 `pid` 升序 |

### 响应结构

```jsonc
{
  "instance": "main",
  "template": "problem.list",
  "status": 200,
  "locale": "zh-CN",
  "data": {
    "problems": {
      "perPage": 50,
      "count": 17285,          // 总题数
      "result": [               // 本页 50 题
        {
          "pid": "P1000",       // 题号（P 前缀 / B 前缀）
          "type": "P",          // P 或 B
          "name": "超级玛丽游戏",
          "difficulty": 1,      // 0-8，见 §5
          "tags": [2, 108],     // 标签 ID 数组
          "totalSubmit": 1821709,
          "totalAccepted": 698363,
          "flag": 5,            // 位掩码，见 §6
          "provider": {         // 出题人（完整 user 对象）
            "uid": 3, "avatar": "...", "name": "洛谷",
            "slogan": "", "badge": null, "isAdmin": true,
            "isBanned": false, "color": "Purple",
            "ccfLevel": 0, "xcpcLevel": 0, "background": ""
          }
        }
      ]
    },
    "filter": {                 // 回显本次筛选
      "tag": [], "content": null, "keyword": "",
      "difficulty": [], "type": "luogu", "page": 1
    }
  },
  "user": null,                  // 未登录为 null
  "time": 1786892025.386249
}
```

## 3. 题目详情接口

```
GET https://www.luogu.com.cn/problem/{pid}      // 如 /problem/P1000
Header: x-lentille-request: content-only
```

响应 `data.problem` 字段：

- 基础字段：`pid` `type` `name` `difficulty` `tags` `totalSubmit` `totalAccepted` `flag` `provider`
- `contenu` 与 `content`（内容重复的两份）：内含
  `name` `background`(题目背景) `description`(题目描述) `formatI`(输入格式) `formatO`(输出格式) `hint`(提示) `locale`
- `samples`: `[[input, output], ...]`
- `limits`: `{time: [ms], memory: [KB]}`
- `attachments`、`translations`（英/中文翻译）、`recommendations`（相关题目）、
  `forum`、`discussions`、`bookmarked`、`acceptLanguages`、`canEdit` 等

## 4. 标签接口

```
GET https://www.luogu.com.cn/_lfe/tags/zh-CN
```

```jsonc
{
  "tags": [{ "id": 2, "name": "字符串", "type": 2, "parent": null }, ...],
  "types": [{ "id": 1, "type": "Region", "name": "区域", ... }, ...],
  "_locale": "zh-CN", "_version": "..."
}
```

标签类型（`types` / `tag.type`）：

| type | 含义 | 数量 |
|---|---|---|
| 1 | Region 区域（重庆、福建…） | 56 |
| 2 | Algorithm 算法（字符串、DP、图论…） | 262（22 个根分类） |
| 3 | Origin 来源（USACO、NOI、洛谷原创…） | 82 |
| 4 | Time 时间/年份（1997、1998…） | 37 |
| 5 | SpecialProblem 特殊题目（交互题、提交答案、SPJ、O2 优化…） | 5 |
| 6 | Others 其他 | 63 |

完整标签表已保存到 `data/tags.json`。

## 5. 难度（difficulty）取值

实测分布（2026-08-16）：

| 值 | 题数 |
|---|---|
| 0 | 17285（**等价于不过滤**，见下） |
| 1 | 1154 |
| 2 | 1959 |
| 3 | 2335 |
| 4 | 2563 |
| 5 | 2892 |
| 6 | 492 |
| 7 | 3594 |
| 8 | 1892（**新增档位**，旧文档只到 7） |

注意：1+2+…+8 之和为 16881，总题数 17285，差额约 404 道为"暂无评定"
（difficulty=0），但 `difficulty=0` 作为筛选参数被服务端当作"不过滤"处理。

难度名（2026 新命名，见 §6b）：1 入门 / 2 普及− / 3 普及 / 4 普及+/提高− /
5 提高 / 6 提高+/省选− / 7 省选/NOI− / 8 NOI/NOI+/CTS。

## 6. flag 字段

**实测确认（2026-08-16）**：flag **不是位掩码**，而是可见性枚举（取自
`_lfe/config` 的 `problemFlagTypes`）：

| flag | type | 含义 |
|---|---|---|
| -1 | Deleted | 删除 |
| 0 | Hidden | 隐藏 |
| 2 | TeamAccessEnabled | 仅团队可见 |
| 5 | PublicAccessEnabled | **公众可见**（题库列表全部为此值） |
| 6 | ContestMode | 比赛赛题 |

## 6b. 难度标签（2026 新命名）

`_lfe/config` 的 `problemDifficulty` 已更新为 8 档（用户确认，2026-08-16）：

| id | 名称 | id | 名称 |
|---|---|---|---|
| 0 | 暂无评定 | 5 | 提高 |
| 1 | 入门 | 6 | 提高+/省选− |
| 2 | 普及− | 7 | 省选/NOI− |
| 3 | 普及 | 8 | NOI/NOI+/CTS |
| 4 | 普及+/提高− | | |

注意：题库列表数据中 difficulty 取值 1-8（另有 ~404 道为 0=暂无评定），
difficulty=0 作为筛选参数时被服务端当作「不过滤」处理。

## 7. 与 luogu-api-docs 的差异（时效性问题）

1. `_contentOnly` 参数已失效 → 用 `x-lentille-request: content-only` 头。
2. `orderBy` 仅支持 `pid`、`difficulty`（文档里的通用 params 太宽泛）。
3. `difficulty` 多选必须用 `|`，文档没写。
4. 新增 `difficulty=8` 档位。
5. 新增 `_lfe/tags/zh-CN` 标签接口；标签体系带 `parent`/`type` 层级。
6. UA 限制实际比文档宽松。
