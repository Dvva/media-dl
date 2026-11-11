"""批量操作：redl / rename / replace / doctor 的公共逻辑。"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from core import fsops, metadata, naming, patterns, urls as url_tools
from core.result import Status
from core.timeutil import parse_timestamp
from platforms.base import Content

MEDIA_SUFFIXES = {
    ".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv", ".ts",
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic",
    ".mp3", ".m4a", ".aac", ".flac", ".wav", ".opus", ".ogg",
    ".pdf", ".zip", ".7z", ".rar",
}
TEXT_SUFFIXES = {".txt", ".list", ".md", ".lst"}
SKIP_DIRS = {".trash", ".git", "__pycache__", "node_modules"}


@dataclass
class Counts:
    total: int = 0
    ok: int = 0
    skipped: int = 0
    failed: int = 0
    unparsable: int = 0
    details: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        return (f"共 {self.total} 个：成功 {self.ok}  跳过 {self.skipped}  "
                f"失败 {self.failed}  无法解析 {self.unparsable}")


def collect_files(paths: list[str], *, suffixes: set[str] | None = None) -> list[Path]:
    """展开文件 / 目录，过滤隐藏目录和临时文件。"""
    result: list[Path] = []
    suffix_filter = suffixes or MEDIA_SUFFIXES
    for raw in paths:
        path = Path(raw).expanduser()
        if not path.exists():
            continue
        if path.is_file():
            if path.suffix.lower() in suffix_filter:
                result.append(path)
            continue
        for child in path.rglob("*"):
            if not child.is_file():
                continue
            if any(part in SKIP_DIRS for part in child.parts):
                continue
            if child.suffix.lower() in suffix_filter:
                result.append(child)
    # 去重保序
    seen: set[Path] = set()
    unique = []
    for path in result:
        key = path.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _merge_content(platform: str, fields: dict, probed: Content | None) -> Content:
    content = Content(
        platform=platform,
        id=str(fields.get("id") or ""),
        author=str(fields.get("author") or ""),
        nickname=str(fields.get("nickname") or ""),
        author_id=str(fields.get("author_id") or ""),
        title=str(fields.get("title") or ""),
        timestamp=parse_timestamp(fields.get("date")),
    )
    if probed is not None and probed.status is Status.OK:
        content.id = probed.id or content.id
        content.author = probed.author or content.author
        content.nickname = probed.nickname or content.nickname or content.author
        content.author_id = probed.author_id or content.author_id
        content.title = probed.title or content.title
        content.timestamp = probed.timestamp or content.timestamp
        content.cover_url = probed.cover_url
    return content


def describe_file(path: Path, cfg, extra_patterns: list[str] | None = None
                  ) -> tuple[dict | None, str | None]:
    fields = patterns.parse_file(path, cfg=cfg, extra_patterns=extra_patterns)
    if not fields:
        return None, "文件名不符合任何模板"
    url = patterns.rebuild_url(fields["platform"], fields, cfg)
    if not url:
        ok, reason = patterns.can_rebuild(fields["platform"], fields, cfg)
        return fields, reason if not ok else "无法重建网址"
    return fields, None


def doctor(paths: list[str], cfg, *, log=print) -> Counts:
    """扫描目录，报告哪些文件名无法重建网址（首次运行时提醒用）。"""
    files = collect_files(paths)
    counts = Counts(total=len(files))
    per_platform: dict[str, list[int]] = {}
    bad: list[str] = []

    for path in files:
        fields, reason = describe_file(path, cfg)
        if not fields:
            counts.unparsable += 1
            bad.append(f"{path.name}：{reason}")
            continue
        platform = fields["platform"]
        stat = per_platform.setdefault(platform, [0, 0])
        if reason:
            stat[1] += 1
            counts.unparsable += 1
            bad.append(f"{path.name}：{reason}")
        else:
            stat[0] += 1

    log(f"扫描 {len(files)} 个文件：")
    counts.ok = len(files) - counts.unparsable
    for platform in sorted(per_platform):
        ok, bad_count = per_platform[platform]
        log(f"  {platform}: 可重建 {ok}，不可重建 {bad_count}")
    if bad:
        log("以下文件无法从文件名重建网址（rename/redl 会跳过）：")
        for line in bad[:50]:
            log(f"  - {line}")
        if len(bad) > 50:
            log(f"  ……其余 {len(bad) - 50} 个省略")
    else:
        log("全部文件都能从文件名重建网址。")
    return counts


def rename_files(
    paths: list[str],
    cfg,
    *,
    apply: bool,
    pattern: str | None = None,
    platform: str | None = None,
    log=print,
) -> Counts:
    """按文件名反推网址，取属性后按当前 naming 模板改名。"""
    extra = [pattern] if pattern else None
    files = collect_files(paths)
    counts = Counts(total=len(files))
    if not files:
        log("没有找到可处理的文件。")
        return counts

    for path in files:
        fields = patterns.parse_file(path, cfg=cfg, platform=platform,
                                     extra_patterns=extra)
        if not fields:
            counts.unparsable += 1
            log(f"  ! 跳过（文件名解析失败）：{path.name}")
            continue

        resolved_platform = fields["platform"]
        url = patterns.rebuild_url(resolved_platform, fields, cfg)
        if not url:
            ok, reason = patterns.can_rebuild(resolved_platform, fields, cfg)
            counts.unparsable += 1
            log(f"  ! 跳过（{reason}）：{path.name}")
            continue

        probed = None
        if apply:
            probed = metadata.probe(url, resolved_platform, cfg, log=log)
            if probed.status is not Status.OK:
                log(f"  · 取属性失败，仅用文件名：{path.name}（{probed.message}）")

        content = _merge_content(resolved_platform, fields, probed)
        if not content.id:
            counts.unparsable += 1
            log(f"  ! 跳过（没有作品 id）：{path.name}")
            continue

        template = cfg.naming_for(resolved_platform)
        if apply and "{author}" in template and not content.author:
            counts.skipped += 1
            log(f"  ! 跳过（没取到作者，模板需要 {{author}}）：{path.name}")
            continue
        if not apply and "{author}" in template and not content.author:
            log(f"  · 预览：{path.name} 的作者需要联网补全")
        ext = path.suffix
        variables = content.variables(ext=ext.lstrip("."))
        new_stem = naming.render(
            template,
            variables,
            is_multi=bool(fields.get("index")),
            omit_index_when_single=cfg.omit_index_when_single,
            max_len=int(cfg.get("naming.max_len", 120)),
        )
        if fields.get("index"):
            new_stem = f"{new_stem}_{fields['index']:0>2}" if not new_stem.endswith(
                f"_{fields['index']}"
            ) else new_stem
        new_path = path.with_name(new_stem + ext)

        if new_path == path:
            counts.skipped += 1
            log(f"  · 无需改名：{path.name}")
            continue

        log(f"  {path.name}  →  {new_path.name}")
        if not apply:
            counts.ok += 1
            continue

        placed, backup, reason = fsops.place_file(
            path, new_path,
            overwrite=cfg.overwrite,
            backup_root=cfg.backup_dir,
        )
        if not placed:
            counts.skipped += 1
            log(f"    ! {reason}")
            continue
        if backup:
            log(f"    · 旧文件已备份：{backup}")

        if cfg.set_mtime and content.timestamp:
            fsops.apply_mtime(new_path, content.timestamp)

        # 同名封面 .jpg 一起改
        old_cover = path.with_suffix(".jpg")
        if ext.lower() not in {".jpg", ".jpeg"} and old_cover.exists():
            new_cover = new_path.with_suffix(".jpg")
            try:
                fsops.place_file(old_cover, new_cover, overwrite=cfg.overwrite,
                                 backup_root=cfg.backup_dir)
                if cfg.set_mtime and content.timestamp:
                    fsops.apply_mtime(new_cover, content.timestamp)
            except OSError as exc:
                log(f"    ! 封面改名失败：{exc}")

        counts.ok += 1

    return counts


def replace_files(
    paths: list[str],
    cfg,
    *,
    apply: bool,
    quality: int | None,
    pattern: str | None = None,
    platform: str | None = None,
    tag: str | None = None,
    download_func=None,
    log=print,
) -> Counts:
    """按文件名重建网址，用指定清晰度重下，备份旧文件后替换。"""
    extra = [pattern] if pattern else None
    files = collect_files(paths)
    counts = Counts(total=len(files))
    if not files:
        log("没有找到可替换的媒体文件。")
        return counts

    for path in files:
        fields = patterns.parse_file(path, cfg=cfg, platform=platform,
                                     extra_patterns=extra)
        if not fields:
            counts.unparsable += 1
            log(f"  ! 跳过（文件名解析失败）：{path.name}")
            continue
        resolved_platform = fields["platform"]
        url = patterns.rebuild_url(resolved_platform, fields, cfg)
        if not url:
            _, reason = patterns.can_rebuild(resolved_platform, fields, cfg)
            counts.unparsable += 1
            log(f"  ! 跳过（{reason}）：{path.name}")
            continue

        if resolved_platform in {"douyin", "xhs"}:
            log(f"  ! {resolved_platform} 的直链清晰度固定，无法换清晰度：{path.name}")
            counts.skipped += 1
            continue

        log(f"  {path.name}  ←  {url}  ({quality or cfg.max_height}P)")
        if not apply:
            counts.ok += 1
            continue
        if download_func is None:
            counts.failed += 1
            log("    ! 内部错误：没有下载函数")
            continue

        probed = metadata.probe(url, resolved_platform, cfg, log=log)
        timestamp = probed.timestamp if probed.status is Status.OK else None

        import tempfile

        tmpdir = Path(tempfile.mkdtemp(prefix="mediadl_replace_"))
        try:
            status, new_files = download_func(url, tmpdir, quality)
            if status is not Status.OK or not new_files:
                counts.failed += 1
                log(f"    ! 重新下载失败：{status.value}")
                continue

            candidate = _pick_replacement(path, new_files, index=fields.get("index"))
            if candidate is None:
                counts.failed += 1
                log("    ! 下载结果里没有同类型媒体")
                continue

            backup = fsops.backup_file(path, cfg.backup_dir)
            if backup:
                log(f"    · 旧文件已备份：{backup}")

            target = path
            if tag:
                target = path.with_name(f"{path.stem}_{tag}{path.suffix}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                fsops.backup_file(target, cfg.backup_dir)
            shutil.move(str(candidate), str(target))
            if cfg.set_mtime and timestamp:
                fsops.apply_mtime(target, timestamp)
            counts.ok += 1
            log(f"    · 已替换：{target.name}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    return counts


def _pick_replacement(original: Path, new_files: list[Path],
                      index: str | None = None) -> Path | None:
    want_video = original.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v"}

    if index and index.isdigit():
        position = int(index) - 1
        if 0 <= position < len(new_files):
            candidate = new_files[position]
            is_video = candidate.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
            if is_video == want_video:
                return candidate

    best = None
    for path in new_files:
        is_video = path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
        if is_video == want_video:
            if best is None or path.stat().st_size > best.stat().st_size:
                best = path
    return best


def read_inputs(
    items: list[str],
    *,
    cfg,
    platform: str | None = None,
    log=print,
) -> list[dict]:
    """redl 的输入解析：URL / txt 清单 / 目录 / 媒体文件 / 裸 id。"""
    results: list[dict] = []
    seen: set[str] = set()

    def add(url: str, source: str) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        results.append({"url": url, "source": source})

    for raw in items:
        raw = str(raw)
        path = Path(raw).expanduser()

        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError as exc:
                log(f"  ! 读文件失败：{raw}（{exc}）")
                continue
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                for url in url_tools.iter_urls([line]):
                    add(url, raw)
                if not url_tools.iter_urls([line]):
                    _add_bare_id(line, platform, add, raw, log)
            continue

        if path.is_dir():
            for media in collect_files([str(path)]):
                fields = patterns.parse_file(media, cfg=cfg, platform=platform)
                if not fields:
                    log(f"  ! 文件名无法解析：{media.name}")
                    continue
                url = patterns.rebuild_url(fields["platform"], fields, cfg)
                if url:
                    add(url, str(media))
                else:
                    log(f"  ! 无法重建网址：{media.name}")
            continue

        if path.is_file():
            fields = patterns.parse_file(path, cfg=cfg, platform=platform)
            if fields:
                url = patterns.rebuild_url(fields["platform"], fields, cfg)
                if url:
                    add(url, str(path))
                    continue
            log(f"  ! 文件无法解析：{path.name}")
            continue

        found = url_tools.iter_urls([raw])
        if found:
            for url in found:
                add(url, "参数")
            continue
        _add_bare_id(raw, platform, add, "参数", log)

    return results


def _add_bare_id(line: str, platform: str | None, add, source: str, log) -> None:
    match = re.match(r"^(?P<platform>[A-Za-z]+)\s*[: ]\s*(?P<id>[\w-]+)$", line)
    if match:
        resolved = patterns.normalize_platform(match.group("platform"))
        if resolved and patterns.valid_id(resolved, match.group("id")):
            url = patterns.rebuild_url(resolved, {"id": match.group("id")})
            if url:
                add(url, source)
                return
    if platform and patterns.valid_id(platform, line):
        url = patterns.rebuild_url(platform, {"id": line})
        if url:
            add(url, source)
            return
    log(f"  ! 忽略无法识别的参数：{line[:60]}")
