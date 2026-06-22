#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抖音下载器 - 扫码获取 Cookie 工具的快捷入口。"""
import asyncio
import sys
from tools.cookie_fetcher import run_standalone_cookie_fetcher

if __name__ == "__main__":
    sys.exit(asyncio.run(run_standalone_cookie_fetcher()))
