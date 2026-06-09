# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Dr.COM 校园网自动登录工具 — Windows 桌面应用，带 customtkinter GUI、系统托盘、定时登录、自动重连。打包为 Inno Setup 安装程序。

## Commands

```bash
# Run
python main.py                # GUI 模式
python main.py --silent       # 静默模式（无窗口，用于定时任务）

# Test
pytest                        # 运行全部测试
pytest tests/test_login.py    # 单文件
pytest tests/test_login.py::TestAttemptLogin::test_unreachable_no_wifi_configured  # 单用例
pytest --cov=src --cov-report=term-missing   # 覆盖率

# Build（一键打包 exe + 安装程序）
build.bat
# 输出: installer_output/SchoolAutoLogin_Setup_1.0.0.exe

# 手动打包步骤
pyinstaller main.spec
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" setup.iss
```

依赖：Python 3.12+、customtkinter、PyInstaller、Inno Setup 6。无 `requirements.txt` 或 `pyproject.toml`。

## Architecture

### 模块职责

| 模块 | 职责 |
|---|---|
| `main.py` | 入口：`--silent` 走 `run_silent()`，否则启动 `App` GUI |
| `src/login.py` | 核心登录逻辑：`check_auth_status()` 三态探测 → `attempt_login()` 编排 → `do_login()` HTTP 请求 |
| `src/config.py` | `config.json` 读写 + schema 验证（`validate()` 返回新 dict，不修改原对象） |
| `src/app.py` | GUI 主窗口（customtkinter），包含登录面板、设置面板、轮询线程 |
| `src/wifi.py` | WiFi 切换（`netsh wlan connect`），仅在认证服务器不可达时触发 |
| `src/notify.py` | Windows Toast 通知（PowerShell WinRT），`_xml_escape()` 防 XSS |
| `src/scheduler.py` | Windows 任务计划 CRUD（PowerShell `Register-ScheduledTask`） |
| `src/autostart.py` | 开机自启（HKCU `Run` 注册表键） |
| `src/ui/theme.py` | 设计 token：调色板、间距、字体、圆角（全部 `R=0`，新粗野主义风格） |
| `src/ui/components.py` | 可复用组件：`GlassCard`、`BrutalButton`（带阴影动画）、`StatusDot` |

### 登录决策流程（关键）

`src/login.py:attempt_login()` 以认证服务器 `http://10.1.2.3` 为唯一决策枢纽：

```
check_auth_status()
  ├─ "logged_in"     → 返回，无需操作
  ├─ "not_logged_in" → 直接 do_login()（不碰 WiFi）
  └─ "unreachable"   → 有 wifi_ssid 配置？→ wifi.connect() → wait_for_network()
                       → 重试 check_auth_status()
                         ├─ "logged_in"     → 返回
                         ├─ "not_logged_in" → do_login()
                         └─ "unreachable"   → 放弃
```

`do_login()` 失败时按 `max_retries` 重试，间隔 `retry_interval_seconds`。

### GUI 线程模型

- 主线程：customtkinter 事件循环
- 登录/轮询：`threading.Thread(daemon=True)`，通过 `self.after(0, callback)` 回调 UI 更新
- 轮询线程用 `threading.Event` (`_poll_stop`) 实现可中断等待
- 窗口关闭时 `_on_close()` 先 `_stop_polling()` 再 `destroy()`

### 配置

`config.json`（安装后位于 exe 同目录，开发时位于项目根目录）：
- `url`: 认证服务器地址，默认 `http://10.1.2.3`
- `wifi_ssid`: 校园网 WiFi 名称，留空跳过 WiFi 切换
- `operator`: 运营商（当前 Dr.COM 版本不使用运营商后缀）
- `username` / `password`: 学号和密码
- `max_retries` / `retry_interval_seconds`: 登录重试策略
- `polling_enabled` / `polling_interval_seconds`: 断网自动重连
- `scheduled_login_enabled` / `scheduled_login_time`: 定时登录
- `auto_start`: 开机自启（HKCU Run 注册表）
- `notification_enabled`: 桌面通知开关

所有配置通过 `config.validate()` 校验，返回新 dict（不修改原对象）。

### 认证服务器协议

- 编码：GB2312（登录页面）/ GBK（JSONP 响应）
- 登录：HTTP GET JSONP → `dr1003({"result":0/1, "msga":"..."})`
- 判断已登录：页面 `<title>` 包含 "注销"
- 使用 `urllib` 标准库，登录部分无第三方依赖

### 测试结构

`tests/` 下用 pytest + `unittest.mock`：
- `test_login.py`：`check_auth_status` 三态、`do_login` 成功/失败、`attempt_login` 完整编排（mock `urlopen`）
- `test_config.py`：load/save/roundtrip、默认值合并
- `test_notify.py`：`_xml_escape` 特殊字符和中文编码

测试用 `patch("src.login.urlopen")` mock HTTP，不依赖网络。

### 打包

- `main.spec`：PyInstaller 配置（单文件 exe）
- `setup.iss`：Inno Setup 安装脚本，安装时可选创建定时任务，卸载时自动删除
- `build.bat`：一键构建（检查依赖 → PyInstaller → 复制 config → Inno Setup）
