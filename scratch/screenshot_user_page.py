import asyncio
from playwright.async_api import async_playwright
from pathlib import Path

async def main():
    async with async_playwright() as p:
        auth_dir = Path(".auth")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(auth_dir.resolve()),
            headless=True,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0] if context.pages else await context.new_page()
        
        # 柱子哥主页
        url = "https://www.douyin.com/user/MS4wLjABAAAAjN32ZoC90W_FXxpeck2ATV5PCQcnnHM2cSzm8SHdcGCEC3P_fxGweCSTutk3Mvqq"
        print(f"Navigating to {url}...")
        
        await page.goto(url, wait_until="domcontentloaded")
        print("Waiting 6 seconds...")
        await page.wait_for_timeout(6000)
        
        # 存下 HTML 供检索
        Path("user_page_debug.html").write_text(await page.content(), encoding="utf-8")
        
        # 截图保存到 artifacts 目录，以便在 Walkthrough 里能显示或者直接查看
        screenshot_path = Path("/Users/linzifeng/.gemini/antigravity/brain/58dd2013-c20e-4cf8-b263-9f6e7e66b069/debug_user_page.png")
        await page.screenshot(path=str(screenshot_path))
        print(f"Screenshot saved to {screenshot_path}")
        
        # 打印 title
        print(f"Page Title: {await page.title()}")
        
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
