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
            await page.wait_for_timeout(6000)
            
            # 1. 查找包含 "儿童趣味建造" 的 script 标签
            scripts = await page.locator("script").all()
            print(f"Total script tags: {len(scripts)}")
            for idx, script in enumerate(scripts):
                try:
                    text = await script.inner_text()
                    if "儿童趣味建造" in text:
                        print(f"✓ Script [{idx}] contains '儿童趣味建造' (len: {len(text)})")
                        # 打印前 500 个字符和最后 500 个字符
                        print("Start snippet:")
                        print(text[:500])
                        print("End snippet:")
                        print(text[-500:])
                        Path(f"script_contains_data.txt").write_text(text, encoding="utf-8")
                        print("Saved this script content to script_contains_data.txt")
                except Exception as se:
                    pass
                    
            # 2. 检查全局 window 属性
            window_keys = await page.evaluate("() => Object.keys(window)")
            print("\nWindow global keys count:", len(window_keys))
            # 打印与 douyin, router, state, data, play 相关的 key
            for key in window_keys:
                key_lower = key.lower()
                if any(x in key_lower for x in ["state", "router", "preload", "detail", "data", "aweme"]):
                    print(f"  window.{key}")
                    
        except Exception as e:
            print(f"Error: {e}")
            
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
