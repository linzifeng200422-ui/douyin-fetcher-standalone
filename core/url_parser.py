import re
from typing import Any, Dict, Optional

from utils.logger import setup_logger
from utils.validators import parse_url_type

logger = setup_logger("URLParser")


class URLParser:
    @staticmethod
    def parse(url: str) -> Optional[Dict[str, Any]]:
        url_type = parse_url_type(url)
        if not url_type:
            logger.error("Unsupported URL type: %s", url)
            return None

        result = {
            "original_url": url,
            "type": url_type,
        }

        if url_type == "video":
            aweme_id = URLParser._extract_video_id(url)
            if aweme_id:
                result["aweme_id"] = aweme_id

        elif url_type == "user":
            sec_uid = URLParser._extract_user_id(url)
            if sec_uid:
                result["sec_uid"] = sec_uid

        elif url_type == "collection":
            mix_id = URLParser._extract_mix_id(url)
            if mix_id:
                result["mix_id"] = mix_id

        elif url_type == "gallery":
            note_id = URLParser._extract_note_id(url)
            if note_id:
                result["note_id"] = note_id
                result["aweme_id"] = note_id

        elif url_type == "music":
            music_id = URLParser._extract_music_id(url)
            if music_id:
                result["music_id"] = music_id

        elif url_type == "live":
            room_id = URLParser._extract_room_id(url)
            if room_id:
                result["room_id"] = room_id

        return result

    @staticmethod
    def _extract_video_id(url: str) -> Optional[str]:
        match = re.search(r"/video/(\d+)", url)
        if match:
            return match.group(1)

        match = re.search(r"modal_id=(\d+)", url)
        if match:
            return match.group(1)

        return None

    @staticmethod
    def _extract_user_id(url: str) -> Optional[str]:
        match = re.search(r"/user/([A-Za-z0-9_-]+)", url)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _extract_mix_id(url: str) -> Optional[str]:
        match = re.search(r"/collection/(\d+)", url)
        if not match:
            match = re.search(r"/mix/(\d+)", url)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _extract_note_id(url: str) -> Optional[str]:
        match = re.search(r"/(?:note|gallery|slides)/(\d+)", url)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _extract_music_id(url: str) -> Optional[str]:
        match = re.search(r"/music/(\d+)", url)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _extract_room_id(url: str) -> Optional[str]:
        # 直播链接形态：
        #   https://live.douyin.com/123456789
        #   https://www.douyin.com/follow/live/123456789
        match = re.search(r"/live/(\d+)", url)
        if match:
            return match.group(1)
        match = re.search(r"live\.douyin\.com/(\d+)", url)
        if match:
            return match.group(1)
        return None


# ============================================================
# 以下为 douyin-fetcher-standalone 独有跳转探查逻辑
# ============================================================

def resolve_share_url(url: str, cookie_str: str = None) -> tuple:
    """模拟跳转以探查链接类型，识别主页与单视频。
    
    返回 (final_url, sec_user_id)。
    """
    import subprocess
    import urllib.parse
    import re
    from utils.logger import setup_logger
    
    log = setup_logger("URLParser")
    DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    
    cmd_redirect = [
        "curl", "-s", "-I", "-L",
        "-H", f"User-Agent: {DEFAULT_USER_AGENT}",
        url
    ]
    if cookie_str:
        cmd_redirect += ["-H", f"Cookie: {cookie_str}"]

    sec_user_id = None
    final_url = url
    try:
        res = subprocess.run(cmd_redirect, capture_output=True, text=True, encoding="utf-8")
        locations = re.findall(r'[lL]ocation:\s*([^\r\n]+)', res.stdout)
        final_url = locations[-1].strip() if locations else url

        # 匹配博主个人主页模式
        user_match = re.search(r'share/user/([a-zA-Z0-9_-]+)', final_url)
        if user_match:
            sec_user_id = user_match.group(1)
        else:
            # 从 url 参数中提取 sec_uid
            parsed_url = urllib.parse.urlparse(final_url)
            params = urllib.parse.parse_qs(parsed_url.query)
            if 'sec_uid' in params:
                sec_user_id = params['sec_uid'][0]
    except Exception as e:
        log.warning(f"获取跳转链接失败: {e}，尝试作为原链接处理")

    return final_url, sec_user_id

