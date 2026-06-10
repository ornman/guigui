# SchoolAutoLogin

校园网自动登录工具 — 自动检测网络状态、一键登录 Dr.COM 认证门户，支持定时登录、断网重连、开机自启。

## 功能

- **一键登录** — 自动检测认证状态，未登录则发起 Dr.COM 登录请求
- **WiFi 切换** — 认证服务器不可达时自动连接校园网 WiFi（可配置）
- **断网重连** — 后台轮询网络状态，断网自动重登
- **定时登录** — Windows 任务计划，每日定时静默登录
- **开机自启** — 注册 HKCU Run 键，开机自动运行
- **桌面通知** — Windows Toast 通知登录结果
- **系统托盘** — 最小化到托盘后台运行

## 界面

暗色新粗野主义（Neo-Brutalism）风格，460×780 窗口：

- 登录面板 — 状态指示灯 + 手动登录按钮
- 设置面板 — 账号密码、WiFi、运营商、重试策略、轮询间隔、定时任务、开机自启、通知开关

## 快速开始

### 前置要求

- Windows 10/11
- Python 3.12+
- [Inno Setup 6](https://jrsoftware.org/isinfo.php)（仅打包安装程序时需要）

### 安装依赖

```bash
pip install customtkinter
```

### 运行

```bash
# GUI 模式
python main.py

# 静默模式（无窗口，用于定时任务）
python main.py --silent
```

首次运行会在项目根目录生成 `config.json`，填入学号和密码即可。

## 配置

编辑 `config.json`（或通过 GUI 设置面板）：

```json
{
    "url": "http://10.1.2.3",
    "wifi_ssid": "",
    "operator": "中国电信",
    "username": "学号",
    "password": "密码",
    "max_retries": 3,
    "retry_interval_seconds": 5,
    "polling_enabled": false,
    "polling_interval_seconds": 60,
    "scheduled_login_enabled": false,
    "scheduled_login_time": "06:55",
    "auto_start": false,
    "notification_enabled": true
}
```

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `url` | 认证服务器地址 | `http://10.1.2.3` |
| `wifi_ssid` | 校园网 WiFi 名称，留空跳过 WiFi 切换 | `""` |
| `operator` | 运营商（中国电信 / 中国联通 / 校园用户） | `"中国电信"` |
| `username` | 学号 | — |
| `password` | 密码 | — |
| `max_retries` | 登录失败最大重试次数 | `3` |
| `retry_interval_seconds` | 重试间隔（秒） | `5` |
| `polling_enabled` | 启用断网自动重连 | `false` |
| `polling_interval_seconds` | 轮询间隔（秒） | `60` |
| `scheduled_login_enabled` | 启用定时登录 | `false` |
| `scheduled_login_time` | 每日登录时间（HH:MM） | `"06:55"` |
| `auto_start` | 开机自启 | `false` |
| `notification_enabled` | 桌面通知 | `true` |

## 登录流程

```
检测认证服务器状态
├─ 已登录         → 完成
├─ 未登录         → 直接登录
└─ 不可达         → 有 WiFi 配置？
                   ├─ 是 → 连接 WiFi → 等待网络 → 重新检测
                   └─ 否 → 放弃
```

登录使用 Dr.COM JSONP 接口（HTTP GET），编码 GB2312/GBK，无第三方依赖。

## 测试

```bash
pytest                                # 全部测试
pytest tests/test_login.py            # 单文件
pytest --cov=src --cov-report=term-missing   # 覆盖率
```

测试使用 `unittest.mock` 模拟 HTTP 请求，不依赖网络。

## 打包

一键打包 exe + 安装程序：

```bash
build.bat
```

输出：`installer_output/SchoolAutoLogin_Setup_1.0.0.exe`

`build.bat` 会自动检查并安装 PyInstaller 和 Inno Setup 6。安装程序：

- 安装到 `%APPDATA%\SchoolAutoLogin`（无需管理员权限）
- 可选创建每日 06:55 定时登录任务
- 卸载时自动删除定时任务

## 项目结构

```
auto-login/
├── main.py              # 入口（--silent 静默 / GUI 模式）
├── src/
│   ├── login.py         # 核心登录逻辑 + 日志
│   ├── config.py        # 配置读写 + 校验
│   ├── app.py           # GUI 主窗口（customtkinter）
│   ├── wifi.py          # WiFi 切换（netsh wlan connect）
│   ├── notify.py        # Windows Toast 通知
│   ├── scheduler.py     # Windows 任务计划管理
│   ├── autostart.py     # 开机自启（注册表）
│   └── ui/
│       ├── theme.py     # 设计 token（颜色、字体、间距）
│       └── components.py # 可复用 UI 组件
├── tests/               # pytest 测试
├── main.spec            # PyInstaller 配置
├── setup.iss            # Inno Setup 安装脚本
├── build.bat            # 一键构建脚本
└── config.example.json  # 配置示例
```

## 许可证

本项目仅供学习交流使用。
