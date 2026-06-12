import asyncio
import json
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
            
            # 1. 尝试获取 SSR_RENDER_DATA
            try:
                ssr_data = await page.evaluate("() => window.SSR_RENDER_DATA")
                if ssr_data:
                    Path("ssr_render_data.json").write_text(json.dumps(ssr_data, ensure_ascii=False, indent=2), encoding="utf-8")
                    print("✓ Saved window.SSR_RENDER_DATA")
                else:
                    print("✗ window.SSR_RENDER_DATA is empty")
            except Exception as e:
                print(f"Error getting SSR_RENDER_DATA: {e}")
                
            # 2. 尝试获取 __INLINE_PLAYER_DATA__
            try:
                player_data = await page.evaluate("() => window.__INLINE_PLAYER_DATA__")
                if player_data:
                    Path("inline_player_data.json").write_text(json.dumps(player_data, ensure_ascii=False, indent=2), encoding="utf-8")
                    print("✓ Saved window.__INLINE_PLAYER_DATA__")
                else:
                    print("✗ window.__INLINE_PLAYER_DATA__ is empty")
            except Exception as e:
                print(f"Error getting __INLINE_PLAYER_DATA__: {e}")
                
            # 3. 尝试获取 EXPOSE_DATA
            try:
                expose_data = await page.evaluate("() => window.EXPOSE_DATA")
                if expose_data:
                    Path("expose_data.json").write_text(json.dumps(expose_data, ensure_ascii=False, indent=2), encoding="utf-8")
                    print("✓ Saved window.EXPOSE_DATA")
                else:
                    print("✗ window.EXPOSE_DATA is empty")
            except Exception as e:
                print(f"Error getting EXPOSE_DATA: {e}")
                
        except Exception as e:
            print(f"Error: {e}")
            
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
