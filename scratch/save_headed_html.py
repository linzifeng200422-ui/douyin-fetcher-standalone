import asyncio
from playwright.async_api import async_playwright
from pathlib import Path

async def main():
    async with async_playwright() as p:
        auth_dir = Path(".auth")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(auth_dir.resolve()),
            headless=False,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0] if context.pages else await context.new_page()
        
        url = "https://www.douyin.com/user/MS4wLjABAAAAjN32ZoC90W_FXxpeck2ATV5PCQcnnHM2cSzm8SHdcGCEC3P_fxGweCSTutk3Mvqq"
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(6000)
        
        # 保存 HTML
        Path("headed_user_page.html").write_text(await page.content(), encoding="utf-8")
        print("Saved headed_user_page.html")
        
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
