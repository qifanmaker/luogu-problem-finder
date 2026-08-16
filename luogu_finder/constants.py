"""全局常量：难度标签、题目类型、默认参数。"""

# 难度标签（用户确认的 2026 新命名体系，8 档）
DIFFICULTY_LABELS = {
    0: "暂无评定",
    1: "入门",
    2: "普及−",
    3: "普及",
    4: "普及+/提高−",
    5: "提高",
    6: "提高+/省选−",
    7: "省选/NOI−",
    8: "NOI/NOI+/CTS",
}

# 题目类型（来自 _lfe/config 的 problemTypes）。当前洛谷题库实际只有 P、B。
PROBLEM_TYPES = ["P", "T", "U", "B", "CF", "SP", "AT", "UVA"]

# 请求间隔默认值（秒）。实际间隔为 delay * random(0.5, 1.5) 抖动。
DEFAULT_DELAY = 0.8
# 延迟抖动范围（相对倍数）
DELAY_JITTER = (0.5, 1.5)
# 网络/5xx 错误重试次数与退避基准秒
MAX_RETRIES = 3
RETRY_BACKOFF = [1.0, 3.0, 6.0]

# 分页大小（洛谷固定 50，服务端返回）
PER_PAGE = 50

# 缓存有效期（小时）
DEFAULT_TTL_HOURS = 24

# 导出默认分隔符与分段
DEFAULT_SEP = ","
DEFAULT_SPLIT = 50

# 请求头
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
