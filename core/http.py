"""统一的 HTTP 会话：UA、代理、Referer、重试。"""

from __future__ import annotations

import time
from pathlib import Path

import requests

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
)


def load_netscape_cookies(path: Path | None) -> dict[str, str]:
    """把 Netscape cookies.txt 读成 {name: value}，按行容错解析。"""
    if not path or not path.exists():
        return {}
    jars: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        name, value = parts[5], parts[6]
        if name:
            jars[name] = value
    return jars


def make_session(
    proxy: str = "",
    cookies: dict[str, str] | None = None,
    ua: str = DESKTOP_UA,
    referer: str = "",
) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": ua, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    if referer:
        session.headers["Referer"] = referer
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    for name, value in (cookies or {}).items():
        session.cookies.set(name, value)
    return session


def get_with_retry(
    session: requests.Session,
    url: str,
    *,
    retry: int = 2,
    backoff: float = 1.5,
    **kwargs,
):
    """GET 带指数退避重试。4xx 不重试（权限问题重试无用）。"""
    last_exc: Exception | None = None
    for attempt in range(retry + 1):
        try:
            resp = session.get(url, timeout=kwargs.pop("timeout", 30), **kwargs)
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                return resp
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < retry:
                time.sleep(backoff ** attempt)
    raise last_exc  # type: ignore[misc]
