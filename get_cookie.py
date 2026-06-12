#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import sys
from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("错误：未检测到 playwright 库。请先运行: pip install playwright && playwright install chromium")
    sys.exit(1)

async def main():
    print("==================================================")
    print("正在启动浏览器以获取抖音 Cookie...")
    print("==================================================")
    
    async with async_playwright() as p:
        # 使用持久化上下文启动 headed 模式浏览器，以便保存登录态，防止重复登录
        auth_dir = Path(".auth")
        auth_dir.mkdir(exist_ok=True)
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(auth_dir.resolve()),
            headless=False,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0] if context.pages else await context.new_page()
        
        # 打开抖音官网
        await page.goto("https://www.douyin.com")
        
        print("\n[提示] 请在弹出的浏览器窗口中正常浏览，或直接扫码登录（若需要）。")
        print("[提示] 已经实现【实时保存】，你无需关闭浏览器，直接扫码，脚本会自动更新 cookie.txt 并执行下载！")
        
        # 循环等待，直到浏览器被关闭，期间每 2 秒自动保存一次 Cookie
        try:
            while True:
                # 检查浏览器是否还处于开启状态
                if len(context.pages) == 0:
                    break
                
                # 实时提取并保存 Cookie
                cookies = await context.cookies()
                if cookies:
                    cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                    cookie_file = Path("cookie.txt")
                    cookie_file.write_text(cookie_str, encoding="utf-8")
                    print(f"✓ 实时同步 {len(cookies)} 个 Cookie 到 cookie.txt...", flush=True)

                await asyncio.sleep(2)
        except Exception as e:
            print(f"提取过程发生异常: {e}")
            
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
