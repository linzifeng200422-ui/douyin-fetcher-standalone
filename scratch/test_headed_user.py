import asyncio
from playwright.async_api import async_playwright
from pathlib import Path

async def main():
    async with async_playwright() as p:
        auth_dir = Path(".auth")
        print(f"Loading persistent context in headed mode (headless=False)...")
        
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(auth_dir.resolve()),
            headless=False, # 使用 headed 模式绕过 headless 检测
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0] if context.pages else await context.new_page()
        
        # 柱子哥主页
        url = "https://www.douyin.com/user/MS4wLjABAAAAjN32ZoC90W_FXxpeck2ATV5PCQcnnHM2cSzm8SHdcGCEC3P_fxGweCSTutk3Mvqq"
        print(f"Navigating to {url}...")
        
        try:
            await page.goto(url, wait_until="domcontentloaded")
            print("Page loaded. Waiting 6 seconds for videos to render...")
            await page.wait_for_timeout(6000)
            
            # 截图保存，看是不是真实的博主主页
            screenshot_path = Path("/Users/linzifeng/.gemini/antigravity/brain/58dd2013-c20e-4cf8-b263-9f6e7e66b069/headed_user_page.png")
            await page.screenshot(path=str(screenshot_path))
            print(f"Screenshot saved to {screenshot_path}")
            
            # 获取所有视频
            locators = page.locator("a[href*='/video/']")
            count = await locators.count()
            print(f"Found {count} video links in headed mode:")
            
            for idx in range(min(count, 10)):
                href = await locators.nth(idx).get_attribute("href")
                text = await locators.nth(idx).inner_text()
                print(f"  [{idx+1}] Link: {href}")
                print(f"      Title: {text.strip()[:80]}")
                
        except Exception as e:
            print(f"Error: {e}")
            
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
