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
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        print("Navigating to user page...")
        try:
            async with page.expect_response(
                lambda r: "/aweme/v1/web/aweme/post/" in r.url and r.status == 200,
                timeout=20000
            ) as response_info:
                await page.goto("https://www.douyin.com/user/MS4wLjABAAAAjN32ZoC90W_FXxpeck2ATV5PCQcnnHM2cSzm8SHdcGCEC3P_fxGweCSTutk3Mvqq")
                
            response = await response_info.value
            print(f"✓ Intercepted API: {response.url[:80]}...")
            body = await response.body()
            print(f"Body start: {body[:100]}")
            json_data = json.loads(body.decode("utf-8"))
            print(f"✓ Parsed JSON successfully! Videos count: {len(json_data.get('aweme_list', []))}")
            if json_data.get('aweme_list'):
                print(f"First video: {json_data['aweme_list'][0].get('desc')}")
        except Exception as e:
            print(f"Failed to capture or parse response: {e}")
            
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
