from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from core.downloader_base import BaseDownloader, DownloadResult
from core.user_mode_registry import UserModeRegistry
from utils.logger import setup_logger

logger = setup_logger("UserDownloader")


class UserDownloader(BaseDownloader):
    SELF_COLLECT_MODES = {"collect", "collectmix"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mode_registry = UserModeRegistry()
        self._mode_strategy_cache: Dict[str, Any] = {}

    async def download(self, parsed_url: Dict[str, Any]) -> DownloadResult:
        result = DownloadResult()

        sec_uid = parsed_url.get("sec_uid")
        if not sec_uid:
            # URL parser already validates this; treat as fatal instead of
            # a silent empty result so the UI surfaces a real error rather
            # than "已完成 0 项".
            raise RuntimeError("无法从链接中解析出用户 ID，请确认链接是否完整")

        modes_config = self.config.get("mode", ["post"])
        if isinstance(modes_config, str):
            modes = [modes_config]
        elif isinstance(modes_config, list):
            modes = [str(mode).strip() for mode in modes_config if str(mode).strip()]
        else:
            modes = ["post"]

        if not self._validate_mode_scope(sec_uid, modes):
            return result

        user_info = await self._resolve_user_info(sec_uid, modes)
        if not user_info:
            logger.error("Failed to get user info: %s", sec_uid)
            # Raising here instead of returning an empty result means the
            # job ends in `failed` state with a clear message. Returning
            # {total:0,success:0,failed:0} made JobManager mark it as
            # `success`, which rendered as "已完成 0 项" — a silent failure
            # that's indistinguishable from "nothing happened" in the UI.
            raise RuntimeError("获取用户信息失败，请检查 Cookie 是否有效或重新登录抖音")

        # Cache author metadata on the hosting job so retry doesn't have
        # to re-fetch user_info, and so JobRow can display the nickname.
        self._progress_report_author(
            nickname=user_info.get("nickname"),
            sec_uid=user_info.get("sec_uid") or sec_uid,
        )

        self._progress_update_step("下载模式", f"模式: {', '.join(modes)}")

        seen_aweme_ids: Set[str] = set()
        for mode in modes:
            strategy = self._get_mode_strategy(mode)
            if strategy is None:
                logger.warning("Unsupported user mode: %s", mode)
                continue

            self._progress_update_step("下载模式", f"开始处理 {mode} 作品")
            mode_result = await strategy.download_mode(
                sec_uid, user_info, seen_aweme_ids=seen_aweme_ids
            )
            result.total += mode_result.total
            result.success += mode_result.success
            result.failed += mode_result.failed
            result.skipped += mode_result.skipped

        return result

    def _validate_mode_scope(self, sec_uid: str, modes: List[str]) -> bool:
        normalized_modes = {str(mode or "").strip() for mode in modes}
        has_collect_mode = bool(normalized_modes & self.SELF_COLLECT_MODES)
        has_regular_mode = bool(normalized_modes - self.SELF_COLLECT_MODES)

        if has_collect_mode and sec_uid != "self":
            # Desktop "我的内容 / 下载本收藏夹" sends the real self sec_uid
            # together with a ``collects_id`` filter — by the time the
            # request reaches here the sidecar has already verified via
            # the cookie scope (``_resolve_viewer_sec_uid``) that the
            # caller is the logged-in user, so a real sec_uid + collect
            # mode + collects_id is the legit my-content path. Without
            # this branch ``download()`` would short-circuit and produce
            # an empty DownloadResult, which the JobManager renders as
            # the silent "已完成 0 项" failure.
            collects_id = (str(self.config.get("collects_id") or "")).strip()
            if not collects_id:
                logger.error(
                    "Modes collect/collectmix only support "
                    "/user/self?showTab=favorite_collection or "
                    "my-content 下载本收藏夹 (collects_id required)"
                )
                return False
        if has_collect_mode and has_regular_mode:
            logger.error("Modes collect/collectmix cannot be combined with post/like/mix/music")
            return False
        return True

    def _filter_pinned_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if self._download_pinned_enabled():
            return items
        return [item for item in items if not self._is_pinned_aweme(item)]

    def _download_pinned_enabled(self) -> bool:
        return self._as_bool(self.config.get("download_pinned", False))

    @staticmethod
    def _is_pinned_aweme(item: Dict[str, Any]) -> bool:
        value = item.get("is_top")
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    async def _resolve_user_info(self, sec_uid: str, modes: List[str]) -> Optional[Dict[str, Any]]:
        normalized_modes = {str(mode or "").strip() for mode in modes}
        if sec_uid == "self" and normalized_modes.issubset(self.SELF_COLLECT_MODES):
            self._progress_update_step("获取作者信息", "使用当前登录账号收藏夹上下文")
            return {
                "uid": "self",
                "sec_uid": "self",
                "nickname": "self",
            }

        # Desktop my-content "下载本收藏夹" path: real sec_uid + collect
        # mode + collects_id filter. The cookie scope upstream already
        # guarantees this is the viewer themselves, so we can skip the
        # network round-trip via ``api_client.get_user_info``.
        if (
            normalized_modes.issubset(self.SELF_COLLECT_MODES)
            and (str(self.config.get("collects_id") or "")).strip()
        ):
            self._progress_update_step("获取作者信息", "使用当前登录账号收藏夹上下文")
            return {
                "uid": sec_uid,
                "sec_uid": sec_uid,
                "nickname": "self",
            }

        self._progress_update_step("获取作者信息", f"sec_uid={sec_uid}")
        return await self.api_client.get_user_info(sec_uid)

    def _get_mode_strategy(self, mode: str):
        normalized_mode = (mode or "").strip()

        # The "collect" strategy supports an optional ``collects_id`` filter
        # that constrains paging to a single folder (desktop "我的收藏 / 下载
        # 本收藏夹"). When the filter is set we bypass the cache so the next
        # call with a different (or absent) filter doesn't reuse a stale
        # strategy bound to the previous folder. The no-filter path keeps
        # caching to preserve the existing CLI behaviour.
        if normalized_mode == "collect":
            return self._make_collect_strategy()

        if normalized_mode in self._mode_strategy_cache:
            return self._mode_strategy_cache[normalized_mode]

        strategy_cls = self.mode_registry.get(normalized_mode)
        if strategy_cls is None:
            return None

        strategy = strategy_cls(self)
        self._mode_strategy_cache[normalized_mode] = strategy
        return strategy

    def _make_collect_strategy(self):
        """Construct the collect strategy, threading ``collects_id`` from
        the per-job config when present. Caches only the no-filter path
        (matching the historic CLI behaviour) so a subsequent call with a
        different filter doesn't pick up a stale binding.
        """
        strategy_cls = self.mode_registry.get("collect")
        if strategy_cls is None:
            return None

        raw_filter = self.config.get("collects_id")
        collects_id = (str(raw_filter).strip() if raw_filter is not None else "") or None

        if collects_id is None:
            cached = self._mode_strategy_cache.get("collect")
            if cached is not None:
                return cached
            strategy = strategy_cls(self)
            self._mode_strategy_cache["collect"] = strategy
            return strategy

        # Filtered path is request-scoped — never cached.
        return strategy_cls(self, collects_id=collects_id)

    async def _download_mode_items(
        self,
        mode: str,
        items: List[Dict[str, Any]],
        author_name: str,
        seen_aweme_ids: Optional[Set[str]] = None,
    ) -> DownloadResult:
        if seen_aweme_ids is None:
            seen_aweme_ids = set()
        deduped_items: List[Dict[str, Any]] = []
        local_seen: Set[str] = set()

        for item in items:
            aweme_id = str(item.get("aweme_id") or "").strip()
            if not aweme_id:
                continue
            if aweme_id in seen_aweme_ids or aweme_id in local_seen:
                continue
            local_seen.add(aweme_id)
            seen_aweme_ids.add(aweme_id)
            deduped_items.append(item)

        result = DownloadResult()
        result.total = len(deduped_items)
        self._progress_set_item_total(result.total, "作品待下载")
        self._progress_update_step("下载作品", f"待处理 {result.total} 条")

        # Accumulate per-aweme DB records and flush in a single transaction
        # at the end — avoids one fsync per item across the whole batch.
        db_batch: Optional[List[Dict[str, Any]]] = [] if self.database else None

        async def _process_aweme(item: Dict[str, Any]):
            aweme_id = item.get("aweme_id")
            if not await self._should_download(str(aweme_id or "")):
                self._progress_advance_item("skipped", str(aweme_id or "unknown"))
                return {"status": "skipped", "aweme_id": aweme_id}

            success = await self._download_aweme_assets(
                item, author_name, mode=mode, db_batch=db_batch
            )
            status = "success" if success else "failed"
            self._progress_advance_item(status, str(aweme_id or "unknown"))
            return {
                "status": status,
                "aweme_id": aweme_id,
            }

        download_results = await self.queue_manager.download_batch(_process_aweme, deduped_items)

        if db_batch:
            await self.database.add_aweme_batch(db_batch)

        for entry in download_results:
            status = entry.get("status") if isinstance(entry, dict) else None
            if status == "success":
                result.success += 1
            elif status == "failed":
                result.failed += 1
            elif status == "skipped":
                result.skipped += 1
            else:
                result.failed += 1
                self._progress_advance_item("failed", "unknown")

        return result

    # 向后兼容：旧测试仍直接调用 post 下载入口。
    async def _download_user_post(self, sec_uid: str, user_info: Dict[str, Any]) -> DownloadResult:
        strategy = self._get_mode_strategy("post")
        if strategy is None:
            return DownloadResult()
        return await strategy.download_mode(sec_uid, user_info, seen_aweme_ids=set())

    async def _recover_user_post_with_browser(
        self,
        sec_uid: str,
        user_info: Dict[str, Any],
        aweme_list: List[Dict[str, Any]],
    ) -> None:
        browser_cfg = self.config.get("browser_fallback", {}) or {}
        if not browser_cfg.get("enabled", True):
            return

        number_limit = self.config.get("number", {}).get("post", 0)
        # 在分页受限场景下，user_info.aweme_count 常常不可靠（经常只返回 20）
        # 因此仅在用户显式设置 number_limit 时才限制浏览器采集目标数量。
        expected_count = int(number_limit or 0)
        if expected_count and len(aweme_list) >= expected_count:
            return

        try:
            browser_aweme_ids = await self.api_client.collect_user_post_ids_via_browser(
                sec_uid,
                expected_count=expected_count,
                headless=bool(browser_cfg.get("headless", False)),
                max_scrolls=int(browser_cfg.get("max_scrolls", 240) or 240),
                idle_rounds=int(browser_cfg.get("idle_rounds", 8) or 8),
                wait_timeout_seconds=int(browser_cfg.get("wait_timeout_seconds", 600) or 600),
            )
        except Exception as exc:
            logger.error("Browser fallback failed: %s", exc)
            return

        browser_aweme_items: Dict[str, Dict[str, Any]] = {}
        browser_post_stats: Dict[str, int] = {}
        if hasattr(self.api_client, "pop_browser_post_aweme_items"):
            try:
                browser_aweme_items = self.api_client.pop_browser_post_aweme_items() or {}
            except Exception as exc:
                logger.debug("Fetch browser post items skipped: %s", exc)
        if hasattr(self.api_client, "pop_browser_post_stats"):
            try:
                browser_post_stats = self.api_client.pop_browser_post_stats() or {}
            except Exception as exc:
                logger.debug("Fetch browser post stats skipped: %s", exc)

        if not browser_aweme_ids:
            logger.warning("Browser fallback returned no aweme_id")
            return

        existing_ids = {str(item.get("aweme_id")) for item in aweme_list if item.get("aweme_id")}
        missing_ids = [aweme_id for aweme_id in browser_aweme_ids if aweme_id not in existing_ids]
        if not missing_ids:
            return

        logger.warning(
            "Recovering aweme details from browser list, missing count=%s",
            len(missing_ids),
        )
        detail_failed = 0
        detail_success = 0
        reused_from_browser_items = 0
        total_missing = len(missing_ids)
        for index, aweme_id in enumerate(missing_ids, start=1):
            if number_limit > 0 and len(aweme_list) >= number_limit:
                break

            if index == 1 or index == total_missing or index % 5 == 0:
                self._progress_update_step("浏览器回补", f"补全详情 {index}/{total_missing}")

            detail = browser_aweme_items.get(str(aweme_id))
            if not detail:
                await self.rate_limiter.acquire()
                detail = await self.api_client.get_video_detail(aweme_id, suppress_error=True)
                if detail:
                    detail_success += 1
            else:
                reused_from_browser_items += 1
            if not detail:
                detail_failed += 1
                continue
            author = detail.get("author", {}) if isinstance(detail, dict) else {}
            detail_sec_uid = author.get("sec_uid") if isinstance(author, dict) else None
            if detail_sec_uid and str(detail_sec_uid) != str(sec_uid):
                logger.warning(
                    "Skip aweme_id=%s due to mismatched sec_uid (%s)",
                    aweme_id,
                    detail_sec_uid,
                )
                continue
            aweme_list.append(detail)

        self._progress_update_step(
            "浏览器回补",
            f"回补完成，复用 {reused_from_browser_items}，补拉成功 {detail_success}，失败 {detail_failed}",
        )
        logger.warning(
            "Browser fallback summary: merged_ids=%s selected_ids=%s post_items=%s post_pages=%s reused=%s detail_success=%s detail_failed=%s",
            browser_post_stats.get("merged_ids", 0),
            browser_post_stats.get("selected_ids", len(browser_aweme_ids)),
            browser_post_stats.get("post_items", len(browser_aweme_items)),
            browser_post_stats.get("post_pages", 0),
            reused_from_browser_items,
            detail_success,
            detail_failed,
        )

        if detail_failed > 0:
            logger.warning(
                "Browser fallback detail fetch failed: %s/%s",
                detail_failed,
                total_missing,
            )


# ============================================================
# 以下为 douyin-fetcher-standalone 独有博主主页下载与处理流程
# ============================================================

import shutil
import json
from pathlib import Path
from utils.logger import setup_logger
from utils.helpers import sanitize_folder_name

from core.downloader_base import (
    get_aweme_media_selection,
    is_completed_video_dir,
    completed_video_matches_selection,
)
from core.video_downloader import download_file, write_sample_status
from core.audio_extraction import extract_audio_from_video
from core.metadata import write_meta_file
from core.transcript_manager import finalize_transcript

def merge_aweme_lists_by_id(
  base_items: list[dict[str, Any]],
  extra_items: list[dict[str, Any]],
  preferred_order: list[str] | None = None,
) -> list[dict[str, Any]]:
  by_id: dict[str, dict[str, Any]] = {}
  order: list[str] = []

  def add_item(item: dict[str, Any], *, override: bool) -> None:
    aweme_id = str(item.get("aweme_id") or item.get("video_id") or "").strip()
    if not aweme_id:
      return
    if aweme_id not in by_id:
      order.append(aweme_id)
    if override or aweme_id not in by_id:
      by_id[aweme_id] = item

  for item in base_items:
    if isinstance(item, dict):
      add_item(item, override=False)
  for item in extra_items:
    if isinstance(item, dict):
      add_item(item, override=True)

  final_order: list[str] = []
  seen: set[str] = set()
  for aweme_id in preferred_order or []:
    if aweme_id in by_id and aweme_id not in seen:
      final_order.append(aweme_id)
      seen.add(aweme_id)
  for aweme_id in order:
    if aweme_id in by_id and aweme_id not in seen:
      final_order.append(aweme_id)
      seen.add(aweme_id)
  return [by_id[aweme_id] for aweme_id in final_order]


def process_aweme_list(
  aweme_list: list[dict[str, Any]],
  *,
  nickname: str,
  output_base: Path,
  cookie_str: str,
  whisper_path: str,
  skip_asr: bool,
  keep_video: bool,
  source_path: str,
  video_quality: str,
  video_orientation: str,
  comments_cfg: dict | None = None,
) -> dict[str, int]:
  log = setup_logger("UserDownloader")
  account_folder = sanitize_folder_name(nickname)
  stats_summary = {"success": 0, "failed": 0, "skipped": 0}

  log.info(f"共获取到 {len(aweme_list)} 个作品，开始依次处理媒体提取与台词转写...")

  for i, aweme in enumerate(aweme_list):
    aweme_id = str(aweme.get("aweme_id") or aweme.get("video_id") or "").strip()
    if not aweme_id:
      log.warning("跳过缺少 aweme_id 的作品。")
      stats_summary["failed"] += 1
      continue

    desc = aweme.get("desc") or aweme.get("title") or "无标题"
    video_dir = output_base / account_folder / aweme_id
    video_dir.mkdir(parents=True, exist_ok=True)
    audio_path = video_dir / "audio.mp3"
    video_path = video_dir / "video.mp4"
    media_selection = get_aweme_media_selection(
      aweme,
      video_quality=video_quality,
      video_orientation=video_orientation,
    )
    audio_url = media_selection["audio_url"]
    video_url = media_selection["video_url"]
    images_urls = media_selection.get("images_urls") or []
    video_selection = media_selection["video_selection"]
    is_image_album = len(images_urls) > 0

    if is_completed_video_dir(video_dir, is_image_album=is_image_album, expected_images_count=len(images_urls)):
      if is_image_album or completed_video_matches_selection(video_dir, video_selection):
        log.info(f"[{i+1}/{len(aweme_list)}] 跳过已完成作品: {aweme_id}")
        stats_summary["skipped"] += 1
        continue
      log.warning(
        "[%s/%s] 已完成作品的视频尺寸不匹配当前最佳流，重新下载修复: %s",
        i + 1,
        len(aweme_list),
        aweme_id,
      )

    sample_status = {
      "video_id": aweme_id,
      "status": "metadata_only",
      "metadata": True,
      "media_downloaded": False,
      "audio_ready": False,
      "video_ready": False,
      "transcript_ready": False,
      "source_path": source_path,
      "video_selection": video_selection,
      "video_quality": video_quality,
      "video_orientation": video_orientation,
      "is_image_album": is_image_album,
      "notes": []
    }
    write_sample_status(video_dir, sample_status)

    if not video_url and not is_image_album:
      log.warning(f"视频ID {aweme_id} 缺少可用的视频播放资源链接，跳过")
      sample_status["status"] = "download_failed"
      sample_status["notes"].append(
        f"no video play url found for orientation={video_orientation}"
      )
      write_sample_status(video_dir, sample_status)
      stats_summary["failed"] += 1
      continue

    log.info(f"[{i+1}/{len(aweme_list)}] 正在拉取作品: {aweme_id} | 标题: {str(desc)[:15]}...")

    if is_image_album:
      log.info(f"拉取无水印图集原图列表 (共 {len(images_urls)} 张)...")
      try:
        for idx, img_url in enumerate(images_urls):
          img_path = video_dir / f"image_{idx + 1}.jpg"
          log.info(f"正在下载第 {idx + 1}/{len(images_urls)} 张图...")
          download_file(img_url, img_path, cookie_str)
        sample_status["media_downloaded"] = True
        sample_status["video_ready"] = True
      except KeyboardInterrupt:
        sample_status["status"] = "interrupted"
        sample_status["notes"].append("interrupted during image album download")
        write_sample_status(video_dir, sample_status)
        raise
      except Exception as e:
        log.error(f"图集图片下载失败: {e}")
        sample_status["status"] = "download_failed"
        sample_status["notes"].append(f"image album download failed: {e}")
        write_sample_status(video_dir, sample_status)
        stats_summary["failed"] += 1
        continue
    else:
      log.info("拉取无水印视频流...")
      try:
        download_file(video_url, video_path, cookie_str)
        sample_status["media_downloaded"] = True
        sample_status["video_ready"] = True
      except KeyboardInterrupt:
        sample_status["status"] = "interrupted"
        sample_status["notes"].append("interrupted during video download")
        write_sample_status(video_dir, sample_status)
        raise
      except Exception as e:
        log.error(f"视频文件下载失败: {e}")
        sample_status["status"] = "download_failed"
        sample_status["notes"].append(f"video download failed: {e}")
        write_sample_status(video_dir, sample_status)
        stats_summary["failed"] += 1
        continue

    if audio_url:
      log.info("拉取无水印音频流...")
      try:
        download_file(audio_url, audio_path, cookie_str)
        sample_status["audio_ready"] = True
      except KeyboardInterrupt:
        sample_status["status"] = "interrupted"
        sample_status["notes"].append("interrupted during audio download")
        write_sample_status(video_dir, sample_status)
        raise
      except Exception as e:
        log.error(f"音频文件下载失败: {e}")
        sample_status["status"] = "download_failed"
        sample_status["notes"].append(f"audio download failed: {e}")
        write_sample_status(video_dir, sample_status)
        stats_summary["failed"] += 1
        continue
    elif not is_image_album:
      log.info("未发现直接音频流。正在从 video.mp4 提取音轨...")
      try:
        extract_audio_from_video(video_path, audio_path)
        sample_status["audio_ready"] = True
        log.info("FFmpeg 音轨转码成功！")
      except KeyboardInterrupt:
        sample_status["status"] = "interrupted"
        sample_status["notes"].append("interrupted during video download or ffmpeg")
        write_sample_status(video_dir, sample_status)
        raise
      except Exception as e:
        log.error(f"媒体流抓取或转码发生异常: {e}")
        sample_status["status"] = "download_failed"
        sample_status["notes"].append(f"ffmpeg extract audio failed: {e}")
        write_sample_status(video_dir, sample_status)
        stats_summary["failed"] += 1
        continue

    write_meta_file(video_dir, aweme, nickname)

    # 爬取评论逻辑（若开启）
    if comments_cfg and comments_cfg.get("enabled"):
      log.info("开始拉取该作品的评论列表...")
      try:
        from core.comments_collector import CommentsCollector
        from core.api_client import DouyinAPIClient
        from storage.metadata_handler import MetadataHandler
        from utils.cookie_utils import parse_cookie_header
        import asyncio

        cookie_dict = parse_cookie_header(cookie_str)
        api_client = DouyinAPIClient(cookies=cookie_dict)
        metadata_handler = MetadataHandler()
        collector = CommentsCollector(
          api_client,
          metadata_handler,
          include_replies=bool(comments_cfg.get("include_replies", False)),
          max_comments=int(comments_cfg.get("max_comments", 0) or 0),
          page_size=int(comments_cfg.get("page_size", 20) or 20),
        )
        comments_path = video_dir / f"{aweme_id}_comments.json"
        
        async def run_collect():
          async with api_client:
            return await collector.collect_and_save(aweme_id, comments_path)

        try:
          loop = asyncio.get_event_loop()
        except RuntimeError:
          loop = asyncio.new_event_loop()
          asyncio.set_event_loop(loop)
        
        if loop.is_running():
          import nest_asyncio
          nest_asyncio.apply()
          loop.run_until_complete(run_collect())
        else:
          asyncio.run(run_collect())

        log.info("评论保存成功！")
      except Exception as ce:
        log.error(f"评论爬取失败: {ce}")

    try:
      finalize_transcript(
        audio_path,
        video_dir,
        sample_status,
        skip_asr=skip_asr,
        whisper_path=whisper_path,
      )
    except KeyboardInterrupt:
      sample_status["status"] = "interrupted"
      sample_status["notes"].append("interrupted during asr")
      write_sample_status(video_dir, sample_status)
      raise
    write_sample_status(video_dir, sample_status)
    if sample_status["status"] == "success":
      stats_summary["success"] += 1
    else:
      stats_summary["failed"] += 1

  return stats_summary


def process_ytdlp_items(
  items: list,
  *,
  output_base: Path,
  whisper_path: str,
  skip_asr: bool,
) -> dict[str, int]:
  from backends.ytdlp_backend import YtDlpItem
  log = setup_logger("UserDownloader")
  summary = {"success": 0, "failed": 0, "skipped": 0}
  temp_roots = {item.temporary_root for item in items}
  try:
    for item in items:
      account_folder = sanitize_folder_name(item.uploader or item.extractor or "external")
      media_id = sanitize_folder_name(item.media_id)
      video_dir = output_base / account_folder / media_id
      video_dir.mkdir(parents=True, exist_ok=True)
      audio_path = video_dir / "audio.mp3"

      if is_completed_video_dir(video_dir):
        log.info(f"跳过已完成外部作品: {media_id}")
        summary["skipped"] += 1
        continue

      sample_status = {
        "video_id": media_id,
        "status": "metadata_only",
        "metadata": True,
        "media_downloaded": False,
        "audio_ready": False,
        "transcript_ready": False,
        "source_path": f"yt-dlp:{item.extractor}",
        "notes": [],
      }
      write_sample_status(video_dir, sample_status)

      try:
        if item.audio_path.suffix.lower() == ".mp3":
          shutil.copy2(item.audio_path, audio_path)
        else:
          cmd_ffmpeg = [
            "ffmpeg", "-y", "-i", str(item.audio_path),
            "-vn", "-acodec", "libmp3lame", "-q:a", "2",
            str(audio_path)
          ]
          subprocess.run(cmd_ffmpeg, check=True, capture_output=True)
        sample_status["media_downloaded"] = True
        sample_status["audio_ready"] = True
      except KeyboardInterrupt:
        sample_status["status"] = "interrupted"
        sample_status["notes"].append("interrupted during yt-dlp normalization")
        write_sample_status(video_dir, sample_status)
        raise
      except Exception as e:
        sample_status["status"] = "download_failed"
        sample_status["notes"].append(f"yt-dlp output normalize failed: {e}")
        write_sample_status(video_dir, sample_status)
        log.error(f"外部作品归一化失败 {media_id}: {e}")
        summary["failed"] += 1
        continue

      meta_text = (
        f"## 视频信息\n"
        f"标题：{item.title}\n"
        f"作者：{item.uploader}\n"
        f"视频ID：{item.media_id}\n"
        f"来源：{item.webpage_url}\n\n"
        f"## 数据\n"
        f"播放：{item.info.get('view_count', 0)}\n"
        f"点赞：{item.info.get('like_count', 0)}\n"
        f"评论数：{item.info.get('comment_count', 0)}\n\n"
      )
      (video_dir / "meta.md").write_text(meta_text, encoding="utf-8")
      (video_dir / "source.info.json").write_text(
        json.dumps(item.info, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
      )
      try:
        finalize_transcript(
          audio_path,
          video_dir,
          sample_status,
          skip_asr=skip_asr,
          whisper_path=whisper_path,
        )
      except KeyboardInterrupt:
        sample_status["status"] = "interrupted"
        sample_status["notes"].append("interrupted during asr")
        write_sample_status(video_dir, sample_status)
        raise
      write_sample_status(video_dir, sample_status)
      if sample_status["status"] == "success":
        summary["success"] += 1
      else:
        summary["failed"] += 1
  finally:
    for root in temp_roots:
      try:
        if root.exists():
          shutil.rmtree(root)
      except OSError as exc:
        log.warning("清理 yt-dlp 临时媒体目录失败 %s: %s", root, exc)
  return summary


def print_list_probe(
  aweme_list: list[dict[str, Any]],
  *,
  source: str = "",
  expected_count: int | None = None,
  complete: bool | None = None,
  pages: int | None = None,
  diagnostics: list[dict[str, Any]] | None = None,
) -> None:
  payload: dict[str, Any] = {
    "count": len(aweme_list),
    "expected_count": expected_count,
    "complete": complete,
    "source": source,
    "aweme_ids": [
      str(item.get("aweme_id") or item.get("video_id") or "")
      for item in aweme_list
    ],
  }
  if pages is not None:
    payload["pages"] = pages
  if diagnostics is not None:
    payload["diagnostics"] = diagnostics
  print(json.dumps(payload, ensure_ascii=False, indent=2))

