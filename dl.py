#!/usr/bin/env python3
"""media-dl —— 一个链接，自动识别平台并下载图片 / 视频。

命令：
    dl.py URL...                     下载（可多个链接、分享文案、拼接链接）
    dl.py redl 清单.txt              从文件里的 URL / 视频 id 重新下载
    dl.py rename --apply 目录         按文件名重建网址并重新命名
    dl.py replace --quality 1080 文件  换清晰度重下并替换
    dl.py probe URL或文件             只解析属性，不下载
    dl.py doctor 目录                检查哪些文件名无法重建网址

旧用法完全兼容：第一个参数不是子命令时，按“下载”处理。
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

# Windows 下管道输出常被按 cp936 编码，日志会乱码；统一成 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from core import batch, detect, fsops, metadata, patterns          # noqa: E402
from core.config import Config                                      # noqa: E402
from core.downloader import save                                    # noqa: E402
from core.finalize import finalize                                  # noqa: E402
from core.http import load_netscape_cookies, make_session, proxy_alive  # noqa: E402
from core.result import Status                                      # noqa: E402
from platforms import douyin, gallerydl_backend, xhs, ytdlp_backend  # noqa: E402

YTDLP_PLATFORMS = {"tiktok", "bilibili", "telegram", "youtube"}
GALLERY_PLATFORMS = {"twitter"}
COMMANDS = {"download", "redl", "rename", "replace", "probe", "doctor"}

VERSION = "1.1.0"


# ---------------------------------------------------------------- 日志

def setup_logger(cfg, verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("media-dl")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    log_dir = cfg.get("general.log_dir")
    if log_dir:
        path = Path(os.path.expanduser(str(log_dir)))
        try:
            path.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(path / time.strftime("media-dl-%Y%m%d.log"),
                                          encoding="utf-8")
            handler.setFormatter(fmt)
            logger.addHandler(handler)
        except OSError:
            pass
    return logger


# ---------------------------------------------------------------- 单实例锁

def acquire_lock(lock_path: Path) -> bool:
    """跨平台单实例锁：用 pid 文件 + 陈旧超时。"""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        try:
            pid = int(lock_path.read_text().strip() or "0")
            if pid and _pid_alive(pid):
                return False
        except ValueError:
            pass
        lock_path.unlink(missing_ok=True)
    lock_path.write_text(str(os.getpid()))
    return True


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def release_lock(lock_path: Path) -> None:
    lock_path.unlink(missing_ok=True)


# ---------------------------------------------------------------- 首次运行提醒

def first_run_notice(cfg, logger) -> None:
    if not cfg.get("behavior.first_run_notice", True):
        return
    marker = Path(cfg.state_dir) / ".first_run_notified"
    if marker.exists():
        return
    logger.warning("首次运行提醒：旧文件名如果不是「平台_作者_id」形状，")
    logger.warning("  rename / redl 无法从文件名反推网址，会跳过并提示。")
    logger.warning("  可先运行：dl.py doctor <下载目录> 检查有多少文件可重建。")
    logger.warning("  推特旧名 <tweet_id>-<hash> 只能反推 id/网址；TikTok 缺 @handle、")
    logger.warning("  Telegram 缺频道名时无法重建网址。")
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------- 下载

def _download(
    url: str,
    cfg,
    logger,
    *,
    cover: str | None,
    quality: int | None,
    out: Path | None,
    progress: str,
    index: int = 1,
    count: int = 1,
) -> tuple[Status, list[Path], object | None]:
    """下载单条链接，返回 (状态, 文件, Content)。"""
    platform, final = detect.detect(url)
    if not platform:
        logger.error("无法识别平台：%s", url)
        return Status.SKIP_UNSUPPORTED, [], None
    if not cfg.enabled(platform):
        logger.error("平台 %s 未启用（config.toml 的 platforms.enabled）", platform)
        return Status.SKIP_UNSUPPORTED, [], None

    logger.info("平台=%s  链接=%s", platform, final)

    delay = cfg.delay(platform)
    if delay > 0:
        time.sleep(delay)

    effective_cover = cover or cfg.cover_mode_for(platform)

    extraction = None
    try:
        if platform in GALLERY_PLATFORMS:
            extraction = gallerydl_backend.extract(
                final, platform, cfg, log=logger.info,
                progress=progress, index=index, count=count,
            )
        elif platform in YTDLP_PLATFORMS:
            extraction = ytdlp_backend.extract(
                final, platform, cfg, max_height=quality, log=logger.info,
                progress=progress, index=index, count=count,
            )
        elif platform == "douyin":
            extraction = douyin.extract(final, cfg, log=logger.info)
        elif platform == "xhs":
            extraction = xhs.extract(final, cfg, log=logger.info)
        else:
            logger.error("平台 %s 还没有实现", platform)
            return Status.SKIP_UNSUPPORTED, [], None

        content = extraction.content
        if content.status is not Status.OK:
            logger.warning("跳过 [%s] %s", content.status.value, content.message)
            return content.status, [], content

        cookies = load_netscape_cookies(cfg.cookie_file(platform))
        session = make_session(cfg.proxy, cookies=cookies)

        if extraction.mode == "local":
            status, files = finalize(
                extraction, cfg, session, output_dir=out,
                cover_mode=effective_cover, log=logger.info,
            )
        else:
            status, files = save(
                content, session=session, cfg=cfg, output_dir=out,
                cover_mode=effective_cover, progress=progress, log=logger.info,
            )
        return status, files, content
    except Exception as exc:  # noqa: BLE001 - 单条失败不影响其它链接
        logger.error("处理失败：%s（%s）", url, exc)
        return Status.FAIL_PARSE, [], None
    finally:
        if extraction is not None and extraction.tmpdir is not None:
            shutil.rmtree(extraction.tmpdir, ignore_errors=True)


def maybe_merge(files: list[Path], platform: str, logger, cfg, *,
                timestamp: float | None = None, keep_origin: bool = False) -> Status:
    """按尺寸分组合并：同尺寸的拼成一张，不同尺寸的跳过但其余照合并。"""
    from core.merge import group_by_size, merge_horizontal, pick_images

    images = pick_images(files)
    if len(images) < 2:
        logger.warning("不合并：图片不足 2 张")
        return Status.OK

    groups = group_by_size(images)
    mergeable = {size: group for size, group in groups.items() if len(group) >= 2}
    if not mergeable:
        detail = "、".join(f"{w}x{h}×{len(g)}" for (w, h), g in groups.items())
        logger.warning("不合并：没有两张及以上同尺寸图片（%s）", detail)
        return Status.OK

    removed: list[Path] = []
    for order, (size, group) in enumerate(mergeable.items(), 1):
        suffix = "_merged" if order == 1 else f"_merged{order}"
        target = group[0].with_name(group[0].stem + suffix + ".jpg")
        if not merge_horizontal(group, target):
            logger.warning("合并失败（%dx%d），保留原图", size[0], size[1])
            continue
        if cfg.set_mtime and timestamp:
            fsops.apply_mtime(target, timestamp)
        logger.info("已合并 %d 张（%dx%d）-> %s", len(group), size[0], size[1], target.name)
        removed.extend(group)

    if removed and not keep_origin:
        for path in removed:
            try:
                fsops.trash_path(path, mode=cfg.trash_mode, backup_root=cfg.backup_dir)
            except OSError:
                pass
        logger.info("已把参与合并的原图移动 %d 张（--keep 可保留）", len(removed))
    return Status.OK


def run(
    url: str,
    cfg,
    logger,
    *,
    cover: str | None,
    quality: int | None,
    out: Path | None,
    dry_run: bool,
    merge: bool = False,
    keep_origin: bool = False,
    progress: str = "bar",
    index: int = 1,
    count: int = 1,
) -> Status:
    if dry_run:
        platform, final = detect.detect(url)
        if not platform:
            logger.error("无法识别平台：%s", url)
            return Status.SKIP_UNSUPPORTED
        logger.info("[dry-run] 平台=%s  链接=%s", platform, final)
        return Status.OK

    status, files, content = _download(
        url, cfg, logger, cover=cover, quality=quality, out=out,
        progress=progress, index=index, count=count,
    )
    if merge and status is Status.OK and files and content is not None:
        status = maybe_merge(files, content.platform, logger, cfg,
                             timestamp=content.timestamp, keep_origin=keep_origin)
    logger.info("完成 [%s] 共 %d 个文件", status.value, len(files))
    return status


def _summary(results: list[Status], started: float, logger, output_dir: Path) -> int:
    ok = sum(1 for status in results if status is Status.OK)
    failed = sum(1 for status in results if status.value.startswith("FAIL"))
    skipped = len(results) - ok - failed
    elapsed = time.time() - started
    logger.info("总计 %d 条：成功 %d  跳过 %d  失败 %d  用时 %.1fs",
                len(results), ok, skipped, failed, elapsed)
    logger.info("输出目录：%s", output_dir)
    return 0 if failed == 0 and ok == len(results) else (0 if ok and failed == 0 else 1)


# ---------------------------------------------------------------- 子命令

def cmd_download(args, cfg, logger) -> int:
    items = list(args.items)
    for file_name in args.from_file or []:
        path = Path(file_name).expanduser()
        if not path.exists():
            logger.error("清单文件不存在：%s", path)
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip() and not line.strip().startswith("#"):
                items.append(line)

    urls = detect.extract_urls(*items)
    if not urls:
        logger.error("没有从参数里找到有效链接。")
        logger.error("提示：链接需以 http:// 或 https:// 开头；可直接粘贴分享文案。")
        return 2

    started = time.time()
    results: list[Status] = []
    for index, url in enumerate(urls, 1):
        if len(urls) > 1:
            logger.info("=== [%d/%d] %s", index, len(urls), url[:100])
        results.append(run(
            url, cfg, logger,
            cover=args.cover, quality=args.quality, out=_out_dir(args),
            dry_run=args.dry_run, merge=args.merge, keep_origin=args.keep,
            progress=args.progress, index=index, count=len(urls),
        ))
    return _summary(results, started, logger, _out_dir(args) or cfg.output_dir)


def cmd_redl(args, cfg, logger) -> int:
    items = list(args.items)
    for file_name in args.from_file or []:
        items.append(file_name)
    if not items:
        logger.error("redl 需要清单文件 / 目录 / 媒体文件 / URL。")
        return 2

    inputs = batch.read_inputs(items, cfg=cfg, platform=args.platform, log=logger.info)
    if not inputs:
        logger.error("没有解析出任何可下载的链接。")
        return 2

    if args.dry_run:
        for item in inputs:
            logger.info("[dry-run] %s", item["url"])
        return 0

    started = time.time()
    results: list[Status] = []
    for index, item in enumerate(inputs, 1):
        logger.info("=== [%d/%d] %s", index, len(inputs), item["url"][:100])
        results.append(run(
            item["url"], cfg, logger,
            cover=args.cover, quality=args.quality, out=_out_dir(args),
            dry_run=False, merge=args.merge, keep_origin=args.keep,
            progress=args.progress, index=index, count=len(inputs),
        ))
    return _summary(results, started, logger, _out_dir(args) or cfg.output_dir)


def cmd_rename(args, cfg, logger) -> int:
    paths = list(args.items) or [str(cfg.output_dir)]
    apply = bool(args.apply)
    logger.info("模式：%s", "执行" if apply else "预览（加 --apply 才真正改名）")
    counts = batch.rename_files(
        paths, cfg, apply=apply, pattern=args.pattern,
        platform=args.platform, log=logger.info,
    )
    logger.info(counts.as_text())
    return 0 if counts.failed == 0 else 1


def cmd_replace(args, cfg, logger) -> int:
    paths = list(args.items)
    if not paths:
        logger.error("replace 需要文件名 / 目录。")
        return 2
    apply = bool(args.apply)
    logger.info("模式：%s", "执行" if apply else "预览（加 --apply 才真正下载替换）")

    def download_func(url: str, out_dir: Path, quality: int | None):
        status, files, _ = _download(
            url, cfg, logger, cover=None, quality=quality, out=out_dir,
            progress=args.progress,
        )
        return status, files

    counts = batch.replace_files(
        paths, cfg, apply=apply, quality=args.quality, pattern=args.pattern,
        platform=args.platform, tag=args.tag, download_func=download_func,
        log=logger.info,
    )
    logger.info(counts.as_text())
    return 0 if counts.failed == 0 else 1


def cmd_probe(args, cfg, logger) -> int:
    if not args.items:
        logger.error("probe 需要 URL 或文件名。")
        return 2

    failed = 0
    for raw in args.items:
        path = Path(raw).expanduser()
        platform = args.platform
        url = None

        if path.exists():
            fields = patterns.parse_file(path, cfg=cfg, platform=platform,
                                         extra_patterns=[args.pattern] if args.pattern else None)
            if not fields:
                logger.error("文件名解析失败：%s", path.name)
                failed += 1
                continue
            platform = fields["platform"]
            url = patterns.rebuild_url(platform, fields, cfg)
            if not url:
                _, reason = patterns.can_rebuild(platform, fields, cfg)
                logger.error("无法重建网址：%s（%s）", path.name, reason)
                failed += 1
                continue
            logger.info("文件：%s", path.name)
        else:
            urls = detect.extract_urls(raw)
            if not urls:
                logger.error("不是有效 URL：%s", raw)
                failed += 1
                continue
            url = urls[0]
            platform = detect.platform_of(url) or platform

        content = metadata.probe(url, platform, cfg, log=logger.info)
        if content.status is not Status.OK:
            logger.error("解析失败：%s（%s）", url, content.message)
            failed += 1
            continue

        logger.info("平台：%s", content.platform)
        logger.info("作者：%s（昵称：%s）", content.author or "-", content.nickname or "-")
        logger.info("作品 id：%s", content.id or "-")
        logger.info("时间：%s", content.timestamp or "-")
        logger.info("网址：%s", url)
        preview = _preview_name(content, cfg)
        logger.info("将生成文件名：%s", preview)
    return 0 if failed == 0 else 1


def cmd_doctor(args, cfg, logger) -> int:
    paths = list(args.items) or [str(cfg.output_dir)]
    counts = batch.doctor(paths, cfg, log=logger.info)
    logger.info(counts.as_text())
    return 0


def _preview_name(content, cfg) -> str:
    from core import naming as naming_module

    template = cfg.naming_for(content.platform)
    variables = content.variables(ext="mp4")
    return naming_module.render(
        template, variables, is_multi=False,
        omit_index_when_single=cfg.omit_index_when_single,
        max_len=int(cfg.get("naming.max_len", 120)),
    )


def _out_dir(args) -> Path | None:
    return Path(os.path.expanduser(args.out)) if args.out else None


# ---------------------------------------------------------------- 入口

def build_parser(command: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dl.py",
        description="media-dl：输入链接，自动识别平台并下载图片 / 视频。",
        epilog=(
            "命令：download（默认）| redl | rename | replace | probe | doctor\n"
            "示例：\n"
            "  dl.py \"https://x.com/user/status/123\"\n"
            "  dl.py redl 清单.txt\n"
            "  dl.py rename --apply ./下载目录\n"
            "  dl.py replace --quality 1080 ./twitter_foo_123.mp4\n"
            "  dl.py probe https://b23.tv/xxxx\n"
            "  dl.py doctor ./下载目录"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("items", nargs="*", help="链接 / 文件 / 目录（按命令解释）")
    parser.add_argument("--config", help="额外配置文件路径")
    parser.add_argument("--out", help="输出目录，覆盖配置")
    parser.add_argument("--quality", type=int, help="画质上限，如 720 / 1080")
    parser.add_argument("--cover", choices=["sidecar", "embed", "both", "none"],
                        help="封面处理方式，覆盖配置")
    parser.add_argument("-m", "--merge", action="store_true",
                        help="下载后把多张同尺寸图片横向拼成一张")
    parser.add_argument("--keep", action="store_true",
                        help="合并后保留原图（默认移到回收站）")
    parser.add_argument("--progress", choices=["bar", "none", "off"], default="bar",
                        help="进度条显示方式")
    parser.add_argument("--no-progress", action="store_true", help="关闭进度条")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不下载")
    parser.add_argument("--no-proxy", action="store_true", help="本次忽略代理，直连")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试信息")
    parser.add_argument("--overwrite", action="store_true",
                        help="目标存在时先备份再覆盖（默认跳过）")
    parser.add_argument("--from-file", action="append", metavar="FILE",
                        help="从文件读取 URL / ID（可重复）")
    parser.add_argument("--pattern", help="文件名模板 / 反向解析模板，如 {platform}_{1}_{2}")
    parser.add_argument("--platform", help="手动指定平台（redl 裸 id / probe 文件时用）")
    parser.add_argument("--apply", action="store_true",
                        help="rename / replace 真正执行（默认只预览）")
    parser.add_argument("--tag", help="replace 后给文件名加后缀，如 1080p")
    parser.add_argument("--print-config", action="store_true",
                        help="打印生效配置及来源后退出")
    parser.add_argument("--check-config", action="store_true",
                        help="只校验配置，退出码 0/1/2")
    parser.add_argument("--version", action="version", version=f"media-dl {VERSION}")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    command = "download"
    if raw and raw[0] in COMMANDS:
        command = raw.pop(0)

    parser = build_parser(command)
    args = parser.parse_args(raw)
    if args.no_progress:
        args.progress = "none"

    overrides: dict = {}
    if args.out:
        overrides["general.output_dir"] = args.out
    if args.quality is not None:
        overrides["quality.max_height"] = args.quality
    if args.cover:
        overrides["cover.mode"] = args.cover
    if args.overwrite:
        overrides["behavior.overwrite"] = True

    try:
        cfg = Config.load(args.config, overrides=overrides)
    except FileNotFoundError as exc:
        print(f"配置文件不存在：{exc}", file=sys.stderr)
        return 2

    if args.print_config:
        for line in cfg.effective_lines():
            print(line)
        return 0

    if args.check_config:
        errors = cfg.validate()
        if not cfg.config_files:
            print("没有找到 config.toml 或 config.example.toml", file=sys.stderr)
            return 2
        if errors:
            for error in errors:
                print(f"配置错误：{error}", file=sys.stderr)
            return 1
        print(f"配置通过（{', '.join(p.name for p in cfg.config_files)}）")
        return 0

    logger = setup_logger(cfg, args.verbose)

    if args.no_proxy:
        cfg.override_proxy("")
    elif cfg.proxy and not proxy_alive(cfg.proxy):
        logger.warning("代理 %s 连不上，本次改为直连", cfg.proxy)
        cfg.override_proxy("")

    first_run_notice(cfg, logger)

    lock_path = Path(os.path.expanduser(str(cfg.get(
        "general.lock_file", "~/.local/state/media-dl/.lock"))))
    write_commands = {"download", "redl"}
    if command in {"rename", "replace"}:
        write_commands.add(command if args.apply else "")

    locked = False
    if command in write_commands:
        if not acquire_lock(lock_path):
            logger.error("已有实例在运行（锁文件 %s）", lock_path)
            return 2
        locked = True

    started = time.time()
    try:
        if command == "download":
            return cmd_download(args, cfg, logger)
        if command == "redl":
            return cmd_redl(args, cfg, logger)
        if command == "rename":
            return cmd_rename(args, cfg, logger)
        if command == "replace":
            return cmd_replace(args, cfg, logger)
        if command == "probe":
            return cmd_probe(args, cfg, logger)
        if command == "doctor":
            return cmd_doctor(args, cfg, logger)
        logger.error("未知命令：%s", command)
        return 2
    finally:
        if locked:
            release_lock(lock_path)
        logger.debug("总用时 %.2fs", time.time() - started)


if __name__ == "__main__":
    raise SystemExit(main())
