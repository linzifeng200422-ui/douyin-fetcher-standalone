import asyncio
from playwright.async_api import async_playwright
from pathlib import Path

async def main():
    async with async_playwright() as p:
        auth_dir = Path(".auth")
        state_file = auth_dir / "state.json"
        
        # 启动 headed 模式以防 headless 缺少某些编解码组件，或者 headless=True 也可以
        # 我们用 headless=True 测试
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(auth_dir.resolve()),
            headless=True,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        
        # 测试视频 ID: 7257716014706724156
        video_url = "https://www.douyin.com/video/7257716014706724156"
        print(f"Navigating to {video_url} ...")
        
        try:
            await page.goto(video_url, wait_until="domcontentloaded", timeout=45000)
            print("Successfully loaded page.")
            
            # 等待 video 元素出现（抖音视频播放器加载可能需要 1-3 秒）
            print("Waiting for video element...")
            await page.wait_for_selector("video", timeout=15000)
            
            # 获取 video 的 src 属性
            video_locator = page.locator("video").first
            video_src = await video_locator.get_attribute("src")
            print(f"✓ Found Video Source URL: {video_src[:120]}...")
            
            # 获取视频描述（标题）
            desc = ""
            try:
                # 抖音网页版视频标题的各种常见 css/xpath 匹配
                # 比如包含 h1 或是特定的 data-e2e 属性
                desc_element = page.locator("[data-e2e='detail-desc']").first
                if await desc_element.count() > 0:
                    desc = await desc_element.inner_text()
                else:
                    # 兜底
                    desc = await page.title()
            except Exception as e:
                print(f"Failed to get detail desc: {e}")
                desc = await page.title()
                
            print(f"✓ Video Desc/Title: {desc}")
            
            # 保存截图看看页面长啥样
            await page.screenshot(path="debug_video_play.png")
            print("Saved debug screenshot to debug_video_play.png")
            
        except Exception as e:
            print(f"Error during extraction: {e}")
            try:
                await page.screenshot(path="debug_video_error.png")
                print("Saved error screenshot to debug_video_error.png")
            except Exception:
                pass
                
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
