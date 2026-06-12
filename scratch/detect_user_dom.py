import asyncio
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
        
        # 柱子哥主页
        url = "https://www.douyin.com/user/MS4wLjABAAAAjN32ZoC90W_FXxpeck2ATV5PCQcnnHM2cSzm8SHdcGCEC3P_fxGweCSTutk3Mvqq"
        print(f"Navigating to {url}...")
        
        await page.goto(url, wait_until="domcontentloaded")
        print("Page loaded. Waiting 5 seconds for cards to load...")
        await page.wait_for_timeout(5000)
        
        # 打印所有 video a 标签的详细路径信息
        locators = page.locator("a[href*='/video/']")
        count = await locators.count()
        print(f"Total video link elements: {count}")
        
        for idx in range(count):
            loc = locators.nth(idx)
            href = await loc.get_attribute("href")
            # 获取所有父级链的标签名和 class 类名
            parent_info = await loc.evaluate("""el => {
                let info = [];
                let curr = el.parentElement;
                while (curr && curr.tagName !== 'BODY') {
                    info.push(curr.tagName.toLowerCase() + (curr.className ? '.' + curr.className.split(' ').join('.') : ''));
                    curr = curr.parentElement;
                }
                return info.reverse().join(' > ');
            }""")
            # 获取文本内容
            text = await loc.inner_text()
            print(f"[{idx+1}] Link: {href}")
            print(f"    Text: {text.strip()[:60]}")
            print(f"    Path: {parent_info[:150]}...")
            print("-" * 40)
            
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
