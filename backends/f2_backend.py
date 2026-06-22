# -*- coding: utf-8 -*-
"""抖音下载器 - F2 适配后端。"""
from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backends.venv_manager import (
    ensure_f2_python,
    ensure_external_dirs,
    secure_write_text,
    cleanup_paths,
    run_supervised,
    ExternalBackendError,
    RUNTIME_DIR,
)

@dataclass
class F2FetchResult:
  aweme_list: list[dict[str, Any]]
  pages: int
  sec_user_id: str
  expected_count: int | None = None
  nickname: str = ""
  has_more: bool = False
  next_cursor: int = 0
  termination_reason: str = ""
  locate_probe: dict[str, Any] = field(default_factory=dict)
  page_diagnostics: list[dict[str, Any]] = field(default_factory=list)
  source: str = "f2"


@dataclass
class F2DetailResult:
  aweme_list: list[dict[str, Any]]
  errors: list[dict[str, str]]
  requested: int
  source: str = "f2-detail"


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


F2_FETCHER_CODE = r'''
import asyncio
import json
import sys
import traceback
from pathlib import Path

from f2.apps.douyin.crawler import DouyinCrawler
from f2.apps.douyin.handler import DouyinHandler
from f2.apps.douyin.model import PostLocate


def _login_tip(raw):
    if not isinstance(raw, dict):
        return False
    not_login_module = raw.get("not_login_module")
    if isinstance(not_login_module, dict) and not_login_module.get("guide_login_tip_exist"):
        return True
    status_msg = str(raw.get("status_msg") or raw.get("msg") or "")
    return "登录" in status_msg or "login" in status_msg.lower()


def _verify_page(raw):
    if not isinstance(raw, dict):
        return False
    return bool(raw.get("verify_ticket") or raw.get("verify_info") or raw.get("verify_center_decision_conf"))


def _aweme_id(aweme):
    if not isinstance(aweme, dict):
        return ""
    return str(aweme.get("aweme_id") or aweme.get("video_id") or "").strip()


def _add_aweme(result, seen, aweme):
    aweme_id = _aweme_id(aweme)
    if not aweme_id:
        return ""
    if aweme_id in seen:
        return ""
    seen.add(aweme_id)
    result["aweme_list"].append(aweme)
    return aweme_id


def _page_termination(page_items, has_more, login_tip, verify_page, cursor_stall):
    if login_tip:
        return "login_tip"
    if verify_page:
        return "verify_ticket"
    if cursor_stall:
        return "cursor_stall"
    if not page_items:
        return "empty_page"
    if not has_more:
        return "has_more_false"
    return ""


async def _try_locate_recovery(kwargs, result, seen, sec_user_id, last_aweme_id, last_cursor, last_locate_cursor, page_counts):
    probe = {
        "attempted": True,
        "initial_termination_reason": result.get("termination_reason") or "",
        "start_aweme_id": last_aweme_id,
        "start_cursor": last_cursor,
        "start_locate_item_cursor": last_locate_cursor,
        "rounds": [],
        "merged_items": 0,
        "error": "",
    }
    result["locate_probe"] = probe
    if not last_aweme_id or not (last_cursor or last_locate_cursor):
        probe["error"] = "missing last aweme_id or cursor"
        return

    current_aweme_id = last_aweme_id
    current_cursor = str(last_cursor or 0)
    current_locate_cursor = str(last_locate_cursor or last_cursor or 0)
    max_rounds = 3

    try:
        async with DouyinCrawler(kwargs) as crawler:
            for round_index in range(1, max_rounds + 1):
                params = PostLocate(
                    sec_user_id=sec_user_id,
                    max_cursor=current_cursor,
                    locate_item_id=current_aweme_id,
                    locate_item_cursor=current_locate_cursor,
                    count=page_counts,
                )
                raw = await crawler.fetch_locate_post(params)
                if not isinstance(raw, dict):
                    probe["rounds"].append({"round": round_index, "error": "non-dict response"})
                    result["termination_reason"] = "empty_page"
                    break

                page_items = raw.get("aweme_list") if isinstance(raw.get("aweme_list"), list) else []
                has_more = bool(raw.get("has_more"))
                max_cursor = int(raw.get("max_cursor") or 0)
                locate_item_cursor = str(raw.get("locate_item_cursor") or max_cursor or current_locate_cursor or "")
                login_tip = _login_tip(raw)
                verify_page = _verify_page(raw)
                cursor_stall = has_more and bool(max_cursor) and str(max_cursor) == current_cursor
                merged_this_round = 0
                last_new_id = ""

                for aweme in page_items:
                    added_id = _add_aweme(result, seen, aweme)
                    if added_id:
                        merged_this_round += 1
                        last_new_id = added_id

                probe["merged_items"] += merged_this_round
                probe["rounds"].append({
                    "round": round_index,
                    "items": len(page_items),
                    "merged_items": merged_this_round,
                    "has_more": has_more,
                    "max_cursor": max_cursor,
                    "locate_item_cursor": locate_item_cursor,
                    "status_code": raw.get("status_code"),
                    "login_tip": login_tip,
                    "verify_page": verify_page,
                    "cursor_stall": cursor_stall,
                })

                result["has_more"] = has_more
                result["next_cursor"] = max_cursor
                termination = _page_termination(page_items, has_more, login_tip, verify_page, cursor_stall)
                if termination:
                    result["termination_reason"] = termination
                if termination or not merged_this_round:
                    break

                current_aweme_id = last_new_id or current_aweme_id
                current_cursor = str(max_cursor or current_cursor)
                current_locate_cursor = locate_item_cursor or current_locate_cursor
    except Exception as exc:
        probe["error"] = str(exc)


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
        "termination_reason": "",
        "locate_probe": {"attempted": False},
        "page_diagnostics": [],
        "aweme_list": [],
        "errors": [],
    }
    seen = set()
    max_counts = count_limit if count_limit > 0 else None
    previous_cursor = None
    last_aweme_id = ""
    last_cursor = 0
    last_locate_cursor = ""

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
            locate_item_cursor = str(raw.get("locate_item_cursor") or max_cursor or "") if isinstance(raw, dict) else ""
            login_tip = _login_tip(raw)
            verify_page = _verify_page(raw)
            cursor_stall = bool(has_more and previous_cursor is not None and max_cursor == previous_cursor)
            result["has_more"] = has_more
            result["next_cursor"] = max_cursor
            page_items = raw.get("aweme_list") if isinstance(raw, dict) else []
            if not isinstance(page_items, list):
                page_items = []
            result["page_diagnostics"].append({
                "page": result["pages"],
                "items": len(page_items),
                "has_more": has_more,
                "max_cursor": max_cursor,
                "locate_item_cursor": locate_item_cursor,
                "status_code": raw.get("status_code") if isinstance(raw, dict) else None,
                "login_tip": login_tip,
                "verify_page": verify_page,
                "cursor_stall": cursor_stall,
            })
            if max_cursor:
                last_cursor = max_cursor
            if locate_item_cursor:
                last_locate_cursor = locate_item_cursor
            if not page_items:
                result["termination_reason"] = _page_termination(
                    page_items,
                    has_more,
                    login_tip,
                    verify_page,
                    cursor_stall,
                )
                break
            for aweme in page_items:
                aweme_id = _add_aweme(result, seen, aweme)
                if aweme_id:
                    last_aweme_id = aweme_id
                if count_limit > 0 and len(result["aweme_list"]) >= count_limit:
                    result["termination_reason"] = "count_limit"
                    break
            if count_limit > 0 and len(result["aweme_list"]) >= count_limit:
                break
            termination = _page_termination(
                page_items,
                has_more,
                login_tip,
                verify_page,
                cursor_stall,
            )
            if termination:
                result["termination_reason"] = termination
                break
            previous_cursor = max_cursor

        if not result["termination_reason"]:
            result["termination_reason"] = "count_limit" if count_limit > 0 else "empty_page"
        if count_limit <= 0 and result["termination_reason"] in {"has_more_false", "empty_page", "cursor_stall"}:
            await _try_locate_recovery(
                kwargs,
                result,
                seen,
                sec_user_id,
                last_aweme_id,
                last_cursor,
                last_locate_cursor,
                page_counts,
            )
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
      termination_reason=str(data.get("termination_reason") or ""),
      locate_probe=data.get("locate_probe") if isinstance(data.get("locate_probe"), dict) else {},
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
