"""统一的结果状态枚举。

下载器遇到"拿不到"的情况必须区分原因，而不是无脑重试。
"""

from enum import Enum


class Status(str, Enum):
    """单条内容的终态。"""

    OK = "OK"                        # 下载成功
    SKIP_PRIVATE = "SKIP_PRIVATE"    # 私密 / 好友可见 / 未关注
    SKIP_DELETED = "SKIP_DELETED"    # 已删除 / 已下架
    SKIP_PAYWALLED = "SKIP_PAYWALLED"  # 付费 / 会员限定
    SKIP_AUTHOR_DISABLED = "SKIP_AUTHOR_DISABLED"  # 作者关闭了下载
    SKIP_NO_MEDIA = "SKIP_NO_MEDIA"  # 成功解析但没有任何媒体
    SKIP_UNSUPPORTED = "SKIP_UNSUPPORTED"  # 平台不支持 / 链接类型不支持
    FAIL_NETWORK = "FAIL_NETWORK"    # 网络层失败，可重试
    FAIL_PARSE = "FAIL_PARSE"        # 页面结构变化，解析失败
    FAIL_TOOL = "FAIL_TOOL"          # 外部工具（yt-dlp/gallery-dl）失败

    @property
    def is_ok(self) -> bool:
        return self is Status.OK

    @property
    def retryable(self) -> bool:
        """只有网络层失败值得重试。"""
        return self is Status.FAIL_NETWORK


# 软开关（作者意愿）与硬限制的区分，给日志统计用
SOFT_SKIPS = {Status.SKIP_AUTHOR_DISABLED}
HARD_SKIPS = {
    Status.SKIP_PRIVATE,
    Status.SKIP_DELETED,
    Status.SKIP_PAYWALLED,
}
