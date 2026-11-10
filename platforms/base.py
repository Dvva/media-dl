"""内容与媒体条目的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.result import Status


@dataclass
class MediaItem:
    """一条可下载的媒体。"""

    url: str
    type: str = "video"          # video | image
    ext: str = ""                # 留空则从 URL / Content-Type 推断
    index: int = 1               # 同一内容内的序号，从 1 开始
    headers: dict = field(default_factory=dict)


@dataclass
class Content:
    """一次解析的结果：一条推文 / 一条笔记 / 一个视频。"""

    platform: str
    id: str
    status: Status = Status.OK
    message: str = ""
    author: str = ""
    author_id: str = ""
    title: str = ""
    url: str = ""                # 原始链接，供 {url} 模板变量使用
    timestamp: float | None = None
    items: list[MediaItem] = field(default_factory=list)
    cover_url: str | None = None
    cover_headers: dict = field(default_factory=dict)

    @property
    def is_multi(self) -> bool:
        return len(self.items) > 1

    def variables(self, ext: str = "") -> dict:
        from core.naming import fmt_date

        date, datetime_str = fmt_date(self.timestamp)
        return {
            "platform": self.platform,
            "author": self.author or "unknown",
            "author_id": self.author_id or "",
            "id": self.id or "unknown",
            "title": self.title or "",
            "url": self.url,
            "date": date,
            "datetime": datetime_str,
            "type": self.items[0].type if self.items else "media",
            "ext": ext,
        }


@dataclass
class Extraction:
    """解析结果。

    mode="remote" 时 items 里是直链，交给 downloader 下载；
    mode="local"  时 files 里是外部工具（yt-dlp/gallery-dl）已经下好的本地文件，
    由 finalize 阶段按模板重命名归档。
    """

    content: Content
    mode: str = "remote"
    files: list[Path] = field(default_factory=list)
    tmpdir: Path | None = None
