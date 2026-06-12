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
        # 启动 headed 模式浏览器
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        # 打开抖音官网
        await page.goto("https://www.douyin.com")
        
        print("\n[提示] 请在弹出的浏览器窗口中正常浏览，或直接扫码登录（若需要）。")
        print("[提示] 准备就绪后，直接关闭弹出的浏览器窗口，脚本将自动提取并保存 Cookie。")
        
        # 循环等待，直到浏览器被关闭
        try:
            while True:
                # 检查浏览器是否还处于开启状态
                if not browser.is_connected() or len(context.pages) == 0:
                    break
                await asyncio.sleep(1)
        except Exception:
            pass
            
        # 提取并格式化 Cookie
        cookies = await context.cookies()
        if cookies:
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            cookie_file = Path("cookie.txt")
            cookie_file.write_text(cookie_str, encoding="utf-8")
            print(f"\n✓ 成功提取 {len(cookies)} 个 Cookie 指标！")
            print(f"✓ Cookie 已成功写入至: {cookie_file.resolve()}")
            print("==================================================")
        else:
            print("\n❌ 未能获取到有效的 Cookie，请确保浏览器已成功打开过页面。")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
