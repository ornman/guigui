# Auto Login - 校园网自动登录

Dr.COM 校园网认证系统自动登录工具，带 GUI 界面（customtkinter）、系统托盘、定时登录。打包为 Inno Setup 安装程序，安装后开箱即用。

## 项目结构

```
auto-login/
├── main.py              # 入口（GUI 模式 / --silent 静默模式）
├── src/                 # 核心模块
│   ├── app.py           # GUI 主窗口（customtkinter）
│   ├── config.py        # 配置读写
│   ├── login.py         # HTTP GET 登录逻辑
│   ├── notify.py        # Windows 通知（PowerShell WinRT）
│   ├── wifi.py          # WiFi 自动切换（netsh）
│   └── ui/
│       ├── components.py # 可复用 UI 组件
│       └── theme.py      # 主题 / 设计 token
├── auto_login.py        # 旧版单文件脚本（build.bat 仍引用，待迁移）
├── auto_login.spec      # 旧版 PyInstaller 配置
├── config.json          # 账号密码配置（gitignore）
├── config.example.json  # 配置模板
├── setup.iss            # Inno Setup 安装脚本
├── build.bat            # 一键构建脚本
├── PRD.md               # 产品需求文档
├── docs/
│   └── screenshots/     # UI 调试截图（gitignore）
├── build/               # PyInstaller 中间产物（gitignore）
├── dist/                # PyInstaller 输出（gitignore）
└── installer_output/    # 安装程序输出（gitignore）
```

## 配置

`config.json`（安装在 `%APPDATA%\SchoolAutoLogin\` 下）：
- `wifi_ssid`: 校园网 WiFi 名称，登录前自动切换到该网络（可选，不填则跳过）
- `operator`: 运营商（"中国电信"/"中国联通"/"校园用户"），当前 Dr.COM 版本不使用运营商后缀
- `username`: 学号
- `password`: 密码
- `max_retries`: 失败重试次数，默认 3
- `retry_interval_seconds`: 重试间隔秒数，默认 5

## 运行模式

| 模式 | 触发方式 | 窗口 | 通知 |
|------|---------|------|------|
| GUI 模式 | 双击 exe / `python main.py` | customtkinter 窗口 | Windows 通知 |
| 静默模式 | `python main.py --silent` | 无 | Windows 通知 |
| 定时任务 | 任务计划 06:55 | 无 | Windows 通知 |

## 定时任务

Windows 任务计划 `SchoolAutoLogin`，每天 06:55 执行，启用 WakeToRun（从睡眠唤醒）和 StartWhenAvailable（错过后补执行）。

安装程序自动创建，卸载时自动删除。

```bash
# 查看
schtasks //query //tn "SchoolAutoLogin"

# 手动触发
schtasks //run //tn "SchoolAutoLogin"

# 删除
schtasks //delete //tn "SchoolAutoLogin" //f
```

## 打包

依赖：PyInstaller、Inno Setup 6、customtkinter

```bash
# 一键构建（检查依赖 → 打包 exe → 生成安装程序）
build.bat

# 输出: installer_output/SchoolAutoLogin_Setup_1.0.0.exe
```

手动步骤：
```bash
pyinstaller auto_login.spec
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" setup.iss
```

> **注意**：`build.bat` 和 `auto_login.spec` 仍指向旧版 `auto_login.py`，需要更新为 `main.py` + `src/` 结构。

## 技术细节

- 认证系统：Dr.COM eportal，页面编码 GB2312
- 登录检测：访问 `http://10.1.2.3`，页面 `<title>` 含"注销"表示已登录
- 登录方式：HTTP GET 请求 JSONP 接口
  - URL: `http://10.1.2.3/drcom/login?callback=dr1003&DDDDD=<学号>&upass=<密码>&0MKKey=123456&R1=0&R2=&R3=1&R6=0&para=00&v6ip=&terminal_type=1&lang=zh-cn&jsVersion=4.2.1&v=<timestamp>&lang=zh`
  - 响应格式: `dr1003({"result":0/1, "msga":"...", ...})`
  - `result=1` 表示登录成功，`result=0` 表示失败
- 使用 `urllib` 标准库，无需第三方依赖（登录部分）
- GUI 使用 `customtkinter`（基于 tkinter 的现代主题库）
- Windows 通知通过 PowerShell WinRT API 实现，无需额外安装包
- 启动时自动切换到指定 WiFi（通过 `netsh wlan connect`），解决睡眠唤醒后连接到其他网络的问题
- 等待网络就绪（最多 120 秒），解决睡眠唤醒后网络延迟问题
