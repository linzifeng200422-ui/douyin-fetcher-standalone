#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""External downloader/fetcher adapters for douyin-fetcher-standalone.

The adapters keep sensitive cookies out of command-line arguments and bind
child-process lifetime to the parent process.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("douyin-fetcher-standalone.external")

EXTERNAL_DIR = Path(".external")
RUNTIME_DIR = EXTERNAL_DIR / "runtime"
F2_VENV_DIR = EXTERNAL_DIR / "venv-f2"
YT_DLP_ARCHIVE = EXTERNAL_DIR / "yt-dlp-archive.txt"


class ExternalBackendError(RuntimeError):
  """Raised when an external backend cannot complete its work."""


@dataclass
class F2FetchResult:
  aweme_list: list[dict[str, Any]]
  pages: int
  sec_user_id: str
  expected_count: int | None = None
  nickname: str = ""
  has_more: bool = False
  next_cursor: int = 0
  page_diagnostics: list[dict[str, Any]] = field(default_factory=list)
  source: str = "f2"


@dataclass
class F2DetailResult:
  aweme_list: list[dict[str, Any]]
  errors: list[dict[str, str]]
  requested: int
  source: str = "f2-detail"


@dataclass
class YtDlpItem:
  media_id: str
  title: str
  uploader: str
  extractor: str
  webpage_url: str
  audio_path: Path
  info: dict[str, Any]
  temporary_root: Path


@dataclass
class YtDlpProbeItem:
  media_id: str
  title: str
  uploader: str
  extractor: str
  webpage_url: str


def ensure_external_dirs() -> None:
  RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def secure_write_text(path: Path, text: str) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(text, encoding="utf-8")
  if os.name != "nt":
    try:
      os.chmod(path, 0o600)
    except OSError as exc:
      logger.warning("无法设置临时敏感文件权限 %s: %s", path, exc)


def cleanup_paths(paths: list[Path]) -> None:
  for path in paths:
    try:
      if path.is_dir():
        shutil.rmtree(path)
      elif path.exists():
        path.unlink()
    except OSError as exc:
      logger.warning("清理临时文件失败 %s: %s", path, exc)


def parse_cookie_header(cookie_str: str) -> dict[str, str]:
  cookies: dict[str, str] = {}
  for part in (cookie_str or "").split(";"):
    if "=" not in part:
      continue
    key, value = part.split("=", 1)
    key = key.strip()
    value = value.strip()
    if key:
      cookies[key] = value
  return cookies


def redact_cookie_values(text: str, cookie_str: str) -> str:
  if not text or not cookie_str:
    return text
  redacted = text.replace(cookie_str, "[COOKIE_REDACTED]")
  for value in parse_cookie_header(cookie_str).values():
    if len(value) >= 8:
      redacted = redacted.replace(value, "[COOKIE_VALUE_REDACTED]")
  return redacted


def summarize_backend_error(details: str) -> str:
  compact = " ".join((details or "").split())
  if (
    "请求响应内容为空" in compact
    or "cookie" in compact.lower()
    or "unauthorized" in compact.lower()
  ):
    return "F2 返回空响应，通常是 cookie.txt 失效或登录态变成游客态。请重新运行 get_cookie.py 扫码登录后再试。"
  if len(compact) > 600:
    return compact[:600] + "..."
  return compact or "unknown error"


def venv_python_path(venv_dir: Path) -> Path:
  if os.name == "nt":
    return venv_dir / "Scripts" / "python.exe"
  return venv_dir / "bin" / "python"


def python_can_import(python_bin: Path, module_name: str) -> bool:
  try:
    result = subprocess.run(
      [str(python_bin), "-c", f"import {module_name}"],
      capture_output=True,
      text=True,
      timeout=20,
    )
    return result.returncode == 0
  except Exception:
    return False


