#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抖音下载器 - 扫码获取 Cookie 工具的快捷入口。"""
import sys
import json
from pathlib import Path
from tools.cookie_fetcher import main

if __name__ == "__main__":
    # 组装命令行参数
    args = []
    
    # 指定输出为上游推荐的 config/cookies.json
    args.extend(["--output", "config/cookies.json"])
    
    # 如果本地配置 config.yml 存在，将其作为参数传入，工具会自动更新配置文件中的 cookies 段
    if Path("config.yml").exists():
        args.extend(["--config", "config.yml"])
        
    print("==================================================")
    print("正在启动浏览器以获取抖音 Cookie (上游精简版)...")
    print("==================================================")
    
    # 启动上游 cookie 捕获器
    exit_code = main(args)
    
    # 成功捕获后，将精简清洗后的核心 Cookie 额外同步一份到根目录 cookie.txt，以向下兼容部分旧组件
    if exit_code == 0:
        cookies_json_path = Path("config/cookies.json")
        if cookies_json_path.is_file():
            try:
                cookies_dict = json.loads(cookies_json_path.read_text(encoding="utf-8"))
                cookie_str = "; ".join([f"{k}={v}" for k, v in cookies_dict.items()])
                Path("cookie.txt").write_text(cookie_str, encoding="utf-8")
                print("✓ [同步成功] 已将提纯后的核心 Cookie 导出到根目录 cookie.txt 文件。")
            except Exception as e:
                print(f"[警告] 同步 cookie.txt 失败: {e}")
                
    sys.exit(exit_code)
