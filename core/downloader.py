"""下载执行：拉流 → 命名 → 落盘 → 封面 → 改时间。"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import requests

from platforms.base import Content
from . import fsops, naming
from .cover import write_cover
from .progress import ProgressBar
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


def _download_one(
    session,
    item,
    dest_dir: Path,
    basename: str,
    timeout: int,
    *,
    index: int = 1,
    count: int = 1,
    progress: str = "bar",
    overwrite: bool = False,
    backup_root: Path | None = None,
    timestamp: float | None = None,
    referer: str = "",
    log=print,
) -> Path | None:
    headers = {"Referer": referer} if referer else {}
    headers.update(item.headers or {})
    resp = session.get(item.url, headers=headers, timeout=timeout, stream=True)
    resp.raise_for_status()
    ext = guess_ext(item, resp, item.url)
    # 模板里若已经带了扩展名，就不要重复拼
    filename = basename if basename.lower().endswith(ext.lower()) else f"{basename}{ext}"
    path = dest_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and not overwrite:
        log(f"  · 已存在，跳过：{path.name}")
        resp.close()
        return None
    if path.exists() and overwrite and backup_root is not None:
        backup = fsops.backup_file(path, backup_root)
        if backup:
            log(f"  · 旧文件已备份：{backup}")

    tmp = fsops.part_path(path)
    total = int(resp.headers.get("Content-Length") or 0)
    bar = None
    if progress != "none":
        bar = ProgressBar(total, index=index, count=count, name=filename,
                          enabled=None if progress != "off" else False)
    try:
        with tmp.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                fh.write(chunk)
                if bar:
                    bar.update(len(chunk))
        tmp.replace(path)
    finally:
        if bar:
            bar.finish()
            bar.close()
        resp.close()
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass

    if timestamp:
        fsops.apply_mtime(path, timestamp)
    return path


def save(
    content: Content,
    *,
    session: requests.Session,
    cfg,
    output_dir: Path | None = None,
    cover_mode: str | None = None,
    max_height: int | None = None,  # 预留：直链流不做转码
    progress: str = "bar",
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
    overwrite = bool(cfg.overwrite)
    backup_root = cfg.backup_dir

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

            path = _download_one(
                session, item, dest_dir, basename, timeout,
                index=item.index, count=len(content.items),
                progress=progress,
                overwrite=overwrite,
                backup_root=backup_root,
                timestamp=content.timestamp if cfg.set_mtime else None,
                referer="https://www.douyin.com/" if content.platform == "douyin" else "",
                log=log,
            )
            if path is None:
                continue
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
                        if cfg.set_mtime:
                            fsops.apply_mtime(cover_path, content.timestamp)
                        log(f"  · 封面 {cover_path}")
                except requests.RequestException:
                    log("  ! 封面下载失败，跳过")

            # 封面嵌入会重建 mp4，文件时间会被重置，所以放在封面处理之后
            if cfg.set_mtime and path is not None:
                fsops.apply_mtime(path, content.timestamp)
                cover_sidecar = path.with_suffix(".jpg")
                if cover_sidecar.exists():
                    fsops.apply_mtime(cover_sidecar, content.timestamp)
    except requests.RequestException as exc:
        log(f"  ! 下载失败: {exc}")
        return Status.FAIL_NETWORK, written
    except OSError as exc:
        log(f"  ! 写文件失败: {exc}")
        return Status.FAIL_PARSE, written

    return Status.OK, written
