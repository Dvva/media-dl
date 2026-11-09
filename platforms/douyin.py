"""抖音：解析分享页 SSR 数据，单条无需签名。

分享页（www.iesdouyin.com/share/video/<id>/）会把数据塞进
window._ROUTER_DATA（新版）或 RENDER_DATA（旧版），
里面同时包含无水印 play_addr 和图文笔记的 images。
"""

from __future__ import annotations

import json
import re
from urllib.parse import unquote

from core import detect
from core.http import MOBILE_UA, make_session
from core.result import Status
from .base import Content, Extraction, MediaItem

ROUTER_RE = re.compile(r"_ROUTER_DATA\s*=\s*(\{.*?\})\s*;?\s*</script>", re.S)
RENDER_RE = re.compile(r'id="RENDER_DATA"[^>]*>(.*?)</script>', re.S)


def _walk_item(node):
    """递归找出第一个带 aweme_id 的 item。"""
    if isinstance(node, dict):
        if node.get("aweme_id"):
            return node
        for value in node.values():
            found = _walk_item(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _walk_item(value)
            if found:
                return found
    return None


def _parse_page(html: str) -> dict | None:
    match = ROUTER_RE.search(html)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = RENDER_RE.search(html)
    if match:
        try:
            return json.loads(unquote(match.group(1)))
        except json.JSONDecodeError:
            pass
    return None


def _nowatermark(url: str) -> str:
    return url.replace("playwm", "play")


def extract(url: str, cfg, *, log=print) -> Extraction:
    session = make_session(cfg.proxy, ua=MOBILE_UA, referer="https://www.douyin.com/")
    final = detect.resolve(url, session=session)
    try:
        resp = session.get(final, timeout=30)
    except Exception as exc:  # noqa: BLE001 - 网络异常统一转状态
        return Extraction(Content(platform="douyin", id="", status=Status.FAIL_NETWORK,
                                  message=str(exc)))

    if resp.status_code in (401, 403):
        return Extraction(Content(platform="douyin", id="", status=Status.SKIP_PRIVATE,
                                  message=f"HTTP {resp.status_code}"))
    if resp.status_code == 404:
        return Extraction(Content(platform="douyin", id="", status=Status.SKIP_DELETED,
                                  message="HTTP 404"))

    data = _parse_page(resp.text)
    item = _walk_item(data) if data else None
    if not item:
        return Extraction(Content(platform="douyin", id="", status=Status.SKIP_PRIVATE,
                                  message="未取到作品数据（可能已删除或需登录）"))

    aweme_id = str(item.get("aweme_id") or "")
    video = item.get("video") or {}
    images = item.get("images") or []
    items: list[MediaItem] = []

    if images:
        for idx, image in enumerate(images, 1):
            candidates = (image.get("url_list") or image.get("download_url_list") or [])
            if candidates:
                items.append(MediaItem(url=candidates[0], type="image", index=idx))
    else:
        play = (video.get("play_addr") or {}).get("url_list") or []
        if not play:
            play = (video.get("download_addr") or {}).get("url_list") or []
        if play:
            items.append(MediaItem(url=_nowatermark(play[0]), type="video", index=1))

    if not items:
        # 有作品数据却没有媒体，通常是作者关闭了下载或内容受限
        return Extraction(Content(platform="douyin", id=aweme_id,
                                  status=Status.SKIP_AUTHOR_DISABLED,
                                  message="作品存在但无可下载媒体地址"))

    cover = None
    for key in ("cover", "origin_cover", "dynamic_cover"):
        urls = (video.get(key) or {}).get("url_list") or []
        if urls:
            cover = urls[0]
            break

    author = item.get("author") or {}
    content = Content(
        platform="douyin",
        id=aweme_id,
        author=str(author.get("nickname") or ""),
        author_id=str(author.get("sec_uid") or author.get("uid") or ""),
        title=str(item.get("desc") or ""),
        timestamp=float(item["create_time"]) if item.get("create_time") else None,
        items=items,
        cover_url=cover,
    )
    return Extraction(content=content)
