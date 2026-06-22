# Active Context

## 当前状态
已成功完成本项目与 `jiji262/douyin-downloader` 的融合升级。移除了全部旧命令行接收参数，实现了完全基于 `config.yml` 纯 YAML 配置驱动的多后端（F2, Playwright, yt-dlp, dy-downloader）调度逻辑。所有核心代码重构完工，共 99 个单元测试与冒烟测试 100% 验证通过。

## 上次做了什么
1. 拷贝并优化了命令行控制主模块 `cli/main.py` 以及测试套件。
2. 修复了 Playwright 同步 API 与 asyncio 线程冲突，并将 CLI 模块下载主干流程改造为更健壮的同步 `main_sync` 模式。
3. 优化了 `resolve_share_url` 的解析逻辑，增加了对 PC 浏览器直接复制的主页链接（`douyin.com/user/`）的直接正则提取支持。
4. 清理了 `douyin_parser.py`、`external_backends.py` 等冗余 legacy 临时代码文件。
5. 编写并修订了中英双语的权威 `README.md` 与 `README.zh-CN.md` 手册。

## 下一步具体操作
1. 提交所有更改，并向用户提供完整的开发总结和测试报告。

## 关键技术决策
1. **纯 YAML 配置文件驱动**：完全砍掉冗余命令行，只保留 `--config` 加载配置与 `--serve` 提供后端接口服务，简化了部署与批量调用。
2. **多后端模块解耦**：将所有外部适配后端解耦进 `backends/` 子包（f2, ytdlp, browser_fallback, dy_downloader, venv_manager），使核心 `core/` 下载层可专注处理单一作品的高画质与文案转录事务。
