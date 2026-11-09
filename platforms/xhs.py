"""小红书：解析笔记页 __INITIAL_STATE__。

必须带 a1 / web_session cookie，否则会被 461 风控拦下。
图片直链基本可直连下载；视频优先取 masterUrl，回退到 originVideoKey 拼 CDN。
"""

from __future__ import annotations

import json
import re

from core import detect
from core.http import DESKTOP_UA, load_netscape_cookies, make_session
from core.result import Status
from .base import Content, Extraction, MediaItem

CDN_VIDEO = "https://sns-video-bd.xhscdn.com/"


def _extract_json_after(html: str, marker: str) -> dict | None:
    """从 marker 之后用括号配对抠 JSON。

    页面里的 JSON 很大且嵌套深，`\\{.*?\\}` 这种正则会被第一个 `}` 带偏。
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


def _parse_state(html: str) -> dict | None:
    # 页面里的 JSON 是 JS 对象序列化，混着 undefined / new Map() 这类语法
    fixed = html.replace("undefined", "null")
    fixed = re.sub(r"new\s+Map\([^)]*\)", "{}", fixed)
    fixed = re.sub(r"new\s+Set\([^)]*\)", "[]", fixed)
    idx = fixed.find("__INITIAL_STATE__")
    if idx < 0:
        return None
    start = fixed.find("{", idx)
    if start < 0:
        return None
    try:
        # raw_decode 会自己处理嵌套与字符串转义，比手写配平更稳
        data, _ = json.JSONDecoder().raw_decode(fixed, start)
        return data
    except json.JSONDecodeError:
        return None


def _pick_note(state: dict) -> tuple[str, dict] | None:
    note_map = ((state.get("note") or {}).get("noteDetailMap") or {})
    for note_id, wrapper in note_map.items():
        note = (wrapper or {}).get("note")
        if note:
            return str(note_id), note
    return None


def _image_urls(note: dict) -> list[str]:
    urls: list[str] = []
    for image in note.get("imageList") or []:
        if image.get("urlDefault"):
            urls.append(image["urlDefault"])
            continue
        infos = image.get("infoList") or []
        if infos and infos[0].get("url"):
            urls.append(infos[0]["url"])
    return urls


def _video_url(note: dict) -> str | None:
    video = note.get("video") or {}
    streams = ((video.get("media") or {}).get("stream") or {})
    for codec in ("h264", "h265", "av1"):
        entries = streams.get(codec) or []
        if entries and entries[0].get("masterUrl"):
            return entries[0]["masterUrl"]
    key = (video.get("consumer") or {}).get("originVideoKey")
    if key:
        return CDN_VIDEO + key
    return None


def extract(url: str, cfg, *, log=print) -> Extraction:
    cookies = load_netscape_cookies(cfg.cookie_file("xhs"))
    if not cookies:
        log("  ! 未找到小红书 cookie，未登录请求大概率被 461 拦截")
    session = make_session(
        cfg.proxy, cookies=cookies, ua=DESKTOP_UA, referer="https://www.xiaohongshu.com/"
    )
    final = detect.resolve(url, session=session)

    try:
        resp = session.get(final, timeout=30)
    except Exception as exc:  # noqa: BLE001
        return Extraction(Content(platform="xhs", id="", status=Status.FAIL_NETWORK, message=str(exc)))

    if resp.status_code == 461:
        return Extraction(Content(platform="xhs", id="", status=Status.FAIL_NETWORK,
                                  message="触发风控 461，请更新 cookie 或降低请求频率"))
    if resp.status_code in (401, 403):
        return Extraction(Content(platform="xhs", id="", status=Status.SKIP_PRIVATE,
                                  message=f"HTTP {resp.status_code}"))
    if resp.status_code == 404:
        return Extraction(Content(platform="xhs", id="", status=Status.SKIP_DELETED,
                                  message="HTTP 404"))

    state = _parse_state(resp.text)
    picked = _pick_note(state) if state else None
    if not picked:
        return Extraction(Content(platform="xhs", id="", status=Status.SKIP_PRIVATE,
                                  message="未取到笔记数据（可能私密、已删除或需登录）"))

    note_id, note = picked
    items: list[MediaItem] = []
    video_url = _video_url(note)
    if video_url:
        items.append(MediaItem(url=video_url, type="video", index=1))
    else:
        for idx, image_url in enumerate(_image_urls(note), 1):
            items.append(MediaItem(url=image_url, type="image", index=idx))

    if not items:
        return Extraction(Content(platform="xhs", id=note_id, status=Status.SKIP_NO_MEDIA,
                                  message="笔记没有可下载的图片或视频"))

    user = note.get("user") or {}
    cover = None
    if items and items[0].type == "video":
        images = note.get("imageList") or []
        if images:
            cover = images[0].get("urlDefault")

    content = Content(
        platform="xhs",
        id=note_id,
        author=str(user.get("nickname") or ""),
        author_id=str(user.get("userId") or ""),
        title=str(note.get("title") or note.get("desc") or ""),
        timestamp=float(note["time"]) / 1000 if note.get("time") else None,
        items=items,
        cover_url=cover,
    )
    return Extraction(content=content)