def ensure_f2_python(auto_install: bool = True) -> Path:
  """Return a Python executable that can import f2.

  If f2 is missing and auto_install is true, install it into .external/venv-f2.
  """
  candidates = [Path(sys.executable), venv_python_path(F2_VENV_DIR)]
  for candidate in candidates:
    if candidate.exists() and python_can_import(candidate, "f2"):
      return candidate

  if not auto_install:
    raise ExternalBackendError("未检测到可导入 f2 的 Python 环境。")

  if sys.version_info < (3, 10):
    raise ExternalBackendError("F2 需要 Python >= 3.10；当前 Python 版本过低。")

  ensure_external_dirs()
  logger.info("未检测到 F2，正在创建隔离环境: %s", F2_VENV_DIR)
  subprocess.run([sys.executable, "-m", "venv", str(F2_VENV_DIR)], check=True)
  python_bin = venv_python_path(F2_VENV_DIR)
  pip_cmd = [str(python_bin), "-m", "pip", "install", "f2"]
  logger.info("正在隔离环境安装 F2，此步骤可能需要数分钟...")
  subprocess.run(pip_cmd, check=True)

  if not python_can_import(python_bin, "f2"):
    raise ExternalBackendError("F2 安装完成但仍无法导入。")
  return python_bin


def terminate_process_group(proc: subprocess.Popen) -> None:
  if proc.poll() is not None:
    return
  try:
    if os.name != "nt":
      os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    else:
      proc.terminate()
    proc.wait(timeout=10)
  except Exception:
    try:
      if os.name != "nt":
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
      else:
        proc.kill()
    except Exception:
      pass


def run_supervised(
  cmd: list[str],
  *,
  cwd: Path | None = None,
  cookie_str: str = "",
  timeout: int | None = None,
) -> subprocess.CompletedProcess:
  start_new_session = os.name != "nt"
  proc = subprocess.Popen(
    cmd,
    cwd=str(cwd) if cwd else None,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    start_new_session=start_new_session,
  )
  try:
    stdout, stderr = proc.communicate(timeout=timeout)
  except KeyboardInterrupt:
    terminate_process_group(proc)
    raise
  except subprocess.TimeoutExpired:
    terminate_process_group(proc)
    raise ExternalBackendError(f"外部命令超时: {cmd[0]}")

  stdout = redact_cookie_values(stdout or "", cookie_str)
  stderr = redact_cookie_values(stderr or "", cookie_str)
  return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


