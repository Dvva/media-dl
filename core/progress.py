"""下载进度条（两行刷新）。

第一行：下载中 [██████████░░░░░░░░░░]  50%  3.2/6.4 MB  1.8 MB/s
第二行：1/8    文件名.mp4   剩余 00:05

只在 stdout 是终端时启用；重定向到文件/日志时自动静默。
"""

from __future__ import annotations

import sys
import time


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"


def _clock(seconds: float) -> str:
    if seconds is None or seconds < 0 or seconds > 36000:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


class ProgressBar:
    """按字节推进的两行进度条。"""

    BAR_WIDTH = 20

    def __init__(self, total: int = 0, *, index: int = 1, count: int = 1,
                 name: str = "", note: str = "", enabled: bool | None = None):
        self.total = total
        self.index = index
        self.count = count
        self.name = name[:40]
        self.note = note
        self.enabled = sys.stdout.isatty() if enabled is None else enabled
        self.done = 0
        self.start = time.time()
        self._last = 0.0
        self._last_time = self.start
        self._speed = 0.0
        self._printed = False
        self._lines = 0

    # ---------------- 内部 ----------------

    def _compute(self) -> tuple[float, float, float]:
        percent = (self.done / self.total * 100) if self.total else 0.0
        elapsed = max(time.time() - self.start, 0.001)
        inst = self.done / elapsed
        # 小文件可能一两帧就下完，没有 0.3s 门槛兜底，否则速度永远是 0
        self._speed = inst if self._speed == 0 else self._speed * 0.7 + inst * 0.3
        remain = ((self.total - self.done) / self._speed) if self._speed > 0 else 0
        return percent, self._speed, remain

    def _draw(self) -> None:
        percent, speed, remain = self._compute()
        filled = int(self.BAR_WIDTH * percent / 100) if self.total else 0
        bar = "█" * filled + " " * (self.BAR_WIDTH - filled)

        first = (
            f"下载中 [{bar}] {percent:3.0f}%  "
            f"{_human(self.done)}/{_human(self.total) if self.total else '?'}  "
            f"{_human(speed)}/s"
        )
        second = f"{self.index}/{self.count}    {self.name}   剩余 {_clock(remain)}"
        if self.note:
            second += f"   {self.note}"

        buf = ""
        if self._printed:
            buf += "\033[2A"  # 上移两行
        buf += f"\033[K{first}\n\033[K{second}\n"
        sys.stdout.write(buf)
        sys.stdout.flush()
        self._printed = True

    # ---------------- 对外的 ----------------

    def update(self, chunk: int) -> None:
        self.done += chunk
        if not self.enabled:
            return
        now = time.time()
        if now - self._last_time < 0.1:  # 10fps 够了，避免刷屏拖慢下载
            return
        self._last_time = now
        self._draw()

    def set(self, done: int, total: int | None = None) -> None:
        """外部工具用：直接设置已下载量 / 总量。"""
        self.done = max(0, int(done))
        if total is not None and total > 0:
            self.total = int(total)
        if not self.enabled:
            return
        now = time.time()
        if now - self._last_time < 0.1:
            return
        self._last_time = now
        self._draw()

    def set_name(self, name: str) -> None:
        self.name = (name or "")[:40]

    def finish(self) -> None:
        if not self.enabled:
            return
        if self.total:
            self.done = self.total
        self._draw()
        self._printed = False

    def close(self) -> None:
        """非终端模式下补一行摘要，便于看日志。"""
        if not self.enabled:
            elapsed = max(time.time() - self.start, 0.001)
            speed = self.done / elapsed
            sys.stdout.write(
                f"  · {self.name}  {_human(self.done)}  {_human(speed)}/s"
                f"  用时 {_clock(elapsed)}\n"
            )
            sys.stdout.flush()
