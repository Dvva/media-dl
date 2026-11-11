"""真实链接冒烟测试（需要网络 / 代理 / 对应平台 cookie）。

用法：
    python tests/smoke_links.py --probe
    python tests/smoke_links.py --download --limit 2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import detect, metadata                     # noqa: E402
from core.config import Config                        # noqa: E402
from core.http import proxy_alive                     # noqa: E402
from core.result import Status                        # noqa: E402

LINKS = Path(__file__).resolve().parent / "data" / "links.txt"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true", help="只取元数据（默认）")
    parser.add_argument("--download", action="store_true", help="真的下载")
    parser.add_argument("--limit", type=int, default=0, help="最多处理几条")
    parser.add_argument("--no-proxy", action="store_true")
    args = parser.parse_args()

    cfg = Config.load()
    if args.no_proxy:
        cfg.override_proxy("")
    elif cfg.proxy and not proxy_alive(cfg.proxy):
        print(f"代理连不上，改直连：{cfg.proxy}")
        cfg.override_proxy("")

    links = []
    for line in LINKS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            links.append(line)
    if args.limit:
        links = links[: args.limit]

    ok = failed = 0
    for index, url in enumerate(links, 1):
        platform = detect.platform_of(url)
        print(f"[{index}/{len(links)}] {platform} {url}")
        content = metadata.probe(url, platform, cfg, log=print)
        if content.status is not Status.OK:
            print(f"  失败：{content.status.value} {content.message}")
            failed += 1
            continue
        print(f"  id={content.id} author={content.author} nickname={content.nickname}")
        print(f"  time={content.timestamp} title={content.title[:50]}")

        if args.download:
            import dl

            status, files, _ = dl._download(
                url, cfg, dl.logging.getLogger("smoke"),
                cover=None, quality=None, out=None, progress="bar",
            )
            print(f"  下载：{status.value}，{len(files)} 个文件")
            failed += 0 if status is Status.OK else 1
        ok += 1

    print(f"完成：成功 {ok}，失败 {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
