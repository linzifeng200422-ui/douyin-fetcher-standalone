# -*- coding: utf-8 -*-
"""抖音下载器 - 纯 YAML 驱动的主程序。"""
import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import ConfigLoader
from utils.logger import setup_logger
from utils.cookie_utils import parse_cookie_header
from utils.helpers import collection_incomplete_reason
from core.url_parser import resolve_share_url
from core.user_downloader import merge_aweme_lists_by_id, process_aweme_list, process_ytdlp_items

from backends.f2_backend import fetch_user_posts_with_f2, fetch_aweme_details_with_f2
from backends.browser_fallback import scrape_user_posts_via_browser_fallback
from backends.ytdlp_backend import run_ytdlp_audio, probe_ytdlp_items, looks_like_douyin_url
from backends.dy_downloader_backend import run_dy_downloader_backend, ExternalBackendError

logger = setup_logger("CLI")

SESSION_COOKIE_NAMES = {
    "sessionid",
    "sessionid_ss",
    "sid_guard",
    "uid_tt",
    "uid_tt_ss",
    "passport_auth_status",
    "passport_auth_status_ss",
}


def cookie_header_has_login(cookie_str: str) -> bool:
    cookie_names = set(parse_cookie_header(cookie_str).keys())
    return bool(cookie_names & SESSION_COOKIE_NAMES)


def fetch_api_json(base_url: str, endpoint: str, params: dict, source_label: str, cookie: str = "") -> dict | None:
    DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
    PUBLIC_API_BASE_URL = os.getenv("DOUYIN_API_BASE_URL", "https://api.douyin.wtf")
    LOCAL_API_BASE_URL = os.getenv("LOCAL_DOUYIN_API_BASE_URL", "http://127.0.0.1:8080")
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
    DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("未检测到 playwright 库。请先安装: pip install playwright && playwright install chromium")
        return None

    DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
            page.wait_for_timeout(800)
            body = response.body()
            res_json = json.loads(body.decode("utf-8"))
            detail_data = res_json.get("aweme_detail")
        except Exception as ex:
            logger.error(f"在浏览器中拦截视频 {video_id} 详情 API 失败: {ex}")
            
        context.close()
        browser.close()
        
    return detail_data


