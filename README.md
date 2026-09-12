# auto-login

桂桂（GuiGui）— 桂航学子专属的校园网自动登录工具。单仓库四层：主程序、官网、文档、v1 归档。

## 目录

| 路径 | 内容 |
|------|------|
| `guigui/` | v2 主项目：pywebview(WebView2) 壳 + `app/static` 前端 + `core/` 后端 + `tests/` + 打包脚本 |
| `site/` | 桂桂官网，自包含静态站（线上 guigui-guat.pages.dev，部署从本目录执行） |
| `docs/` | v2 文档：`prd/guigui-prd-v2.*`（产品）、`tech/`（后端计划 / 桥接契约 / 保真审计 / 打包实测） |
| `legacy-v1/` | v1 SchoolAutoLogin（customtkinter 版）整体归档，含测试与打包脚本；不再维护 |

## 常用命令

```bash
# 前端开发壳（无边框保真验证，mock 数据走 ?dev=1）
python guigui/devshell.py [scene]    # scene ∈ ok|out|down|waiting|daily|rejected

# v2 测试（用专用 venv）
.venv-guigui/Scripts/python -m pytest guigui/tests

# v2 打包（exe → dist/guigui，安装器 → guigui/Output）
cd guigui && build_guigui.bat
```

## 约定

- 开发约定见 `AGENTS.md`（每次修改后必须提交、设计 taste 流程等）。
- v2 运行时数据在 `%LOCALAPPDATA%\GuiGui`，不落仓库；凭据存 Windows 凭据管理器。
- v1 归档件如需运行，进入 `legacy-v1/` 目录内执行（其脚本全部为相对路径）。

## 许可证

本项目源代码以 [MIT License](LICENSE) 发布(2026-09-12 起);`legacy-v1/` 归档与 `docs/prd/vendor/` 内第三方资产遵循其各自注明之条款。

## 隐私

桂桂**不含任何自动上报/遥测**。仅当你主动提交问题反馈时,才会附带学号标识与诊断信息(系统/网络状态摘要,HTTPS 直传项目反馈端点);密码永远只存本机 Windows 凭据管理器,不出设备、不进任何上报。卸载时可选择是否清除本地数据。