F2_FETCHER_CODE = r'''
import asyncio
import json
import sys
import traceback
from pathlib import Path

from f2.apps.douyin.handler import DouyinHandler


async def main():
    config_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    cookie = cfg.get("cookie", "")
    sec_user_id = cfg["sec_user_id"]
    count_limit = int(cfg.get("count_limit") or 0)
    page_counts = int(cfg.get("page_counts") or 20)
    timeout = int(cfg.get("timeout") or 10)
    max_retries = int(cfg.get("max_retries") or 3)

    kwargs = {
        "headers": {
            "User-Agent": cfg.get("user_agent", ""),
            "Referer": "https://www.douyin.com/",
        },
        "proxies": {"http://": None, "https://": None},
        "timeout": timeout,
        "max_retries": max_retries,
        "cookie": cookie,
    }

    result = {
        "ok": True,
        "sec_user_id": sec_user_id,
        "pages": 0,
        "expected_count": None,
        "nickname": "",
        "has_more": False,
        "next_cursor": 0,
        "page_diagnostics": [],
        "aweme_list": [],
        "errors": [],
    }
    seen = set()
    max_counts = count_limit if count_limit > 0 else None

    try:
        handler = DouyinHandler(kwargs)
        try:
            profile = await handler.fetch_user_profile(sec_user_id)
            raw_profile = profile._to_raw() if hasattr(profile, "_to_raw") else {}
            expected_count = getattr(profile, "aweme_count", None)
            nickname = getattr(profile, "nickname", None)
            if expected_count is None and isinstance(raw_profile, dict):
                expected_count = (raw_profile.get("user") or {}).get("aweme_count")
            if nickname is None and isinstance(raw_profile, dict):
                nickname = (raw_profile.get("user") or {}).get("nickname")
            if expected_count is not None:
                result["expected_count"] = int(expected_count)
            if nickname:
                result["nickname"] = str(nickname)
        except Exception as exc:
            result["errors"].append(f"profile fetch failed: {exc}")

        async for page in handler.fetch_user_post_videos(
            sec_user_id,
            0,
            0,
            page_counts,
            max_counts,
        ):
            result["pages"] += 1
            raw = page._to_raw() if hasattr(page, "_to_raw") else {}
            has_more = bool(raw.get("has_more")) if isinstance(raw, dict) else False
            max_cursor = int(raw.get("max_cursor") or 0) if isinstance(raw, dict) else 0
            result["has_more"] = has_more
            result["next_cursor"] = max_cursor
            page_items = raw.get("aweme_list") if isinstance(raw, dict) else []
            result["page_diagnostics"].append({
                "page": result["pages"],
                "items": len(page_items) if isinstance(page_items, list) else 0,
                "has_more": has_more,
                "max_cursor": max_cursor,
                "status_code": raw.get("status_code") if isinstance(raw, dict) else None,
            })
            if not page_items:
                continue
            for aweme in page_items:
                if not isinstance(aweme, dict):
                    continue
                aweme_id = str(aweme.get("aweme_id") or aweme.get("video_id") or "")
                if aweme_id and aweme_id in seen:
                    continue
                if aweme_id:
                    seen.add(aweme_id)
                result["aweme_list"].append(aweme)
                if count_limit > 0 and len(result["aweme_list"]) >= count_limit:
                    break
            if count_limit > 0 and len(result["aweme_list"]) >= count_limit:
                break
    except Exception as exc:
        result["ok"] = False
        result["errors"].append(str(exc))
        result["traceback"] = traceback.format_exc()

    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not result["ok"]:
        sys.exit(2)


asyncio.run(main())
'''


F2_DETAIL_FETCHER_CODE = r'''
import asyncio
import json
import sys
import traceback
from pathlib import Path

from f2.apps.douyin.handler import DouyinHandler


async def main():
    config_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    cookie = cfg.get("cookie", "")
    aweme_ids = [str(item) for item in cfg.get("aweme_ids", []) if str(item).strip()]
    sec_user_id = str(cfg.get("sec_user_id") or "")
    timeout = int(cfg.get("timeout") or 10)
    max_retries = int(cfg.get("max_retries") or 3)

    kwargs = {
        "headers": {
            "User-Agent": cfg.get("user_agent", ""),
            "Referer": "https://www.douyin.com/",
        },
        "proxies": {"http://": None, "https://": None},
        "timeout": timeout,
        "max_retries": max_retries,
        "cookie": cookie,
    }

    result = {
        "ok": True,
        "requested": len(aweme_ids),
        "aweme_list": [],
        "errors": [],
    }
    seen = set()

    try:
        handler = DouyinHandler(kwargs)

        async def _noop_notification(*args, **kwargs):
            return None

        handler.enable_bark = False
        handler._send_bark_notification = _noop_notification

        for aweme_id in aweme_ids:
            if aweme_id in seen:
                continue
            seen.add(aweme_id)
            try:
                detail = await handler.fetch_one_video(aweme_id)
                raw = detail._to_raw() if hasattr(detail, "_to_raw") else {}
                aweme = raw.get("aweme_detail") if isinstance(raw, dict) else None
                if not isinstance(aweme, dict):
                    result["errors"].append({"aweme_id": aweme_id, "error": "missing aweme_detail"})
                    continue
                author = aweme.get("author") if isinstance(aweme.get("author"), dict) else {}
                detail_sec_uid = str(author.get("sec_uid") or "")
                if sec_user_id and detail_sec_uid and detail_sec_uid != sec_user_id:
                    result["errors"].append({
                        "aweme_id": aweme_id,
                        "error": f"author sec_uid mismatch: {detail_sec_uid}",
                    })
                    continue
                result["aweme_list"].append(aweme)
            except Exception as exc:
                result["errors"].append({"aweme_id": aweme_id, "error": str(exc)})
    except Exception as exc:
        result["ok"] = False
        result["errors"].append({"aweme_id": "", "error": str(exc)})
        result["traceback"] = traceback.format_exc()

    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not result["ok"]:
        sys.exit(2)


asyncio.run(main())
'''


