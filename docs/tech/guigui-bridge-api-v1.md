# 桂桂 v2 · JS↔Python 桥接契约 v1.1.0

> **地位**:前后端通信协议的**唯一权威**(《guigui-work-split.md》§一.2)。后端 bridge 实现以此为准;`static/dev/mock.js` 是它的可执行规范(仅开发)。
> **绑定**:命名空间 `window.guigui.*`。pywebview 经 `js_api` 暴露,实现侧自行决定 camelCase 方法名或 snake_case+映射(契约只锁 JS 侧名字)。
> **变更规则**:改本文必须 bump 版本并登记「变更记录」,对方适配并回注后才生效。禁止静默改。

## 0. 总则

- **传输中立**:契约只定义方法/参数/返回/事件,不绑死 pywebview;前端经 `GG` 适配器绑定(`window.guigui` → `window.pywebview.api`),后端就位即切真,前端零改动。
- **mock 只许活在开发目录(1.0.1 起)**:可执行规范位于 `guigui/app/static/dev/mock.js`,仅当 URL 带 `?dev=1` 时由 `app.js` 动态注入;生产 `index.html` 不引用它。**后端打包必须整目录排除 `guigui/app/static/dev/`**。
- **生产禁止假数据回落**:生产模式后端未绑定时,适配器一律返回 `BRIDGE_MISSING`(见错误码表),UI 停在开机页明说「连不上后端,请重启/重装」;绝不渲染 mock 数据、绝不假成功。
- **统一信封**:所有方法返回 Promise。
  - 成功:`{ok:true, data:<载荷>}`
  - 失败:`{ok:false, code:<错误码>, message:<人话,可直显>}` —— 后端**不得抛异常代替信封**。
- **凭据纪律**:密码**永不下行**(任何返回都不含 password 字段);学号(uid)可以下行。登录时前端把用户键入的密码上行一次,后端存入 OS 凭据管理器。
- **视图路由不进契约**:三分流(ok/掉线/不可达)、来路栈、庆祝触发时机全部是前端逻辑;契约只供状态数据。
- **并发**:方法可并发调用;后端不得因一个长动作(登录/连 WiFi)阻塞查询类方法。

## 1. 错误码枚举

| code | 场景 | 前端表现(约定) |
|---|---|---|
| `NET_UNREACHABLE` | 认证服务器不可达 | 状态行/引导页,非弹窗 |
| `AUTH_REJECTED` | `result!=1`,密码被拒 | v-login 内联 `#login-err` |
| `WIFI_SCAN_FAILED` | netsh 扫描失败 | 列表区显示空态文案 |
| `WIFI_CONNECT_FAILED` | 连接失败(重试耗尽) | WiFi 行就地提示 |
| `WIFI_CONNECT_TIMEOUT` | 连接超时(90s) | 同上 |
| `NOT_CONFIGURED` | 未完成首装就触发动作 | 引导回首装页 |
| `SAVE_FAILED` | 配置落盘失败 | 设置项回滚 + 提示 |
| `BRIDGE_MISSING` | 后端未绑定/方法缺失(生产无回落) | 停在开机页,明示重启/重装 |
| `INTERNAL` | 兜底 | 内联提示,不弹窗 |

## 2. 方法清单

### 2.1 probe() — 开机探测(启动/手动重测共用)

时延承诺:≤10s(不可达判定的 HTTP 超时在内);期间前端停在 v-boot。

```jsonc
// data
{
  "configured": true,          // 首装已完成(学号+密码+任务就位)
  "net": {
    "state": "logged_in",      // logged_in | not_logged_in | unreachable | waiting
                                // waiting = 网络栈未就绪(刚开机/WiFi 还在连),对应 bootWait 等门 UI
    "ssid": "Campus-WiFi",     // 当前 WiFi,无则 null
    "server": "10.1.2.3"       // 认证服务器显示名
  }
}
```

### 2.2 identify() — 学号识别(chkstatus 抓取)

```jsonc
{ "uid": "2025000000001", "source": "chkstatus" }   // source: chkstatus | config | none
```

### 2.3 login({sid?, password?}) — 登录(首装开启/立即登录/重新登录共用)

- 省略 `password` → 用已存凭据;省略 `sid` → 用已存学号。重试节奏按配置,期间推 `login:progress` 事件。
- 时延承诺:最坏 ≈ 次数×(10s 超时+间隔),前端以事件驱动 UI,不设本地超时。

```jsonc
{ "result": "success", "uid": "2025…7209", "attempts": 1 }
// result: success | already | rejected | unreachable
// already = 探测发现已登录(等效成功,不算失败)
```

