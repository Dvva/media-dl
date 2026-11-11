"""基于 gallery-dl 的后端：twitter / x。

优先只取媒体直链（`gallery-dl -g`），交给本项目的下载器：
  - 进度条、文件时间、命名、覆盖备份都由我们自己控制；
  - 不显示 gallery-dl 的命令与刷屏输出。
只有直链拿不到（m3u8、未知后缀）时才退回本地下载，并同样隐藏工具输出。
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from core import metadata
from core.progress import ProgressBar
from core.result import Status
from core.toolrun import parse_percent, run_hidden, which
from .base import Content, Extraction, MediaItem

SKIP_SUFFIXES = {".json", ".txt"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MEDIA_EXTS = VIDEO_EXTS | IMAGE_EXTS
URL_RE = re.compile(r"^https?://", re.I)


def _common_args(cfg) -> list[str]:
    args: list[str] = []
    cookie = cfg.cookie_file("twitter")
    if cookie:
        args += ["--cookies", str(cookie)]
    if cfg.proxy:
        args += ["--proxy", cfg.proxy]
    return args


def _gallery_urls(url: str, cfg) -> tuple[list[str], str]:
    exe = which("gallery-dl")
    if not exe:
        return [], "未找到 gallery-dl"
    cmd = [exe, "-g", *_common_args(cfg), url]
    try:
        code, lines = run_hidden(cmd, timeout=120)
    except Exception as exc:  # noqa: BLE001
        return [], f"gallery-dl -g 失败: {exc}"

    urls: list[str] = []
    for line in lines:
        text = line.strip()
        if not URL_RE.match(text):
            continue
        if text not in urls:
            urls.append(text)
    if not urls:
        detail = "；".join(lines[-2:]) if lines else f"退出码 {code}"
        return [], f"gallery-dl 没返回媒体直链（{detail}）"
    return urls, ""


def _media_ext(url: str) -> str:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in MEDIA_EXTS:
        return suffix
    # 推特图片常是 /media/xxx?format=jpg&name=large，路径里没有后缀
    from urllib.parse import parse_qs

    fmt = (parse_qs(parsed.query).get("format") or [""])[0].lower()
    if fmt in {"jpg", "jpeg", "png", "webp", "gif", "mp4", "webm", "mov"}:
        return "." + ("jpg" if fmt == "jpeg" else fmt)
    return suffix


def _usable_items(urls: list[str]) -> tuple[list[MediaItem] | None, str]:
    """直链必须是可直接下载的媒体；m3u8 等交给本地下载回退。"""
    items: list[MediaItem] = []
    for url in urls:
        ext = _media_ext(url)
        if ext not in MEDIA_EXTS:
            continue
        items.append(MediaItem(
            url=url,
            type="video" if ext in VIDEO_EXTS else "image",
            index=len(items) + 1,
        ))
    if not items:
        return None, "没有可直接下载的媒体直链"
    return items, ""


def _content_from_meta(meta: dict, url: str, platform: str) -> Content:
    content = metadata.content_from_gallery(meta, url, platform)
    if not content.id:
        match = re.search(r"/status/(\d+)", url)
        if match:
            content.id = match.group(1)
    if not content.author:
        match = re.search(r"(?:x|twitter)\.com/([^/]+)/status", url)
        if match and match.group(1) not in {"i", "home"}:
            content.author = match.group(1)
    return content


def _read_meta_files(tmpdir: Path) -> dict:
    """本地回退时读 gallery-dl 写出的元数据，兼容 dict / list。"""
    for meta_file in sorted(tmpdir.rglob("*.json")):
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8", errors="ignore"))
        except (json.JSONDecodeError, OSError):
            continue
        found = _find_meta(data)
        if found:
            return found
    return {}


def _find_meta(obj) -> dict | None:
    if isinstance(obj, dict):
        if "tweet_id" in obj or ("id" in obj and ("username" in obj or "user_id" in obj)):
            return obj
        for value in obj.values():
            found = _find_meta(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_meta(value)
            if found:
                return found
    return None


def _local_download(url: str, platform: str, cfg, *, progress: str,
                    index: int, count: int, log) -> Extraction:
    """回退：让 gallery-dl 自己下到临时目录，输出全部隐藏。"""
    exe = which("gallery-dl")
    tmpdir = Path(tempfile.mkdtemp(prefix="mediadl_twitter_"))
    if not exe:
        content = Content(platform=platform, id="", status=Status.FAIL_TOOL,
                          message="未找到 gallery-dl，请先 pip install gallery-dl")
        return Extraction(content=content, mode="local", tmpdir=tmpdir)

    cmd = [exe, "-d", str(tmpdir), "--write-metadata", "--no-mtime", *_common_args(cfg), url]
    bar = ProgressBar(0, index=index, count=count, name="twitter",
                      enabled=progress != "none")

    def on_line(line: str) -> None:
        percent = parse_percent(line)
        if percent is not None:
            bar.set(int(percent), 100)

    try:
        code, lines = run_hidden(cmd, timeout=600, on_line=on_line)
    except Exception as exc:  # noqa: BLE001
        bar.close()
        content = Content(platform=platform, id="", status=Status.FAIL_TOOL, message=str(exc))
        return Extraction(content=content, mode="local", tmpdir=tmpdir)
    bar.finish()
    bar.close()

    files = sorted(
        path for path in tmpdir.rglob("*")
        if path.is_file() and path.suffix.lower() not in SKIP_SUFFIXES
    )
    meta = _read_meta_files(tmpdir)
    content = _content_from_meta(meta, url, platform)

    if not files:
        if code != 0:
            content.status = Status.FAIL_TOOL
            content.message = "gallery-dl 失败"
        else:
            content.status = Status.SKIP_NO_MEDIA
        return Extraction(content=content, mode="local", tmpdir=tmpdir)

    return Extraction(content=content, mode="local", files=files, tmpdir=tmpdir)


def extract(
    url: str,
    platform: str,
    cfg,
    *,
    log=print,
    progress: str = "bar",
    index: int = 1,
    count: int = 1,
) -> Extraction:
    meta, meta_error = metadata.gallery_meta(url, cfg)
    urls, url_error = _gallery_urls(url, cfg)
    items, reason = _usable_items(urls) if urls else (None, url_error)

    if items:
        content = _content_from_meta(meta, url, platform)
        content.url = url
        content.items = items
        thumb = meta.get("thumbnail")
        if content.cover_url is None and isinstance(thumb, str):
            content.cover_url = thumb
        if not content.id:
            content.status = Status.FAIL_PARSE
            content.message = meta_error or "没解析到推文 id"
            return Extraction(content=content, mode="remote")
        return Extraction(content=content, mode="remote")

    if not items:
        log("  · 直链不可用，改用 gallery-dl 本地下载（输出已隐藏）")
        return _local_download(url, platform, cfg, progress=progress,
                               index=index, count=count, log=log)


def fallback_allowed(reason: str) -> bool:
    """保留给外部判断：目前任何拿不到直链的情况都尝试本地回退。"""
    return True
