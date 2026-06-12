import json
from pathlib import Path

def main():
    json_file = Path("detail_api_response.json")
    if not json_file.exists():
        print("detail_api_response.json not found")
        return
        
    data = json.loads(json_file.read_text(encoding="utf-8"))
    aweme = data.get("aweme_detail", {})
    
    print("Aweme ID:", aweme.get("aweme_id"))
    print("Desc:", aweme.get("desc"))
    
    # statistics
    stats = aweme.get("statistics", {})
    print("Stats:")
    print(f"  Play: {stats.get('play_count')}")
    print(f"  Digg: {stats.get('digg_count')}")
    print(f"  Comment: {stats.get('comment_count')}")
    
    # Author
    author = aweme.get("author", {})
    print(f"Author Nickname: {author.get('nickname')}")
    
    # Video play url
    video = aweme.get("video", {})
    play_addr = video.get("play_addr", {})
    url_list = play_addr.get("url_list", [])
    print(f"Video play urls count: {len(url_list)}")
    if url_list:
        print("  First play url:", url_list[0])
        
    # Music
    music = aweme.get("music", {})
    m_play_url = music.get("play_url", {})
    m_url_list = m_play_url.get("url_list", [])
    print(f"Music play urls count: {len(m_url_list)}")
    if m_url_list:
        print("  First music url:", m_url_list[0])

if __name__ == "__main__":
    main()
