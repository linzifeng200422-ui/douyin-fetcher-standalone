from datetime import datetime
from typing import Union


def parse_timestamp(timestamp: Union[int, str], fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    if isinstance(timestamp, str):
        timestamp = int(timestamp)
    return datetime.fromtimestamp(timestamp).strftime(fmt)


def format_size(bytes_size: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} TB"


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


# ============================================================
# 以下为本项目独有工具函数
# ============================================================

def sanitize_folder_name(value: str) -> str:
    """清理文件夹名中的特殊字符。"""
    import re
    safe = re.sub(r'[\\/:*?"<>| ]', "_", value or "未命名账号")
    return safe.strip("._") or "未命名账号"


def safe_int(value, default: int = 0) -> int:
    """安全的整数转换，失败返回默认值。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_positive_int(value) -> int | None:
    """将值转为正整数，非正数返回 None。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def collection_target_count(expected_count: int | None, count_limit: int | None) -> int | None:
    """计算采集目标数量。"""
    expected = _coerce_positive_int(expected_count)
    limit = _coerce_positive_int(count_limit)
    if limit is not None and expected is not None:
        return min(limit, expected)
    if limit is not None:
        return limit
    return expected


def collection_incomplete_reason(
    actual_count: int,
    *,
    expected_count: int | None,
    count_limit: int | None,
    has_more: bool = False,
) -> str:
    """判断作品列表是否完整，返回不完整原因。"""
    if count_limit is None and _coerce_positive_int(expected_count) is None:
        return f"无法获取主页作品总数，不能验证完整性；本次只拿到 {actual_count} 个"
    target = collection_target_count(expected_count, count_limit)
    if target is not None and actual_count < target:
        if expected_count:
            return f"作品列表不完整：主页显示 {expected_count} 个作品，本次只拿到 {actual_count} 个，目标至少 {target} 个"
        return f"作品列表不完整：目标 {target} 个，本次只拿到 {actual_count} 个"
    if count_limit is None and has_more:
        return f"作品列表分页仍显示 has_more=true，但本次只拿到 {actual_count} 个"
    return ""


def extract_author_nickname(aweme: dict, default: str = "未命名账号") -> str:
    """从 aweme 数据中提取作者昵称。"""
    author = aweme.get("author") if isinstance(aweme.get("author"), dict) else {}
    return (
        author.get("nickname")
        or aweme.get("nickname")
        or aweme.get("author_name")
        or default
    )

