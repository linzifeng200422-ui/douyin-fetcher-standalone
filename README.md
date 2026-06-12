# 抖音视频解析与文案提取工具 (Douyin Fetcher Standalone)

这是一个完全独立的开源抖音视频解析与文案提取工具。支持抖音博主主页作品分页抓取、统一输出目录、音轨提取，并可调用本地 Whisper 开展 ASR 台词还原。

本工具为独立项目，不依赖任何第三方内容校准框架。

当前推荐抖音主页后端是 [Johnserf-Seed/f2](https://github.com/Johnserf-Seed/f2)。本项目只复用 F2 的作品列表分页、A-Bogus 签名和必要下载能力，不使用 F2 的 `--auto-cookie`。登录态仍通过本项目的 `get_cookie.py` 写入 `cookie.txt` 和 `.auth/`。

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

### 3. 扫码保存抖音 Cookie
```bash
python3 get_cookie.py
```

扫码登录后确认当前目录生成或更新：

```text
cookie.txt
.auth/state.json
```

关闭扫码浏览器后再次运行 `python3 get_cookie.py`，如果浏览器仍保持登录态，就说明 Cookie 持久化正常。

### 4. 探测主页作品列表，不下载
```bash
python3 douyin_parser.py \
  --url "https://v.douyin.com/user_home_link/" \
  --backend f2 \
  --list-only
```

### 5. 下载主页最近 1 个作品，跳过 ASR
```bash
python3 douyin_parser.py \
  --url "https://v.douyin.com/user_home_link/" \
  --backend f2 \
  --count 1 \
  --skip-asr
```

### 6. 全量下载博主主页作品
```bash
python3 douyin_parser.py \
  --url "https://v.douyin.com/user_home_link/" \
  --backend f2 \
  --all \
  --skip-asr
```

`--all` 会让 F2 按 `max_cursor/has_more` 分页模型拉取全部可访问作品。中途 `Ctrl+C` 后，已成功写入 `audio.mp3` 且 `collection-status.json(status=success)` 的作品会在下次运行时跳过。

### 7. 批量拉取个人主页最近作品
```bash
python3 douyin_parser.py \
  --url "https://v.douyin.com/user_home_link/" \
  --backend f2 \
  --count 5
```

### 8. 加载 Cookie 进行请求
```bash
# 传入字符串
python3 douyin_parser.py --url "https://v.douyin.com/..." --cookie "ttwid=xxx; sessionid=yyy"

# 传入本地 txt 文件
python3 douyin_parser.py --url "https://v.douyin.com/..." --cookie-file "./cookie.txt"
```

---

## 后端选择

```bash
python3 douyin_parser.py --url "<链接>" --backend auto
python3 douyin_parser.py --url "<抖音主页链接>" --backend f2 --all --skip-asr
python3 douyin_parser.py --url "<通用视频链接>" --backend yt-dlp
python3 douyin_parser.py --url "<抖音链接>" --backend legacy --count 3
```

后端含义：

*   `auto`：默认模式。抖音主页优先走 F2；通用非抖音链接交给 `yt-dlp`。
*   `f2`：抖音博主主页主后端，支持 `--all`，不逐个打开视频详情页。
*   `yt-dlp`：通用视频链接后端，只负责下载，最终目录仍由本项目归一化。
*   `legacy`：旧公共 API / 本地 API / Playwright 兜底逻辑，不支持 `--all`。

F2 不存在时，脚本会自动创建隔离环境 `.external/venv-f2` 并安装 `f2`。如只想检查本机环境，不希望自动安装：

```bash
python3 douyin_parser.py --url "<抖音主页链接>" --backend f2 --list-only --no-install-f2
```

F2 的临时输入配置写入 `.external/runtime/`，权限为 `0600`，执行后清理。Cookie 不会出现在 F2 子进程命令行参数里。

---

## Cookie 稳定性测试

建议按下面顺序测试：

```bash
python3 get_cookie.py
test -s cookie.txt
test -s .auth/state.json
python3 get_cookie.py
python3 get_cookie.py
```

第一次扫码后关闭浏览器；第二、三次启动时应复用 `.auth/` 登录态，不需要重新扫码。若手动破坏 `cookie.txt`，`--backend f2` 会明确提示重新运行 `get_cookie.py`，不会静默回退到错误数据。

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

断点续跑判断条件为：`audio.mp3` 存在且非空，同时 `collection-status.json` 中 `status` 为 `success`。失败、中断或 ASR 失败的作品不会被当成已完成，会在重跑时重新处理。

若需了解底层解析与抓取原理（iesdouyin 网页参数解密及接口请求流），请参阅 [skills/SKILL.md](skills/SKILL.md) 详细文档。
