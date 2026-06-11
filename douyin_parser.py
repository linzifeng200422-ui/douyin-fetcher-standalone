#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
douyin_parser.py — 抖音视频/博主主页无水印解析下载、音轨转换与 ASR 台词识别工具（独立开源版）。
"""

import argparse
import json
import logging
import os
import re
import sys
import subprocess
import urllib.parse
from pathlib import Path

# 配置全局日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("douyin-fetcher-standalone")

# 配置默认 API 端点，支持环境变量覆盖
PUBLIC_API_BASE_URL = os.getenv("DOUYIN_API_BASE_URL", "https://api.douyin.wtf")
LOCAL_API_BASE_URL = os.getenv("LOCAL_DOUYIN_API_BASE_URL", "http://127.0.0.1:8080")

def load_cookie(cookie_str: str = "", cookie_file: str = "") -> str:
  """
  获取并解析 Cookie。支持直接传参或读取本地文本文件。
  """
  if cookie_str:
    return cookie_str.strip()
  if cookie_file:
    path = Path(cookie_file)
    if path.is_file():
      try:
        # 为防止换行符引发请求头错误，读取后做 strip 清理
        return path.read_text(encoding="utf-8").strip()
      except Exception as e:
        logger.error(f"读取 Cookie 外部文件失败: {e}")
  return ""

def fetch_api_json(base_url: str, endpoint: str, params: dict, source_label: str, cookie: str = "") -> dict | None:
  """
  使用系统底层的 curl 命令行工具发送 HTTP 请求。
  为什么使用 curl：因为 Python 的 urllib 或 requests 在某些系统默认环境下容易被代理拦截或反爬识别，
  使用系统级 curl 加上高仿 User-Agent 具备更好的隐蔽性与绕过成功率。
  """
  query_string = urllib.parse.urlencode(params)
  url = f"{base_url.rstrip('/')}{endpoint}?{query_string}"

  cmd = [
    "curl", "-s", "-L",
    "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    url
  ]
  if cookie:
    cmd += ["-H", f"Cookie: {cookie}"]

  try:
    logger.info(f"发送数据请求: {source_label} -> {url}")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode == 0:
      res_data = json.loads(result.stdout)
      code = res_data.get("code") or res_data.get("detail", {}).get("code")
      if code == 200:
        logger.info(f"数据获取成功: {source_label}")
        return res_data
      else:
        msg = res_data.get("msg") or res_data.get("detail", {}).get("message")
        logger.error(f"解析接口返回业务异常 ({source_label}, Code {code}): {msg}")
        return None
    else:
      logger.error(f"curl 请求命令运行失败 ({source_label}): {result.stderr}")
      return None
  except Exception as e:
    logger.error(f"调用接口服务请求时发生异常 ({source_label}) {url}: {e}")
    return None

def fetch_user_posts(sec_user_id: str, count: int, cookie: str = "") -> dict | None:
  """
  拉取目标博主的主页最近视频。先尝试公共 API 解析，失败后通过本地 API 兜底。
  """
  params = {"sec_user_id": sec_user_id, "count": count}
  res_posts = fetch_api_json(
    PUBLIC_API_BASE_URL,
    "/api/douyin/web/fetch_user_post_videos",
    params,
    "public-api",
    cookie
  )
  if res_posts:
    return res_posts

  if LOCAL_API_BASE_URL and LOCAL_API_BASE_URL != PUBLIC_API_BASE_URL:
    logger.warning("公网 API 响应异常或受限，尝试切换到本地服务...")
    return fetch_api_json(
      LOCAL_API_BASE_URL,
      "/api/douyin/web/fetch_user_post_videos",
      params,
      "local-evil0ctal-api",
      cookie
    )

  return None

def download_file(url: str, dest_path: Path, cookie: str = ""):
  """
  使用系统 curl 工具下载媒体资源原档。
  """
  cmd = [
    "curl", "-s", "-L",
    "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "-H", "Referer: https://www.douyin.com/",
    "-o", str(dest_path),
    url
  ]
  if cookie:
    cmd += ["-H", f"Cookie: {cookie}"]

  try:
    subprocess.run(cmd, check=True)
    logger.info(f"媒体文件成功落盘: {dest_path.name}")
  except Exception as e:
    logger.error(f"文件下载失败 {url}: {e}")
    raise

def write_sample_status(video_dir: Path, status: dict) -> None:
  status_path = video_dir / "collection-status.json"
  status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def run_whisper_transcription(audio_path: Path, output_dir: Path, whisper_path: str = "") -> bool:
  """
  自动唤起本地 Whisper 服务提取音频原声中的台词文本。
  """
  transcript_path = output_dir / "transcript.md"
  
  # 若用户传入了特定 ASR 运行脚本路径
  if whisper_path:
    custom_script = Path(whisper_path)
    if custom_script.is_file():
      logger.info(f"使用用户指定脚本启动 ASR: {custom_script}")
      cmd = ["bash", str(custom_script), str(audio_path), str(output_dir)]
      try:
        subprocess.run(cmd, check=True)
        return True
      except Exception as e:
        logger.error(f"指定的 ASR 脚本执行失败: {e}")
        return False

  # 兜底方案：检测并使用全局的 whisper CLI (openai-whisper)
  try:
    # 探查环境 PATH 里有没有全局命令
    subprocess.run(["whisper", "--version"], capture_output=True, check=True)
    logger.info("检测到全局 whisper 指令，开始在后台运行 ASR 转写流程...")
    
    cmd = [
      "whisper", str(audio_path),
      "--output_dir", str(output_dir),
      "--output_format", "txt",
      "--model", "base",
      "--language", "zh"
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    
    generated_txt = output_dir / f"{audio_path.stem}.txt"
    if generated_txt.is_file():
      text_content = generated_txt.read_text(encoding="utf-8")
      transcript_path.write_text(text_content, encoding="utf-8")
      generated_txt.unlink() # 移除临时转换格式
      
      # 移除 whisper 默认生成的其他附带多媒体格式文件
      for ext in ["vtt", "srt", "tsv", "json"]:
        tmp_file = output_dir / f"{audio_path.stem}.{ext}"
        if tmp_file.is_file():
          tmp_file.unlink()
          
      return True
  except Exception as e:
    logger.warning(f"系统 PATH 中没有发现可用的全局 whisper 命令行工具: {e}")
  
  return False

def main():
  parser = argparse.ArgumentParser(description="抖音视频/主页无水印极速解析与台词转录工具 (独立开源版)")
  parser.add_argument("--url", required=True, help="抖音视频分享链接 或 个人主页链接")
  parser.add_argument("--count", type=int, default=3, help="抓取主页最近的视频数量")
  parser.add_argument("--account-name", default="", help="自定义博主文件夹命名")
  parser.add_argument("--output-dir", default="downloads", help="本地输出路径")
  parser.add_argument("--cookie", default="", help="直接传入 Cookie 字符串")
  parser.add_argument("--cookie-file", default="", help="读取本地 Cookie 的 txt 文件路径")
  parser.add_argument("--whisper-path", default="", help="可选：本地自定义 Whisper ASR 执行脚本路径")
  args = parser.parse_args()

  cookie_str = load_cookie(args.cookie, args.cookie_file)
  output_base = Path(args.output_dir)
  output_base.mkdir(parents=True, exist_ok=True)

  logger.info(f"开始解析链接: {args.url}")

  # 1. 链接探查与重定向获取
  logger.info("模拟跳转以探查链接类型，识别主页与单视频...")
  cmd_redirect = [
    "curl", "-s", "-I", "-L",
    "-H", "User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 Version/17.0 Mobile/15E148 Safari/604.1",
    args.url
  ]
  if cookie_str:
    cmd_redirect += ["-H", f"Cookie: {cookie_str}"]

  sec_user_id = None
  final_url = args.url
  try:
    res = subprocess.run(cmd_redirect, capture_output=True, text=True, encoding="utf-8")
    locations = re.findall(r'[lL]ocation:\s*([^\r\n]+)', res.stdout)
    final_url = locations[-1].strip() if locations else args.url

    # 匹配博主个人主页模式
    user_match = re.search(r'share/user/([a-zA-Z0-9_-]+)', final_url)
    if user_match:
      sec_user_id = user_match.group(1)
    else:
      # 从 url 参数中提取 sec_uid
      parsed_url = urllib.parse.urlparse(final_url)
      params = urllib.parse.parse_qs(parsed_url.query)
      if 'sec_uid' in params:
        sec_user_id = params['sec_uid'][0]
  except Exception as e:
    logger.warning(f"获取跳转链接失败: {e}，尝试作为单视频处理")

  aweme_list = []
  nickname = args.account_name or "未命名账号"

  if sec_user_id:
    # 情况 A：输入为主页链接
    logger.info(f"检测到主页分享链接 (sec_uid: {sec_user_id})")
    logger.info(f"正在拉取该博主最近的 {args.count} 个作品列表...")
    res_posts = fetch_user_posts(sec_user_id, args.count, cookie_str)
    
    post_data = res_posts.get("data", {}) if res_posts else {}
    if post_data and post_data.get("aweme_list"):
      aweme_list = post_data["aweme_list"]
      for aweme in aweme_list:
        author = aweme.get("author", {})
        if author and author.get("nickname"):
          nickname = author.get("nickname")
          break
    else:
      logger.error("拉取博主主页作品失败。若主页被反爬，请尝试传入最新的 Cookie 或提供单视频链接。")
      sys.exit(1)
  else:
    # 情况 B：输入为单视频链接
    logger.info("按单视频分享链接进行本地免 Cookie HTML 解密...")
    try:
      video_id_match = re.search(r'video/(\d+)', final_url)
      if not video_id_match:
        video_id_match = re.search(r'/(\d+)(?:\?|$)', final_url)

      if not video_id_match:
        logger.error(f"无法从最终重定向链接中提取出视频数字 ID: {final_url}")
        sys.exit(1)

      video_id = video_id_match.group(1)
      logger.info(f"成功提取视频 ID: {video_id}。开始向 iesdouyin 发送请求...")

      ies_url = f"https://www.iesdouyin.com/share/video/{video_id}"
      cmd_fetch = [
        "curl", "-s", "-L",
        "-H", "User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 Version/17.0 Mobile/15E148 Safari/604.1",
        ies_url
      ]
      if cookie_str:
        cmd_fetch += ["-H", f"Cookie: {cookie_str}"]

      result = subprocess.run(cmd_fetch, capture_output=True, text=True, encoding="utf-8")
      pattern = re.compile(pattern=r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", flags=re.DOTALL)
      find_res = pattern.search(result.stdout)
      if not find_res:
        logger.error("在网页源码中未匹配到 window._ROUTER_DATA，视频页面可能已被删除或风控限制。")
        sys.exit(1)

      json_str = find_res.group(1).strip()
      if json_str.endswith(';'):
        json_str = json_str[:-1]

      json_data = json.loads(json_str)
      loader_data = json_data.get("loaderData", {})
      
      VIDEO_ID_PAGE_KEY = "video_(id)/page"
      NOTE_ID_PAGE_KEY = "note_(id)/page"

      original_video_info = None
      if VIDEO_ID_PAGE_KEY in loader_data:
        original_video_info = loader_data[VIDEO_ID_PAGE_KEY].get("videoInfoRes")
      elif NOTE_ID_PAGE_KEY in loader_data:
        original_video_info = loader_data[NOTE_ID_PAGE_KEY].get("videoInfoRes")

      if not original_video_info or not original_video_info.get("item_list"):
        logger.error("网页解析成功，但未在 window._ROUTER_DATA 中获取到作品信息。")
        sys.exit(1)

      data = original_video_info["item_list"][0]
      nickname = data.get("author", {}).get("nickname") or data.get("nickname") or "未命名账号"
      aweme_list = [data]
    except Exception as e:
      logger.error(f"解析网页数据还原单视频失败: {e}")
      sys.exit(1)

  if not aweme_list:
    logger.error("获取到的视频列表为空，结束处理。")
    sys.exit(1)

  # 规范化博主命名的文件夹名称，防路径截断安全风险
  account_folder = args.account_name if args.account_name else nickname
  account_folder = re.sub(r'[\\/:*?"<>| ]', "_", account_folder)

  logger.info(f"共获取到 {len(aweme_list)} 个作品，开始依次处理媒体提取与台词转写...")

  for i, aweme in enumerate(aweme_list):
    aweme_id = aweme.get("aweme_id") or aweme.get("video_id")
    desc = aweme.get("desc") or "无标题"
    stats = aweme.get("statistics", {})

    # 优先使用音频原声下载链接
    audio_url = ""
    music_info = aweme.get("music", {})
    if music_info and music_info.get("play_url"):
      url_list = music_info["play_url"].get("url_list")
      if url_list:
        audio_url = url_list[0]
      elif music_info["play_url"].get("uri"):
        audio_url = music_info["play_url"]["uri"]

    # 提取无水印视频地址以做音频转换兜底
    video_url = ""
    video_info = aweme.get("video", {})
    if video_info and video_info.get("play_addr"):
      v_url_list = video_info["play_addr"].get("url_list")
      if v_url_list:
        video_url = v_url_list[0].replace("playwm", "play")

    video_dir = output_base / account_folder / aweme_id
    video_dir.mkdir(parents=True, exist_ok=True)
    audio_path = video_dir / "audio.mp3"

    sample_status = {
      "video_id": aweme_id,
      "status": "metadata_only",
      "metadata": True,
      "media_downloaded": False,
      "audio_ready": False,
      "transcript_ready": False,
      "source_path": "public-api-or-iesdouyin",
      "notes": []
    }

    if not audio_url and not video_url:
      logger.warning(f"视频ID {aweme_id} 缺少可用的播放资源链接，跳过")
      sample_status["status"] = "download_failed"
      sample_status["notes"].append("no media play url found")
      write_sample_status(video_dir, sample_status)
      continue

    logger.info(f"[{i+1}/{len(aweme_list)}] 正在拉取作品: {aweme_id} | 标题: {desc[:15]}...")

    # 自适应媒体流下载
    if audio_url:
      logger.info("拉取无水印音频流...")
      try:
        download_file(audio_url, audio_path, cookie_str)
        sample_status["media_downloaded"] = True
        sample_status["audio_ready"] = True
      except Exception as e:
        logger.error(f"音频文件下载失败: {e}")
        sample_status["status"] = "download_failed"
        sample_status["notes"].append(f"audio download failed: {e}")
        write_sample_status(video_dir, sample_status)
        continue
    else:
      logger.info("未发现直接音频流。正在极速抓取无水印视频并压制音轨...")
      temp_video = video_dir / "temp_video.mp4"
      try:
        download_file(video_url, temp_video, cookie_str)
        sample_status["media_downloaded"] = True
        
        # 运行 FFmpeg 提取音频
        cmd_ffmpeg = [
          "ffmpeg", "-y", "-i", str(temp_video),
          "-vn", "-acodec", "libmp3lame", "-q:a", "2",
          str(audio_path)
        ]
        subprocess.run(cmd_ffmpeg, check=True, capture_output=True)
        sample_status["audio_ready"] = True
        logger.info("FFmpeg 音轨转码成功！")
      except Exception as e:
        logger.error(f"媒体流抓取或转码发生异常: {e}")
        sample_status["status"] = "download_failed"
        sample_status["notes"].append(f"ffmpeg extract audio failed: {e}")
        write_sample_status(video_dir, sample_status)
        continue
      finally:
        if temp_video.is_file():
          temp_video.unlink()

    # 格式化数据指标并写入 meta.md
    raw_play = stats.get("play_count", 0)
    play_w = round(raw_play / 10000.0, 2) if raw_play > 0 else 0.0
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

    # ASR 唤醒转写文案
    asr_success = run_whisper_transcription(audio_path, video_dir, args.whisper_path)
    if asr_success:
      sample_status["transcript_ready"] = True
      sample_status["status"] = "success"
      logger.info("语音识别成功生成 transcript.md")
    else:
      (video_dir / "transcript.md").write_text("N/A", encoding="utf-8")
      sample_status["status"] = "asr_failed"
      sample_status["notes"].append("whisper command line failed or skipped")
      logger.warning("语音识别失败或跳过，已写入空占位文件。")

    write_sample_status(video_dir, sample_status)

  logger.info("任务结束！所有下载与解析数据已放置在指定的输出目录中。")

if __name__ == "__main__":
  main()
