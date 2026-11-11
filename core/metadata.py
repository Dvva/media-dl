"""只取元数据：判平台、拿作者 / 作品 id / 发布时间，不下载媒体。

推特走 gallery-dl --dump-json（拿不到就退回 yt-dlp -J）；
TikTok / B站 / YouTube / Telegram 走 yt-dlp -J；
抖音 / 小红书本来就只请求页面，直接复用解析器。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from core import detect
from core.result import Status
from core.timeutil import parse_timestamp
from core.toolrun import run_hidden, which
from platforms.base import Content

LOG_LINE_RE = re.compile(r"^\[[A-Za-z][^\]]{0,40}\]")

def _load_json(lines: list[str]) -> object | None:
    clean = [line for line in lines if not LOG_LINE_RE.match(line.strip())]
    blob = "\n".join(clean).strip()
    if not blob:
        return None
    start = min((i for i, char in enumerate(blob) if char in "[{"), default=-1)
    if start < 0:
        return None
    try:
        return json.loads(blob[start:])
    except json.JSONDecodeError:
        return None


def _walk_meta(obj) -> dict | None:
    """gallery-dl 的 dump 是 [[type, data], ...]，递归找带作者信息的 dict。"""
    if isinstance(obj, dict):
        if "tweet_id" in obj or ("id" in obj and ("username" in obj or "user_id" in obj)):
            return obj
        for value in obj.values():
            found = _walk_meta(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _walk_meta(value)
            if found:
                return found
    return None


def _gallery_meta(url: str, cfg) -> tuple[dict, str]:
    exe = which("gallery-dl")
    if not exe:
        return {}, "未找到 gallery-dl"
    cmd = [exe, "--dump-json", "--range", "1"]
    cookie = cfg.cookie_file("twitter")
    if cookie:
        cmd += ["--cookies", str(cookie)]
    if cfg.proxy:
        cmd += ["--proxy", cfg.proxy]
    cmd.append(url)

    try:
        code, lines = run_hidden(cmd, timeout=120)
    except Exception as exc:  # noqa: BLE001
        return {}, f"gallery-dl 元数据失败: {exc}"
    data = _load_json(lines)
    meta = _walk_meta(data) if data is not None else None
    if not meta:
        detail = "；".join(lines[-3:]) if lines else f"退出码 {code}"
        return {}, f"gallery-dl 没返回推文元数据（{detail}）"
    return meta, ""


def _ytdlp_info(url: str, platform: str, cfg) -> tuple[dict, str]:
    exe = which("yt-dlp")
    if not exe:
        return {}, "未找到 yt-dlp"

    cmd = [
        exe, "-J", "--skip-download", "--no-warnings",
        "--socket-timeout", "30",
    ]
    if platform != "telegram":
        cmd.append("--no-playlist")
    if platform == "bilibili":
        cmd += [
            "--add-header", "Referer:https://www.bilibili.com/",
            "--user-agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        ]
    if platform == "youtube":
        cmd += ["--js-runtimes", "node", "--remote-components", "ejs:github"]

    cookie = cfg.cookie_file(platform)
    if cookie:
        cmd += ["--cookies", str(cookie)]
    if cfg.proxy:
        cmd += ["--proxy", cfg.proxy]
    cmd.append(url)

    try:
        code, lines = run_hidden(cmd, timeout=180)
    except Exception as exc:  # noqa: BLE001
        return {}, f"yt-dlp 元数据失败: {exc}"
    data = _load_json(lines)
    if not isinstance(data, dict):
        detail = "；".join(lines[-3:]) if lines else f"退出码 {code}"
        return {}, f"yt-dlp 没返回元数据（{detail}）"
    if data.get("entries"):
        entries = [item for item in data["entries"] if isinstance(item, dict)]
        if entries:
            data = entries[0]
    return data, ""


def _strip_at(value: str) -> str:
    return str(value or "").strip().lstrip("@")


def _gallery_user(meta: dict) -> tuple[str, str, str]:
    """gallery-dl 新版的 username 可能是用户对象，不一定是字符串。"""
    raw = meta.get("username") or meta.get("user") or meta.get("author")
    if isinstance(raw, dict):
        author = str(raw.get("name") or raw.get("screen_name") or "")
        nickname = str(raw.get("nick") or raw.get("name") or "")
        user_id = str(raw.get("id") or "")
        return author, nickname, user_id
    author = _strip_at(raw or "")
    nickname = str(meta.get("fullname") or raw or "")
    return author, nickname, str(meta.get("user_id") or "")


def _content_from_gallery(meta: dict, url: str, platform: str) -> Content:
    tweet_id = str(meta.get("tweet_id") or meta.get("id") or "")
    author, nickname, user_id = _gallery_user(meta)
    thumbnail = meta.get("thumbnail")
    return Content(
        platform=platform,
        id=tweet_id,
        url=url,
        author=author,
        nickname=nickname,
        author_id=user_id,
        title=str(meta.get("content") or meta.get("title") or ""),
        timestamp=parse_timestamp(meta.get("date") or meta.get("timestamp")),
        cover_url=thumbnail if isinstance(thumbnail, str) else None,
    )


def _content_from_ytdlp(info: dict, url: str, platform: str) -> Content:
    raw_id = str(info.get("id") or "")
    author = ""
    nickname = str(info.get("uploader") or info.get("channel") or info.get("creator") or "")

    if platform == "tiktok":
        author = _strip_at(info.get("uploader_id") or info.get("uploader") or "")
    elif platform == "twitter":
        author = _strip_at(info.get("uploader_id") or info.get("uploader") or "")
    elif platform == "telegram":
        author = _strip_at(
            info.get("uploader_id") or info.get("channel") or info.get("uploader") or ""
        )
        if "/" in raw_id:
            channel, _, message_id = raw_id.rpartition("/")
            author = author or _strip_at(channel)
            raw_id = message_id
    else:
        author = str(info.get("uploader") or info.get("channel") or "")

    timestamp = parse_timestamp(
        info.get("timestamp") or info.get("release_timestamp") or info.get("upload_date")
    )
    return Content(
        platform=platform,
        id=raw_id,
        url=url,
        author=author,
        nickname=nickname,
        author_id=str(info.get("uploader_id") or info.get("channel_id") or ""),
        title=str(info.get("title") or info.get("description") or ""),
        timestamp=timestamp,
        cover_url=info.get("thumbnail") or None,
    )


def _cache_path(cfg) -> Path:
    return Path(cfg.state_dir) / "probe-cache.json"


def _cache_get(cfg, url: str, platform: str) -> Content | None:
    path = _cache_path(cfg)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    item = data.get(url)
    if not isinstance(item, dict):
        return None
    try:
        ttl_days = float(cfg.get("behavior.probe_cache_ttl_days", 7))
    except (TypeError, ValueError):
        ttl_days = 7
    if time.time() - float(item.get("_ts") or 0) > ttl_days * 86400:
        return None
    item = dict(item)
    item.pop("_ts", None)
    try:
        return Content(**item)
    except TypeError:
        return None


def _cache_put(cfg, url: str, content: Content) -> None:
    path = _cache_path(cfg)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    record = {
        "platform": content.platform,
        "id": content.id,
        "url": content.url,
        "author": content.author,
        "nickname": content.nickname,
        "author_id": content.author_id,
        "title": content.title,
        "timestamp": content.timestamp,
        "cover_url": content.cover_url,
        "_ts": time.time(),
    }
    data[url] = record
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def gallery_meta(url: str, cfg) -> tuple[dict, str]:
    """公开入口：gallery-dl 元数据（给 gallerydl_backend 复用）。"""
    return _gallery_meta(url, cfg)


def content_from_gallery(meta: dict, url: str, platform: str) -> Content:
    return _content_from_gallery(meta, url, platform)


def content_from_ytdlp(info: dict, url: str, platform: str) -> Content:
    return _content_from_ytdlp(info, url, platform)


def probe(url: str, platform: str | None, cfg, *, log=print, use_cache: bool = True) -> Content:
    """只解析属性，不下载。失败时返回带状态和 message 的 Content。"""
    from core.patterns import normalize_platform

    platform = normalize_platform(platform)
    if not platform:
        platform = detect.platform_of(url)

    if not platform:
        return Content(platform="", id="", status=Status.SKIP_UNSUPPORTED,
                       message="无法识别平台")

    if use_cache:
        cached = _cache_get(cfg, url, platform)
        if cached is not None:
            return cached

    content: Content
    if platform == "twitter":
        meta, error = _gallery_meta(url, cfg)
        if meta:
            content = _content_from_gallery(meta, url, platform)
        else:
            info, error2 = _ytdlp_info(url, platform, cfg)
            content = (_content_from_ytdlp(info, url, platform) if info
                       else Content(platform=platform, id="", status=Status.FAIL_TOOL,
                                    message=error or error2))
    elif platform in {"tiktok", "bilibili", "youtube", "telegram"}:
        info, error = _ytdlp_info(url, platform, cfg)
        content = (_content_from_ytdlp(info, url, platform) if info
                   else Content(platform=platform, id="", status=Status.FAIL_TOOL,
                                message=error))
    elif platform in {"douyin", "xhs"}:
        from platforms import douyin, xhs

        extraction = douyin.extract(url, cfg, log=log) if platform == "douyin" \
            else xhs.extract(url, cfg, log=log)
        content = extraction.content
        content.items = []          # 只取属性，绝不再下媒体
        content.url = content.url or url
    else:
        return Content(platform=platform, id="", status=Status.SKIP_UNSUPPORTED,
                       message=f"{platform} 还没有元数据解析")

    if content.status is Status.OK and content.id:
        _cache_put(cfg, url, content)
    return content
