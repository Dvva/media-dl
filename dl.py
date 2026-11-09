#!/usr/bin/env python3
"""media-dl —— 一个链接，自动识别平台并下载图片 / 视频。

用法：
    python dl.py "https://x.com/user/status/123"
    python dl.py "https://www.xiaohongshu.com/explore/xxx"
    python dl.py "1.23 复制打开抖音 https://v.douyin.com/xxxx/"
    python dl.py --cover embed --quality 1080 "https://b23.tv/xxxx"
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from core import detect                                  # noqa: E402
from core.config import Config                           # noqa: E402
from core.downloader import save                         # noqa: E402
from core.finalize import finalize                       # noqa: E402
from core.http import load_netscape_cookies, make_session, proxy_alive  # noqa: E402
from core.result import Status                           # noqa: E402
from platforms import douyin, gallerydl_backend, xhs, ytdlp_backend  # noqa: E402

YTDLP_PLATFORMS = {"tiktok", "bilibili", "telegram"}
GALLERY_PLATFORMS = {"twitter"}


# ---------------------------------------------------------------- 日志

def setup_logger(cfg) -> logging.Logger:
    logger = logging.getLogger("media-dl")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    log_dir = cfg.get("general.log_dir")
    if log_dir:
        path = Path(os.path.expanduser(str(log_dir)))
        path.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path / time.strftime("media-dl-%Y%m%d.log"),
                                      encoding="utf-8")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
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


# ---------------------------------------------------------------- 主流程

def run(text: str, cfg, logger, *, cover: str | None, quality: int | None,
        out: Path | None, dry_run: bool) -> Status:
    url = detect.extract_url(text) or text.strip()
    platform, final = detect.detect(url)
    if not platform:
        logger.error("无法识别平台：%s", url)
        return Status.SKIP_UNSUPPORTED
    if not cfg.enabled(platform):
        logger.error("平台 %s 未启用（config.toml 的 platforms.enabled）", platform)
        return Status.SKIP_UNSUPPORTED

    logger.info("平台=%s  链接=%s", platform, final)
    if dry_run:
        logger.info("[dry-run] 只识别不下载")
        return Status.OK

    delay = cfg.delay(platform)
    if delay > 0:
        time.sleep(delay)

    if platform in GALLERY_PLATFORMS:
        extraction = gallerydl_backend.extract(final, platform, cfg, log=logger.info)
    elif platform in YTDLP_PLATFORMS:
        extraction = ytdlp_backend.extract(final, platform, cfg,
                                           max_height=quality, log=logger.info)
    elif platform == "douyin":
        extraction = douyin.extract(final, cfg, log=logger.info)
    elif platform == "xhs":
        extraction = xhs.extract(final, cfg, log=logger.info)
    else:
        logger.error("平台 %s 还没有实现", platform)
        return Status.SKIP_UNSUPPORTED

    content = extraction.content
    if content.status is not Status.OK:
        logger.warning("跳过 [%s] %s", content.status.value, content.message)
        return content.status

    if extraction.mode == "local":
        cookies = load_netscape_cookies(cfg.cookie_file(platform))
        session = make_session(cfg.proxy, cookies=cookies)
        status, files = finalize(extraction, cfg, session, output_dir=out,
                                 cover_mode=cover, log=logger.info)
    else:
        cookies = load_netscape_cookies(cfg.cookie_file(platform))
        session = make_session(cfg.proxy, cookies=cookies)
        status, files = save(content, session=session, cfg=cfg, output_dir=out,
                             cover_mode=cover, log=logger.info)

    logger.info("完成 [%s] 共 %d 个文件", status.value, len(files))
    return status


def main() -> int:
    parser = argparse.ArgumentParser(
        description="输入一个链接，自动识别平台并下载其中的图片 / 视频")
    parser.add_argument("url", help="链接，或带链接的分享文案")
    parser.add_argument("--config", help="额外配置文件路径（覆盖 config.toml）")
    parser.add_argument("--out", help="输出目录，覆盖配置")
    parser.add_argument("--quality", type=int, help="画质上限，如 720 / 1080")
    parser.add_argument("--cover", choices=["sidecar", "embed", "both", "none"],
                        help="封面处理方式，覆盖配置")
    parser.add_argument("--dry-run", action="store_true", help="只识别平台，不下载")
    parser.add_argument("--no-proxy", action="store_true", help="本次忽略代理，直连")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试信息")
    args = parser.parse_args()

    cfg = Config.load(args.config)
    logger = setup_logger(cfg)
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    if args.no_proxy:
        cfg.override_proxy("")
    elif cfg.proxy and not proxy_alive(cfg.proxy):
        logger.warning("代理 %s 连不上，本次改为直连", cfg.proxy)
        cfg.override_proxy("")

    lock = Path(os.path.expanduser(str(cfg.get("general.lock_file", "~/media-dl.lock"))))
    if not acquire_lock(lock):
        logger.error("已有实例在运行（锁文件 %s）", lock)
        return 2

    try:
        out = Path(os.path.expanduser(args.out)) if args.out else None
        status = run(args.url, cfg, logger, cover=args.cover, quality=args.quality,
                     out=out, dry_run=args.dry_run)
        return 0 if status is Status.OK else 1
    finally:
        release_lock(lock)


if __name__ == "__main__":
    raise SystemExit(main())
