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
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
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
        stderr = (proc.stderr or "").lower()
        if any(k in stderr for k in ("unauthorized", "protected", "login", "403")):
            content.status = Status.SKIP_PRIVATE
        elif any(k in stderr for k in ("404", "not found", "deleted")):
            content.status = Status.SKIP_DELETED
        else:
            content.status = Status.FAIL_TOOL
        lines = [ln for ln in (proc.stderr or "").strip().splitlines() if ln.strip()]
        content.message = lines[-1] if lines else "gallery-dl 失败"
        return Extraction(content=content, mode="local", tmpdir=tmpdir)

    return Extraction(content=content, mode="local", files=files, tmpdir=tmpdir)
