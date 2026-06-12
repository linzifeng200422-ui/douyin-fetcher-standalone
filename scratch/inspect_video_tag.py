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
        print(f"Navigating to {video_url} ...")
        
        try:
            await page.goto(video_url, wait_until="domcontentloaded")
            await page.wait_for_selector("video", timeout=10000)
            
            # 获取 video 的 outerHTML
            html = await page.locator("video").first.evaluate("el => el.outerHTML")
            print("Video element HTML:")
            print(html)
            
            # 同时检查是否有 source 标签
            sources = await page.locator("video source").all()
            print(f"Sources count: {len(sources)}")
            for i, src in enumerate(sources):
                s_html = await src.evaluate("el => el.outerHTML")
                print(f"Source [{i}]: {s_html}")
                
        except Exception as e:
            print(f"Error: {e}")
            
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
