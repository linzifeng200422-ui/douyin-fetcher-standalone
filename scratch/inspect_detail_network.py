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
        
        captured_requests = []
        captured_details = []

        async def handle_response(response):
            url = response.url
            status = response.status
            content_type = response.headers.get("content-type", "")
            
            # 1. 搜集可能为视频或音频流的 CDN 请求
            if "mime" in url or "video" in url or "audio" in url or ".mp4" in url or ".m4s" in url or "bytevoc" in url or "byteimg" in url:
                if status == 200 or status == 206: # 206 Partial Content 很常见于媒体流
                    captured_requests.append({
                        "url": url,
                        "status": status,
                        "content_type": content_type
                    })
                    
            # 2. 搜集视频详情 API /aweme/v1/web/aweme/detail/
            if "aweme/v1/web/aweme/detail" in url:
                try:
                    body = await response.body()
                    text = body.decode("utf-8", errors="ignore")
                    captured_details.append({
                        "url": url,
                        "status": status,
                        "text": text
                    })
                except Exception as ex:
                    captured_details.append({
                        "url": url,
                        "status": status,
                        "error": str(ex)
                    })

        page.on("response", handle_response)
        
        video_url = "https://www.douyin.com/video/7257716014706724156"
        print(f"Navigating to {video_url}...")
        
        try:
            await page.goto(video_url, wait_until="domcontentloaded")
            print("Successfully loaded page. Waiting 8 seconds for requests to load...")
            await page.wait_for_timeout(8000)
            
            # 提取视频标题和描述 DOM
            print("\nTesting DOM Locators for Title/Desc:")
            try:
                # 尝试多种选择器
                selectors = ["[data-e2e='detail-desc']", "h1", "title"]
                for sel in selectors:
                    loc = page.locator(sel)
                    cnt = await loc.count()
                    if cnt > 0:
                        text = await loc.first.inner_text()
                        print(f"  Selector '{sel}': {text}")
            except Exception as de:
                print(f"  DOM search error: {de}")
                
        except Exception as e:
            print(f"Error: {e}")
            
        print("\n" + "="*50)
        print("Captured API Detail Responses:")
        for idx, item in enumerate(captured_details):
            print(f"[{idx+1}] Status: {item['status']} | URL: {item['url'][:80]}...")
            if "text" in item and item["text"]:
                print(f"    Body len: {len(item['text'])}")
                if len(item["text"]) > 100:
                    try:
                        data = json.loads(item["text"])
                        # 保存
                        Path("detail_api_response.json").write_text(item["text"], encoding="utf-8")
                        print("    ✓ Parsed JSON and saved to detail_api_response.json!")
                        aweme_detail = data.get("aweme_detail", {})
                        print(f"    Title in JSON: {aweme_detail.get('desc')}")
                    except Exception as pe:
                        print(f"    JSON Parse error: {pe}")
            elif "error" in item:
                print(f"    Error: {item['error']}")
                
        print("\n" + "="*50)
        print("Captured Media Stream CDN Requests:")
        for idx, req in enumerate(captured_requests[:20]):
            print(f"[{idx+1}] Status: {req['status']} | Content-Type: {req['content_type']}")
            print(f"    URL: {req['url'][:120]}...")
            
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
