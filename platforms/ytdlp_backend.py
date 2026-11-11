"""基于 yt-dlp 的后端：tiktok / bilibili / telegram / youtube。

yt-dlp 的原始输出全部隐藏，只把它自己的进度行转成本项目的进度条。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from core import metadata
from core.progress import ProgressBar
from core.result import Status
from core.toolrun import parse_percent, run_hidden, which
from .base import Content, Extraction

SKIP_SUFFIXES = {
    ".info.json", ".json", ".description", ".vtt", ".srt", ".part", ".ytdl", ".temp",
}
PROGRESS_PREFIX = "##MEDIADL_PROGRESS##"


def _run_with_progress(cmd: list[str], bar: ProgressBar | None, timeout: int = 900
                       ) -> tuple[int, list[str]]:
    def on_line(line: str) -> None:
        if bar is None or not line.startswith(PROGRESS_PREFIX):
            return
        payload = line[len(PROGRESS_PREFIX):]
        parts = payload.split("|", 4)
        if len(parts) < 5:
            return
        percent_text, downloaded_text, total_text, estimate_text, title = parts
        percent = parse_percent(percent_text)
        try:
            downloaded = int(float(downloaded_text))
        except (TypeError, ValueError):
            downloaded = 0
        total = 0
        for candidate in (total_text, estimate_text):
            try:
                total = int(float(candidate))
                if total > 0:
                    break
            except (TypeError, ValueError):
                continue
        if total <= 0 and percent and downloaded:
            total = int(downloaded / (percent / 100))
        if title and title != "NA":
            bar.set_name(title)
        if total > 0:
            bar.set(downloaded, total)
        elif percent is not None:
            bar.set(int(percent), 100)

    try:
        code, lines = run_hidden(cmd, timeout=timeout, on_line=on_line)
    except subprocess.TimeoutExpired:
        if bar is not None:
            bar.close()
        raise
    return code, [line for line in lines if not line.startswith(PROGRESS_PREFIX)]


def _parse_ts(info: dict) -> float | None:
    from core.timeutil import parse_timestamp

    return parse_timestamp(
        info.get("timestamp") or info.get("release_timestamp") or info.get("upload_date")
    )


def _read_info_files(tmpdir: Path) -> dict:
    """读 yt-dlp 写出的 .info.json，取字段最全的一个。"""
    best: dict = {}
    for info_file in sorted(tmpdir.glob("*.info.json")):
        try:
            data = json.loads(info_file.read_text(encoding="utf-8", errors="ignore"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and len(data) > len(best):
            best = data
    return best


def extract(
    url: str,
    platform: str,
    cfg,
    *,
    max_height: int | None = None,
    log=print,
    progress: str = "bar",
    index: int = 1,
    count: int = 1,
) -> Extraction:
    exe = which("yt-dlp")
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

    import tempfile

    tmpdir = Path(tempfile.mkdtemp(prefix=f"mediadl_{platform}_"))
    cmd = [
        exe,
        "-P", str(tmpdir),
        "-o", "%(id)s_%(autonumber)03d.%(ext)s",
        "-f", fmt,
        "--newline",
        "--progress",
        "--progress-template",
        PROGRESS_PREFIX + "%(progress._percent_str)s|%(progress.downloaded_bytes)s|"
        "%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|%(info.title).80s",
        "--no-warnings",
        "--write-info-json",
        "--no-mtime",
        "--no-simulate",
        "--socket-timeout", "45",
        "--retries", "3",
        "--fragment-retries", "3",
        "--concurrent-fragments", "4",
    ]
    if platform != "telegram":
        cmd.append("--no-playlist")
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

    bar = ProgressBar(0, index=index, count=count, name=platform,
                      enabled=progress != "none")
    try:
        returncode, output = _run_with_progress(cmd, bar)
    except (subprocess.SubprocessError, OSError) as exc:
        bar.close()
        content = Content(platform=platform, id="", status=Status.FAIL_TOOL, message=str(exc))
        return Extraction(content=content, mode="local", tmpdir=tmpdir)
    bar.finish()
    bar.close()

    files = sorted(
        path for path in tmpdir.iterdir()
        if path.is_file() and path.suffix.lower() not in SKIP_SUFFIXES
        and not path.name.endswith(".info.json")
    )

    info = _read_info_files(tmpdir)
    content = metadata.content_from_ytdlp(info, url, platform)

    if not files:
        stderr = "\n".join(output).lower()
        if returncode != 0:
            if any(k in stderr for k in ("private", "login", "sign in", "members-only", "premium")):
                content.status = Status.SKIP_PAYWALLED
            elif any(k in stderr for k in ("unavailable", "removed", "404", "deleted")):
                content.status = Status.SKIP_DELETED
            else:
                content.status = Status.FAIL_TOOL
            lines = [line for line in output if line.strip()]
            content.message = lines[-1] if lines else "yt-dlp 失败"
        else:
            content.status = Status.SKIP_NO_MEDIA
        return Extraction(content=content, mode="local", tmpdir=tmpdir)

    return Extraction(content=content, mode="local", files=files, tmpdir=tmpdir)
