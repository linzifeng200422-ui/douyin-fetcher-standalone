import asyncio
import urllib.parse
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
            print("Page domcontentloaded. Waiting 6 seconds for JS to hydrate...")
            await page.wait_for_timeout(6000)
            
            # 1. 检查页面中 RENDER_DATA 标签的内容
            print("Extracting RENDER_DATA from page DOM...")
            render_data_encoded = await page.locator("script#RENDER_DATA").inner_text()
            if render_data_encoded:
                raw_json = urllib.parse.unquote(render_data_encoded)
                data = json.loads(raw_json)
                
                # 保存并检查
                Path("hydrated_render_data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                print("✓ Saved hydrated RENDER_DATA to hydrated_render_data.json")
                
                # 搜寻标题与播放地址
                found = False
                def search(d, path=""):
                    nonlocal found
                    if isinstance(d, dict):
                        if "playAddr" in d or "play_addr" in d:
                            print(f"  [Found playAddr] {path}: {d.get('playAddr') or d.get('play_addr')}")
                            found = True
                        if "desc" in d and ("awemeId" in d or "aweme_id" in d):
                            print(f"  [Found video info] {path}: ID={d.get('awemeId') or d.get('aweme_id')}, Desc={d.get('desc')}")
                            found = True
                        for k, v in d.items():
                            search(v, f"{path}.{k}")
                    elif isinstance(d, list):
                        for i, item in enumerate(d):
                            search(item, f"{path}[{i}]")
                search(data)
                if not found:
                    print("✗ No playAddr or metadata found in hydrated RENDER_DATA.")
            else:
                print("✗ RENDER_DATA element is empty.")
                
            # 2. 检查是否有 video[src]
            video_src = await page.locator("video").first.get_attribute("src")
            print(f"Video element src: {video_src}")
            
        except Exception as e:
            print(f"Error: {e}")
            
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
