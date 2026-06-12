import subprocess
import re
from pathlib import Path

def test_url(url, cookie_str):
    cmd = [
        "curl", "-s", "-L",
        "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        url
    ]
    if cookie_str:
        cmd += ["-H", f"Cookie: {cookie_str}"]
    
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    print(f"URL: {url}")
    print(f"Stdout length: {len(result.stdout)}")
    print(f"Stderr: {result.stderr}")
    
    # 查找是否有 _ROUTER_DATA 或其他 JSON 数据
    pattern = re.compile(pattern=r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", flags=re.DOTALL)
    find_res = pattern.search(result.stdout)
    if find_res:
        print("✓ Found window._ROUTER_DATA")
        print(f"Sample data: {find_res.group(1)[:300]}")
    else:
        print("✗ window._ROUTER_DATA NOT found")
        # 搜索一下是否有 RENDER_DATA
        render_pattern = re.compile(pattern=r'<script id="RENDER_DATA" type="application/json">(.*?)</script>', flags=re.DOTALL)
        find_render = render_pattern.search(result.stdout)
        if find_render:
            print("✓ Found id=\"RENDER_DATA\"")
            print(f"Sample data: {find_render.group(1)[:300]}")
        else:
            print("✗ id=\"RENDER_DATA\" NOT found")
            # 存下 HTML 片段看看内容
            debug_file = Path("debug_page.html")
            debug_file.write_text(result.stdout, encoding="utf-8")
            print("Saved response html to debug_page.html")

def main():
    cookie_file = Path("cookie.txt")
    cookie_str = cookie_file.read_text(encoding="utf-8").strip() if cookie_file.is_file() else ""
    print(f"Using cookie_str (len: {len(cookie_str)}): {cookie_str[:40]}...")
    
    # 测试 ies 域名
    test_url("https://www.iesdouyin.com/share/video/7650119012156585891", cookie_str)
    print("="*50)
    # 测试主站域名
    test_url("https://www.douyin.com/video/7650119012156585891", cookie_str)

if __name__ == "__main__":
    main()
