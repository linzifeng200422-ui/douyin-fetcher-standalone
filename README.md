# 抖音视频解析与文案提取工具 (Douyin Fetcher Standalone)

这是一个完全独立的开源抖音视频解析与文案提取工具。支持免 Cookie 运行、Cookie 本地加密绕过、自动压制无水印音轨，并可调用本地 Whisper 开展 ASR 台词还原。

本工具为独立项目，不依赖任何第三方内容校准框架。

## 系统要求 (System Requirements)

*   **Python**: 3.8 或更高版本
*   **FFmpeg**: 用于音视频转码与合并。请确保 `ffmpeg` 命令在系统 PATH 中。
    *   macOS 安装命令：`brew install ffmpeg`

---

## 快速上手 (Quick Start)

### 1. 安装 Python 依赖
```bash
pip install -r requirements.txt
```

### 2. 下载单个视频
```bash
python3 douyin_parser.py --url "https://v.douyin.com/abcde12/"
```

### 3. 批量拉取个人主页作品
```bash
python3 douyin_parser.py --url "https://v.douyin.com/user_home_link/" --count 5
```

### 4. 加载 Cookie 进行请求
```bash
# 传入字符串
python3 douyin_parser.py --url "https://v.douyin.com/..." --cookie "ttwid=xxx; sessionid=yyy"

# 传入本地 txt 文件
python3 douyin_parser.py --url "https://v.douyin.com/..." --cookie-file "./cookie.txt"
```

---

## 输出目录结构

下载与解析成功后，本脚本会在 `downloads/` 生成标准的脚手架：
```text
downloads/
└── <博主昵称>/
    └── <19位视频ID>/
        ├── audio.mp3               # 提取无水印音频
        ├── meta.md                 # 播放量、点赞量等统计元数据 (Markdown)
        ├── transcript.md           # Whisper 转录台词文案 (Markdown)
        └── collection-status.json  # 采集状态运行指标 (JSON)
```

若需了解底层解析与抓取原理（iesdouyin 网页参数解密及接口请求流），请参阅 [skills/SKILL.md](skills/SKILL.md) 详细文档。
