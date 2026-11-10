"""基于 yt-dlp 的后端：tiktok / bilibili / telegram。

这三个平台都由 yt-dlp 直接支持，脚本只负责：
传入画质上限、cookies、代理，产出元数据，下到临时目录。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from core.result import Status
from .base import Content, Extraction

SKIP_SUFFIXES = {".info.json", ".json", ".description", ".vtt", ".srt", ".part", ".ytdl"}


def _ytdlp() -> str | None:
    return shutil.which("yt-dlp")


def _run_stream(cmd, *, timeout: int = 600) -> tuple[int, str]:
    """运行外部命令，把进度行原地刷新到终端，同时收集全部输出。

    之前用 subprocess.run(capture_output=True) 会把 yt-dlp 的 stderr 进度
    一起吞掉，所以终端里看不到任何下载进度。
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, errors="ignore",
    )
    collected: list[str] = []
    tty = sys.stderr.isatty()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            collected.append(line)
            text = line.rstrip("\n")
            if not text.strip():
                continue
            if tty and ("下载中" in text or text.startswith("[download]")):
                sys.stderr.write("\r\033[K" + text)
                sys.stderr.flush()
            else:
                sys.stderr.write(text + "\n")
                sys.stderr.flush()
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise
    finally:
        if tty:
            sys.stderr.write("\n")
            sys.stderr.flush()
    return proc.returncode, "".join(collected)


def _parse_ts(info: dict) -> float | None:
    if info.get("timestamp"):
        return float(info["timestamp"])
    upload_date = str(info.get("upload_date") or "")
    if len(upload_date) == 8:
        from datetime import datetime, timezone, timedelta

        try:
            dt = datetime.strptime(upload_date, "%Y%m%d").replace(
                tzinfo=timezone(timedelta(hours=8))
            )
            return dt.timestamp()
        except ValueError:
            return None
    return None


def _read_info_files(tmpdir: Path) -> dict:
    """读 yt-dlp 写出的 .info.json，取第一个有效条目。"""
    for info_file in sorted(tmpdir.glob("*.info.json")):
        try:
            data = json.loads(info_file.read_text(encoding="utf-8", errors="ignore"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def extract(
    url: str,
    platform: str,
    cfg,
    *,
    max_height: int | None = None,
    log=print,
) -> Extraction:
    exe = _ytdlp()
    if not exe:
        content = Content(platform=platform, id="", status=Status.FAIL_TOOL,
                          message="未找到 yt-dlp，请先 pip install yt-dlp")
        return Extraction(content=content, mode="local")

    height = max_height or cfg.max_height
    if platform == "telegram":
        fmt = f"b[height<={height}]/b"
    elif platform in {"youtube", "bilibili"}:
        # 优先 mp4：封面只有 mp4 能嵌进视频，webm 只能落成同名 jpg
        fmt = (
            f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
            f"b[height<={height}][ext=mp4]/"
            f"bv*[height<={height}]+ba/b[height<={height}]/bv*+ba/b"
        )
    else:
        fmt = f"bv*[height<={height}]+ba/b[height<={height}]/bv*+ba/b"

    tmpdir = Path(tempfile.mkdtemp(prefix=f"mediadl_{platform}_"))
    cmd = [
        exe,
        "-P", str(tmpdir),
        "-o", "%(id)s.%(ext)s",
        "-f", fmt,
        "--no-playlist",
        "--newline",
        "--progress",
        "--progress-template",
        "下载中 %(progress._percent_str)s  "
        "%(progress._downloaded_bytes_str)s/%(progress._total_bytes_str)s  "
        "%(progress._speed_str)s  "
        "%(info.title).60s",
        "--no-warnings",
        "--write-info-json",
        "--no-simulate",
        "--socket-timeout", "45",
        "--retries", "3",
        "--fragment-retries", "3",
    ]
    cookie = cfg.cookie_file(platform)
    if cookie:
        cmd += ["--cookies", str(cookie)]
    if platform == "bilibili":
        # B站没带 Referer/UA 时容易直接 412
        cmd += [
            "--add-header", "Referer:https://www.bilibili.com/",
            "--user-agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        ]
    if platform == "youtube":
        # 2025 起 YouTube 的解签/n-challenge 必须靠 JS 运行时 + EJS 组件，
        # 否则只能拿到 storyboard，报 "only images are available"
        cmd += [
            "--js-runtimes", "node",
            "--remote-components", "ejs:github",
        ]
    if cfg.proxy:
        cmd += ["--proxy", cfg.proxy]
    cmd.append(url)

    log(f"  $ yt-dlp -f {fmt}")
    try:
        returncode, output = _run_stream(cmd, timeout=600)
    except (subprocess.SubprocessError, OSError) as exc:
        content = Content(platform=platform, id="", status=Status.FAIL_TOOL, message=str(exc))
        return Extraction(content=content, mode="local", tmpdir=tmpdir)

    files = sorted(
        p for p in tmpdir.iterdir()
        if p.is_file() and p.suffix.lower() not in SKIP_SUFFIXES and not p.name.endswith(".info.json")
    )

    info = _read_info_files(tmpdir)
    content = Content(
        platform=platform,
        id=str(info.get("id") or ""),
        author=str(info.get("uploader") or info.get("channel") or ""),
        author_id=str(info.get("uploader_id") or ""),
        title=str(info.get("title") or ""),
        timestamp=_parse_ts(info),
        cover_url=info.get("thumbnail") or None,
    )

    if not files:
        stderr = output.lower()
        if returncode != 0:
            if any(k in stderr for k in ("private", "login", "sign in", "members-only", "premium")):
                content.status = Status.SKIP_PAYWALLED
            elif any(k in stderr for k in ("unavailable", "removed", "404", "deleted")):
                content.status = Status.SKIP_DELETED
            else:
                content.status = Status.FAIL_TOOL
            lines = [ln for ln in output.strip().splitlines() if ln.strip()]
            content.message = lines[-1] if lines else "yt-dlp 失败"
        else:
            content.status = Status.SKIP_NO_MEDIA
        return Extraction(content=content, mode="local", tmpdir=tmpdir)

    return Extraction(content=content, mode="local", files=files, tmpdir=tmpdir)
