"""Shared helpers for extracting normalized fields from raw Douyin aweme payloads.

These helpers centralize the payload-shape dereferencing so that callers across
downloaders (``downloader_base``, ``music_downloader``, future strategies, …)
all agree on how to pull fields like ``author.sec_uid`` out of the various
aweme dict shapes returned by the upstream API.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional


def extract_author_sec_uid(aweme: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Return ``aweme["author"]["sec_uid"]`` or ``None`` if unavailable.

    Defensive against every shape variation observed so far:
      * ``aweme`` itself being ``None`` or not a mapping
      * ``aweme["author"]`` being missing, ``None``, or not a mapping
      * ``sec_uid`` being missing, ``None``, or an empty / whitespace string
        (all collapse to ``None`` so downstream consumers can treat NULL and
        empty-string identically).
    """

    if not isinstance(aweme, Mapping):
        return None
    author = aweme.get("author")
    if not isinstance(author, Mapping):
        return None
    sec_uid = author.get("sec_uid")
    if not isinstance(sec_uid, str):
        return None
    sec_uid = sec_uid.strip()
    return sec_uid or None


# ============================================================
# 以下为 douyin-fetcher-standalone 独有元数据写入逻辑
# ============================================================

from pathlib import Path

def write_meta_file(video_dir: Path, aweme: dict[str, Any], nickname: str) -> None:
  aweme_id = aweme.get("aweme_id") or aweme.get("video_id") or "unknown"
  desc = aweme.get("desc") or aweme.get("title") or "无标题"
  stats = aweme.get("statistics", {}) if isinstance(aweme.get("statistics"), dict) else {}
  raw_play = stats.get("play_count", 0) or 0
  try:
    play_w = round(float(raw_play) / 10000.0, 2) if float(raw_play) > 0 else 0.0
  except Exception:
    play_w = 0.0
  meta_text = (
    f"## 视频信息\n"
    f"标题：{desc}\n"
    f"作者：{nickname}\n"
    f"视频ID：{aweme_id}\n\n"
    f"## 数据\n"
    f"播放：{play_w}w\n"
    f"点赞：{stats.get('digg_count', 0)}\n"
    f"评论数：{stats.get('comment_count', 0)}\n"
    f"转发数：{stats.get('share_count', 0)}\n\n"
  )
  (video_dir / "meta.md").write_text(meta_text, encoding="utf-8")

