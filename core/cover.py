"""封面处理：sidecar / embed / both / none。

sidecar —— 视频或图片旁边存同名 .jpg，媒体库（Emby/Jellyfin）可识别
embed   —— 用 ffmpeg 把封面作为 attached_pic 塞进 mp4；失败自动降级 sidecar
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def embed_cover(media: Path, cover: Path) -> bool:
    """把 cover 作为 attached_pic 嵌入视频。成功返回 True。"""
    exe = _ffmpeg()
    if not exe or media.suffix.lower() not in {".mp4", ".m4v", ".mov"}:
        return False
    tmp = media.with_name(media.stem + ".cover_tmp" + media.suffix)
    cmd = [
        exe, "-y", "-loglevel", "error",
        "-i", str(media),
        "-i", str(cover),
        "-map", "0", "-map", "1",
        "-c", "copy",
        "-disposition:v:1", "attached_pic",
        str(tmp),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
        tmp.replace(media)
        return True
    except (subprocess.SubprocessError, OSError):
        tmp.unlink(missing_ok=True)
        return False


def write_cover(media: Path, cover_bytes: bytes, mode: str) -> Path | None:
    """落盘封面。返回实际生成的 jpg 路径（embed 且无 sidecar 时返回 None）。"""
    if not cover_bytes:
        return None
    sidecar = media.with_suffix(".jpg")
    sidecar.write_bytes(cover_bytes)

    if mode == "embed":
        if embed_cover(media, sidecar):
            sidecar.unlink(missing_ok=True)
            return None
    elif mode == "both":
        embed_cover(media, sidecar)
    return sidecar
