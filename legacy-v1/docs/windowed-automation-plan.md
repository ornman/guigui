# 实施计划:自动化收拢到早间窗口 + GUI 解耦 + 治弹窗

> 状态:待审批 · 日期:2026-06-17 · 执行方式:新会话中 `执行计划`

## 一、问题诊断

### 1.1 现状:全天多触发器重叠,越权
当前任务计划 `SchoolAutoLogin` 三个触发器全天运行:
- `AtLogon`(登录时,全天)+ `Once/Repetition`(每 15 分钟,全天)+ `Daily 06:55`
- 叠加 GUI 内轮询线程(每 30 秒),多层做同一件事
- 全天任务本意只是"保证早上能登录",却让程序 7×24 每 15 分钟起进程,99% 探测结果是"已登录",纯属浪费

### 1.2 弹窗元凶(用户痛点"动不动弹窗")
`ensure.py:_spawn_tray_detached` 在每次 `--ensure` 心跳时,若检测到托盘进程不在,就 `subprocess.Popen([python, main.py])` 拉起一个 GUI 进程。而 `main.py` 无参启动 → `App()` → `CTk` 主窗口默认显示。

```
每15分钟 --ensure → 发现 GUI 被关 → 拉起新 GUI → 主窗口弹出
→ 用户关掉 → 下一个15分钟 → 再拉起 → 再弹窗(死循环)
```
通知(`notify.send`)在每次"恢复"时发 Toast,叠加成"动不动弹通知"。

### 1.3 角色混乱
GUI 同时承担:设置界面 + 常驻守护(轮询)+ 托盘宿主;`--ensure` 被阉割(`skip_wifi=True` 不重连)只当看门狗。没有独立的"静默执行体"角色。

## 二、目标架构(三层分离)

```
┌─ GUI(设置前端,非常驻,手动开关)─────────────┐
│  账号/WiFi/窗口时间 · 手动登录 · 巡逻开关 · 启停按钮 │
│  设完即关,绝不被自动拉起                          │
└──────────────────────────────────────────────┘
                    │ 部署/移除
                    ▼
┌─ 任务计划(自动化核心,静默)─────────────────────┐
│  ① 窗口任务(默认开):06:25–07:25 每5分钟 --ensure  │
│  ② 全天巡逻(可选,GUI开关):全天每N分钟 --ensure    │
└──────────────────────────────────────────────┘
                    │ 触发
                    ▼
┌─ --ensure(静默执行体,无窗口)───────────────────┐
│  登录/重连(含WiFi兜底) · 不拉GUI · 通知仅在状态翻转时 │
└──────────────────────────────────────────────┘
```

**核心原则**:自动化全程静默无窗口;GUI 只在用户手动打开时存在;控制权(巡逻/启停)交还 GUI 开关。

## 三、改动清单

### 3.1 `src/scheduler.py`
- **新增** `create_windowed_task(window_start, window_minutes, interval)`:
  - 用 `Daily -At window_start` + 嫁接 `Repetition(Interval=interval, Duration=window_minutes)`
  - **已验证语法可行**(2026-06-17 实测 `New-ScheduledTaskTrigger -Daily -At "06:25"` + `.Repetition` 嫁接,输出 `Interval=PT5M Duration=PT1H`)
  - Action:`pythonw.exe "main.py" --ensure`(复用已修复的 `scheduled_action_parts`)
- **新增** `create_patrol_task(interval)`:全天每 N 分钟一次(Once + Repetition,Duration 3650 天)
- `create_scheduled_task_multi` **删除**(旧全天心跳模型整体移除);self-heal 迁移逻辑把现存旧全天任务转到「窗口任务」
- 新增对应的 `is_windowed_task()` / `is_patrol_task()` 供 self-heal 对齐判断

### 3.2 `src/ensure.py`(治弹窗的关键)
- **删除** `_spawn_tray_detached` 及 `should_spawn_tray` 逻辑——`--ensure` 不再拉起 GUI
- **去掉** `skip_wifi=True` 限制(或改为 config 控制):让 `--ensure` 能完整重连(含 WiFi 兜底),否则窗口任务/巡逻无法真正保证登录
  - 取舍:窗口任务切 WiFi 合理(早起就是要连校园网);全天巡逻是用户主动开,接受切 WiFi
- **通知治理**:`recovered` 通知加"状态翻转去重"——仅当本次确实从"未登录/断网"变为"已登录"才发一次,不在已登录时反复发
- `tray_is_running` 探测可保留用于日志,但不再触发拉起

### 3.3 `src/selfheal.py`
- `reconcile_scheduler` 按新模型对齐:
  - 默认保证**窗口任务**存在(规格不符则重建)
  - `patrol_enabled` 开 → 保证巡逻任务存在;关 → 删除巡逻任务
- `should_task_be_enabled` / 新增 `should_patrol_be_enabled`
- 兼容旧全天任务检测 → 迁移到窗口任务

