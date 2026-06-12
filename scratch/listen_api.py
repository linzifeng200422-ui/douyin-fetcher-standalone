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
        
        captured_data = []

        async def handle_response(response):
            url = response.url
            if "aweme/post" in url or "aweme/v1/web/aweme/post" in url:
                print(f"\n[Captured Response] URL: {url[:100]}")
                print(f"Status: {response.status}")
                try:
                    headers = response.headers
                    print(f"Content-Type: {headers.get('content-type', 'N/A')}")
                    body = await response.body()
                    print(f"Body size: {len(body)} bytes")
                    # 尝试解码并查找数据
                    text = body.decode('utf-8', errors='ignore')
                    if text:
                        data = json.loads(text)
                        captured_data.append(data)
                        print(f"✓ Parsed JSON. aweme_list count: {len(data.get('aweme_list', []))}")
                        if data.get('aweme_list'):
                            print(f"  First video desc: {data['aweme_list'][0].get('desc')}")
                except Exception as ex:
                    print(f"Error reading response body: {ex}")

        page.on("response", handle_response)
        
        print("Navigating to user page...")
        await page.goto("https://www.douyin.com/user/MS4wLjABAAAAjN32ZoC90W_FXxpeck2ATV5PCQcnnHM2cSzm8SHdcGCEC3P_fxGweCSTutk3Mvqq", wait_until="domcontentloaded")
        
        print("Waiting 8 seconds for requests to settle...")
        await page.wait_for_timeout(8000)
        
        # 滚动一下，触发更多请求
        print("Scrolling...")
        await page.evaluate("window.scrollBy(0, 1000)")
        await page.wait_for_timeout(4000)
        
        if captured_data:
            print("\nSuccessfully captured aweme/post API JSON data!")
            # 写入临时文件供调试
            Path("captured_post_api.json").write_text(json.dumps(captured_data[0], ensure_ascii=False, indent=2), encoding="utf-8")
            print("Saved captured data to captured_post_api.json")
        else:
            print("\nNo aweme/post API JSON data captured.")
            
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
