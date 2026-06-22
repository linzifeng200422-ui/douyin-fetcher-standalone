# 抖音下载器 (Douyin Downloader)

这是一个基于纯 YAML 配置驱动、完全独立的开源抖音视频解析与文案批量下载工具（中文名称：抖音下载器）。支持抖音博主主页作品批量拉取、图集（图片）下载、无水印视频/音频保存、音轨提取、以及调用本地 Whisper ASR 开展台词提取。

## 特征 (Features)

*   **纯 YAML 配置驱动**：不再通过繁琐的命令行参数传参，一切设置均放置在 `config.yml` 中。
*   **多后端适配**：
    *   `auto`：默认。主页下载优先走 F2 后端，其他通用链接交给 `yt-dlp`。
    *   `f2`：抖音博主主页的高效分页与详情提取后端（基于 [Johnserf-Seed/f2](https://github.com/Johnserf-Seed/f2)）。
    *   `yt-dlp`：支持外部多平台的音视频解析下载。
    *   `dy-downloader`：支持调用 [jiji262/douyin-downloader](https://github.com/jiji262/douyin-downloader) 作为适配后端。
    *   `legacy`：旧版免 Cookie 网页解析以及 Playwright 浏览器拦截详情 API 模式。
*   **浏览器兜底与回补**：由于抖音主页分页极易被拦截，项目实现了一套 Playwright 浏览器主页滚动兜底与 F2 detail API 回补逻辑，确保 100% 完整抓取作品。
*   **音频自动提取与 ASR**：对缺失独立音频的作品，调用 FFmpeg 自动从视频中分离出音轨，并可调用本地 Whisper ASR 自动转录为台词文案（`transcript.md`）。
*   **强断点续传机制**：严密校验每个作品文件夹下媒体文件（`video.mp4` / `audio.mp3` 或图集图片）和 `collection-status.json` 的完整性，任何网络中断导致的脏数据均可在下次运行中被自动重试，完美完成增量回补。

---

## 系统要求 (System Requirements)

*   **Python**: 3.8 或更高版本
*   **FFmpeg**: 用于音视频转码与合并。请确保 `ffmpeg` 命令已安装并在系统的 `PATH` 环境变量中。
    *   macOS 安装命令：`brew install ffmpeg`

---

## 快速上手 (Quick Start)

### 1. 安装 Python 依赖
```bash
pip install -r requirements.txt
```

### 2. 扫码保存登录态 Cookie
```bash
python3 get_cookie.py
```
扫码登录后，程序会自动保存登录态到 `cookie.txt` 和 `.auth/state.json`。

### 3. 配置 `config.yml`
将默认配置文件 `config.example.yml` 复制为 `config.yml`：
```bash
cp config.example.yml config.yml
```
在 `config.yml` 中填写需要下载的链接和你的偏好设置。例如：
```yaml
link:
  - https://www.douyin.com/user/MS4wLjABAAAA6O7EZyfDRYXxJrUTpf91K3tmB4rBROkAw-nYMfld8ss

path: ./Downloaded/

backend: "auto"
video_quality: "resolution"

# 是否启用台词转写 (Whisper)
transcript:
  enabled: false
```

### 4. 运行下载
```bash
python3 run.py
```
程序将会全自动按照 `config.yml` 配置加载 Cookie 登录态，依次下载配置列表中的链接并保存作品。

### 5. 启动 REST API 服务模式
```bash
python3 run.py --serve
```
或在 `config.yml` 中配置 `server.enabled: true`。启动后可通过 API 增删下载任务（需安装额外依赖 `fastapi` 和 `uvicorn`）。

---

## 输出目录结构 (Output Structure)

下载成功后，程序将在输出目录下为每个博主和作品创建标准隔离目录：
```text
Downloaded/
└── <博主昵称>/
    └── <19位视频ID>/
        ├── video.mp4               # 无水印视频（图集则无）
        ├── image_1.jpg             # 图集原图（若是图集作品）
        ├── audio.mp3               # 无水印音轨（自动提取/下载）
        ├── meta.md                 # 播放、点赞、标题等元数据 (Markdown)
        ├── transcript.md           # Whisper ASR 转录台词文本 (Markdown)
        └── collection-status.json  # 详细运行状态记录 (JSON)
```

断点续传判断：当 `video.mp4`（或图集下的全部图片）与 `audio.mp3` 均存在且大小大于 0，且 `collection-status.json` 中的 `status` 为 `success` 时，程序会在下次运行时增量跳过。若中途被 `Ctrl+C` 中断或出现网络报错，将在下次运行中全自动进行增量重试回补。
