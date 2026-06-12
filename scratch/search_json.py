import json
from pathlib import Path

def main():
    json_file = Path("video_render_data.json")
    if not json_file.exists():
        print("video_render_data.json not found")
        return
        
    data = json.loads(json_file.read_text(encoding="utf-8"))
    
    # 打印所有的键（第一层和第二层）
    print("Top level keys:")
    for k in data.keys():
        print(f"  {k}")
        if isinstance(data[k], dict):
            print(f"    Sub-keys for {k}: {list(data[k].keys())[:10]}")
            
    # 递归查找包含 url 或是特定大写/小写 key 的位置
    found_urls = []
    found_metadata = []
    
    def traverse(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                # 寻找包含 play, video, music, audio, desc, title 的键
                k_lower = k.lower()
                if any(x in k_lower for x in ["play", "video", "music", "audio", "desc", "title", "text"]):
                    if isinstance(v, (str, int, float)) and v:
                        found_metadata.append((f"{path}.{k}", v))
                traverse(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                traverse(item, f"{path}[{i}]")
        elif isinstance(obj, str):
            if obj.startswith("http://") or obj.startswith("https://"):
                found_urls.append((path, obj))

    traverse(data)
    
    print("\n" + "="*50)
    print("Found potential metadata keys and values:")
    for path, val in found_metadata[:40]:
        print(f"  {path} => {str(val)[:100]}")
        
    print("\n" + "="*50)
    print("Found potential URLs:")
    for path, url in found_urls[:20]:
        print(f"  {path} => {url[:100]}...")

if __name__ == "__main__":
    main()
