"""下载执行：拉流 → 命名 → 落盘 → 封面。"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse

import requests

from platforms.base import Content
from . import naming
from .cover import write_cover
from .result import Status


EXT_BY_TYPE = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def guess_ext(item, resp: requests.Response | None, url: str) -> str:
    if item.ext:
        return item.ext if item.ext.startswith(".") else "." + item.ext
    if resp is not None:
        ctype = resp.headers.get("Content-Type", "").split(";")[0].strip()
        if ctype in EXT_BY_TYPE:
            return EXT_BY_TYPE[ctype]
    path = urlparse(url).path
    suffix = os.path.splitext(path)[1].lower()
    if suffix in {".mp4", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".mov", ".webm", ".m4a"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".bin"


def _download_one(session, item, dest_dir: Path, basename: str, timeout: int) -> Path:
    headers = {"Referer": "https://www.douyin.com/"} if "douyin" in item.url else {}
    headers.update(item.headers or {})
    resp = session.get(item.url, headers=headers, timeout=timeout, stream=True)
    resp.raise_for_status()
    ext = guess_ext(item, resp, item.url)
    # 模板里若已经带了扩展名，就不要重复拼
    filename = basename if basename.lower().endswith(ext.lower()) else f"{basename}{ext}"
    path = dest_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                fh.write(chunk)
    resp.close()
    return path


def save(
    content: Content,
    *,
    session: requests.Session,
    cfg,
    output_dir: Path | None = None,
    cover_mode: str | None = None,
    max_height: int | None = None,  # 预留：直链流不做转码
    log=print,
) -> tuple[Status, list[Path]]:
    """按模板保存整个 Content，返回 (状态, 落盘文件列表)。"""
    if content.status is not Status.OK:
        return content.status, []
    if not content.items:
        return Status.SKIP_NO_MEDIA, []

    root = output_dir or cfg.output_dir
    template = cfg.naming_for(content.platform)
    mode = (cover_mode or cfg.cover_mode) if cfg.cover_enabled else "none"
    timeout = int(cfg.get("general.download_timeout", 60))

    written: list[Path] = []
    try:
        for item in content.items:
            variables = content.variables(ext="")
            basename = naming.render(
                template,
                variables,
                is_multi=content.is_multi,
                omit_index_when_single=cfg.omit_index_when_single,
                max_len=int(cfg.get("naming.max_len", 120)),
            )
            if content.is_multi:
                basename = f"{basename}_{item.index:02d}"

            directory_part, _ = naming.split_template(template)
            dest_dir = root
            if directory_part:
                dir_vars = dict(variables)
                sub = naming.render(
                    directory_part,
                    dir_vars,
                    is_multi=content.is_multi,
                    omit_index_when_single=cfg.omit_index_when_single,
                    max_len=int(cfg.get("naming.max_len", 120)),
                )
                dest_dir = root / sub

            path = _download_one(session, item, dest_dir, basename, timeout)
            written.append(path)
            log(f"  · {path}")

            if mode != "none" and content.cover_url and item.index == 1:
                try:
                    cover_resp = session.get(
                        content.cover_url, headers=content.cover_headers, timeout=timeout
                    )
                    cover_resp.raise_for_status()
                    cover_path = write_cover(path, cover_resp.content, mode)
                    if cover_path:
                        log(f"  · 封面 {cover_path}")
                except requests.RequestException:
                    log("  ! 封面下载失败，跳过")
    except requests.RequestException as exc:
        log(f"  ! 下载失败: {exc}")
        return Status.FAIL_NETWORK, written
    except OSError as exc:
        log(f"  ! 写文件失败: {exc}")
        return Status.FAIL_PARSE, written

    return Status.OK, written
