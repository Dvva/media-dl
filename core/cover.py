"""封面处理：sidecar / embed / both / none。

sidecar —— 视频旁边存同名 .jpg，媒体库（Emby/Jellyfin）可识别
embed   —— 用 ffmpeg 把封面作为 attached_pic 塞进 mp4；失败自动降级 sidecar

注意：YouTube/B站/抖音的缩略图经常是 **WebP**，直接写 .jpg 会让 ffmpeg 报
"codec not currently supported in container"，所以落盘前统一转成真 JPEG。
"""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def ensure_jpeg(data: bytes) -> bytes:
    """把任意图片字节转成真 JPEG；转换失败就原样返回。"""
    if data[:2] == b"\xff\xd8":  # 已经是 JPEG
        return data
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            if im.format == "JPEG":
                return data
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=90)
            return buf.getvalue()
    except Exception:  # noqa: BLE001
        return data


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
        if tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(media)
        return True
    except (subprocess.SubprocessError, OSError):
        tmp.unlink(missing_ok=True)
        return False


def write_cover(media: Path, cover_bytes: bytes, mode: str) -> Path | None:
    """落盘封面。返回实际生成的 jpg 路径（embed 且成功时返回 None）。"""
    if not cover_bytes:
        return None
    data = ensure_jpeg(cover_bytes)
    sidecar = media.with_suffix(".jpg")
    sidecar.write_bytes(data)

    if mode == "embed":
        if embed_cover(media, sidecar):
            sidecar.unlink(missing_ok=True)
            return None
    elif mode == "both":
        embed_cover(media, sidecar)
    return sidecar