失败:`AUTH_REJECTED` / `NET_UNREACHABLE`(信封),`result` 不出现在失败信封里。

### 2.4 scanWifi() — 扫描可用网络(v-guide 列表 / 设置 WiFi 兜底选择)

```jsonc
{ "networks": [ { "ssid": "Campus-WiFi", "signal": "strong" } ] }
// signal: strong | medium | weak  → 前端映射 信号强/中/弱
// 已排除隐藏/空 SSID;重复 SSID 去重
```

### 2.5 connectWifi({ssid}) — 连接指定网络

- 时延承诺:最坏 90s;进度走 `login:progress`(`phase:"connecting_wifi"`)。
- 成功后后端继续探测并推 `net:state`;前端据此决定落 v-login 还是回 v-main。

```jsonc
{ "connected": true, "ssid": "Campus-WiFi" }
```

### 2.6 getConfig() — 读设置(不含密码)

```jsonc
{
  "trigger_time": "07:00",        // HH:MM,每日自动登录时刻(L1 中心)
  "boot_login": true,             // 开机时补登录(L2 AtLogon)
  "heartbeat_minutes": 5,         // 窗口内重试间隔 ∈ 5|10|15
  "wifi_fallback_enabled": false, // WiFi 兜底开关
  "wifi_fallback_ssid": null,     // 兜底目标网络(选不填,来自扫描)
  "patrol_enabled": false,        // 白天巡逻(L3)
  "patrol_minutes": 30,           // ∈ 15|30|60
  "wake_login": false,            // 睡眠唤醒补登录(L5)· 默认关(PRD §5)
  "vacation_silence": true,       // 假期静默
  "notifications": true,          // 弹通知
  "show_gui": true,               // 显示桂桂
  "master": true,                 // 后台自动化总开关(与主页开关同步)
  "login_retries": 3,             // ∈ 1|3|5
  "retry_seconds": 5              // ∈ 5|10|30
}
```

> 字段名是**桥接层契约名**;后端磁盘 `config_v2.json` schema 可自行映射,不必同名。

### 2.7 saveConfig(patch) — 保存设置(增量)

- 入参 = 2.6 的任意子集(不含密码;凭据只经 `login` 上行)。后端保存后**负责任务计划/selfheal 对齐**。
- 返回**完整**新配置(同 2.6 形状),前端用返回值刷新全 UI(避免本地推算漂移)。

### 2.8 masterToggle(on) — 总开关(独立于 saveConfig,语义重:建/删任务)

```jsonc
{ "master": false }
```

### 2.9 logs({days}) — 按天查日志(v-log 全量 / v-main 内嵌取今天)

```jsonc
{ "days": [
  { "label": "今天",              // 现成标签:今天 | 昨天 · 8月29日 | 8月28日 · 假期静默
    "entries": [
      { "ts": "07:00:01", "level": "ok",   "text": "网络可达" },
      { "ts": "07:00:02", "level": "ok",   "text": "已登录 · 2025…7209" },   // 学号打码由后端完成
      { "ts": "07:00:03", "level": "note", "text": "今天到这就下班啦 ☕" },
      { "ts": "07:00:01", "level": "silent", "text": "连不上,今天先不打扰,明天再试一次" }
    ] }
] }
// level: ok → [OK] 绿标签;note/silent/fail → 无标签纯文本(fail 的措辞写在 text 里)
// days 默认 14,上限 90;空天不返回
```

### 2.10 recentResult() — 「昨晚」一行(主页第三行体检)

```jsonc
{ "when": "今早", "time": "07:00", "tries": 1, "outcome": "ok" }
// outcome: ok | fail | silent | none(无记录)
// 前端映射示例:ok+tries=1 →「07:00 第一次就登好了 ✓」
```

### 2.11 winMinimize() / winClose() — 窗口控制

- 最小化=真最小化;关闭=退出 GUI(自动化不受影响,胶囊悬案以后端方案 §三.10 为准)。
- 拖拽不走方法:titlebar 挂 `pywebview-drag` 类,由壳处理。

### 2.12 feedback() — 问题反馈:打码诊断信息(1.1.0 新增)

时延承诺:≤6s(含一次实时网络探测;设置页入口「遇见问题?点击反馈」)。

```jsonc
{ "text": "桂桂 v2.0.0 诊断信息\n…" }
// 多行纯文本,已打码:学号 前4…后4,密码永不包含。
// 段落:版本/时间/系统 · 网络(实时探测)· 配置摘要(全部开关)· 凭据状态
//       · 自动化任务注册状态 · 最近 3 天日志。
// 前端负责展示 + 一键复制到剪贴板(复制动作在前端,后端只产文本)。
```

