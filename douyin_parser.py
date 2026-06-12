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
import shutil
import sys
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any

from external_backends import (
  ExternalBackendError,
  YtDlpItem,
  fetch_aweme_details_with_f2,
  fetch_user_posts_with_f2,
  looks_like_douyin_url,
  parse_cookie_header,
  probe_ytdlp_items,
  run_ytdlp_audio,
)

# 配置全局日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("douyin-fetcher-standalone")

# 配置默认 API 端点，支持环境变量覆盖
PUBLIC_API_BASE_URL = os.getenv("DOUYIN_API_BASE_URL", "https://api.douyin.wtf")
LOCAL_API_BASE_URL = os.getenv("LOCAL_DOUYIN_API_BASE_URL", "http://127.0.0.1:8080")

# 统一全局高仿 User-Agent，避免 UA 不匹配风控
DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
SESSION_COOKIE_NAMES = {
  "sessionid",
  "sessionid_ss",
  "sid_guard",
  "uid_tt",
  "uid_tt_ss",
  "passport_auth_status",
  "passport_auth_status_ss",
}

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
    "-H", f"User-Agent: {DEFAULT_USER_AGENT}",
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


def fetch_single_video_details(video_id: str, cookie_str: str = "") -> dict | None:
  """
  向 iesdouyin 发送请求，抓取单视频 HTML 页面，并从 window._ROUTER_DATA 中解析还原出视频数据。
  """
  ies_url = f"https://www.iesdouyin.com/share/video/{video_id}"
  cmd_fetch = [
    "curl", "-s", "-L",
    "-H", f"User-Agent: {DEFAULT_USER_AGENT}",
    ies_url
  ]
  if cookie_str:
    cmd_fetch += ["-H", f"Cookie: {cookie_str}"]

  try:
    result = subprocess.run(cmd_fetch, capture_output=True, text=True, encoding="utf-8")
    pattern = re.compile(pattern=r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", flags=re.DOTALL)
    find_res = pattern.search(result.stdout)
    if not find_res:
      logger.error(f"在视频 {video_id} 网页源码中未匹配到 window._ROUTER_DATA，可能已被删除或风控限制。")
      return None

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
      logger.error(f"视频 {video_id} 解析成功，但未获取到作品信息。")
      return None

    return original_video_info["item_list"][0]
  except Exception as e:
    logger.error(f"解析视频 {video_id} 网页数据还原失败: {e}")
    return None


def fetch_single_video_details_via_browser(video_id: str) -> dict | None:
  """
  使用 Playwright 本地浏览器打开单视频详情页，在浏览器加载时拦截其详情 API，
  直接获取与 API 原格式兼容的 aweme_detail 数据对象。
  """
  try:
    from playwright.sync_api import sync_playwright
  except ImportError:
    logger.error("未检测到 playwright 库。请先安装: pip install playwright && playwright install chromium")
    return None

  state_file = Path(".auth/state.json")
  detail_url = f"https://www.douyin.com/video/{video_id}"
  logger.info(f"启动 Playwright 本地浏览器解析单视频: {detail_url}")

  detail_data = None
  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    if state_file.is_file():
      context = browser.new_context(
        storage_state=str(state_file),
        user_agent=DEFAULT_USER_AGENT,
        viewport={"width": 1440, "height": 900}
      )
    else:
      context = browser.new_context(
        user_agent=DEFAULT_USER_AGENT,
        viewport={"width": 1440, "height": 900}
      )

    page = context.new_page()
    try:
      def expect_detail_filter(r):
        return "aweme/v1/web/aweme/detail" in r.url and r.status == 200

      with page.expect_response(expect_detail_filter, timeout=25000) as response_info:
        page.goto(detail_url, wait_until="load")
      
      response = response_info.value
      page.wait_for_timeout(800) # 等待网络数据完全传输完毕以防 Protocol error
      body = response.body()
      res_json = json.loads(body.decode("utf-8"))
      detail_data = res_json.get("aweme_detail")
    except Exception as ex:
      logger.error(f"在浏览器中拦截视频 {video_id} 详情 API 失败: {ex}")
      
    context.close()
    browser.close()
    
  return detail_data


def scrape_user_videos_via_browser(sec_user_id: str, count: int) -> tuple[list[dict], str]:
  """
  使用 Playwright 本地浏览器访问博主主页，提取视频 ID 列表；
  然后复用同一个浏览器会话，遍历这些视频 ID，通过网络拦截 /aweme/v1/web/aweme/detail/ 接口，
  还原出与 API 兼容的 aweme_detail 数据结构。
  """
  try:
    from playwright.sync_api import sync_playwright
  except ImportError:
    logger.error("未检测到 playwright 库。请先安装: pip install playwright && playwright install chromium")
    return [], "未命名账号"

  aweme_details = []
  nickname = "未命名账号"
  user_page_url = f"https://www.douyin.com/user/{sec_user_id}"
  state_file = Path(".auth/state.json")

  logger.info(f"启动 Playwright 本地浏览器抓取主页: {user_page_url}")

  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    
    # 使用 state.json 恢复登录态
    if state_file.is_file():
      logger.info(f"正在读取 {state_file.name} 恢复登录态...")
      context = browser.new_context(
        storage_state=str(state_file),
        user_agent=DEFAULT_USER_AGENT,
        viewport={"width": 1440, "height": 900}
      )
    else:
      logger.warning("未检测到登录状态 state.json 文件，将以游客身份访问。")
      context = browser.new_context(
        user_agent=DEFAULT_USER_AGENT,
        viewport={"width": 1440, "height": 900}
      )

    page = context.new_page()
    
    # 访问主页
    try:
      page.goto(user_page_url, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
      logger.warning(f"主页加载超时或异常，尝试继续解析: {e}")

    # 获取博主昵称
    try:
      title = page.title()
      if "的主页" in title:
        nickname = title.split("的主页")[0].strip()
      elif "的个人主页" in title:
        nickname = title.split("的个人主页")[0].strip()
      else:
        nickname = title.split(" - ")[0].strip()
      logger.info(f"解析到博主昵称: {nickname}")
    except Exception as ne:
      logger.warning(f"获取博主昵称异常: {ne}")

    # 滚动收集视频 ID
    video_ids = []
    last_count = 0
    no_change_scrolls = 0
    max_scrolls = 20

    for scroll in range(max_scrolls):
      try:
        locators = page.locator("a[href*='/video/']")
        elem_count = locators.count()
      except Exception:
        elem_count = 0

      current_ids = []
      for idx in range(elem_count):
        try:
          href = locators.nth(idx).get_attribute("href")
          if href:
            match = re.search(r'video/(\d+)', href)
            if match:
              current_ids.append(match.group(1))
        except Exception:
          continue

      for vid in current_ids:
        if vid not in video_ids:
          video_ids.append(vid)

      logger.info(f"第 {scroll+1} 次滚动: 当前已获取到 {len(video_ids)} 个视频 ID (目标: {count})")
      if len(video_ids) >= count:
        break

      if len(video_ids) == last_count:
        no_change_scrolls += 1
        if no_change_scrolls >= 4:
          logger.info("滚动视频无增长，判定已触底。")
          break
      else:
        no_change_scrolls = 0

      last_count = len(video_ids)

      try:
        page.evaluate("window.scrollBy(0, 1000)")
        page.wait_for_timeout(1500)
      except Exception:
        break

    # 截取目标数量
    target_vids = video_ids[:count]
    logger.info(f"✓ 主页视频 ID 提取完毕，准备依次拦截解析以下 {len(target_vids)} 个视频的详情: {target_vids}")

    # 依次解析详情
    for vid in target_vids:
      detail_url = f"https://www.douyin.com/video/{vid}"
      logger.info(f"正在浏览器中加载并解析视频详情: {vid}")
      
      detail_data = None
      try:
        def expect_detail_filter(r):
          return "aweme/v1/web/aweme/detail" in r.url and r.status == 200

        with page.expect_response(expect_detail_filter, timeout=25000) as response_info:
          page.goto(detail_url, wait_until="load")
        
        response = response_info.value
        page.wait_for_timeout(800) # 等待网络数据完全传输完毕以防 Protocol error
        body = response.body()
        res_json = json.loads(body.decode("utf-8"))
        detail_data = res_json.get("aweme_detail")
      except Exception as ex:
        logger.error(f"拦截视频 {vid} 详情 API 失败: {ex}")
        
      if detail_data:
        aweme_details.append(detail_data)
        logger.info(f"✓ 成功捕获视频 {vid} 详情")
      else:
        logger.warning(f"未能捕获视频 {vid} 的详情，已跳过")

    context.close()
    browser.close()

  return aweme_details, nickname


def _coerce_positive_int(value: Any) -> int | None:
  try:
    number = int(value)
  except (TypeError, ValueError):
    return None
  return number if number > 0 else None


def collection_target_count(expected_count: int | None, count_limit: int | None) -> int | None:
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
  if count_limit is None and _coerce_positive_int(expected_count) is None:
    return f"无法获取主页作品总数，不能验证 --all 完整性；本次只拿到 {actual_count} 个"
  target = collection_target_count(expected_count, count_limit)
  if target is not None and actual_count < target:
    if expected_count:
      return f"作品列表不完整：主页显示 {expected_count} 个作品，本次只拿到 {actual_count} 个，目标至少 {target} 个"
    return f"作品列表不完整：目标 {target} 个，本次只拿到 {actual_count} 个"
  if count_limit is None and has_more:
    return f"作品列表分页仍显示 has_more=true，但本次只拿到 {actual_count} 个"
  return ""


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


def add_cookie_header_to_context(context, cookie_str: str) -> None:
  cookies = []
  for name, value in parse_cookie_header(cookie_str).items():
    cookies.append({
      "name": name,
      "value": value,
      "url": "https://www.douyin.com/",
    })
  if cookies:
    context.add_cookies(cookies)


def persist_browser_auth_if_logged_in(context) -> None:
  try:
    cookies = context.cookies("https://www.douyin.com")
  except Exception as exc:
    logger.debug(f"读取浏览器 Cookie 失败，跳过同步: {exc}")
    return

  if not cookies:
    return
  cookie_names = {str(cookie.get("name") or "") for cookie in cookies}
  if not (cookie_names & SESSION_COOKIE_NAMES):
    logger.warning("浏览器上下文未检测到登录态 Cookie，不覆盖 cookie.txt 或 .auth/state.json。")
    return

  cookie_str = "; ".join(
    f"{cookie.get('name')}={cookie.get('value')}"
    for cookie in cookies
    if cookie.get("name") and cookie.get("value")
  )
  Path("cookie.txt").write_text(cookie_str, encoding="utf-8")
  auth_dir = Path(".auth")
  auth_dir.mkdir(exist_ok=True)
  context.storage_state(path=str(auth_dir / "state.json"))
  logger.info("已从浏览器兜底上下文同步登录态到 cookie.txt 和 .auth/state.json。")


def extract_aweme_ids_from_page(page) -> list[str]:
  script = r"""
() => {
  const result = [];
  const seen = new Set();
  const push = (id) => {
    if (!id || seen.has(id)) return;
    seen.add(id);
    result.push(id);
  };
  const collectFrom = (text, pattern) => {
    if (!text) return;
    let match;
    while ((match = pattern.exec(text)) !== null) push(match[1]);
  };
  for (const node of document.querySelectorAll("a[href]")) {
    const href = node.getAttribute("href") || "";
    collectFrom(href, /\/video\/(\d{15,20})/g);
    collectFrom(href, /\/note\/(\d{15,20})/g);
  }
  const html = document.documentElement ? document.documentElement.innerHTML : "";
  collectFrom(html, /"aweme_id":"(\d{15,20})"/g);
  collectFrom(html, /"group_id":"(\d{15,20})"/g);
  return result;
}
"""
  try:
    data = page.evaluate(script)
  except Exception as exc:
    logger.debug(f"从页面提取 aweme_id 失败: {exc}")
    return []
  if not isinstance(data, list):
    return []
  return [str(item) for item in data if item]


def scrape_user_posts_via_browser_fallback(
  sec_user_id: str,
  *,
  cookie_str: str,
  expected_count: int | None,
  count_limit: int | None,
  headless: bool,
  max_scrolls: int,
  idle_rounds: int,
  wait_timeout_seconds: int,
) -> tuple[list[dict[str, Any]], str, list[str]]:
  try:
    from playwright.sync_api import sync_playwright
  except ImportError:
    logger.error("未检测到 playwright 库。请先安装: pip install playwright && playwright install chromium")
    return [], "", []

  target = collection_target_count(expected_count, count_limit)
  target_url = f"https://www.douyin.com/user/{sec_user_id}"
  state_file = Path(".auth/state.json")
  post_aweme_by_id: dict[str, dict[str, Any]] = {}
  id_order: list[str] = []
  id_seen: set[str] = set()
  nickname = ""
  post_api_pages = 0

  def merge_ids(new_ids: list[str]) -> None:
    for aweme_id in new_ids:
      if aweme_id and aweme_id not in id_seen:
        id_seen.add(aweme_id)
        id_order.append(aweme_id)

  logger.warning(
    "F2/API 分页疑似受限，启动浏览器主页兜底。若出现验证码，请在弹出的浏览器中手动完成验证。"
  )

  with sync_playwright() as p:
    browser = p.chromium.launch(
      headless=headless,
      args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
    )
    if state_file.is_file():
      context = browser.new_context(
        storage_state=str(state_file),
        user_agent=DEFAULT_USER_AGENT,
        locale="zh-CN",
        viewport={"width": 1600, "height": 900},
      )
    else:
      context = browser.new_context(
        user_agent=DEFAULT_USER_AGENT,
        locale="zh-CN",
        viewport={"width": 1600, "height": 900},
      )
    add_cookie_header_to_context(context, cookie_str)
    page = context.new_page()

    def handle_response(response) -> None:
      nonlocal post_api_pages
      if "/aweme/v1/web/aweme/post/" not in (response.url or ""):
        return
      try:
        data = response.json()
      except Exception:
        return
      if not isinstance(data, dict):
        return
      page_items = data.get("aweme_list")
      if not isinstance(page_items, list):
        return
      post_api_pages += 1
      extracted_ids: list[str] = []
      for item in page_items:
        if not isinstance(item, dict):
          continue
        aweme_id = str(item.get("aweme_id") or item.get("video_id") or "").strip()
        if not aweme_id:
          continue
        extracted_ids.append(aweme_id)
        post_aweme_by_id[aweme_id] = item
      merge_ids(extracted_ids)

    page.on("response", handle_response)
    try:
      page.goto(target_url, wait_until="domcontentloaded", timeout=max(30, wait_timeout_seconds) * 1000)
    except Exception as exc:
      logger.warning(f"浏览器主页加载异常，继续尝试从当前页面采集: {exc}")

    try:
      title = page.title()
      if "验证码" in title and not headless:
        logger.warning("检测到验证码页面，请手动完成验证；程序会继续等待页面恢复。")
        deadline = page.context.pages[0].evaluate("Date.now()") + wait_timeout_seconds * 1000
        while page.evaluate("Date.now()") < deadline:
          if "验证码" not in page.title():
            break
          page.wait_for_timeout(1000)
      if "的主页" in title:
        nickname = title.split("的主页")[0].strip()
      elif "的个人主页" in title:
        nickname = title.split("的个人主页")[0].strip()
      elif title:
        nickname = title.split(" - ")[0].strip()
    except Exception:
      pass

    if not headless:
      logger.warning("浏览器窗口已打开；如出现登录弹窗或验证码，请先处理，程序会等待主页数据出现。")
      try:
        warmup_deadline = page.evaluate("Date.now()") + min(wait_timeout_seconds, 90) * 1000
        while page.evaluate("Date.now()") < warmup_deadline:
          merge_ids(extract_aweme_ids_from_page(page))
          if post_aweme_by_id or id_order:
            break
          page.wait_for_timeout(1000)
      except Exception:
        pass

    stable_rounds = 0
    for scroll_index in range(max(1, max_scrolls)):
      before = len(id_order) + len(post_aweme_by_id)
      merge_ids(extract_aweme_ids_from_page(page))
      logger.info(
        "浏览器兜底滚动 %s/%s：ID=%s，带详情=%s，目标=%s",
        scroll_index + 1,
        max_scrolls,
        len(id_order),
        len(post_aweme_by_id),
        target or "unknown",
      )
      if target is not None and len(post_aweme_by_id) >= target:
        break
      try:
        page.mouse.wheel(0, 3800)
        page.wait_for_timeout(1200)
      except Exception:
        break
      after = len(id_order) + len(post_aweme_by_id)
      if after <= before:
        stable_rounds += 1
      else:
        stable_rounds = 0
      if target is None and stable_rounds >= max(1, idle_rounds):
        break

    try:
      page.wait_for_timeout(1000)
    except Exception:
      pass
    persist_browser_auth_if_logged_in(context)
    context.close()
    browser.close()

  browser_items = [
    post_aweme_by_id[aweme_id]
    for aweme_id in id_order
    if aweme_id in post_aweme_by_id
  ]
  for aweme_id, item in post_aweme_by_id.items():
    if aweme_id not in id_seen:
      browser_items.append(item)

  logger.warning(
    "浏览器兜底采集结束：主页接口页数=%s，ID=%s，完整元数据=%s",
    post_api_pages,
    len(id_order),
    len(browser_items),
  )
  return browser_items, nickname, id_order


def download_file(url: str, dest_path: Path, cookie: str = ""):
  """
  使用系统 curl 工具下载媒体资源原档。
  """
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
  whisper_bin = shutil.which("whisper")
  if whisper_bin:
    try:
      logger.info("检测到全局 whisper 指令，开始在后台运行 ASR 转写流程...")
      
      cmd = [
        whisper_bin, str(audio_path),
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
      logger.error(f"Whisper ASR 转写运行时发生异常: {e}")
  else:
    logger.warning("系统 PATH 中没有发现可用的全局 whisper 命令行工具，跳过语音转写。")
  
  return False


def sanitize_folder_name(value: str) -> str:
  safe = re.sub(r'[\\/:*?"<>| ]', "_", value or "未命名账号")
  return safe.strip("._") or "未命名账号"


def is_completed_video_dir(video_dir: Path) -> bool:
  status_path = video_dir / "collection-status.json"
  audio_path = video_dir / "audio.mp3"
  video_path = video_dir / "video.mp4"
  if (
    not status_path.is_file()
    or not video_path.is_file()
    or video_path.stat().st_size <= 0
    or not audio_path.is_file()
    or audio_path.stat().st_size <= 0
  ):
    return False
  try:
    status = json.loads(status_path.read_text(encoding="utf-8"))
  except Exception:
    return False
  return status.get("status") == "success"


def extract_author_nickname(aweme: dict[str, Any], default: str = "未命名账号") -> str:
  author = aweme.get("author") if isinstance(aweme.get("author"), dict) else {}
  return (
    author.get("nickname")
    or aweme.get("nickname")
    or aweme.get("author_name")
    or default
  )


def get_aweme_media_urls(aweme: dict[str, Any]) -> tuple[str, str]:
  audio_url = ""
  music_info = aweme.get("music", {})
  if isinstance(music_info, dict) and music_info.get("play_url"):
    play_url = music_info["play_url"]
    if isinstance(play_url, dict):
      url_list = play_url.get("url_list")
      if url_list:
        audio_url = url_list[0]
      elif play_url.get("uri"):
        audio_url = play_url["uri"]

  video_url = ""
  video_info = aweme.get("video", {})
  if isinstance(video_info, dict):
    play_addr = video_info.get("play_addr") or video_info.get("play_addr_h264")
    if isinstance(play_addr, dict):
      v_url_list = play_addr.get("url_list")
      if v_url_list:
        video_url = v_url_list[0].replace("playwm", "play")
    bit_rate = video_info.get("bit_rate")
    if not video_url and isinstance(bit_rate, list) and bit_rate:
      first_rate = bit_rate[0]
      if isinstance(first_rate, dict):
        br_play_addr = first_rate.get("play_addr")
        if isinstance(br_play_addr, dict) and br_play_addr.get("url_list"):
          video_url = br_play_addr["url_list"][0].replace("playwm", "play")

  return audio_url, video_url


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


def finalize_transcript(
  audio_path: Path,
  video_dir: Path,
  sample_status: dict[str, Any],
  *,
  skip_asr: bool,
  whisper_path: str,
) -> None:
  if skip_asr:
    transcript_path = video_dir / "transcript.md"
    if not transcript_path.exists():
      transcript_path.write_text("N/A", encoding="utf-8")
    sample_status["transcript_ready"] = False
    sample_status["status"] = "success"
    sample_status["notes"].append("asr skipped by --skip-asr")
    logger.info("已跳过 ASR，下载状态记为 success。")
    return

  asr_success = run_whisper_transcription(audio_path, video_dir, whisper_path)
  if asr_success:
    sample_status["transcript_ready"] = True
    sample_status["status"] = "success"
    logger.info("语音识别成功生成 transcript.md")
  else:
    (video_dir / "transcript.md").write_text("N/A", encoding="utf-8")
    sample_status["status"] = "asr_failed"
    sample_status["notes"].append("whisper command line failed or skipped")
    logger.warning("语音识别失败或跳过，已写入空占位文件。")


def extract_audio_from_video(video_path: Path, audio_path: Path) -> None:
  cmd_ffmpeg = [
    "ffmpeg", "-y", "-i", str(video_path),
    "-vn", "-acodec", "libmp3lame", "-q:a", "2",
    str(audio_path)
  ]
  subprocess.run(cmd_ffmpeg, check=True, capture_output=True)


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
) -> dict[str, int]:
  account_folder = sanitize_folder_name(nickname)
  stats_summary = {"success": 0, "failed": 0, "skipped": 0}

  logger.info(f"共获取到 {len(aweme_list)} 个作品，开始依次处理媒体提取与台词转写...")

  for i, aweme in enumerate(aweme_list):
    aweme_id = str(aweme.get("aweme_id") or aweme.get("video_id") or "").strip()
    if not aweme_id:
      logger.warning("跳过缺少 aweme_id 的作品。")
      stats_summary["failed"] += 1
      continue

    desc = aweme.get("desc") or aweme.get("title") or "无标题"
    video_dir = output_base / account_folder / aweme_id
    video_dir.mkdir(parents=True, exist_ok=True)
    audio_path = video_dir / "audio.mp3"
    video_path = video_dir / "video.mp4"

    if is_completed_video_dir(video_dir):
      logger.info(f"[{i+1}/{len(aweme_list)}] 跳过已完成作品: {aweme_id}")
      stats_summary["skipped"] += 1
      continue

    sample_status = {
      "video_id": aweme_id,
      "status": "metadata_only",
      "metadata": True,
      "media_downloaded": False,
      "audio_ready": False,
      "video_ready": False,
      "transcript_ready": False,
      "source_path": source_path,
      "notes": []
    }
    write_sample_status(video_dir, sample_status)

    audio_url, video_url = get_aweme_media_urls(aweme)
    if not video_url:
      logger.warning(f"视频ID {aweme_id} 缺少可用的视频播放资源链接，跳过")
      sample_status["status"] = "download_failed"
      sample_status["notes"].append("no video play url found")
      write_sample_status(video_dir, sample_status)
      stats_summary["failed"] += 1
      continue

    logger.info(f"[{i+1}/{len(aweme_list)}] 正在拉取作品: {aweme_id} | 标题: {str(desc)[:15]}...")

    logger.info("拉取无水印视频流...")
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
      logger.error(f"视频文件下载失败: {e}")
      sample_status["status"] = "download_failed"
      sample_status["notes"].append(f"video download failed: {e}")
      write_sample_status(video_dir, sample_status)
      stats_summary["failed"] += 1
      continue

    if audio_url:
      logger.info("拉取无水印音频流...")
      try:
        download_file(audio_url, audio_path, cookie_str)
        sample_status["audio_ready"] = True
      except KeyboardInterrupt:
        sample_status["status"] = "interrupted"
        sample_status["notes"].append("interrupted during audio download")
        write_sample_status(video_dir, sample_status)
        raise
      except Exception as e:
        logger.error(f"音频文件下载失败: {e}")
        sample_status["status"] = "download_failed"
        sample_status["notes"].append(f"audio download failed: {e}")
        write_sample_status(video_dir, sample_status)
        stats_summary["failed"] += 1
        continue
    else:
      logger.info("未发现直接音频流。正在从 video.mp4 提取音轨...")
      try:
        extract_audio_from_video(video_path, audio_path)
        sample_status["audio_ready"] = True
        logger.info("FFmpeg 音轨转码成功！")
      except KeyboardInterrupt:
        sample_status["status"] = "interrupted"
        sample_status["notes"].append("interrupted during video download or ffmpeg")
        write_sample_status(video_dir, sample_status)
        raise
      except Exception as e:
        logger.error(f"媒体流抓取或转码发生异常: {e}")
        sample_status["status"] = "download_failed"
        sample_status["notes"].append(f"ffmpeg extract audio failed: {e}")
        write_sample_status(video_dir, sample_status)
        stats_summary["failed"] += 1
        continue

    write_meta_file(video_dir, aweme, nickname)
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
  items: list[YtDlpItem],
  *,
  output_base: Path,
  whisper_path: str,
  skip_asr: bool,
) -> dict[str, int]:
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
        logger.info(f"跳过已完成外部作品: {media_id}")
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
        logger.error(f"外部作品归一化失败 {media_id}: {e}")
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
        logger.warning("清理 yt-dlp 临时媒体目录失败 %s: %s", root, exc)
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

def main():
  parser = argparse.ArgumentParser(description="抖音视频/主页无水印极速解析与台词转录工具 (独立开源版)")
  parser.add_argument("--url", required=True, help="抖音视频分享链接 或 个人主页链接")
  parser.add_argument("--count", type=int, default=3, help="抓取主页最近的视频数量；0 或 --all 表示全量")
  parser.add_argument("--all", action="store_true", help="下载博主主页全部可访问作品")
  parser.add_argument(
    "--backend",
    choices=["auto", "f2", "yt-dlp", "legacy"],
    default="auto",
    help="抓取/下载后端。auto: 主页优先 F2，普通链接优先 yt-dlp",
  )
  parser.add_argument("--account-name", default="", help="自定义博主文件夹命名")
  parser.add_argument("--output-dir", default="downloads", help="本地输出路径")
  parser.add_argument("--cookie", default="", help="直接传入 Cookie 字符串")
  parser.add_argument("--cookie-file", default="", help="读取本地 Cookie 的 txt 文件路径")
  parser.add_argument("--whisper-path", default="", help="可选：本地自定义 Whisper ASR 执行脚本路径")
  parser.add_argument("--skip-asr", action="store_true", help="跳过 Whisper 转写，适合全量下载测试")
  parser.add_argument("--keep-video", action="store_true", help="兼容旧参数；当前默认保存 video.mp4")
  parser.add_argument("--list-only", action="store_true", help="只拉取作品列表并打印 aweme_id，不下载媒体")
  parser.add_argument("--no-install-f2", action="store_true", help="F2 不存在时不自动创建 .external/venv-f2")
  parser.add_argument(
    "--browser-fallback",
    action=argparse.BooleanOptionalAction,
    default=True,
    help="F2/API 分页不完整时启动浏览器主页兜底；默认开启",
  )
  parser.add_argument("--browser-headless", action="store_true", help="浏览器兜底使用 headless 模式；默认弹窗方便手动过验证")
  parser.add_argument("--browser-max-scrolls", type=int, default=240, help="浏览器兜底最大滚动次数")
  parser.add_argument("--browser-idle-rounds", type=int, default=8, help="未知总量时连续无增长多少轮后停止")
  parser.add_argument("--browser-wait-timeout", type=int, default=600, help="浏览器兜底等待验证码/页面恢复的秒数")
  parser.add_argument(
    "--detail-fill",
    action=argparse.BooleanOptionalAction,
    default=True,
    help="浏览器只拿到作品 ID 时，用 F2 单作品 detail API 补元数据；默认开启",
  )
  args = parser.parse_args()

  cookie_str = load_cookie(args.cookie, args.cookie_file)
  if not cookie_str and not args.cookie and not args.cookie_file:
    # 默认自动加载当前目录下的 cookie.txt
    default_cookie_path = Path("cookie.txt")
    if default_cookie_path.is_file():
      logger.info("检测到本地 cookie.txt，正在自动加载登录态...")
      cookie_str = load_cookie(cookie_file="cookie.txt")

  output_base = Path(args.output_dir)
  output_base.mkdir(parents=True, exist_ok=True)

  logger.info(f"开始解析链接: {args.url}")

  # 1. 链接探查与重定向获取
  logger.info("模拟跳转以探查链接类型，识别主页与单视频...")
  cmd_redirect = [
    "curl", "-s", "-I", "-L",
    "-H", f"User-Agent: {DEFAULT_USER_AGENT}",
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
  count_limit = None if args.all or args.count <= 0 else args.count
  effective_url = final_url or args.url

  # 非抖音链接或显式 yt-dlp 后端：交给 yt-dlp，当前项目只做归一化与转写。
  if args.backend == "yt-dlp" or (
    args.backend == "auto" and not looks_like_douyin_url(effective_url)
  ):
    try:
      if args.list_only:
        ytdlp_probe_items = probe_ytdlp_items(
          url=args.url,
          cookie_str=cookie_str,
          use_douyin_cookie=looks_like_douyin_url(effective_url),
        )
        print(json.dumps({
          "count": len(ytdlp_probe_items),
          "ids": [item.media_id for item in ytdlp_probe_items],
          "items": [
            {
              "id": item.media_id,
              "title": item.title,
              "uploader": item.uploader,
              "extractor": item.extractor,
              "url": item.webpage_url,
            }
            for item in ytdlp_probe_items
          ],
        }, ensure_ascii=False, indent=2))
        return

      ytdlp_items = run_ytdlp_audio(
        url=args.url,
        cookie_str=cookie_str,
        use_douyin_cookie=looks_like_douyin_url(effective_url),
      )
      if not ytdlp_items:
        logger.error("yt-dlp 未返回任何可归一化的媒体文件。")
        sys.exit(1)
      summary = process_ytdlp_items(
        ytdlp_items,
        output_base=output_base,
        whisper_path=args.whisper_path,
        skip_asr=args.skip_asr,
      )
      logger.info(
        "yt-dlp 后端完成：成功 %s / 跳过 %s / 失败 %s",
        summary["success"], summary["skipped"], summary["failed"],
      )
      return
    except ExternalBackendError as exc:
      logger.error(f"yt-dlp 后端失败: {exc}")
      sys.exit(1)

  if sec_user_id:
    # 情况 A：输入为主页链接
    logger.info(f"检测到主页分享链接 (sec_uid: {sec_user_id})")

    if args.backend in ("auto", "f2"):
      try:
        logger.info("正在通过 F2 后端分页拉取主页作品列表...")
        f2_result = fetch_user_posts_with_f2(
          sec_user_id=sec_user_id,
          count_limit=count_limit,
          cookie_str=cookie_str,
          user_agent=DEFAULT_USER_AGENT,
          auto_install=not args.no_install_f2,
        )
        aweme_list = f2_result.aweme_list
        logger.info(
          "F2 后端拉取完成：%s 页，%s 个作品，主页总数=%s，has_more=%s",
          f2_result.pages,
          len(aweme_list),
          f2_result.expected_count,
          f2_result.has_more,
        )
        if f2_result.nickname:
          nickname = args.account_name or f2_result.nickname
        for aweme in aweme_list:
          candidate = extract_author_nickname(aweme, "")
          if candidate:
            nickname = args.account_name or candidate
            break

        if not aweme_list:
          logger.error("F2 后端未返回任何作品。请检查 Cookie 是否有效或稍后重试。")
          sys.exit(1)

        source_path = "f2"
        diagnostics = list(f2_result.page_diagnostics)
        if any(item.get("login_tip") for item in diagnostics):
          logger.warning("抖音接口返回登录提示：当前 Cookie 可能是游客态或登录态不足。")
        incomplete_reason = collection_incomplete_reason(
          len(aweme_list),
          expected_count=f2_result.expected_count,
          count_limit=count_limit,
          has_more=f2_result.has_more,
        )

        if incomplete_reason:
          logger.warning("F2 作品列表不完整：%s", incomplete_reason)
          if args.browser_fallback:
            browser_items, browser_nickname, browser_ids = scrape_user_posts_via_browser_fallback(
              sec_user_id,
              cookie_str=cookie_str,
              expected_count=f2_result.expected_count,
              count_limit=count_limit,
              headless=args.browser_headless,
              max_scrolls=args.browser_max_scrolls,
              idle_rounds=args.browser_idle_rounds,
              wait_timeout_seconds=args.browser_wait_timeout,
            )
            if browser_nickname:
              nickname = args.account_name or browser_nickname
            aweme_list = merge_aweme_lists_by_id(
              aweme_list,
              browser_items,
              preferred_order=browser_ids,
            )
            source_path = "f2+browser"
            diagnostics.append({
              "backend": "browser_fallback",
              "items": len(browser_items),
              "ids": len(browser_ids),
            })
            if args.detail_fill and browser_ids:
              existing_ids = {
                str(item.get("aweme_id") or item.get("video_id") or "").strip()
                for item in aweme_list
                if isinstance(item, dict)
              }
              missing_detail_ids = [
                aweme_id for aweme_id in browser_ids
                if aweme_id and aweme_id not in existing_ids
              ]
              if missing_detail_ids:
                logger.warning(
                  "浏览器拿到 %s 个缺失元数据的作品 ID，开始用 F2 detail API 回补。",
                  len(missing_detail_ids),
                )
                detail_result = fetch_aweme_details_with_f2(
                  aweme_ids=missing_detail_ids,
                  sec_user_id=sec_user_id,
                  cookie_str=cookie_str,
                  user_agent=DEFAULT_USER_AGENT,
                  auto_install=not args.no_install_f2,
                )
                aweme_list = merge_aweme_lists_by_id(
                  aweme_list,
                  detail_result.aweme_list,
                  preferred_order=browser_ids,
                )
                source_path = "f2+browser+detail"
                diagnostics.append({
                  "backend": "f2_detail_fill",
                  "requested": detail_result.requested,
                  "items": len(detail_result.aweme_list),
                  "errors": len(detail_result.errors),
                })
            incomplete_reason = collection_incomplete_reason(
              len(aweme_list),
              expected_count=f2_result.expected_count,
              count_limit=count_limit,
              has_more=False,
            )

        if args.list_only:
          print_list_probe(
            aweme_list,
            source=source_path,
            expected_count=f2_result.expected_count,
            complete=not bool(incomplete_reason),
            pages=f2_result.pages,
            diagnostics=diagnostics,
          )
          if incomplete_reason:
            logger.error("列表探测未通过完整性校验：%s", incomplete_reason)
            sys.exit(1)
          return

        if incomplete_reason:
          logger.error(
            "拒绝执行全量下载：%s。请保持浏览器兜底窗口打开并完成验证，或稍后重试。",
            incomplete_reason,
          )
          sys.exit(1)

        summary = process_aweme_list(
          aweme_list,
          nickname=nickname,
          output_base=output_base,
          cookie_str=cookie_str,
          whisper_path=args.whisper_path,
          skip_asr=args.skip_asr,
          keep_video=args.keep_video,
          source_path=source_path,
        )
        logger.info(
          "F2 后端任务结束：成功 %s / 跳过 %s / 失败 %s / 总计 %s",
          summary["success"],
          summary["skipped"],
          summary["failed"],
          len(aweme_list),
        )
        return
      except ExternalBackendError as exc:
        if args.backend == "f2" or count_limit is None:
          logger.error(f"F2 后端失败: {exc}")
          sys.exit(1)
        logger.warning(f"F2 后端不可用，回退 legacy 逻辑: {exc}")

    if args.all or args.count <= 0:
      logger.error("legacy 后端不支持 --all；请使用 --backend f2 或修复 F2 环境。")
      sys.exit(1)
    
    # 1. 尝试使用公共/本地 API 接口拉取主页作品
    logger.info(f"正在通过 API 拉取该博主最近的 {args.count} 个作品列表...")
    res_posts = fetch_user_posts(sec_user_id, args.count, cookie_str)
    
    post_data = res_posts.get("data", {}) if res_posts else {}
    if post_data and post_data.get("aweme_list"):
      logger.info("✓ 通过 API 成功拉取到主页作品列表")
      aweme_list = post_data["aweme_list"]
      for aweme in aweme_list:
        author = aweme.get("author", {})
        if author and author.get("nickname"):
          nickname = author.get("nickname")
          break
    else:
      # 2. 如果 API 被拦截或失败，使用 Playwright 浏览器 DOM 提取与 API 拦截兜底
      logger.warning("API 拉取主页失败，正在启动本地浏览器 DOM 提取与 API 拦截兜底...")
      browser_details, scraped_nickname = scrape_user_videos_via_browser(sec_user_id, args.count)
      if scraped_nickname and scraped_nickname != "未命名账号":
        nickname = scraped_nickname
        
      if browser_details:
        logger.info(f"✓ 通过本地浏览器成功提取并拦截解析了 {len(browser_details)} 个视频的详情")
        aweme_list = browser_details
      else:
        logger.error("本地浏览器提取博主视频详情失败，结束处理。")
        sys.exit(1)
  else:
    if args.backend == "f2":
      logger.error("F2 后端当前仅用于博主主页作品分页；单视频请使用 auto/legacy/yt-dlp。")
      sys.exit(1)

    # 情况 B：输入为单视频链接
    logger.info("按单视频分享链接进行本地免 Cookie HTML 解密...")
    video_id_match = re.search(r'video/(\d+)', final_url)
    if not video_id_match:
      video_id_match = re.search(r'/(\d+)(?:\?|$)', final_url)

    if not video_id_match:
      logger.error(f"无法从最终重定向链接中提取出视频数字 ID: {final_url}")
      sys.exit(1)

    video_id = video_id_match.group(1)
    logger.info(f"成功提取视频 ID: {video_id}。开始解析详情...")
    
    # 优先尝试免 Cookie HTML 解密
    video_data = fetch_single_video_details(video_id, cookie_str)
    if not video_data:
      logger.warning("通过免 Cookie HTML 解密单视频失败，尝试使用本地浏览器拦截解析...")
      video_data = fetch_single_video_details_via_browser(video_id)
      
    if video_data:
      aweme_list = [video_data]
      nickname = video_data.get("author", {}).get("nickname") or video_data.get("nickname") or "未命名账号"
    else:
      logger.error("解析单视频网页数据失败，结束处理。")
      sys.exit(1)

  if not aweme_list:
    logger.error("最终获取到的可用视频列表为空，结束处理。")
    sys.exit(1)

  if args.list_only:
    print_list_probe(aweme_list)
    return

  summary = process_aweme_list(
    aweme_list,
    nickname=nickname,
    output_base=output_base,
    cookie_str=cookie_str,
    whisper_path=args.whisper_path,
    skip_asr=args.skip_asr,
    keep_video=args.keep_video,
    source_path="legacy",
  )
  logger.info(
    "任务结束：成功 %s / 跳过 %s / 失败 %s / 总计 %s",
    summary["success"],
    summary["skipped"],
    summary["failed"],
    len(aweme_list),
  )

if __name__ == "__main__":
  main()