def fetch_user_posts_with_f2(
  *,
  sec_user_id: str,
  count_limit: int | None,
  cookie_str: str,
  user_agent: str,
  auto_install: bool = True,
  page_counts: int = 20,
) -> F2FetchResult:
  if not cookie_str:
    raise ExternalBackendError("F2 后端需要有效 cookie.txt；请先运行 get_cookie.py 扫码登录。")

  ensure_external_dirs()
  python_bin = ensure_f2_python(auto_install=auto_install)

  input_path = RUNTIME_DIR / f"f2-input-{os.getpid()}.json"
  output_path = RUNTIME_DIR / f"f2-output-{os.getpid()}.json"
  script_path = RUNTIME_DIR / f"f2-fetcher-{os.getpid()}.py"
  cleanup_targets = [input_path, output_path, script_path]

  payload = {
    "sec_user_id": sec_user_id,
    "count_limit": count_limit or 0,
    "page_counts": page_counts,
    "cookie": cookie_str,
    "user_agent": user_agent,
  }

  try:
    secure_write_text(input_path, json.dumps(payload, ensure_ascii=False, indent=2))
    secure_write_text(script_path, F2_FETCHER_CODE)
    cmd = [str(python_bin), str(script_path), str(input_path), str(output_path)]
    result = run_supervised(cmd, cookie_str=cookie_str)
    if result.returncode != 0:
      details = result.stderr.strip() or result.stdout.strip()
      raise ExternalBackendError(f"F2 作品列表抓取失败: {summarize_backend_error(details)}")
    if not output_path.is_file():
      raise ExternalBackendError("F2 未生成作品列表输出。")
    data = json.loads(output_path.read_text(encoding="utf-8"))
    if not data.get("ok"):
      errors = "; ".join(data.get("errors") or ["unknown error"])
      raise ExternalBackendError(f"F2 作品列表抓取失败: {errors}")
    aweme_list = data.get("aweme_list") or []
    expected_count = data.get("expected_count")
    try:
      expected_count = int(expected_count) if expected_count is not None else None
    except (TypeError, ValueError):
      expected_count = None
    return F2FetchResult(
      aweme_list=[item for item in aweme_list if isinstance(item, dict)],
      pages=int(data.get("pages") or 0),
      sec_user_id=sec_user_id,
      expected_count=expected_count,
      nickname=str(data.get("nickname") or ""),
      has_more=bool(data.get("has_more")),
      next_cursor=int(data.get("next_cursor") or 0),
      page_diagnostics=[
        item for item in data.get("page_diagnostics", []) if isinstance(item, dict)
      ],
    )
  finally:
    cleanup_paths(cleanup_targets)


