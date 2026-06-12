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
        
        # 注入高阶脚本，处理 arraybuffer/blob 兼容解码
        init_js = """
        window.__scraped_data__ = [];
        
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
                        let text = '';
                        // 如果 responseType 是 arraybuffer，需要解码 ArrayBuffer
                        if (this.responseType === 'arraybuffer' || this.response instanceof ArrayBuffer) {
                            const decoder = new TextDecoder('utf-8');
                            text = decoder.decode(this.response);
                        } else if (this.responseType === 'blob' || this.response instanceof Blob) {
                            // Blob 异步读取
                            const reader = new FileReader();
                            const self = this;
                            reader.onload = function() {
                                window.__scraped_data__.push({
                                    type: 'xhr_blob',
                                    url: self.__url,
                                    text: reader.result
                                });
                            };
                            reader.readAsText(this.response);
                            return;
                        } else {
                            // 默认读取 responseText 或者 response
                            text = this.responseText || (typeof this.response === 'string' ? this.response : '');
                        }
                        
                        window.__scraped_data__.push({
                            type: 'xhr',
                            url: this.__url,
                            text: text,
                            responseType: this.responseType
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
        
        print("Waiting for page load...")
        await page.wait_for_timeout(8000)
        
        scraped = await page.evaluate("window.__scraped_data__")
        print(f"Captured items count: {len(scraped)}")
        
        for idx, item in enumerate(scraped):
            print(f"[{idx+1}] Type: {item['type']} | URL: {item['url'][:80]}...")
            print(f"    ResponseType: {item.get('responseType', 'N/A')}")
            if 'text' in item and item['text']:
                body_len = len(item['text'])
                print(f"    Body length: {body_len}")
                if body_len > 100:
                    try:
                        data = json.loads(item['text'])
                        print(f"    ✓ Parsed JSON! aweme_list count: {len(data.get('aweme_list', []))}")
                    except Exception as parse_err:
                        print(f"    Error parsing JSON: {parse_err}")
                        print(f"    Snippet: {item['text'][:300]}")
                        
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
