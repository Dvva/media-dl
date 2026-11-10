"""图片横向拼接（合并推文/笔记里的多图）。

规则：
  - 少于 2 张不合并
  - 尺寸（宽高）不完全一致就不合并，交回调用方保留原图
  - 从左到右横向排列
"""

from __future__ import annotations

from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def pick_images(files: list[Path]) -> list[Path]:
    """从下载结果里挑出图片，保持原有顺序。"""
    return [f for f in files if f.suffix.lower() in IMAGE_SUFFIXES]


def can_merge(files: list[Path]) -> tuple[bool, str]:
    """判断能否合并，返回 (是否可以, 原因)。"""
    if len(files) < 2:
        return False, "图片不足 2 张"
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        return False, "缺少 Pillow（pkg install python-pillow）"

    sizes = set()
    for f in files:
        try:
            from PIL import Image

            with Image.open(f) as im:
                sizes.add(im.size)
        except Exception as exc:  # noqa: BLE001
            return False, f"读图失败 {f.name}: {exc}"
    if len(sizes) != 1:
        detail = "、".join(f"{w}x{h}" for w, h in sorted(sizes))
        return False, f"尺寸不一致（{detail}），不合并"
    return True, ""


def merge_horizontal(files: list[Path], out_path: Path, *, quality: int = 95) -> bool:
    """从左到右横向拼接，成功返回 True。"""
    if not files:
        return False
    from PIL import Image

    images = []
    try:
        for f in files:
            im = Image.open(f)
            images.append(im.convert("RGB"))
        width, height = images[0].size
        canvas = Image.new("RGB", (width * len(images), height), "white")
        for index, im in enumerate(images):
            canvas.paste(im, (index * width, 0))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        suffix = out_path.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            canvas.save(out_path, quality=quality)
        else:
            canvas.save(out_path)
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        for im in images:
            try:
                im.close()
            except Exception:  # noqa: BLE001
                pass
