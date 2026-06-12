import asyncio
from playwright.async_api import async_playwright
from pathlib import Path

async def main():
    async with async_playwright() as p:
        auth_dir = Path(".auth")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(auth_dir.resolve()),
            headless=True, # 测试 headless=True 模式
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0] if context.pages else await context.new_page()
        
        print("Navigating to user page (headless)...")
        await page.goto("https://www.douyin.com/user/MS4wLjABAAAAjN32ZoC90W_FXxpeck2ATV5PCQcnnHM2cSzm8SHdcGCEC3P_fxGweCSTutk3Mvqq")
        
        print("Waiting for video list to load...")
        try:
            # 等待包含 /video/ 的 a 标签出现，最多等 10 秒
            await page.wait_for_selector("a[href*='/video/']", timeout=10000)
            
            # 获取所有视频卡片的 a 标签
            locators = page.locator("a[href*='/video/']")
            count = await locators.count()
            print(f"✓ Found {count} video links on page (headless):")
            
            for i in range(min(count, 10)):
                href = await locators.nth(i).get_attribute("href")
                print(f"  [{i+1}] Link: {href}")
        except Exception as e:
            print(f"Failed to find video elements in headless: {e}")
            await page.screenshot(path="debug_headless.png")
            print("✓ Saved debug screenshot to debug_headless.png")
            
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
