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
        
        video_url = "https://www.douyin.com/video/7257716014706724156"
        print(f"Navigating to {video_url}...")
        
        try:
            await page.goto(video_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)
            
            print(f"Current URL: {page.url}")
            await page.screenshot(path="inspect_redirect.png")
            print("Screenshot saved to inspect_redirect.png")
            
            # 打印当前页面的 title
            print(f"Page Title: {await page.title()}")
            
        except Exception as e:
            print(f"Error: {e}")
            
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
