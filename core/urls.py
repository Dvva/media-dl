"""链接抽取：从分享文案 / 多个参数 / 拼接字符串里抠出所有 URL。

设计要点：
  - 不止取第一个：抖音分享文案、多个链接直接拼接（…qhttps://…）都要拆开；
  - 遇到中文、全角标点、空白就截断，避免把“复制此链接”吞进 URL；
  - 去重保序，非 URL 参数直接忽略（由调用方决定是否报错）。
"""

from __future__ import annotations

import html
import re
from typing import Iterable

URL_START_RE = re.compile(r"https?://", re.IGNORECASE)

# 这些字符出现在 URL 里基本意味着文案结束
STOP_CHARS = set(' \t\r\n\v\f<>"\'`|，。；、！？：（）【】《》〈〉「」『』“”‘’')

# 中日韩文字与全角符号：URL 里极少出现未编码的汉字
CJK_RE = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")

# URL 末尾常见的标点，属于文案而不是链接
TRAILING = '.,;:!?)]}>"\'' + '，。；、！？：）】》」』”’'

# 协议后面必须跟一个像域名的东西，过滤 “https://” 这种正文
HOST_RE = re.compile(r"^https?://[A-Za-z0-9\u0080-\uffff][^\s/]*", re.IGNORECASE)


def _clean_url(raw: str) -> str:
    """截断中文、去掉末尾标点，返回干净 URL。"""
    text = html.unescape(raw)

    match = CJK_RE.search(text)
    if match:
        text = text[: match.start()]

    text = text.rstrip(TRAILING)
    # 括号可能成对出现在路径里，只在明显不平衡时再削一次
    while text and text[-1] in ")]}" and text.count(text[-1]) > text.count(
        {")": "(", "]": "[", "}": "{"}[text[-1]]
    ):
        text = text[:-1].rstrip(TRAILING)

    return text


def iter_urls(texts: Iterable[object]) -> list[str]:
    """从任意多个字符串里抽出全部 URL，去重保序。"""
    text = "\n".join("" if item is None else str(item) for item in texts)
    text = html.unescape(text)

    starts = [m.start() for m in URL_START_RE.finditer(text)]
    found: list[str] = []

    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        chunk = text[start:end]

        # 先按空白 / 文案标点截断
        cut = len(chunk)
        for pos, char in enumerate(chunk):
            if char in STOP_CHARS:
                cut = pos
                break
        chunk = _clean_url(chunk[:cut])

        if not HOST_RE.match(chunk):
            continue
        if chunk not in found:
            found.append(chunk)

    return found


def extract_urls(*texts: object) -> list[str]:
    """iter_urls 的便捷入口。"""
    return iter_urls(texts)


def first_url(text: object) -> str | None:
    urls = iter_urls([text])
    return urls[0] if urls else None
