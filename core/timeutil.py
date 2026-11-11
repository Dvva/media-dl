"""时间解析：各平台 / 各工具的时间字段格式不统一，这里统一成时间戳。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))


def parse_timestamp(value) -> float | None:
    """把 int / float / 秒或毫秒时间戳 / ISO 字符串 / YYYYMMDD 转成秒级时间戳。"""
    if value is None or value == "":
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        number = float(value)
        # 毫秒时间戳（小红书常见）
        if number > 10_000_000_000:
            number /= 1000.0
        if number <= 0:
            return None
        return number

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=TZ)
        return value.timestamp()

    text = str(value).strip()
    if not text:
        return None

    if text.isdigit():
        return parse_timestamp(int(text))

    # 2026-11-12T02:19:30+08:00 / 2026-11-12 02:19:30 / 2026-11-12
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.timestamp()
    except ValueError:
        pass

    for fmt in ("%Y%m%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y%m%d_%H%M"):
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=TZ)
            return dt.timestamp()
        except ValueError:
            continue

    return None
