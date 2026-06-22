from typing import Any, Dict

from core.downloader_base import BaseDownloader, DownloadResult
from utils.logger import setup_logger

logger = setup_logger("VideoDownloader")


class VideoDownloader(BaseDownloader):
    async def download(self, parsed_url: Dict[str, Any]) -> DownloadResult:
        result = DownloadResult()

        aweme_id = parsed_url.get("aweme_id")
        if not aweme_id:
            logger.error("No aweme_id found in parsed URL")
            return result

        result.total = 1
        self._progress_set_item_total(1, "单作品下载")
        self._progress_update_step("下载作品", "单作品资源下载中")

        if not await self._should_download(aweme_id):
            logger.info("Video %s already downloaded, skipping", aweme_id)
            result.skipped += 1
            self._progress_advance_item("skipped", str(aweme_id))
            return result

        await self.rate_limiter.acquire()

        aweme_data = await self.api_client.get_video_detail(aweme_id)
        if not aweme_data:
            logger.error("Failed to get video detail: %s", aweme_id)
            result.failed += 1
            self._progress_advance_item("failed", str(aweme_id))
            return result

        success = await self._download_aweme(aweme_data)
        if success:
            result.success += 1
            self._progress_advance_item("success", str(aweme_id))
        else:
            result.failed += 1
            self._progress_advance_item("failed", str(aweme_id))

        return result

    async def _download_aweme(self, aweme_data: Dict[str, Any]) -> bool:
        author = aweme_data.get("author", {}) or {}
        author_name = author.get("nickname", "unknown")
        # Cache author on the hosting job so JobRow can display the nickname
        # and `retry_failed_awemes` doesn't need to re-fetch user info.
        self._progress_report_author(
            nickname=author_name if author_name != "unknown" else None,
            sec_uid=author.get("sec_uid"),
        )
        return await self._download_aweme_assets(aweme_data, author_name)


# ============================================================
# 以下为 douyin-fetcher-standalone 独有底层文件下载与状态写入逻辑
# ============================================================

import subprocess
import json
from pathlib import Path

def download_file(url: str, dest_path: Path, cookie: str = ""):
  """
  使用系统 curl 工具下载媒体资源原档。
  """
  from utils.logger import setup_logger
  log = setup_logger("VideoDownloader")
  DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
  cmd = [
    "curl", "-s", "-L",
    "-H", f"User-Agent: {DEFAULT_USER_AGENT}",
    "-H", "Referer: https://www.douyin.com/",
    "-o", str(dest_path),
    url
  ]
  if cookie:
    cmd += ["-H", f"Cookie: {cookie}"]

  try:
    subprocess.run(cmd, check=True)
    log.info(f"媒体文件成功落盘: {dest_path.name}")
  except Exception as e:
    log.error(f"文件下载失败 {url}: {e}")
    raise

def write_sample_status(video_dir: Path, status: dict) -> None:
  status_path = video_dir / "collection-status.json"
  status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

