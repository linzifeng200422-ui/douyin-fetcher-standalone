import asyncio
from playwright.async_api import async_playwright
from pathlib import Path

async def main():
    async with async_playwright() as p:
        auth_dir = Path(".auth")
        print(f"Launching headed context to check cookies...")
        
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(auth_dir.resolve()),
            headless=False,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0] if context.pages else await context.new_page()
        
        print("Navigating to https://www.douyin.com ...")
        await page.goto("https://www.douyin.com", wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)
        
        cookies = await context.cookies("https://www.douyin.com")
        print(f"\nTotal douyin cookies found in headed mode: {len(cookies)}")
        
        has_session = False
        for c in cookies:
            c_name = c["name"]
            if "sessionid" in c_name.lower():
                print(f"✓ Found session cookie: {c_name} = {c['value'][:15]}...")
                has_session = True
            elif "uid" in c_name.lower():
                print(f"  Found uid cookie: {c_name} = {c['value'][:15]}...")
                
        if not has_session:
            print("❌ NO sessionid cookie found! You are NOT logged in in the persistent context.")
            # 存下截图，看是不是真的未登录
            await page.screenshot(path="headed_cookie_check.png")
            print("Saved screenshot to headed_cookie_check.png")
            
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