def fetch_aweme_details_with_f2(
  *,
  aweme_ids: list[str],
  sec_user_id: str,
  cookie_str: str,
  user_agent: str,
  auto_install: bool = True,
) -> F2DetailResult:
  clean_ids = []
  seen = set()
  for aweme_id in aweme_ids:
    value = str(aweme_id or "").strip()
    if not value or value in seen:
      continue
    seen.add(value)
    clean_ids.append(value)
  if not clean_ids:
    return F2DetailResult(aweme_list=[], errors=[], requested=0)
  if not cookie_str:
    raise ExternalBackendError("F2 detail 回补需要有效 cookie.txt；请先运行 get_cookie.py 扫码登录。")

  ensure_external_dirs()
  python_bin = ensure_f2_python(auto_install=auto_install)

  input_path = RUNTIME_DIR / f"f2-detail-input-{os.getpid()}.json"
  output_path = RUNTIME_DIR / f"f2-detail-output-{os.getpid()}.json"
  script_path = RUNTIME_DIR / f"f2-detail-fetcher-{os.getpid()}.py"
  cleanup_targets = [input_path, output_path, script_path]

  payload = {
    "aweme_ids": clean_ids,
    "sec_user_id": sec_user_id,
    "cookie": cookie_str,
    "user_agent": user_agent,
  }

  try:
    secure_write_text(input_path, json.dumps(payload, ensure_ascii=False, indent=2))
    secure_write_text(script_path, F2_DETAIL_FETCHER_CODE)
    cmd = [str(python_bin), str(script_path), str(input_path), str(output_path)]
    result = run_supervised(cmd, cookie_str=cookie_str)
    if result.returncode != 0:
      details = result.stderr.strip() or result.stdout.strip()
      raise ExternalBackendError(f"F2 detail 回补失败: {summarize_backend_error(details)}")
    if not output_path.is_file():
      raise ExternalBackendError("F2 detail 回补未生成输出。")
    data = json.loads(output_path.read_text(encoding="utf-8"))
    if not data.get("ok"):
      errors = data.get("errors") or [{"error": "unknown error"}]
      raise ExternalBackendError(f"F2 detail 回补失败: {errors}")
    return F2DetailResult(
      aweme_list=[
        item for item in data.get("aweme_list", []) if isinstance(item, dict)
      ],
      errors=[
        item for item in data.get("errors", []) if isinstance(item, dict)
      ],
      requested=int(data.get("requested") or len(clean_ids)),
    )
  finally:
    cleanup_paths(cleanup_targets)


def write_netscape_cookie_file(cookie_str: str, path: Path, domain: str = ".douyin.com") -> None:
  lines = [
    "# Netscape HTTP Cookie File",
    "# Generated by douyin-fetcher-standalone.",
  ]
  for key, value in parse_cookie_header(cookie_str).items():
    safe_value = value.replace("\n", "").replace("\r", "")
    lines.append(f"{domain}\tTRUE\t/\tTRUE\t0\t{key}\t{safe_value}")
  secure_write_text(path, "\n".join(lines) + "\n")


def run_ytdlp_audio(
  *,
  url: str,
  cookie_str: str = "",
  use_douyin_cookie: bool = False,
) -> list[YtDlpItem]:
  yt_dlp_bin = shutil.which("yt-dlp")
  if not yt_dlp_bin:
    raise ExternalBackendError("未检测到 yt-dlp，请先安装 yt-dlp 或改用 legacy 后端。")

  ensure_external_dirs()
  run_dir = RUNTIME_DIR / f"yt-dlp-{os.getpid()}"
  cookie_path = RUNTIME_DIR / f"yt-dlp-cookies-{os.getpid()}.txt"
  cleanup_targets = [cookie_path]
  run_dir.mkdir(parents=True, exist_ok=True)

  output_template = "%(extractor_key|external)s/%(id)s/%(id)s.%(ext)s"
  cmd = [
    yt_dlp_bin,
    "--ignore-errors",
    "--no-progress",
    "--write-info-json",
    "--download-archive",
    str(YT_DLP_ARCHIVE),
    "--extract-audio",
    "--audio-format",
    "mp3",
    "--paths",
    str(run_dir),
    "--output",
    output_template,
    url,
  ]
  if cookie_str and use_douyin_cookie:
    write_netscape_cookie_file(cookie_str, cookie_path)
    cmd[1:1] = ["--cookies", str(cookie_path)]

  try:
    result = run_supervised(cmd, cookie_str=cookie_str)
    if result.returncode != 0:
      details = result.stderr.strip() or result.stdout.strip()
      raise ExternalBackendError(f"yt-dlp 下载失败: {details}")
    return scan_ytdlp_outputs(run_dir)
  finally:
    cleanup_paths(cleanup_targets)


