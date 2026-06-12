import subprocess
import re
import json
import urllib.parse
from pathlib import Path

def main():
    cookie_file = Path("cookie.txt")
    cookie_str = cookie_file.read_text(encoding="utf-8").strip() if cookie_file.is_file() else ""
    
    url = "https://www.douyin.com/video/7257716014706724156" # 换一个视频 ID 测试
    cmd = [
        "curl", "-s", "-L",
        "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "-H", f"Cookie: {cookie_str}",
        url
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    
    # 查找 RENDER_DATA
    render_pattern = re.compile(pattern=r'<script id="RENDER_DATA" type="application/json">(.*?)</script>', flags=re.DOTALL)
    find_render = render_pattern.search(result.stdout)
    if not find_render:
        print("RENDER_DATA not found in douyin.com/video page")
        Path("failed_page.html").write_text(result.stdout, encoding="utf-8")
        return
        
    raw_json = urllib.parse.unquote(find_render.group(1))
    data = json.loads(raw_json)
    
    # 写入文件查看完整结构
    Path("video_render_data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("✓ Saved RENDER_DATA to video_render_data.json")
    
    # 递归搜索 aweme 相关的数据，看看视频详情在哪里
    def search_for_video_details(d, path=""):
        if isinstance(d, dict):
            # 抖音详情页的结构里可能有 videoInfoRes，或者 awemeDetail, 或者 itemInfo 等
            # 我们检查它是否含有 video 的播放地址
            if "playAddr" in d or "play_addr" in d:
                # 打印出来
                print(f"Found play address at {path}: {d.get('playAddr') or d.get('play_addr')}")
            # 另外看看有没有 desc 标题
            if "desc" in d and ("awemeId" in d or "aweme_id" in d or "itemId" in d or "item_id" in d):
                print(f"Found video metadata at {path}, ID: {d.get('awemeId') or d.get('aweme_id') or d.get('itemId') or d.get('item_id')}, Title: {d.get('desc')}")
                
            for k, v in d.items():
                search_for_video_details(v, f"{path}.{k}")
        elif isinstance(d, list):
            for i, item in enumerate(d):
                search_for_video_details(item, f"{path}[{i}]")

    search_for_video_details(data)

if __name__ == "__main__":
    main()
