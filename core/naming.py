"""文件名模板渲染与字符清理。

模板变量：
  {platform} {author} {nickname} {author_id} {id} {date} {datetime}
  {title} {index} {type} {ext}

字符规则（按你的要求）：
  - 文件系统非法字符、控制字符、emoji、零宽字符一律**删除**，不替换成下划线；
  - 空白折叠成一个空格；首尾的点和空格去掉；
  - 清完为空时退回 untitled。
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone, timedelta

INVALID_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
CONTROL_CHARS = re.compile(r"[\u0000-\u001f\u007f-\u009f]")
ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\uFEFF]")
# emoji、旗帜、变体选择符、组合用零宽连接符
EMOJI = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002600-\U000027BF"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA70-\U0001FAFF"
    "\uFE0F\u20E3\u200D"
    "]"
)
MULTI_SEP = re.compile(r"[_\-.]{2,}")
MULTI_SPACE = re.compile(r"[ \t]+")


def sanitize(name: str, limit: int = 0) -> str:
    """删除非法 / 奇怪字符，压缩空白与重复分隔符。"""
    name = str(name or "")
    name = unicodedata.normalize("NFC", name)
    name = INVALID_CHARS.sub("", name)
    name = CONTROL_CHARS.sub("", name)
    name = ZERO_WIDTH.sub("", name)
    name = EMOJI.sub("", name)
    name = name.replace("\u3000", " ")
    name = MULTI_SPACE.sub(" ", name)
    name = name.strip().strip(".")
    name = name.strip("_-. ")
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
    tpl = re.sub(r"\{[A-Za-z0-9_]+\}", "", tpl)
    tpl = tpl.strip("_-. ")
    return sanitize(tpl, limit=max_len)


def split_template(template: str) -> tuple[str, str]:
    """把模板拆成 (目录部分, 文件名部分)，用于建子目录。"""
    tpl = template.replace("\\", "/")
    if "/" not in tpl:
        return "", tpl
    head, _, tail = tpl.rpartition("/")
    return head, tail
