# -*- coding: utf-8 -*-
"""抖音下载器 - 命令行与调度冒烟集成测试。"""
import sys
from pathlib import Path
import pytest

from config import ConfigLoader
from cli.main import main, main_sync


def test_empty_config_smoke():
    """测试配置中 link 为空时，程序可以优雅返回而非崩溃。"""
    config = ConfigLoader(None)
    config.config["link"] = []
    # 应当优雅返回，不抛出异常
    main_sync(config)


def test_invalid_config_file_exit():
    """测试当配置文件不存在时，main() 应当非零退出。"""
    sys.argv = ["run.py", "-c", "non_existent_config_file_xyz.yml"]
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code != 0


def test_help_argument():
    """测试 --help 命令能够正确运行。"""
    sys.argv = ["run.py", "--help"]
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 0
