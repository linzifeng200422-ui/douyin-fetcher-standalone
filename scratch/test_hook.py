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
        
        # 注入初始化脚本，挂钩 fetch 和 XMLHttpRequest
        init_js = """
        window.__scraped_data__ = [];
        
        // 挂钩 fetch
        const originalFetch = window.fetch;
        window.fetch = async function(...args) {
            const response = await originalFetch.apply(this, args);
            const url = args[0];
            if (typeof url === 'string' && url.includes('aweme/v1/web/aweme/post')) {
                try {
                    const clone = response.clone();
                    const text = await clone.text();
                    window.__scraped_data__.push({
                        type: 'fetch',
                        url: url,
                        text: text
                    });
                } catch (e) {
                    window.__scraped_data__.push({
                        type: 'fetch_error',
                        url: url,
                        error: e.toString()
                    });
                }
            }
            return response;
        };
        
        // 挂钩 XMLHttpRequest
        const originalOpen = XMLHttpRequest.prototype.open;
        const originalSend = XMLHttpRequest.prototype.send;
        
        XMLHttpRequest.prototype.open = function(method, url, ...rest) {
            this.__url = url;
            return originalOpen.apply(this, [method, url, ...rest]);
        };
        
        XMLHttpRequest.prototype.send = function(...args) {
            this.addEventListener('load', function() {
                if (this.__url && this.__url.includes('aweme/v1/web/aweme/post')) {
                    try {
                        window.__scraped_data__.push({
                            type: 'xhr',
                            url: this.__url,
                            text: this.responseText
                        });
                    } catch (e) {
                        window.__scraped_data__.push({
                            type: 'xhr_error',
                            url: this.__url,
                            error: e.toString()
                        });
                    }
                }
            });
            return originalSend.apply(this, args);
        };
        """
        
        await page.add_init_script(init_js)
        
        print("Navigating to user page...")
        await page.goto("https://www.douyin.com/user/MS4wLjABAAAAjN32ZoC90W_FXxpeck2ATV5PCQcnnHM2cSzm8SHdcGCEC3P_fxGweCSTutk3Mvqq", wait_until="domcontentloaded")
        
        print("Waiting for page load and API requests...")
        await page.wait_for_timeout(8000)
        
        # 提取内存中的拦截数据
        scraped = await page.evaluate("window.__scraped_data__")
        print(f"Captured items count: {len(scraped)}")
        
        success = False
        for idx, item in enumerate(scraped):
            print(f"[{idx+1}] Type: {item['type']} | URL: {item['url'][:80]}...")
            if 'text' in item and item['text']:
                body_len = len(item['text'])
                print(f"    Body length: {body_len}")
                if body_len > 100:
                    try:
                        data = json.loads(item['text'])
                        print(f"    ✓ Successfully parsed JSON! aweme_list count: {len(data.get('aweme_list', []))}")
                        if data.get('aweme_list'):
                            first = data['aweme_list'][0]
                            print(f"    First video title: {first.get('desc')}")
                            # 打印视频播放地址
                            video = first.get("video", {})
                            if video and video.get("play_addr"):
                                print(f"    ✓ Found Play URL: {video['play_addr'].get('url_list', [None])[0]}")
                            success = True
                            # 保存一份样本 JSON
                            Path("hooked_post_data.json").write_text(item['text'], encoding="utf-8")
                            print("    Saved hooked data to hooked_post_data.json")
                    except Exception as parse_err:
                        print(f"    Error parsing JSON: {parse_err}")
            elif 'error' in item:
                print(f"    Error: {item['error']}")
                
        if not success:
            print("Failed to scrape any valid post data via JS hook.")
            
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
