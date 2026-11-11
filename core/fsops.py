"""文件操作：时间、备份、回收站、原子替换。

规则要求：只移动不删除、覆盖前备份、删除走回收站。
Windows 优先用 send2trash；没有该库或 Termux 上退回到输出目录旁的 .trash/日期/。
"""

from __future__ import annotations

import os
import shutil
import time
from datetime import datetime
from pathlib import Path

try:  # 可选依赖，没有就退回 .trash 目录
    from send2trash import send2trash as _send2trash
except Exception:  # noqa: BLE001
    _send2trash = None


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d")


def apply_mtime(path: str | Path, timestamp: float | int | None) -> bool:
    """把文件时间改成作品发布时间；时间无效时不动。"""
    if not timestamp:
        return False
    try:
        ts = float(timestamp)
        if ts <= 0:
            return False
        os.utime(str(path), (ts, ts))
        return True
    except (OSError, ValueError, OverflowError):
        return False


def unique_path(path: Path) -> Path:
    """目标已存在时追加 -1、-2，避免覆盖。"""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}-{int(time.time())}{suffix}")


def backup_file(path: Path, backup_root: Path) -> Path | None:
    """把文件移动到备份目录，返回备份后的路径。"""
    if not path.exists():
        return None
    target_dir = Path(backup_root) / _stamp()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(target_dir / path.name)
    shutil.move(str(path), str(target))
    return target


def trash_path(path: Path, *, mode: str = "auto", backup_root: Path | None = None) -> Path | None:
    """删除走回收站；返回文件最终位置（没有移动则 None）。"""
    path = Path(path)
    if not path.exists():
        return None

    mode = (mode or "auto").lower()
    if mode == "none":
        return None

    if mode in {"auto", "recycle"} and _send2trash is not None:
        try:
            _send2trash(str(path))
            return None
        except Exception:  # noqa: BLE001 - 回收站失败时退回 .trash
            pass

    if backup_root is not None and mode == "backup":
        return backup_file(path, backup_root)

    target_dir = path.parent / ".trash" / _stamp()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(target_dir / path.name)
    shutil.move(str(path), str(target))
    return target


def place_file(
    src: Path,
    dst: Path,
    *,
    overwrite: bool,
    backup_root: Path,
) -> tuple[bool, Path | None, str]:
    """把 src 放到 dst。

    返回 (是否放置, 备份文件, 说明)。
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None

    if dst.exists():
        if not overwrite:
            return False, None, "目标已存在，跳过（--overwrite 可覆盖）"
        backup = backup_file(dst, backup_root)

    shutil.move(str(src), str(dst))
    return True, backup, ""


def part_path(path: Path) -> Path:
    """下载中的临时文件路径，避免半截文件冒充成品。"""
    return path.with_name(path.name + ".part")
