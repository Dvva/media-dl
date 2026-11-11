"""文件名模板 ↔ 字段 ↔ 网址。

两个方向：
  1. 正向：`naming.render()` 把字段填进模板，生成文件名；
  2. 反向：本模块把已有文件名按模板拆回字段，再拼回作品网址。

位置参数（你在命令行里说的写法）：
  {1} = 作者   {2} = 作品 id   {3} = 平台   {4} = 日期   {5} = 序号
也支持具名：{platform} {author} {author_id} {nickname} {id} {date} {index}
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

PLATFORMS = ("twitter", "xhs", "douyin", "tiktok", "bilibili", "youtube", "telegram")

PLATFORM_ALIASES = {
    "x": "twitter",
    "twitter": "twitter",
    "xhs": "xhs",
    "xiaohongshu": "xhs",
    "douyin": "douyin",
    "tiktok": "tiktok",
    "bilibili": "bilibili",
    "b23": "bilibili",
    "youtube": "youtube",
    "yt": "youtube",
    "telegram": "telegram",
    "tg": "telegram",
}

POSITIONAL = {
    "1": "author",
    "2": "id",
    "3": "platform",
    "4": "date",
    "5": "index",
}

SUPPORTED_VARS = {
    "platform", "author", "author_id", "nickname", "id", "date", "datetime",
    "title", "index", "type", "ext", "url",
}

# 各平台默认的重建规则；可在 config.toml 的 [urls] 段覆盖
DEFAULT_URLS = {
    "twitter": "https://x.com/i/status/{id}",
    "xhs": "https://www.xiaohongshu.com/explore/{id}",
    "douyin": "https://www.douyin.com/video/{id}",
    # TikTok 必须有作者 handle；昵称拼不出可访问链接
    "tiktok": "https://www.tiktok.com/@{author}/video/{id}",
    "bilibili": "https://www.bilibili.com/video/{id}",
    "youtube": "https://www.youtube.com/watch?v={id}",
    # Telegram 必须有频道名 + 消息号
    "telegram": "https://t.me/{author}/{id}",
}

VAR_RE = re.compile(r"\{([A-Za-z0-9_]+)\}")
KNOWN_SUFFIXES = {
    ".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv", ".ts",
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic",
    ".mp3", ".m4a", ".aac", ".flac", ".wav", ".opus", ".ogg",
    ".pdf", ".zip", ".7z", ".rar",
}
INDEX_SUFFIX_RE = re.compile(r"^(?P<stem>.*?)[_\-\.](?P<index>\d{2})$")
PLATFORM_PREFIX_RE = re.compile(
    r"^(?P<platform>" + "|".join(PLATFORMS) + r")[_\-\.](?P<rest>.+)$", re.I
)
GALLERYDL_RAW_RE = re.compile(r"^(?P<id>\d{15,25})[-_](?P<hash>[A-Za-z0-9_-]+)$")
LEGACY_PREFIXED_RAW_RE = re.compile(
    r"^(?P<platform>" + "|".join(PLATFORMS) + r")[_\-](?P<id>\d{15,25})"
    r"[-_](?P<hash>[A-Za-z0-9_-]+)$",
    re.I,
)


def _valid_id(platform: str | None, value: str) -> bool:
    """粗校验 id，避免把 ``telegram_某频道`` 误当成 ``平台_id``。"""
    if not value:
        return False
    value = str(value).strip()
    platform = normalize_platform(platform)
    if platform in {"twitter", "douyin", "tiktok", "telegram"}:
        return value.isdigit() and len(value) >= 5
    if platform == "xhs":
        return bool(re.fullmatch(r"[0-9a-fA-F]{16,}", value))
    if platform == "bilibili":
        return bool(re.fullmatch(r"(BV[0-9A-Za-z]+|\d+)", value))
    if platform == "youtube":
        return bool(re.fullmatch(r"[A-Za-z0-9_-]{6,}", value))
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{4,}", value))


def valid_id(platform: str | None, value: str) -> bool:
    """公开的 id 粗校验（redl 裸 id 用）。"""
    return _valid_id(platform, value)




def normalize_platform(platform: str | None) -> str | None:
    if not platform:
        return None
    return PLATFORM_ALIASES.get(str(platform).strip().lower(), str(platform).strip().lower())


def normalize_template(template: str) -> str:
    """把 {1}..{5} 换成具名变量，统一路径分隔符。"""
    template = (template or "").replace("\\", "/")

    def repl(match: re.Match) -> str:
        key = match.group(1)
        return "{" + POSITIONAL.get(key, key) + "}"

    return VAR_RE.sub(repl, template)


def basename_template(template: str) -> str:
    """只取文件名部分（目录部分不参与反向解析）。"""
    return normalize_template(template).rsplit("/", 1)[-1]


def template_vars(template: str) -> set[str]:
    return {m.group(1) for m in VAR_RE.finditer(normalize_template(template))}


def check_template(template: str) -> list[str]:
    """返回模板里的未知变量名。"""
    return sorted(v for v in template_vars(template) if v not in SUPPORTED_VARS)


def split_index(stem: str) -> tuple[str, str | None]:
    """拆出末尾两位序号（多文件时追加的 _01）。"""
    match = INDEX_SUFFIX_RE.match(stem)
    if match and match.group("index") != "00":
        return match.group("stem"), match.group("index")
    return stem, None


def compile_template(template: str) -> re.Pattern | None:
    """把模板编译成正则；模板为空或变量重复时返回 None。"""
    tpl = basename_template(template)
    # 序号单独处理：模板里的 {index} 段直接去掉，文件名末尾两位再拆
    tpl = re.sub(r"[_\-\.]?\{index\}", "", tpl)

    parts: list[tuple[str, str]] = []
    pos = 0
    for match in VAR_RE.finditer(tpl):
        if match.start() > pos:
            parts.append(("lit", tpl[pos:match.start()]))
        parts.append(("var", match.group(1)))
        pos = match.end()
    if pos < len(tpl):
        parts.append(("lit", tpl[pos:]))

    variables = [value for kind, value in parts if kind == "var"]
    if not variables or len(variables) != len(set(variables)):
        return None

    regex = "^"
    for index, (kind, value) in enumerate(parts):
        if kind == "lit":
            regex += re.escape(value)
            continue
        # 最后一个变量贪婪，避免作者名里的下划线把 id 抢走
        greedy = index == len(parts) - 1
        regex += f"(?P<{value}>.+)" if greedy else f"(?P<{value}>.+?)"
    regex += "$"
    try:
        return re.compile(regex, re.IGNORECASE)
    except re.error:
        return None


def _infer_platform(name: str, explicit: str | None) -> str | None:
    platform = normalize_platform(explicit)
    if platform:
        return platform
    match = PLATFORM_PREFIX_RE.match(name)
    if match:
        return normalize_platform(match.group("platform"))
    return None


def _candidate_templates(cfg, platform: str | None, extra: list[str] | None) -> list[str]:
    templates: list[str] = []

    def add(value) -> None:
        if not value:
            return
        for item in (value if isinstance(value, (list, tuple)) else [value]):
            text = str(item).strip()
            if text and text not in templates:
                templates.append(text)

    if cfg is not None:
        if platform:
            add(cfg.naming_for(platform))
            add(cfg.get(f"patterns.{platform}"))
        else:
            for name in PLATFORMS:
                add(cfg.naming_for(name))
            add(cfg.get("naming.default"))
        add(cfg.get("patterns.default"))
        add(cfg.get("patterns.legacy"))

    add(extra or [])

    # 兜底：最常见的两种形状
    add("{platform}_{author}_{id}")
    add("{platform}_{id}")
    return templates


def _rebalance(fields: dict) -> dict:
    """作者名里带下划线时，把被 id 抢走的前缀还回作者。

    例：twitter_foo_bar_123456789 先匹配成 author=foo、id=bar_123456789，
    这里按“最后一个下划线后的数字才是 id”改回 author=foo_bar、id=123456789。
    """
    platform = normalize_platform(fields.get("platform"))
    author = fields.get("author")
    value = fields.get("id")
    if not author or not value:
        return fields

    # YouTube 的 id 固定 11 位、B站 BV 号固定 12 位，可以直接按长度切
    if platform == "youtube" and len(str(value)) > 11:
        tail = str(value)[-11:]
        if _valid_id("youtube", tail):
            prefix = str(value)[:-11].rstrip("_-")
            return {**fields, "author": f"{author}_{prefix}", "id": tail}
    if platform == "bilibili" and str(value).upper().find("BV") > 0:
        text = str(value)
        pos = text.upper().rfind("BV")
        tail = text[pos:]
        if _valid_id("bilibili", tail):
            prefix = text[:pos].rstrip("_-")
            return {**fields, "author": f"{author}_{prefix}", "id": tail}

    if "_" not in str(value):
        return fields
    if platform not in {"twitter", "douyin", "tiktok", "telegram", "xhs", "bilibili"}:
        return fields
    prefix, _, tail = str(value).rpartition("_")
    if prefix and _valid_id(platform, tail):
        fields = dict(fields)
        fields["author"] = f"{author}_{prefix}"
        fields["id"] = tail
    return fields


def parse_name(
    name: str,
    *,
    cfg=None,
    platform: str | None = None,
    extra_patterns: list[str] | None = None,
) -> dict | None:
    """文件名（不含扩展名也可）→ 字段字典；失败返回 None。"""
    text = str(name)
    suffix = Path(text).suffix.lower()
    # 只剥掉已知媒体后缀；作者名里带点（wayru.fx）时不能按 Path.stem 乱切
    if suffix in KNOWN_SUFFIXES:
        text = text[: -len(suffix)]
    stem = text
    stem, index = split_index(stem)
    inferred = _infer_platform(stem, platform)

    for template in _candidate_templates(cfg, inferred, extra_patterns):
        regex = compile_template(template)
        if not regex:
            continue
        match = regex.match(stem)
        if not match:
            continue
        fields = {key: value for key, value in match.groupdict().items() if value}
        if not fields.get("id"):
            continue

        fields["platform"] = normalize_platform(fields.get("platform")) or inferred
        if not fields["platform"]:
            # 没有平台字段时，从文件名前缀推断
            prefix = _infer_platform(stem, None)
            if prefix:
                fields["platform"] = prefix
            else:
                continue
        fields = _rebalance(fields)
        variables = template_vars(template)
        # 只有“平台_id”两段时，id 必须是像 id 的东西，不能是频道名
        if variables == {"platform", "id"} and not _valid_id(fields["platform"], fields["id"]):
            continue
        fields["index"] = index
        fields["stem"] = stem
        fields["template"] = template
        return fields

    # 旧命名：twitter_<tweet_id>-<hash>.jpg
    match = LEGACY_PREFIXED_RAW_RE.match(stem)
    if match:
        return {
            "platform": normalize_platform(match.group("platform")),
            "id": match.group("id"),
            "index": index,
            "stem": stem,
            "template": "<legacy-raw>",
        }

    # 旧命名：gallery-dl 的 <tweet_id>-<hash>.jpg
    match = GALLERYDL_RAW_RE.match(stem)
    if match and inferred:
        return {
            "platform": inferred,
            "id": match.group("id"),
            "index": index,
            "stem": stem,
            "template": "<gallery-dl-raw>",
        }

    return None


def parse_file(path: str | Path, *, cfg=None, platform: str | None = None,
               extra_patterns: list[str] | None = None) -> dict | None:
    return parse_name(Path(path).name, cfg=cfg, platform=platform,
                      extra_patterns=extra_patterns)


def url_template_for(platform: str, cfg=None) -> str | None:
    platform = normalize_platform(platform) or platform
    if cfg is not None:
        value = cfg.get(f"urls.{platform}")
        if value:
            return str(value)
    return DEFAULT_URLS.get(platform)


def rebuild_url(platform: str, fields: dict, cfg=None) -> str | None:
    """字段 → 作品网址；信息不足返回 None。"""
    platform = normalize_platform(platform) or platform
    fields = dict(fields)
    fields["platform"] = platform

    # 推特有作者就用规范形式，没有就用 /i/status/，两者都能打开
    if platform == "twitter" and fields.get("author"):
        template = "https://x.com/{author}/status/{id}"
    else:
        template = url_template_for(platform, cfg)
    if not template:
        return None

    needed = template_vars(template)
    for key in needed:
        value = fields.get(key)
        if value is None or str(value).strip() == "":
            return None

    result = template
    for key in needed:
        value = str(fields[key]).strip()
        if key in {"author", "author_id", "nickname"}:
            value = quote(value, safe="@._-")
        result = result.replace("{" + key + "}", value)
    return result


def can_rebuild(platform: str, fields: dict, cfg=None) -> tuple[bool, str]:
    """能否重建网址，不能时返回原因（用于首次运行提醒）。"""
    platform = normalize_platform(platform) or platform
    url = rebuild_url(platform, fields, cfg)
    if url:
        return True, ""
    if platform == "tiktok" and not fields.get("author"):
        return False, "TikTok 重建网址需要作者 handle（昵称不行），文件名里缺作者"
    if platform == "telegram" and not fields.get("author"):
        return False, "Telegram 重建网址需要频道名 + 消息号"
    if not fields.get("id"):
        return False, "文件名里没有作品 id"
    return False, "缺少重建该平台网址所需的字段"
