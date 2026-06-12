import asyncio
from playwright.async_api import async_playwright
from pathlib import Path

async def main():
    async with async_playwright() as p:
        auth_dir = Path(".auth")
        print(f"Using auth_dir: {auth_dir.resolve()}")
        
        # 启动持久化浏览器，不传 headless，默认为 True，看能不能通过持久化目录恢复登录态
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(auth_dir.resolve()),
            headless=True,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0] if context.pages else await context.new_page()
        
        print("Navigating to https://www.douyin.com ...")
        try:
            # 抖音网页很大，使用 domcontentloaded 并设置 45 秒超时，避免 networkidle 超时
            await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=45000)
            print("Page loaded successfully.")
        except Exception as e:
            print(f"Navigation error/timeout (continuing anyway): {e}")
        
        # 截图保存，看是否登录成功
        screenshot_path = "debug_check_login.png"
        try:
            await page.screenshot(path=screenshot_path)
            print(f"Screenshot saved to {screenshot_path}")
        except Exception as se:
            print(f"Failed to capture screenshot: {se}")
        
        # 尝试查找登录后的标志元素
        html = await page.content()
        is_logged_in = "登录" not in html or "发布视频" in html or "创作者服务" in html
        print(f"Is logged in (heuristic check): {is_logged_in}")
        
        # 打印当前的所有 Cookie 数量
        cookies = await context.cookies()
        print(f"Active cookies count: {len(cookies)}")
        for c in cookies:
            if "sessionid" in c["name"].lower() or "uid" in c["name"].lower():
                print(f"  Cookie: {c['name']} = {c['value'][:10]}... (domain: {c['domain']})")
                
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
