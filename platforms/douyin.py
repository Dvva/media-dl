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
from core.http import MOBILE_UA, load_netscape_cookies, make_session
from core.result import Status
from .base import Content, Extraction, MediaItem

RENDER_RE = re.compile(r'id="RENDER_DATA"[^>]*>(.*?)</script>', re.S)

# 分享页对请求头敏感，缺这几个会被降级成空壳页
DOUYIN_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "sec-ch-ua": '"Chromium";v="126", "Google Chrome";v="126"',
    "sec-ch-ua-mobile": "?1",
    "sec-ch-ua-platform": '"Android"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}


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


def _extract_json_after(html: str, marker: str) -> dict | None:
    """从 marker 之后用括号配对抠出 JSON。

    不能用正则：页面里的 JSON 很大且嵌套深，`\\{.*?\\}` 会匹配错位。
    """
    idx = html.find(marker)
    if idx < 0:
        return None
    start = html.find("{", idx)
    if start < 0:
        return None
    depth = 0
    in_str = False
    escaped = False
    for pos in range(start, len(html)):
        ch = html[pos]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:pos + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _parse_page(html: str) -> dict | None:
    data = _extract_json_after(html, "window._ROUTER_DATA")
    if data:
        return data
    match = RENDER_RE.search(html)
    if match:
        try:
            return json.loads(unquote(match.group(1)))
        except json.JSONDecodeError:
            pass
    return None


def _nowatermark(url: str) -> str:
    return url.replace("playwm", "play")


def _aweme_id_of(url: str) -> str | None:
    match = re.search(r"/(?:share/)?(?:video|note|slides)/(\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"[?&](?:modal_id|aweme_id)=(\d+)", url)
    return match.group(1) if match else None


def _candidate_pages(url: str) -> list[str]:
    """难点：PC 端 www.douyin.com 是前端渲染，HTML 里没有数据。

    只有旧分享页 iesdouyin.com/share/... 才内嵌 _ROUTER_DATA，
    所以优先把链接改写成分享页。
    """
    aweme_id = _aweme_id_of(url)
    pages: list[str] = []
    if aweme_id:
        kind = "note" if "/note/" in url or "/slides/" in url else "video"
        pages.append(f"https://www.iesdouyin.com/share/{kind}/{aweme_id}/")
    pages.append(url)
    return pages


def _fetch_api(aweme_id: str, session, *, log=print):
    """SSR 拿不到时退回 web 详情接口（需要有效 cookie 才不会被 Argus 拦）。"""
    url = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
    params = {
        "aweme_id": aweme_id,
        "aid": "6383",
        "device_platform": "webapp",
        "version_code": "170400",
        "publish_video_strategy_type": "2",
    }
    try:
        resp = session.get(url, params=params, headers=DOUYIN_HEADERS, timeout=30)
    except Exception as exc:  # noqa: BLE001
        log(f"  · detail 接口异常: {exc}")
        return None
    if resp.status_code != 200:
        log(f"  · detail 接口 HTTP {resp.status_code}")
        return None
    try:
        data = resp.json()
    except ValueError:
        log("  · detail 接口返回非 JSON")
        return None
    detail = data.get("aweme_detail")
    if not detail:
        log(f"  · detail 接口无 aweme_detail（status_code={data.get('status_code')}）")
        return None
    return detail


def extract(url: str, cfg, *, log=print) -> Extraction:
    cookies = load_netscape_cookies(cfg.cookie_file("douyin"))
    session = make_session(cfg.proxy, cookies=cookies, ua=MOBILE_UA,
                           referer="https://www.douyin.com/")
    final = detect.resolve(url, session=session)

    data = None
    resp = None
    for page in _candidate_pages(final):
        try:
            resp = session.get(page, headers=DOUYIN_HEADERS, timeout=30)
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
        if data and _walk_item(data):
            break
        log(f"  · {page} 没有内嵌数据，换下一个")
        data = None

    item = _walk_item(data) if data else None
    if not item:
        aweme_id = _aweme_id_of(final)
        if aweme_id:
            log("  · SSR 没数据，改走 detail 接口")
            item = _fetch_api(aweme_id, session, log=log)
    if not item:
        return Extraction(Content(platform="douyin", id=_aweme_id_of(final) or "",
                                  status=Status.SKIP_PRIVATE,
                                  message="未取到作品数据（可能已删除、私密或需登录）"))

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
        url=final,
        author=str(author.get("nickname") or ""),
        nickname=str(author.get("nickname") or ""),
        author_id=str(author.get("sec_uid") or author.get("uid") or ""),
        title=str(item.get("desc") or ""),
        timestamp=float(item["create_time"]) if item.get("create_time") else None,
        items=items,
        cover_url=cover,
    )
    return Extraction(content=content)
