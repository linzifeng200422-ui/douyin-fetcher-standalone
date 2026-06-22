# -*- coding: utf-8 -*-
"""抖音下载器 - 浏览器兜底与拦截适配后端。"""
from __future__ import annotations

import os
import re
import json
import time
from pathlib import Path
from typing import Any

from utils.cookie_utils import parse_cookie_header, sanitize_cookies
from utils.logger import setup_logger
from utils.helpers import collection_target_count

logger = setup_logger("BrowserFallback")

SESSION_COOKIE_NAMES = {
  "sessionid",
  "sessionid_ss",
  "sid_guard",
  "uid_tt",
  "uid_tt_ss",
  "passport_auth_status",
  "passport_auth_status_ss",
}

DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def cookie_header_has_login(cookie_str: str) -> bool:
  cookie_names = set(parse_cookie_header(cookie_str).keys())
  return bool(cookie_names & SESSION_COOKIE_NAMES)


def playwright_cookies_have_login(cookies: list[dict[str, Any]]) -> bool:
  cookie_names = {str(cookie.get("name") or "") for cookie in cookies or []}
  return bool(cookie_names & SESSION_COOKIE_NAMES)


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
  if not playwright_cookies_have_login(cookies):
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
  trust_expected_count: bool = True,
  headless: bool,
  max_scrolls: int,
  idle_rounds: int,
  wait_timeout_seconds: int,
  require_login: bool,
) -> tuple[list[dict[str, Any]], str, list[str]]:
  try:
    from playwright.sync_api import sync_playwright
  except ImportError:
    logger.error("未检测到 playwright 库。请先安装: pip install playwright && playwright install chromium")
    return [], "", []

  target = collection_target_count(
    expected_count if trust_expected_count else None,
    count_limit,
  )
  target_url = f"https://www.douyin.com/user/{sec_user_id}"
  state_file = Path(".auth/state.json")
  post_aweme_by_id: dict[str, dict[str, Any]] = {}
  id_order: list[str] = []
  id_seen: set[str] = set()
  nickname = ""
  post_api_pages = 0
  post_api_login_tip_seen = False
  post_api_verify_seen = False

  def merge_ids(new_ids: list[str]) -> None:
    for aweme_id in new_ids:
      if aweme_id and aweme_id not in id_seen:
        id_seen.add(aweme_id)
        id_order.append(aweme_id)

  logger.warning(
    "F2/API 分页疑似受限，启动浏览器主页兜底。若出现验证码，请在弹出的浏览器中手动完成验证。"
  )

  with sync_playwright() as p:
    auth_dir = Path(".auth")
    auth_dir.mkdir(exist_ok=True)
    if headless:
      browser = p.chromium.launch(
        headless=True,
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
      close_browser = browser.close
    else:
      context = p.chromium.launch_persistent_context(
        user_data_dir=str(auth_dir.resolve()),
        headless=False,
        user_agent=DEFAULT_USER_AGENT,
        locale="zh-CN",
        viewport={"width": 1600, "height": 900},
        args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
      )
      close_browser = lambda: None
    add_cookie_header_to_context(context, cookie_str)
    page = context.new_page()

    def handle_response(response) -> None:
      nonlocal post_api_pages, post_api_login_tip_seen, post_api_verify_seen
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
      if isinstance(data.get("not_login_module"), dict) and (
        (data.get("not_login_module") or {}).get("guide_login_tip_exist")
      ):
        post_api_login_tip_seen = True
      if data.get("verify_ticket"):
        post_api_verify_seen = True
      extracted_ids: list[str] = []
      for item in page_items:
        if not isinstance(item, dict):
          continue
        aweme_id = str(item.get("aweme_id") or item.get("video_id") or "").strip()
        if not aweme_id:
          continue
        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        item_sec_uid = str(author.get("sec_uid") or "").strip()
        if sec_user_id and item_sec_uid and item_sec_uid != sec_user_id:
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

    if require_login and headless:
      logger.warning("当前 Cookie 疑似游客态，但浏览器兜底运行在 headless 模式，无法人工登录/验证。")

    if not headless:
      logger.warning("浏览器窗口已打开；如出现登录弹窗或验证码，请先处理，程序会等待登录态和主页数据出现。")
      login_wait_deadline = time.monotonic() + max(30, wait_timeout_seconds)
      last_login_log = 0.0
      while require_login and time.monotonic() < login_wait_deadline:
        try:
          current_cookies = context.cookies("https://www.douyin.com")
        except Exception:
          current_cookies = []
        if playwright_cookies_have_login(current_cookies):
          logger.warning("检测到登录态 Cookie，重新加载目标主页并开始采集。")
          persist_browser_auth_if_logged_in(context)
          try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
          except Exception as exc:
            logger.warning(f"登录后重新加载目标主页异常，继续采集: {exc}")
          break
        now = time.monotonic()
        if now - last_login_log >= 10:
          logger.warning("仍未检测到登录态 Cookie；请在浏览器中完成扫码登录/验证码。")
          last_login_log = now
        page.wait_for_timeout(1000)

      try:
        warmup_deadline = page.evaluate("Date.now()") + min(wait_timeout_seconds, 90) * 1000
        while page.evaluate("Date.now()") < warmup_deadline:
          merge_ids(extract_aweme_ids_from_page(page))
          if post_aweme_by_id or (id_order and not require_login):
            break
          if id_order and require_login:
            try:
              if playwright_cookies_have_login(context.cookies("https://www.douyin.com")):
                break
            except Exception:
              pass
          page.wait_for_timeout(1000)
      except Exception:
        pass

    stable_rounds = 0
    for scroll_index in range(max(1, max_scrolls)):
      before = len(id_order) + len(post_aweme_by_id)
      merge_ids(extract_aweme_ids_from_page(page))
      logger.info(
        "浏览器兜底滚动 %s/%s：裸ID=%s，带详情=%s，目标=%s",
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
        page.wait_for_timeout(400)
        page.evaluate("window.scrollBy(0, 4000)")
        page.wait_for_timeout(400)
        page.keyboard.press("End")
        page.wait_for_timeout(400)
      except Exception:
        break
      after = len(id_order) + len(post_aweme_by_id)
      if after <= before:
        stable_rounds += 1
      else:
        stable_rounds = 0
      if (
        target is not None
        and len(id_order) >= target
        and stable_rounds >= max(2, idle_rounds)
      ):
        logger.info(
          "浏览器兜底 ID 数已达到目标且连续 %s 轮无增长，停止滚动并进入 detail 回补。",
          stable_rounds,
        )
        break
      if target is None and stable_rounds >= max(1, idle_rounds):
        break

    try:
      page.wait_for_timeout(1000)
    except Exception:
      pass
    persist_browser_auth_if_logged_in(context)
    context.close()
    close_browser()

  browser_items = [
    post_aweme_by_id[aweme_id]
    for aweme_id in id_order
    if aweme_id in post_aweme_by_id
  ]
  for aweme_id, item in post_aweme_by_id.items():
    if aweme_id not in id_seen:
      browser_items.append(item)

  logger.warning(
    "浏览器兜底采集结束：主页接口页数=%s，裸ID=%s，完整元数据=%s，login_tip=%s，verify=%s",
    post_api_pages,
    len(id_order),
    len(browser_items),
    post_api_login_tip_seen,
    post_api_verify_seen,
  )
  return browser_items, nickname, id_order


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
    
    try:
      page.goto(user_page_url, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
      logger.warning(f"主页加载超时或异常，尝试继续解析: {e}")

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

    target_vids = video_ids[:count]
    logger.info(f"✓ 主页视频 ID 提取完毕，准备依次拦截解析以下 {len(target_vids)} 个视频的详情: {target_vids}")

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
        page.wait_for_timeout(800)
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