def scrape_user_videos_via_browser(sec_user_id: str, count: int) -> tuple[list[dict], str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("未检测到 playwright 库。请先安装: pip install playwright && playwright install chromium")
        return [], "未命名账号"

    DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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


async def main_async(config: ConfigLoader):
    urls = config.get_links()
    if not urls:
        logger.warning("配置文件中未配置有效 link，优雅退出。")
        return

    cookie_dict = config.get_cookies()
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_dict.items()) if cookie_dict else ""
    
    if not cookie_str:
        default_cookie_path = Path("cookie.txt")
        if default_cookie_path.is_file():
            logger.info("检测到本地 cookie.txt，正在自动加载登录态...")
            try:
                cookie_str = default_cookie_path.read_text(encoding="utf-8").strip()
            except Exception as e:
                logger.error(f"读取 cookie.txt 失败: {e}")

    output_dir = config.get("path") or "./Downloaded/"
    output_base = Path(output_dir)
    output_base.mkdir(parents=True, exist_ok=True)

    backend = config.get("backend") or "auto"
    video_quality = config.get("video_quality") or "resolution"
    video_orientation = config.get("video_orientation") or "auto"

    f2_cfg = config.get("f2") or {}
    auto_install_f2 = f2_cfg.get("auto_install", True)
    detail_fill = f2_cfg.get("detail_fill", True)

    browser_cfg = config.get("browser_fallback") or {}
    browser_fallback_enabled = browser_cfg.get("enabled", True)
    browser_headless = browser_cfg.get("headless", False)
    browser_max_scrolls = browser_cfg.get("max_scrolls", 240)
    browser_idle_rounds = browser_cfg.get("idle_rounds", 8)
    browser_wait_timeout = browser_cfg.get("wait_timeout_seconds", 600)

    transcript_cfg = config.get("transcript") or {}
    skip_asr = not transcript_cfg.get("enabled", False)
    whisper_path = transcript_cfg.get("whisper_path", "")
    keep_video = True

    number_cfg = config.get("number") or {}
    post_count = int(number_cfg.get("post", 0) or 0)
    count_limit = None if post_count <= 0 else post_count

    logger.info(f"抖音下载器启动，检测到 {len(urls)} 个链接待处理")
    
    for idx, url in enumerate(urls, 1):
        logger.info(f"开始处理第 {idx}/{len(urls)} 个链接: {url}")
        
        final_url, sec_user_id = resolve_share_url(url, cookie_str)
        effective_url = final_url or url

        if backend in ("dy-downloader", "jiji"):
            try:
                dy_output_dir = output_base / "dy-downloader"
                logger.info("正在通过 jiji262/douyin-downloader 后端下载，输出目录: %s", dy_output_dir)
                thread_count = config.get("thread") or 5
                
                result = run_dy_downloader_backend(
                    url=url,
                    output_dir=dy_output_dir,
                    count_limit=count_limit,
                    cookie_str=cookie_str,
                    thread=thread_count,
                    video_quality=video_quality,
                    auto_install=auto_install_f2,
                )
                logger.info("dy-downloader 后端完成：输出目录 %s，当前扫描到视频文件 %s 个", result.output_dir, len(result.video_files))
            except ExternalBackendError as exc:
                logger.error(f"dy-downloader 后端失败: {exc}")
            continue

        if backend == "yt-dlp" or (backend == "auto" and not looks_like_douyin_url(effective_url)):
            try:
                ytdlp_items = run_ytdlp_audio(
                    url=url,
                    cookie_str=cookie_str,
                    use_douyin_cookie=looks_like_douyin_url(effective_url),
                )
                if not ytdlp_items:
                    logger.error("yt-dlp 未返回任何可归一化的媒体文件。")
                    continue
                summary = process_ytdlp_items(
                    ytdlp_items,
                    output_base=output_base,
                    whisper_path=whisper_path,
                    skip_asr=skip_asr,
                )
                logger.info("yt-dlp 后端完成：成功 %s / 跳过 %s / 失败 %s", summary["success"], summary["skipped"], summary["failed"])
            except ExternalBackendError as exc:
                logger.error(f"yt-dlp 后端失败: {exc}")
            continue

        aweme_list = []
        nickname = "未命名账号"
        source_path = "legacy"

        if sec_user_id:
            logger.info(f"检测到主页分享链接 (sec_uid: {sec_user_id})")

            if backend in ("auto", "f2"):
                f2_failed = False
                f2_error = None
                try:
                    logger.info("正在通过 F2 后端分页拉取主页作品列表...")
                    DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    f2_result = fetch_user_posts_with_f2(
                        sec_user_id=sec_user_id,
                        count_limit=count_limit,
                        cookie_str=cookie_str,
                        user_agent=DEFAULT_USER_AGENT,
                        auto_install=auto_install_f2,
                    )
                    aweme_list = f2_result.aweme_list
                    logger.info("F2 后端拉取完成：%s 页，%s 个作品，主页总数=%s，has_more=%s", f2_result.pages, len(aweme_list), f2_result.expected_count, f2_result.has_more)
                    
                    if f2_result.nickname:
                        nickname = f2_result.nickname
                    for aweme in aweme_list:
                        from utils.helpers import extract_author_nickname
                        candidate = extract_author_nickname(aweme, "")
                        if candidate:
                            nickname = candidate
                            break

                    if not aweme_list:
                        logger.error("F2 后端未返回任何作品。")
                        f2_failed = True
                        f2_error = "F2 返回空列表"
                    else:
                        source_path = "f2"
                        incomplete_reason = collection_incomplete_reason(
                            len(aweme_list),
                            expected_count=f2_result.expected_count,
                            count_limit=count_limit,
                            has_more=f2_result.has_more,
                        )
                        should_verify_all_with_browser = count_limit is None and browser_fallback_enabled
                        
                        if browser_fallback_enabled and (incomplete_reason or should_verify_all_with_browser):
                            requires_browser_login = (
                                any(item.get("login_tip") for item in f2_result.page_diagnostics)
                                or not cookie_header_has_login(cookie_str)
                            )
                            browser_items, browser_nickname, browser_ids = scrape_user_posts_via_browser_fallback(
                                sec_user_id,
                                cookie_str=cookie_str,
                                expected_count=f2_result.expected_count,
                                count_limit=count_limit,
                                trust_expected_count=not should_verify_all_with_browser,
                                headless=browser_headless,
                                max_scrolls=browser_max_scrolls,
                                idle_rounds=browser_idle_rounds,
                                wait_timeout_seconds=browser_wait_timeout,
                                require_login=requires_browser_login,
                            )
                            if browser_nickname:
                                nickname = browser_nickname
                            aweme_list = merge_aweme_lists_by_id(
                                aweme_list,
                                browser_items,
                                preferred_order=browser_ids,
                            )
                            source_path = "f2+browser"
                            
                            if detail_fill and browser_ids:
                                existing_ids = {
                                    str(item.get("aweme_id") or item.get("video_id") or "").strip()
                                    for item in aweme_list if isinstance(item, dict)
                                }
                                missing_detail_ids = [aid for aid in browser_ids if aid and aid not in existing_ids]
                                if missing_detail_ids:
                                    logger.warning("浏览器拿到 %s 个缺失元数据的作品 ID，开始用 F2 detail API 回补。", len(missing_detail_ids))
                                    detail_result = fetch_aweme_details_with_f2(
                                        aweme_ids=missing_detail_ids,
                                        sec_user_id=sec_user_id,
                                        cookie_str=cookie_str,
                                        user_agent=DEFAULT_USER_AGENT,
                                        auto_install=auto_install_f2,
                                    )
                                    aweme_list = merge_aweme_lists_by_id(
                                        aweme_list,
                                        detail_result.aweme_list,
                                        preferred_order=browser_ids,
                                    )
                                    source_path = "f2+browser+detail"
                except ExternalBackendError as exc:
                    f2_failed = True
                    f2_error = exc

                if f2_failed:
                    if not browser_fallback_enabled:
                        logger.error(f"F2 后端失败: {f2_error}")
                        continue
                    logger.warning(f"F2 后端拉取异常 ({f2_error})，由于启用了浏览器兜底，将直接通过浏览器抓取主页...")
                    browser_items, browser_nickname, browser_ids = scrape_user_posts_via_browser_fallback(
                        sec_user_id,
                        cookie_str=cookie_str,
                        expected_count=None,
                        count_limit=count_limit,
                        trust_expected_count=False,
                        headless=browser_headless,
                        max_scrolls=browser_max_scrolls,
                        idle_rounds=browser_idle_rounds,
                        wait_timeout_seconds=browser_wait_timeout,
                        require_login=not cookie_header_has_login(cookie_str),
                    )
                    nickname = browser_nickname or "未命名账号"
                    aweme_list = browser_items or []
                    if not aweme_list:
                        logger.error("通过浏览器兜底也未能抓取到任何作品。")
                        continue
                    source_path = "browser_fallback_only"

            elif backend == "legacy":
                logger.info(f"正在通过 API 拉取该博主最近的 {count_limit or 3} 个作品列表...")
                res_posts = fetch_user_posts(sec_user_id, count_limit or 3, cookie_str)
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
                    logger.warning("API 拉取主页失败，正在启动本地浏览器 DOM 提取与 API 拦截兜底...")
                    browser_details, scraped_nickname = scrape_user_videos_via_browser(sec_user_id, count_limit or 3)
                    if scraped_nickname and scraped_nickname != "未命名账号":
                        nickname = scraped_nickname
                    if browser_details:
                        logger.info(f"✓ 通过本地浏览器成功提取并拦截解析了 {len(browser_details)} 个视频的详情")
                        aweme_list = browser_details
                    else:
                        logger.error("本地浏览器提取博主视频详情失败。")
                        continue
                source_path = "legacy"
        else:
            if backend == "f2":
                logger.error("F2 后端当前仅用于博主主页作品分页；单视频请使用 auto/legacy/yt-dlp。")
                continue
                
            logger.info("按单视频分享链接进行本地免 Cookie HTML 解密...")
            video_id_match = re.search(r'video/(\d+)', final_url)
            if not video_id_match:
                video_id_match = re.search(r'/(\d+)(?:\?|$)', final_url)
            if not video_id_match:
                logger.error(f"无法从最终重定向链接中提取出视频数字 ID: {final_url}")
                continue
                
            video_id = video_id_match.group(1)
            logger.info(f"成功提取视频 ID: {video_id}。开始解析详情...")
            
            video_data = fetch_single_video_details(video_id, cookie_str)
            if not video_data:
                logger.warning("通过免 Cookie HTML 解密单视频失败，尝试使用本地浏览器拦截解析...")
                video_data = fetch_single_video_details_via_browser(video_id)
            if video_data:
                aweme_list = [video_data]
                nickname = video_data.get("author", {}).get("nickname") or video_data.get("nickname") or "未命名账号"
            else:
                logger.error("解析单视频网页数据失败。")
                continue
            source_path = "single_video"

        if not aweme_list:
            logger.error("最终获取到的可用视频列表为空。")
            continue

        summary = process_aweme_list(
            aweme_list,
            nickname=nickname,
            output_base=output_base,
            cookie_str=cookie_str,
            whisper_path=whisper_path,
            skip_asr=skip_asr,
            keep_video=keep_video,
            source_path=source_path,
            video_quality=video_quality,
            video_orientation=video_orientation,
        )
        logger.info(
            "链接处理结束：成功 %s / 跳过 %s / 失败 %s / 总计 %s",
            summary["success"],
            summary["skipped"],
            summary["failed"],
            len(aweme_list),
        )


