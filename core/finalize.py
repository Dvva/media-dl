"""外部工具产物的重命名与归档。"""

from __future__ import annotations

import shutil
from pathlib import Path

from platforms.base import Extraction
from . import naming
from .cover import write_cover
from .result import Status


def finalize(
    extraction: Extraction,
    cfg,
    session=None,
    *,
    output_dir: Path | None = None,
    cover_mode: str | None = None,
    log=print,
) -> tuple[Status, list[Path]]:
    """把外部工具下好的文件按模板改名并移动到输出目录。"""
    content = extraction.content
    files = [f for f in extraction.files if f.is_file()]
    if not files:
        return Status.SKIP_NO_MEDIA, []

    root = output_dir or cfg.output_dir
    template = cfg.naming_for(content.platform)
    mode = (cover_mode or cfg.cover_mode) if cfg.cover_enabled else "none"
    multi = len(files) > 1
    max_len = int(cfg.get("naming.max_len", 120))
    written: list[Path] = []

    for order, src in enumerate(files, 1):
        ext = src.suffix
        variables = content.variables(ext=ext.lstrip("."))
        basename = naming.render(
            template,
            variables,
            is_multi=multi,
            omit_index_when_single=cfg.omit_index_when_single,
            max_len=max_len,
        )
        if multi:
            basename = f"{basename}_{order:02d}"
        if "{ext}" not in template:
            basename = f"{basename}{ext}"

        directory_part, _ = naming.split_template(template)
        dest_dir = root
        if directory_part:
            sub = naming.render(
                directory_part,
                variables,
                is_multi=multi,
                omit_index_when_single=cfg.omit_index_when_single,
                max_len=max_len,
            )
            dest_dir = root / sub

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / basename
        shutil.move(str(src), str(dest))
        written.append(dest)
        log(f"  · {dest}")

        if mode != "none" and content.cover_url and order == 1 and session is not None:
            try:
                resp = session.get(content.cover_url, headers=content.cover_headers, timeout=60)
                resp.raise_for_status()
                cover_path = write_cover(dest, resp.content, mode)
                if cover_path:
                    log(f"  · 封面 {cover_path}")
            except Exception:
                log("  ! 封面下载失败，跳过")

    return Status.OK, written
