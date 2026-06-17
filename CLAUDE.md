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
# build.bat 会自动检查并安装 PyInstaller 和 Inno Setup

# 手动打包步骤
pyinstaller main.spec
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" setup.iss
```

依赖：Python 3.12+、customtkinter、PyInstaller、Inno Setup 6。无 `requirements.txt` 或 `pyproject.toml`。

## Architecture

### 模块职责

| 模块 | 职责 |
|---|---|
| `main.py` | 入口：`--ensure` 静默执行 / 否则启动 `App` GUI（`--silent` 已废弃并入 `--ensure`） |
| `src/login.py` | 核心登录逻辑 + 日志初始化（`RotatingFileHandler` → `login.log`） |
| `src/config.py` | `config.json` 读写 + schema 验证（`validate()` 返回仅含 schema 键的新 dict，丢弃未知键） |
| `src/app.py` | GUI 主窗口（设置前端 + 手动登录，非常驻，无后台轮询） |
| `src/wifi.py` | WiFi 切换（`netsh wlan connect`），仅在认证服务器不可达时触发 |
| `src/notify.py` | Windows Toast 通知（PowerShell WinRT），`_xml_escape()` 防 XSS |
| `src/scheduler.py` | Windows 任务计划 CRUD：窗口任务（AtLogon+窗口 Daily/Repetition）+ 巡逻任务（全天 Repetition），`_ps_escape()` 防注入 |
| `src/ensure.py` | `--ensure` 静默执行体：幂等登录（含 WiFi 兜底）+ `decide_notify()` 状态翻转去重，绝不拉起 GUI |
| `src/selfheal.py` | 把任务计划幂等对齐到窗口+巡逻模型（缺失/旧版迁移/应关却存在才动手） |
| `src/instance.py` | 单实例锁（Win32 命名互斥量，ctypes） |
| `src/tray.py` | 系统托盘（pystray + Pillow） |
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

### 自动化模型（窗口 + 巡逻，三层分离）

GUI 非常驻（设完即关，绝不自动拉起）；后台自动化全部在任务计划里，`--ensure` 是唯一静默执行体：

```
┌─ GUI（设置前端 + 手动登录，非常驻）──────────────────────┐
│  账号/WiFi/窗口时间/巡逻开关 · 启用自动化 · 手动登录       │
└──────────────────────────────────────────────────────┘
                    │ 部署/移除（self-heal 对齐）
                    ▼
┌─ 任务计划（自动化核心，静默）────────────────────────────┐
│  ① 核心窗口任务 SchoolAutoLogin（默认开）                │
│     AtLogon（登录时登录一次）+ 窗口 Daily@start+Repetition │
│  ② 巡逻任务 SchoolAutoLogin-Patrol（默认关，GUI 开关）   │
│     Once + Repetition（全天每 N 分钟断网重连）            │
└──────────────────────────────────────────────────────┘
                    │ 触发
                    ▼
┌─ --ensure（静默执行体，无窗口）──────────────────────────┐
│  完整登录（含 WiFi 兜底）· 不拉 GUI · 通知仅状态翻转时    │
└──────────────────────────────────────────────────────┘
```

- `resilience_enabled` 是自动化总开关：关 → 核心任务（含 AtLogon）与巡逻全删。
- 窗口起点 = `scheduled_login_time - window_duration_minutes/2`（跨午夜回绕）。
- `selfheal.reconcile_scheduler(cfg)` 幂等对齐：核心任务缺失/旧版（`is_legacy_task`）→ 迁移重建；巡逻按 `patrol_enabled` 增删。
- 通知去重：`ensure.decide_notify()` 跨进程记忆 `ensure_state.json`，"断→通" 与 "登录失败" 各发一次，已登录不打扰。

### GUI 线程模型

- 主线程：customtkinter 事件循环
- 手动登录：`threading.Thread(daemon=True)`，通过 `self.after(0, callback)` 回调 UI 更新
- **无后台轮询**：断网重连交给巡逻任务，GUI 不再常驻探测
- 关窗：`resilience` 开 → 最小化到托盘保活；否则 `_real_quit()`（停托盘 + destroy）

### 路径解析

`src/config.py` 中的 `APP_DIR` 决定所有运行时文件位置：
- 开发模式：项目根目录（`src/` 的父目录）
- 打包模式（`sys.frozen`）：exe 所在目录

由此派生 `CONFIG_PATH`（`config.json`）、`LOG_PATH`（`login.log`）与 `ensure.STATE_PATH`（`ensure_state.json`）。

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

- `main.spec`：PyInstaller 配置（单文件 exe，`console=False`，打包 customtkinter 数据文件）
- `setup.iss`：Inno Setup 安装脚本，安装到 `%USERAPPDATA%`（非 Program Files），安装时可选创建定时任务，卸载时自动删除
- `build.bat`：一键构建（自动安装依赖 → PyInstaller → 复制 config → Inno Setup）
