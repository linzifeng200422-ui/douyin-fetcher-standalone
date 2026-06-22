# -*- coding: utf-8 -*-
"""抖音下载器 - dy-downloader (jiji262/douyin-downloader) 适配后端。"""
from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backends.venv_manager import (
    ensure_external_dirs,
    ensure_dy_downloader_python,
    secure_write_text,
    cleanup_paths,
    run_supervised,
    ExternalBackendError,
    RUNTIME_DIR,
    DY_DOWNLOADER_DIR,
)

@dataclass
class DyDownloaderRunResult:
  output_dir: Path
  video_files: list[Path]
  stdout: str
  stderr: str


def dy_downloader_quality(video_quality: str) -> str:
  if video_quality == "original":
    return "highest"
  if video_quality in ("balanced", "resolution"):
    return "1440p"
  if video_quality == "bitrate":
    return "highest"
  if video_quality == "h264":
    return "1080p"
  return "1440p"


def build_dy_downloader_config(
  *,
  url: str,
  output_dir: Path,
  count_limit: int | None,
  thread: int = 5,
  video_quality: str = "balanced",
) -> dict[str, Any]:
  post_count = int(count_limit or 0)
  return {
    "link": [url],
    "path": str(output_dir),
    "music": False,
    "cover": False,
    "avatar": False,
    "json": True,
    "folderstyle": True,
    "filename_template": "{id}",
    "folder_template": "{id}",
    "author_dir": "nickname_uid",
    "download_pinned": True,
    "mode": ["post"],
    "number": {
      "post": post_count,
      "like": 0,
      "allmix": 0,
      "mix": 0,
      "music": 0,
      "collect": 0,
      "collectmix": 0,
    },
    "increase": {
      "post": False,
      "like": False,
      "allmix": False,
      "mix": False,
      "music": False,
    },
    "thread": int(thread or 5),
    "retry_times": 3,
    "rate_limit": 2,
    "proxy": "",
    "database": False,
    "progress": {"quiet_logs": True},
    "browser_fallback": {
      "enabled": True,
      "headless": False,
      "max_scrolls": 240,
      "idle_rounds": 8,
      "wait_timeout_seconds": 600,
    },
    "transcript": {"enabled": False},
    "comments": {"enabled": False},
    "notifications": {"enabled": False, "providers": []},
    "video_quality": dy_downloader_quality(video_quality),
  }


def scan_video_files(root: Path) -> list[Path]:
  if not root.exists():
    return []
  return sorted(
    path for path in root.rglob("*")
    if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".m4v", ".flv"}
  )


def run_dy_downloader_backend(
  *,
  url: str,
  output_dir: Path,
  count_limit: int | None,
  cookie_str: str,
  thread: int = 5,
  video_quality: str = "balanced",
  auto_install: bool = True,
) -> DyDownloaderRunResult:
  if not cookie_str:
    raise ExternalBackendError("dy-downloader 后端需要有效 cookie.txt；请先运行 get_cookie.py 扫码登录。")

  ensure_external_dirs()
  python_bin = ensure_dy_downloader_python(auto_install=auto_install)
  output_dir = output_dir.resolve()
  output_dir.mkdir(parents=True, exist_ok=True)

  config_path = RUNTIME_DIR / f"dy-downloader-config-{os.getpid()}.json"
  cleanup_targets = [config_path]
  config = build_dy_downloader_config(
    url=url,
    output_dir=output_dir,
    count_limit=count_limit,
    thread=thread,
    video_quality=video_quality,
  )

  env = os.environ.copy()
  env["DOUYIN_COOKIE"] = cookie_str
  env["DOUYIN_PATH"] = str(output_dir)
  env["DOUYIN_THREAD"] = str(int(thread or 5))

  try:
    secure_write_text(config_path, json.dumps(config, ensure_ascii=False, indent=2))
    dy_downloader_dir = DY_DOWNLOADER_DIR.resolve()
    cmd = [
      str(python_bin),
      str(dy_downloader_dir / "run.py"),
      "-c",
      str(config_path.resolve()),
    ]
    result = run_supervised(
      cmd,
      cwd=dy_downloader_dir,
      cookie_str=cookie_str,
      env=env,
    )
    if result.returncode != 0:
      details = result.stderr.strip() or result.stdout.strip()
      raise ExternalBackendError(f"dy-downloader 下载失败: {details}")
    return DyDownloaderRunResult(
      output_dir=output_dir,
      video_files=scan_video_files(output_dir),
      stdout=result.stdout,
      stderr=result.stderr,
    )
  finally:
    cleanup_paths(cleanup_targets)
