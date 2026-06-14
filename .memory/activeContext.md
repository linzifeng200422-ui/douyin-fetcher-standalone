# Active Context

## 当前状态
已完成对抖音博主主页作品下载的完整性与最高画质的深入审查与设计方案撰写。

## 上次做了什么
1. 分析了项目根目录下的 `douyin_parser.py` 分页与画质过滤逻辑。
2. 扫描并比对了 `.external/research/` 目录下全部 4 个开源参考项目（`f2`, `douyin-downloader`, `Douyin_TikTok_Download_API`, `TikTokDownloader`）的接口选型及实现。
3. 创建了详尽的分析和改造报告 [analysis_and_plan.md](file:///Users/linzifeng/.gemini/antigravity-cli/brain/e23cb39b-61d7-4fc0-879e-117a386c699c/analysis_and_plan.md)。

## 下一步具体操作
等待用户批准方案。若需要进行实际修改，将开始根据方案逐步改造 Cookie 状态探活模块和合集/裸 ID detail 回补流程。

## 关键技术决策
1. **接口选择**：抖音 App 端的签名机制极其复杂且指纹限制多，而 Web 端的 `/aweme/v1/web/aweme/post/` 配合 A-Bogus 签名和有效的登录态 Cookie 具有最佳的可靠性，故继续维持 Web 端接口方案。
2. **最高画质逻辑**：横屏原片和原比例视频必须通过遍历 `video.bit_rate` 中的所有转码变体，并使用外层 `video.width` 与 `video.height` 的比例作为目标比例进行比例 penalty 计算，剔除被平台裁剪/加黑边后的 9:16 默认播放流（`play_addr`）。
