import re
import json
import urllib.parse
from pathlib import Path

def main():
    html_file = Path("user_page.html")
    if not html_file.exists():
        print("user_page.html not found")
        return
        
    html = html_file.read_text(encoding="utf-8")
    match = re.search(r'<script id="RENDER_DATA" type="application/json">(.*?)</script>', html)
    if not match:
        print("RENDER_DATA not found")
        return
        
    raw_json = urllib.parse.unquote(match.group(1))
    data = json.loads(raw_json)
    
    # Recursively find any key containing aweme_id or video_id, and print its path and value
    def search_for_videos(d, path=""):
        if isinstance(d, dict):
            # If the dict represents a video (has aweme_id or video_id)
            if "aweme_id" in d or "awemeId" in d:
                print(f"Found video dict at {path}, aweme_id: {d.get('aweme_id') or d.get('awemeId')}, title: {d.get('desc') or d.get('title')}")
                return
            for k, v in d.items():
                search_for_videos(v, f"{path}.{k}")
        elif isinstance(d, list):
            for i, item in enumerate(d):
                search_for_videos(item, f"{path}[{i}]")

    search_for_videos(data)

if __name__ == "__main__":
    main()
