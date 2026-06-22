# Douyin Downloader

A strictly YAML-driven, fully independent open-source tool for downloading Douyin videos, albums, and audios (Chinese name: 抖音下载器). It supports batch-fetching blogger homepages, high-resolution media downloading, local FFmpeg audio extraction, and ASR transcript extraction using local Whisper scripts.

> ⚠️ **Disclaimer**: This tool is strictly for technical research and education purposes. Please refer to the [Disclaimer](#disclaimer) section at the bottom for details.

## Features

*   **Strictly YAML-Driven**: No tedious command-line arguments. All configurations are located in `config.yml`.
*   **Multi-Backend Architecture**:
    *   `auto`: Default. Downloads Douyin homepages via F2 backend and delegates other platform links to `yt-dlp`.
    *   `f2`: An efficient scraper for Douyin posts based on [Johnserf-Seed/f2](https://github.com/Johnserf-Seed/f2).
    *   `yt-dlp`: Used for non-Douyin video platforms.
    *   `dy-downloader`: Integrates [jiji262/douyin-downloader](https://github.com/jiji262/douyin-downloader) as an alternative backend.
    *   `legacy`: Fallback using public APIs and Playwright network interceptors.
*   **Browser Fallback & Detail Fill**: Automatically launches a Playwright headless/headed browser session to bypass Douyin's pagination blockages, and leverages F2 detail APIs to retrieve missing metadata for scraped video IDs.
*   **Audio Extraction & Whisper ASR**: Automatically extracts audio tracks (`audio.mp3`) using FFmpeg if a standalone audio stream is missing, and transcribes spoken text into `transcript.md` via local OpenAI Whisper.
*   **Robust Incremental Resume**: Checks the integrity of downloaded media files and `collection-status.json`. Interrupted downloads (e.g. `Ctrl+C` or network drops) will be automatically retried and resolved in the next run.

---

## System Requirements

*   **Python**: 3.8 or higher.
*   **FFmpeg**: Required for audio transcoding and extraction. Make sure `ffmpeg` is available in your system's `PATH`.
    *   macOS installation: `brew install ffmpeg`

---

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Log in and Save Cookie
```bash
python3 get_cookie.py
```
Scan the QR code in the browser. The session state will be written to `cookie.txt` and `.auth/state.json`.

### 3. Setup `config.yml`
Copy the example config:
```bash
cp config.example.yml config.yml
```
Fill in the links you want to download and your preferences in `config.yml`. Example:
```yaml
link:
  - https://www.douyin.com/user/MS4wLjABAAAA6O7EZyfDRYXxJrUTpf91K3tmB4rBROkAw-nYMfld8ss

path: ./Downloaded/

backend: "auto"
video_quality: "resolution"

transcript:
  enabled: false
```

### 4. Run the Downloader
```bash
python3 run.py
```
The program will load your local credentials, process each link sequentially, and save all downloaded media.

### 5. Launch REST API Server
```bash
python3 run.py --serve
```
Or set `server.enabled: true` in `config.yml`. This allows adding download tasks programmatically (requires `fastapi` and `uvicorn` packages).

---

## Output Folder Structure

Downloads will be saved under the designated path structured by blogger nickname and video ID:
```text
Downloaded/
└── <Blogger Nickname>/
    └── <19-digit Video ID>/
        ├── video.mp4               # Watermark-free video
        ├── image_1.jpg             # Image files (if it is a photo gallery)
        ├── audio.mp3               # Audio track
        ├── meta.md                 # Statistics and descriptions (Markdown)
        ├── transcript.md           # Transcribed spoken text (Markdown)
        └── collection-status.json  # Runtime status indicators (JSON)
```

Resume Criteria: A folder is considered fully downloaded and skipped in subsequent runs only if `video.mp4` (or all images in a gallery) and `audio.mp3` are non-empty, and `status` in `collection-status.json` is `success`.

## Disclaimer

This project is intended solely for academic research, technical exchange, and personal data backup. Please use it in compliance with applicable local laws and regulations.

- **Legal Compliance**: Users must strictly comply with applicable cybersecurity, data security, and copyright laws when using this project.
- **Fair Use Only**: This tool is for personal study and legitimate data archiving. It is strictly prohibited to use this project to violate privacy, infringe copyrights, generate commercial profits, harvest sensitive information, or for any other illegal purposes.
- **No Liability**: Users assume all risks and liabilities arising from the use of this project. The author makes no warranties and shall not be held liable for any direct or indirect damages, losses, or legal disputes caused by its use.
- **API Risks**: All interfaces used by this project are based on normal browser rendering protocols and public network traffic. Any functional restriction or failure due to platform rule updates or security counter-measures constitutes normal technical risk.

By using this project, you acknowledge that you have read, understood, and agreed to all of the terms listed in this disclaimer.

## License

This project is licensed under the MIT License - see the [LICENSE](./LICENSE) file for details.
