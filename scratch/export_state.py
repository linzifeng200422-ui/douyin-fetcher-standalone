import asyncio
from playwright.async_api import async_playwright
from pathlib import Path

async def main():
    async with async_playwright() as p:
        auth_dir = Path(".auth")
        print(f"Loading persistent context from {auth_dir.resolve()}...")
        
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
            await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=45000)
            print("Successfully reached Douyin.")
        except Exception as e:
            print(f"Failed to navigate completely: {e}")
            
        print("Saving filtered cookies (only douyin.com) and storage state...")
        # 仅限抖音域
        cookies = await context.cookies("https://www.douyin.com")
        if cookies:
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            cookie_file = Path("cookie.txt")
            cookie_file.write_text(cookie_str, encoding="utf-8")
            print(f"✓ Saved {len(cookies)} filtered cookies to cookie.txt")
        else:
            print("Warning: No cookies found for https://www.douyin.com")
            
        state_file = auth_dir / "state.json"
        await context.storage_state(path=str(state_file))
        print(f"✓ Saved storage state to {state_file}")
        
        await context.close()
        print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
