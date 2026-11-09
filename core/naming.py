"""文件名模板渲染。

模板变量：
  {platform} {author} {author_id} {id} {date} {datetime}
  {title} {index} {type} {ext}
"""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta

INVALID_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
MULTI_SEP = re.compile(r"[_\-\.]{2,}")


def sanitize(name: str, limit: int = 0) -> str:
    """去掉文件系统非法字符，压缩重复分隔符。"""
    name = INVALID_CHARS.sub("_", name or "")
    name = name.strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    name = MULTI_SEP.sub(lambda m: m.group(0)[0], name)
    if limit and len(name) > limit:
        name = name[:limit].rstrip("_-. ")
    return name or "untitled"


def fmt_date(ts: float | int | None, tz_name: str = "Asia/Shanghai") -> tuple[str, str]:
    """时间戳 → (YYYYMMDD, YYYYMMDD_HHMM)。无法解析时退回今天。"""
    tz = timezone(timedelta(hours=8))  # 默认东八区，避免依赖 zoneinfo 数据库
    if ts:
        try:
            dt = datetime.fromtimestamp(float(ts), tz=tz)
        except (ValueError, OSError, OverflowError):
            dt = datetime.now(tz)
    else:
        dt = datetime.now(tz)
    return dt.strftime("%Y%m%d"), dt.strftime("%Y%m%d_%H%M")


def render(
    template: str,
    variables: dict,
    *,
    is_multi: bool,
    omit_index_when_single: bool = True,
    max_len: int = 120,
) -> str:
    """渲染模板。单媒体时按配置剔除 `{index}` 段。"""
    tpl = template
    if not is_multi and omit_index_when_single:
        # 连同一个紧邻的分隔符一起去掉，避免出现 xxx__01 或 xxx_01 的孤立段
        tpl = re.sub(r"[_\-.]?\{index\}", "", tpl)
    for key, value in variables.items():
        tpl = tpl.replace("{" + key + "}", str(value))
    # 未替换的占位符统一清空
    tpl = re.sub(r"\{[a-z_]+\}", "", tpl)
    tpl = MULTI_SEP.sub(lambda m: m.group(0)[0], tpl)
    tpl = tpl.strip("_-. ")
    return sanitize(tpl, limit=max_len)


def split_template(template: str) -> tuple[str, str]:
    """把模板拆成 (目录部分, 文件名部分)，用于建子目录。"""
    tpl = template.replace("\\", "/")
    if "/" not in tpl:
        return "", tpl
    head, _, tail = tpl.rpartition("/")
    return head, tail
