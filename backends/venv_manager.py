# -*- coding: utf-8 -*-
"""抖音下载器 - 外部后端虚拟环境管理器。"""
from __future__ import annotations

import os
import sys
import shutil
import signal
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("抖音下载器.backends.venv_manager")

EXTERNAL_DIR = Path(".external")
RUNTIME_DIR = EXTERNAL_DIR / "runtime"
F2_VENV_DIR = EXTERNAL_DIR / "venv-f2"
DY_DOWNLOADER_DIR = EXTERNAL_DIR / "research" / "douyin-downloader"
DY_DOWNLOADER_VENV_DIR = EXTERNAL_DIR / "venv-douyin-downloader"
YT_DLP_ARCHIVE = EXTERNAL_DIR / "yt-dlp-archive.txt"


class ExternalBackendError(RuntimeError):
  """Raised when an external backend cannot complete its work."""


def ensure_external_dirs() -> None:
  RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def secure_write_text(path: Path, text: str) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(text, encoding="utf-8")
  if os.name != "nt":
    try:
      os.chmod(path, 0o600)
    except OSError as exc:
      logger.warning("无法设置临时敏感文件权限 %s: %s", path, exc)


def cleanup_paths(paths: list[Path]) -> None:
  for path in paths:
    try:
      if path.is_dir():
        shutil.rmtree(path)
      elif path.exists():
        path.unlink()
    except OSError as exc:
      logger.warning("清理临时文件失败 %s: %s", path, exc)


def parse_cookie_header(cookie_str: str) -> dict[str, str]:
  cookies: dict[str, str] = {}
  for part in (cookie_str or "").split(";"):
    if "=" not in part:
      continue
    key, value = part.split("=", 1)
    key = key.strip()
    value = value.strip()
    if key:
      cookies[key] = value
  return cookies


def redact_cookie_values(text: str, cookie_str: str) -> str:
  if not text or not cookie_str:
    return text
  redacted = text.replace(cookie_str, "[COOKIE_REDACTED]")
  for value in parse_cookie_header(cookie_str).values():
    if len(value) >= 8:
      redacted = redacted.replace(value, "[COOKIE_VALUE_REDACTED]")
  return redacted


def venv_python_path(venv_dir: Path) -> Path:
  if os.name == "nt":
    return venv_dir / "Scripts" / "python.exe"
  return venv_dir / "bin" / "python"


def python_can_import(python_bin: Path, module_name: str) -> bool:
  try:
    result = subprocess.run(
      [str(python_bin), "-c", f"import {module_name}"],
      capture_output=True,
      text=True,
      timeout=20,
    )
    return result.returncode == 0
  except Exception:
    return False


def python_can_import_all(python_bin: Path, module_names: list[str]) -> bool:
  imports = "; ".join(f"import {name}" for name in module_names)
  try:
    result = subprocess.run(
      [str(python_bin), "-c", imports],
      capture_output=True,
      text=True,
      timeout=20,
    )
    return result.returncode == 0
  except Exception:
    return False


def ensure_f2_python(auto_install: bool = True) -> Path:
  """Return a Python executable that can import f2."""
  candidates = [Path(sys.executable), venv_python_path(F2_VENV_DIR)]
  for candidate in candidates:
    if candidate.exists() and python_can_import(candidate, "f2"):
      return candidate

  if not auto_install:
    raise ExternalBackendError("未检测到可导入 f2 的 Python 环境。")

  if sys.version_info < (3, 10):
    raise ExternalBackendError("F2 需要 Python >= 3.10；当前 Python 版本过低。")

  ensure_external_dirs()
  logger.info("未检测到 F2，正在创建隔离环境: %s", F2_VENV_DIR)
  subprocess.run([sys.executable, "-m", "venv", str(F2_VENV_DIR)], check=True)
  python_bin = venv_python_path(F2_VENV_DIR)
  pip_cmd = [str(python_bin), "-m", "pip", "install", "f2"]
  logger.info("正在隔离环境安装 F2，此步骤可能需要数分钟...")
  subprocess.run(pip_cmd, check=True)

  if not python_can_import(python_bin, "f2"):
    raise ExternalBackendError("F2 安装完成但仍无法导入。")
  return python_bin


def ensure_dy_downloader_python(auto_install: bool = True) -> Path:
  """Return a Python executable suitable for jiji262/douyin-downloader."""
  if not DY_DOWNLOADER_DIR.is_dir():
    raise ExternalBackendError(
      f"未找到 jiji262/douyin-downloader 源码目录: {DY_DOWNLOADER_DIR}"
    )

  required_modules = ["aiohttp", "yaml", "rich"]
  candidates = [venv_python_path(DY_DOWNLOADER_VENV_DIR), Path(sys.executable)]
  for candidate in candidates:
    if candidate.exists() and python_can_import_all(candidate, required_modules):
      return candidate

  if not auto_install:
    raise ExternalBackendError(
      "未检测到可运行 dy-downloader 的 Python 环境。"
    )

  ensure_external_dirs()
  logger.info("未检测到 dy-downloader 依赖，正在创建隔离环境: %s", DY_DOWNLOADER_VENV_DIR)
  subprocess.run([sys.executable, "-m", "venv", str(DY_DOWNLOADER_VENV_DIR)], check=True)
  python_bin = venv_python_path(DY_DOWNLOADER_VENV_DIR)
  requirements_path = DY_DOWNLOADER_DIR / "requirements.txt"
  if not requirements_path.is_file():
    raise ExternalBackendError(f"dy-downloader requirements.txt 不存在: {requirements_path}")
  logger.info("正在隔离环境安装 dy-downloader 依赖，此步骤可能需要数分钟...")
  subprocess.run(
    [str(python_bin), "-m", "pip", "install", "-r", str(requirements_path)],
    check=True,
  )

  if not python_can_import_all(python_bin, required_modules):
    raise ExternalBackendError("dy-downloader 依赖安装完成但仍无法导入。")
  return python_bin


def terminate_process_group(proc: subprocess.Popen) -> None:
  if proc.poll() is not None:
    return
  try:
    if os.name != "nt":
      os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    else:
      proc.terminate()
    proc.wait(timeout=10)
  except Exception:
    try:
      if os.name != "nt":
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
      else:
        proc.kill()
    except Exception:
      pass


def run_supervised(
  cmd: list[str],
  *,
  cwd: Path | None = None,
  cookie_str: str = "",
  timeout: int | None = None,
  env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
  start_new_session = os.name != "nt"
  proc = subprocess.Popen(
    cmd,
    cwd=str(cwd) if cwd else None,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    start_new_session=start_new_session,
    env=env,
  )
  try:
    stdout, stderr = proc.communicate(timeout=timeout)
  except KeyboardInterrupt:
    terminate_process_group(proc)
    raise
  except subprocess.TimeoutExpired:
    terminate_process_group(proc)
    raise ExternalBackendError(f"外部命令超时: {cmd[0]}")

  stdout = redact_cookie_values(stdout or "", cookie_str)
  stderr = redact_cookie_values(stderr or "", cookie_str)
  return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