async def _run_serve_subcommand(config: ConfigLoader, host: str, port: int) -> None:
    try:
        from server.app import run_server
    except ImportError as exc:
        print(
            f"REST 服务模式需要安装可选依赖 fastapi + uvicorn：\n"
            f"  pip install fastapi uvicorn\n"
            f"原始错误：{exc}"
        )
        sys.exit(1)

    print(f"启动 REST 服务：http://{host}:{port}")
    await run_server(config, host=host, port=port)


def main():
    parser = argparse.ArgumentParser(description="抖音下载器 - 纯 YAML 配置驱动")
    parser.add_argument("-c", "--config", default="config.yml", help="配置文件路径（默认: config.yml）")
    parser.add_argument("--serve", action="store_true", help="启动 REST API 服务模式")
    parser.add_argument("--serve-host", type=str, default="127.0.0.1", help="REST 服务监听地址")
    parser.add_argument("--serve-port", type=int, default=8000, help="REST 服务监听端口")
    
    args = parser.parse_args()
    
    print("====================================================")
    print("            抖音下载器 (YAML Config Edition)         ")
    print("====================================================")

    config_path = args.config
    config = ConfigLoader(config_path if Path(config_path).exists() else None)
    
    if args.serve or (config.get("server") or {}).get("enabled", False):
        host = args.serve_host or (config.get("server") or {}).get("host", "127.0.0.1")
        port = args.serve_port or (config.get("server") or {}).get("port", 8000)
        try:
            asyncio.run(_run_serve_subcommand(config, host, port))
        except KeyboardInterrupt:
            print("\n服务被用户中断")
            sys.exit(0)
    else:
        try:
            asyncio.run(main_async(config))
        except KeyboardInterrupt:
            print("\n下载任务被用户中断")
            sys.exit(0)
        except Exception as e:
            logger.exception(f"运行发生未捕获的异常: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