def probe_ytdlp_items(
  *,
  url: str,
  cookie_str: str = "",
  use_douyin_cookie: bool = False,
) -> list[YtDlpProbeItem]:
  yt_dlp_bin = shutil.which("yt-dlp")
  if not yt_dlp_bin:
    raise ExternalBackendError("未检测到 yt-dlp，请先安装 yt-dlp 或改用 legacy 后端。")

  ensure_external_dirs()
  cookie_path = RUNTIME_DIR / f"yt-dlp-probe-cookies-{os.getpid()}.txt"
  cleanup_targets = [cookie_path]
  cmd = [
    yt_dlp_bin,
    "--ignore-errors",
    "--no-progress",
    "--flat-playlist",
    "--dump-json",
    url,
  ]
  if cookie_str and use_douyin_cookie:
    write_netscape_cookie_file(cookie_str, cookie_path)
    cmd[1:1] = ["--cookies", str(cookie_path)]

  try:
    result = run_supervised(cmd, cookie_str=cookie_str)
    if result.returncode != 0:
      details = result.stderr.strip() or result.stdout.strip()
      raise ExternalBackendError(f"yt-dlp 列表探测失败: {details}")
    items: list[YtDlpProbeItem] = []
    for line in result.stdout.splitlines():
      line = line.strip()
      if not line:
        continue
      try:
        info = json.loads(line)
      except json.JSONDecodeError:
        continue
      media_id = str(info.get("id") or info.get("url") or "").strip()
      if not media_id:
        continue
      items.append(
        YtDlpProbeItem(
          media_id=media_id,
          title=str(info.get("title") or media_id),
          uploader=str(info.get("uploader") or info.get("channel") or ""),
          extractor=str(info.get("extractor_key") or info.get("extractor") or ""),
          webpage_url=str(info.get("webpage_url") or info.get("url") or ""),
        )
      )
    return items
  finally:
    cleanup_paths(cleanup_targets)


def scan_ytdlp_outputs(root: Path) -> list[YtDlpItem]:
  items: list[YtDlpItem] = []
  if not root.exists():
    return items

  for info_path in root.rglob("*.info.json"):
    try:
      info = json.loads(info_path.read_text(encoding="utf-8"))
    except Exception as exc:
      logger.warning("读取 yt-dlp 元数据失败 %s: %s", info_path, exc)
      continue

    media_id = str(info.get("id") or info_path.stem.replace(".info", "")).strip()
    title = str(info.get("title") or media_id or "untitled")
    uploader = str(info.get("uploader") or info.get("channel") or "external")
    extractor = str(info.get("extractor_key") or info.get("extractor") or "external")
    webpage_url = str(info.get("webpage_url") or "")

    candidates = sorted(
      p for p in info_path.parent.glob(f"{media_id}.*")
      if p.is_file() and not p.name.endswith(".info.json")
    )
    audio_path = next((p for p in candidates if p.suffix.lower() == ".mp3"), None)
    if not audio_path and candidates:
      audio_path = candidates[0]
    if not audio_path:
      logger.warning("yt-dlp 元数据存在但未找到媒体文件: %s", info_path)
      continue

    items.append(
      YtDlpItem(
        media_id=media_id,
        title=title,
        uploader=uploader,
        extractor=extractor,
        webpage_url=webpage_url,
        audio_path=audio_path,
        info=info,
        temporary_root=root,
      )
    )

  return items


def looks_like_douyin_url(url: str) -> bool:
  return bool(re.search(r"(^|//|\.)(douyin|iesdouyin)\.com", url))
