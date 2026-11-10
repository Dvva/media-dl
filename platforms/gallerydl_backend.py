"""基于 gallery-dl 的后端：twitter / x。

一条推文里的多图、视频、GIF 会全部下载，元数据用 --write-metadata 产出。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from core.result import Status
from .base import Content, Extraction

SKIP_SUFFIXES = {".json", ".txt"}


def _gallerydl() -> str | None:
    return shutil.which("gallery-dl")


def extract(url: str, platform: str, cfg, *, log=print) -> Extraction:
    exe = _gallerydl()
    if not exe:
        content = Content(platform=platform, id="", status=Status.FAIL_TOOL,
                          message="未找到 gallery-dl，请先 pip install gallery-dl")
        return Extraction(content=content, mode="local")

    tmpdir = Path(tempfile.mkdtemp(prefix="mediadl_twitter_"))
    # 注意：gallery-dl 没有 --no-progress，加上会直接报 unrecognized arguments
    cmd = [exe, "-d", str(tmpdir), "--write-metadata", "--no-mtime"]
    cookie = cfg.cookie_file("twitter")
    if cookie:
        cmd += ["--cookies", str(cookie)]
    if cfg.proxy:
        cmd += ["--proxy", cfg.proxy]
    cmd.append(url)

    log("  $ gallery-dl --write-metadata")
    try:
        # gallery-dl 的进度写在 stderr，这里让它直接继承终端，
        # 否则进度会被 capture_output 一并吞掉，看起来像卡死。
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=None,
                              text=True, timeout=600)
    except (subprocess.SubprocessError, OSError) as exc:
        content = Content(platform=platform, id="", status=Status.FAIL_TOOL, message=str(exc))
        return Extraction(content=content, mode="local", tmpdir=tmpdir)

    files = sorted(
        p for p in tmpdir.rglob("*")
        if p.is_file() and p.suffix.lower() not in SKIP_SUFFIXES
    )

    meta: dict = {}
    for mf in sorted(tmpdir.rglob("*.json")):
        try:
            meta = json.loads(mf.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(meta, dict):
                break
        except (json.JSONDecodeError, OSError):
            continue

    content = Content(
        platform="twitter",
        id=str(meta.get("tweet_id") or meta.get("id") or ""),
        author=str(meta.get("username") or meta.get("author") or ""),
        author_id=str(meta.get("user_id") or ""),
        title=str(meta.get("content") or meta.get("title") or ""),
        timestamp=meta.get("date") if isinstance(meta.get("date"), (int, float)) else None,
        cover_url=meta.get("thumbnail") or None,
    )

    if not files:
        # stderr 已经继承到终端，这里只能按退出码判断，具体原因看上方输出
        if proc.returncode != 0:
            content.status = Status.FAIL_TOOL
            content.message = f"gallery-dl 退出码 {proc.returncode}，原因见上方输出"
        else:
            content.status = Status.SKIP_NO_MEDIA
        return Extraction(content=content, mode="local", tmpdir=tmpdir)

    return Extraction(content=content, mode="local", files=files, tmpdir=tmpdir)