### 3.4 `src/config.py`
新增字段(带默认值 + 校验):
- `window_start`: `"06:25"`(由 `scheduled_login_time` 06:55 减 30 分钟推导,或独立配置)
- `window_duration_minutes`: `60`(前后各 30 分钟)
- `patrol_enabled`: `false`(默认关——全天巡逻是可选项)
- `patrol_interval_minutes`: `10`
- `heartbeat_interval_minutes` 复用为窗口内间隔(5)
- 保留 `scheduled_login_time` 作为窗口中心点(展示用)

### 3.5 `src/app.py`(GUI 回归设置前端)
- 设置面板新增/调整控件:
  - 窗口时间(展示 06:55,可调)/ 窗口内间隔
  - **「全天巡逻」开关**(对应 `patrol_enabled`)
  - **「启用自动化」按钮**(一键创建/删除任务计划,即启停)
  - 保留:WiFi、手动登录、通知开关
- `_apply_settings` 联动新任务模型(窗口任务 + 可选巡逻)
- `_auto_login_on_launch` 调整:GUI 非常驻,启动登录改为可选(或仅手动)
- 删除 `ensure` 相关的 spawn tray 依赖路径

### 3.6 `src/notify.py`
- 通知去重/限流辅助(配合 ensure 状态翻转)
- 确保仅在用户勾选"桌面通知"时发

### 3.7 `main.py`
- `--silent` 评估是否保留(可能被窗口任务/巡逻的 `--ensure` 取代)
- `--ensure` 保留为唯一静默执行入口

### 3.8 开机自启 / AtLogon(待用户最终确认)
- **推荐**:砍掉 AtLogon 触发器和全天心跳,只留窗口任务(+可选巡逻)
- **开机自启**:推荐砍(开机不一定在窗口内,且 GUI 非常驻);或改为"开机启动到托盘不弹窗"的可选项
- ⚠️ 此项影响"开机是否自动起程序",需用户审批时定

## 四、TDD(逻辑变更强制)
每个新函数/行为变更先写失败测试:
- `create_windowed_task` 生成的 PowerShell 含 `Daily -At '06:25'`、`PT5M`、`PT1H`
- `create_patrol_task` 含全天 Repetition
- `ensure` 不再 spawn tray(删除相关测试/断言)
- `ensure` 通知去重:连续两次 logged_in 只发一次
- `selfheal.reconcile_scheduler` 窗口/巡逻对齐逻辑
- `config` 新字段默认值与校验

## 五、迁移与兼容
- 现有全天任务(已注册)需在升级时替换为窗口任务(self-heal 迁移:检测到旧 `--ensure` 全天任务 → 删除并建窗口任务)
- `is_legacy_task` 扩展识别旧全天任务
- 用户首次运行新版:GUI 启动 self-heal 自动迁移

## 六、e2e 验证(更新 `test_e2e_resilience.py`)
- 窗口任务真实注册:XML 含 `<CalendarTrigger>` + `<Repetition>`(Interval PT5M, Duration PT1H)
- 巡逻任务真实注册:全天 Repetition
- `--ensure` 真实运行:退出码 0,**不产生 GUI 进程**(无弹窗验证)
- self-heal 迁移:旧全天任务 → 窗口任务

## 七、回滚
- 全程 git 分支/commit 粒度提交,可逐步 revert
- `create_scheduled_task_multi` 保留备用,确保能恢复全天模型

## 八、最终决策(2026-06-17 已确认)
1. **开机**:保留 `AtLogon` 触发器(登录 Windows 时静默 `--ensure` 登录一次);**删除开机自启 GUI**(HKCU Run)——避免开机弹窗。开机完全静默登录。
2. **全天机制合并为单一开关**:GUI「全天巡逻」开关,默认**关**。
   - 开 = 全天每 **30 分钟** `--ensure`(断网自动重连)
   - 关 = 无任何全天后台
   - **旧的"全天每 15 分钟心跳"删除**(不再作为独立机制,被巡逻完全取代,不保留两个名字)
3. **窗口任务**:默认开,06:25–07:25 每 5 分钟;**GUI 可调**窗口中心和时长。
4. **通知**:"从断到通" + "登录失败"各发一次;已登录不反复发(状态翻转去重)。
5. **`--silent` 模式**:并入 `--ensure`(废弃 `--silent`,统一一个静默执行入口)。

### 任务计划最终触发器
| 触发器 | 默认 | 说明 |
|---|---|---|
| `AtLogon` | ✅ 开 | 开机/登录时静默登录一次 |
| 窗口 `Daily + Repetition(PT5M/PT1H)` | ✅ 开 | 06:25–07:25 每 5 分钟,早起保底 |
| 巡逻 `Once + Repetition(PT30M/3650d)` | ❌ 默认关 | 全天断网重连,GUI 开关控制 |
| ~~全天每 15 分钟~~ | 🗑 删除 | 被巡逻取代 |
| ~~开机自启 GUI(HKCU Run)~~ | 🗑 删除 | 避免开机弹窗 |
