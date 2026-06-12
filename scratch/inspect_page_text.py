from bs4 import BeautifulSoup
from pathlib import Path

def main():
    html_file = Path("user_page_debug.html")
    if not html_file.exists():
        print("user_page_debug.html not found")
        return
        
    soup = BeautifulSoup(html_file.read_text(encoding="utf-8"), "html.parser")
    
    # 打印 Title
    print("Title:", soup.title.text if soup.title else "No Title")
    
    # 打印博主名字的元素内容
    # 抖音的博主名字通常有特殊的 class
    print("\nPotential Nicknames:")
    for h in soup.find_all(["h1", "h2"]):
        print(f"  {h.name}: {h.text.strip()}")
        
    # 打印所有的超链接中含有 video 的部分以及它们的 innerText
    print("\nAll Video Links and Texts:")
    video_links = soup.find_all("a", href=True)
    count = 0
    for link in video_links:
        href = link["href"]
        if "/video/" in href:
            count += 1
            print(f"  [{count}] Link: {href}")
            print(f"      Text: {link.text.strip()}")
            
    print(f"\nTotal links containing /video/: {count}")

if __name__ == "__main__":
    main()
