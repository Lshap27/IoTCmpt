"""时间序列化工具。

数据库中的时间统一存 naive UTC；对外输出时必须带时区偏移，
否则浏览器 `new Date()` 会把无偏移的 ISO 字符串按本地时区解析，
导致所有展示时间偏移一个时区差。
"""

from __future__ import annotations

from datetime import UTC, datetime


def iso_utc(value: datetime | None) -> str | None:
    """把（naive 视为 UTC 的）datetime 序列化为带 +00:00 偏移的 ISO 字符串。"""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()
