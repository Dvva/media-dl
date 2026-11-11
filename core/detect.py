"""URL → 平台判定。

短链（t.co / v.douyin.com / xhslink.com / vm.tiktok.com / b23.tv）
需要先跟随 302 才能拿到真实域名。
"""

from __future__ import annotations

from urllib.parse import urlparse

from core import urls as url_tools

PLATFORM_DOMAINS = {
    "twitter": ("x.com", "twitter.com", "t.co", "mobile.twitter.com"),
    "tiktok": ("tiktok.com", "vm.tiktok.com", "vt.tiktok.com", "m.tiktok.com"),
    "xhs": ("xiaohongshu.com", "xhslink.com", "xhslink.cn", "www.xiaohongshu.com"),
    "douyin": ("douyin.com", "iesdouyin.com", "v.douyin.com", "m.douyin.com"),
    "bilibili": ("bilibili.com", "b23.tv", "m.bilibili.com", "bilibili.tv"),
    "telegram": ("t.me", "telegram.me", "telegram.dog"),
    "youtube": ("youtube.com", "youtu.be", "m.youtube.com", "music.youtube.com"),
}

SHORT_LINK_HOSTS = {
    "t.co",
    "v.douyin.com",
    "xhslink.com",
    "xhslink.cn",
    "vm.tiktok.com",
    "vt.tiktok.com",
    "b23.tv",
}


def extract_url(text: str) -> str | None:
    """从分享文案里抠出第一个 URL（旧接口，保留兼容）。"""
    return url_tools.first_url(text)


def extract_urls(*texts: object) -> list[str]:
    """从多个参数 / 拼接文案里抠出全部 URL。"""
    return url_tools.iter_urls(texts)


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def platform_of(url: str) -> str | None:
    host = _host(url)
    if not host:
        return None
    for platform, domains in PLATFORM_DOMAINS.items():
        for domain in domains:
            if host == domain or host.endswith("." + domain):
                return platform
    return None


def is_short_link(url: str) -> bool:
    return _host(url) in SHORT_LINK_HOSTS


def resolve(url: str, session=None, timeout: int = 20) -> str:
    """短链跟随重定向；非短链原样返回。"""
    if not is_short_link(url):
        return url
    if session is None:
        import requests

        session = requests.Session()
    try:
        resp = session.get(url, allow_redirects=True, timeout=timeout, stream=True)
        final = resp.url or url
        resp.close()
        return final
    except Exception:
        return url


def detect(url: str, session=None) -> tuple[str | None, str]:
    """返回 (平台, 最终URL)。短链会自动展开。"""
    final = resolve(url, session=session)
    return platform_of(final), final
