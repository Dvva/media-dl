"""外部工具调用：静默执行，只把需要的行交给调用方。

要求：不要打印 yt-dlp / gallery-dl 的原始命令与刷屏输出；
进度由调用方自己的进度条负责。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def which(name: str) -> str | None:
    return shutil.which(name)


def run_hidden(
    cmd: list[str],
    *,
    timeout: int = 600,
    on_line: Callable[[str], None] | None = None,
    keep_lines: int = 200,
) -> tuple[int, list[str]]:
    """运行命令，stdout/stderr 合并后逐行回调。

    返回 (退出码, 最近 keep_lines 行)。超时会杀掉进程并抛 TimeoutExpired。
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    collected: list[str] = []
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            text = line.rstrip("\r\n")
            if not text:
                continue
            collected.append(text)
            if len(collected) > keep_lines:
                del collected[: len(collected) - keep_lines]
            if on_line is not None:
                try:
                    on_line(text)
                except Exception:  # noqa: BLE001 - 进度回调不能影响下载
                    pass
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
    return proc.returncode, collected


def parse_percent(text: str) -> float | None:
    """从工具输出里抠百分比，兼容 yt-dlp / gallery-dl 两种格式。"""
    import re

    match = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", text)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return max(0.0, min(100.0, value))


def parse_bytes(text: str) -> int | None:
    """解析 12.3MiB / 4.5MB / 12345 这类大小。"""
    import re

    match = re.search(r"(\d+(?:\.\d+)?)\s*([KMGT]?i?B)\b", text, re.I)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2).upper()
    factors = {
        "B": 1,
        "KB": 1000, "KIB": 1024,
        "MB": 1000 ** 2, "MIB": 1024 ** 2,
        "GB": 1000 ** 3, "GIB": 1024 ** 3,
        "TB": 1000 ** 4, "TIB": 1024 ** 4,
    }
    return int(number * factors.get(unit, 1))
