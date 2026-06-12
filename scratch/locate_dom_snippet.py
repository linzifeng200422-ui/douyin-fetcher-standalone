import re
from pathlib import Path

def main():
    html_file = Path("headed_user_page.html")
    if not html_file.exists():
        print("headed_user_page.html not found")
        return
        
    html = html_file.read_text(encoding="utf-8")
    print(f"Total HTML length: {len(html)}")
    
    # 查找这个视频 ID 并打印其前后的 HTML 字符串
    target_id = "7601340810298232115"
    idx = html.find(target_id)
    if idx == -1:
        print(f"✗ Target ID {target_id} NOT found in HTML via substring search!")
        # 看看是不是有任何 video id
        matches = re.findall(r'video/(\d+)', html)
        print(f"All video ID matches in HTML (count: {len(matches)}): {matches[:10]}")
        return
        
    print(f"✓ Found target ID at index {idx}")
    start = max(0, idx - 200)
    end = min(len(html), idx + 200)
    print("Snippet:")
    print(html[start:end])

if __name__ == "__main__":
    main()