## 3. 事件推送(后端 → 前端)

后端经 `evaluate_js` 调用 `window.guiguiEmit(type, payload)`;payload 一律为对象。前端忽略未知 type(向前兼容)。

| type | payload | 触发 |
|---|---|---|
| `net:state` | `{state, ssid}`(同 probe.net 子集) | GUI 打开期间网络状态变化(含 connectWifi 之后、等待开门开门后) |
| `login:progress` | `{phase, attempt?, attempts?}`;phase ∈ probe\|connecting_wifi\|requesting\|retrying | login/connectWifi 执行中 |
| `log:appended` | `{day_label, entry}`(entry 同 2.9) | 静默 ensure 落日志(GUI 开着时主页内嵌日志追加) |
| `schedule:changed` | `{master, trigger_time}` | selfheal 对齐/外部变更后,前端同步两处开关与 desc |

## 4. 启动时序(约定,非方法)

1. 前端加载 → 立即 `probe()`(期间 v-boot 仪式照常播)。
2. `configured=false` → 首装单行道(仪式→三分支);`configured=true` → 日常页,`net.state=waiting` 时停在等门 UI 等 `net:state`。
3. 首装「开启每日自动登录」= `saveConfig`(学号+触发时间等)→ `login`(带密码)→ 成功进庆祝页;`AUTH_REJECTED` → 密码警告,不进庆祝。
4. **深链注入(1.0.2 收编)**:壳可在页面 loaded 前注入 `window.__guigui_launch`(一次性,`'main'|'creds'|'settings'`),前端在启动路由完成后消费并清除;未完成首装时忽略(单行道优先)。通知点击路由(`guigui://main` / `guigui://creds`)依赖此机制。

## 5. 版本与变更记录

| 版本 | 日期 | 变更 | 状态 |
|---|---|---|---|
| 1.0.0 | 2026-08-31 | 初版:11 方法 + 4 事件 + 8 错误码 | 已被 1.0.1 取代 |
| 1.0.1 | 2026-08-31 | mock 移入 `static/dev/`,仅 `?dev=1` 加载;生产无绑定返回 `BRIDGE_MISSING` 诚实报错(错误码 +1);打包必须排除 `static/dev/` | 前端已实现;后端已适配(guigui.spec 递归排除 dev/,commit 2026-08-31)— **生效** |
| 1.0.2 | 2026-08-31 | `wake_login` 默认值对齐 PRD §5(→ false,清待办#1);§4 收编深链注入 `window.__guigui_launch`(清待办#2,后端已按此注入) | 前端已实现;后端联调实测生效(wake_login=false 落盘验证,commit 17c0eb1)— **生效** |
| 1.1.0 | 2026-08-31 | 新增 `feedback()`(§2.12):返回打码诊断文本(用户拍板:反馈动作=复制诊断信息);方法 11→12 | 后端已实现(diagnostics+api.feedback,120 测);前端已接(反馈视图+设置入口,commit 1bb4083)— **生效** |

## 6. 集成待办(联调问题记这里)

- **学号打码示例说明(后端记,已随 1.0.1 登记)**:打码规则=前4…后4,对真实学号 2025000000001 得 `2025…0001`;PRD/契约示例里的 `2025…7209` 是手打示意串、非规则推得。前端如做正则校验请以规则为准。
- **`recentResult` tries=0 文案** → 前端已修复(2026-08-31):`tries===0` 映射「(时间) 已经在线 ✓」。
- **`recentResult` when 与行标题** → 前端已修复(2026-08-31):行标题改用 `when`(id=main-last-t),缺省「昨晚」。
- **【已废弃 2026-08-31 下午】窗口圆角配方票关闭**:用户拍板改用 **Win11 原生窗口**(系统标题栏 + DWM 圆角/阴影/贴边),gui.py 已删 `SetWindowRgn` 全套 hack(`frameless`/`shadow=False`/双事件挂载一并移除)。原配方记录存档于打包测试报告与 git(3ffb764)。**连带前端待办见下条。**
- **【前端票】拆自绘标题行(后端记,2026-08-31)**:原生窗口下标题栏由系统绘制,前端的自绘标题行(`桂桂 / GUIGUI` 名称 + `×`/`–` 按钮 + `.pywebview-drag-region` 拖拽区)整行移除即可;§2.11 `winMinimize`/`winClose` 后端保留不删(兼容,前端按钮拆除后自然无人调用)。标题栏名字 = 回主页的交互(`onclick=goDaily()`)随标题行一起消失,如需保留"回主页"请另行安置。`background_color='#2b2740'` 后端仍在传,新用途是兜 WebView2 首帧闪白。
