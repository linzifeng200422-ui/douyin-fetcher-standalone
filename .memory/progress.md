# Progress

## 已完成的审查、设计与重构
- [x] 扫描并比对外部参考项目的接口选型及实现逻辑。
- [x] 移植并升级骨架结构，合并 requirements 核心库。
- [x] 完成 core 核心包内部的音视频画质评估、图集下载、ASR Whisper 以及元数据写入等功能的两步法合并。
- [x] 拆分多后端适配包 `backends/`。
- [x] 拷贝并重构 `cli/main.py` 为纯 YAML 驱动的多后端入口调度器。
- [x] 重构 `get_cookie.py` 扫码入口以调用统合的 `tools/cookie_fetcher.py`。
- [x] 移除 `douyin_parser.py` 等冗余 legacy 临时代码文件。
- [x] 编写中英文版本使用说明手册。
- [x] 修复 Playwright 与 asyncio 线程冲突与 PC 端链接解析细节。
- [x] 迁移并运行 99 个上游和本地的单元/集成/冒烟测试用例，100% 通过。

## 下一步工作
- [ ] 交付项目并合入 main 分支。
