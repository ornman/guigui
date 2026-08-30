# 桂桂 v2 · 后端技术方案 v1

> **状态**:2026-08-31 定稿(依据 `docs/tech/guigui-backend-plan.md` 的 14 章规划展开)。
> **读者**:后端实现者与后续协作者。
> **地位**:服从《guigui-work-split.md》;桥接 API 以《guigui-bridge-api-v1.md》为**唯一权威**,本文 §6 只引用不定义;与 PRD 冲突时行为以 PRD(`docs/prd/guigui-prd-v2.md`,冻结)为准。
> **输入**:v1 代码考古(复用清单见 §13)、PRD AC-01~10、契约 v1.0.0。

---

## 1. 范围与读者

本文只答**"怎么做"**:选型、进程模型、模块拆分、磁盘数据格式、协议实现、状态机、打包、测试。产品行为("做什么")一律以 PRD 为准,本文不重复定义,只做实现映射。前端对接改造不归本文(契约 §;work-split 前端职责)。

## 2. 选型论证

**主选:Python 3.12 + pywebview(EdgeChromium/WebView2 后端)。**

| 理由 | 说明 |
|---|---|
| v1 资产复用率最高 | Dr.COM 协议(`src/login.py:91-128` 生产验证)、任务计划 PS/XML 全套、ensure 通知去重、netsh WiFi、单实例锁——后端 ~70% 代码是移植而非新写 |
| HTML 原型直接变 GUI | 前端已按契约实现 `guigui/app/static/`;pywebview `js_api` 桥即契约落地点,`GG` 适配器二级探测(`window.pywebview.api`)零改动命中 |
| 单用户工具,迭代速度 > 运行时极致 | 协议 quirks(GBK/JSONP/魔法参数)已在 v1 踩平,换语言等于重踩 |

**否决项**:

- **Tauri 2(Rust)**:启动/体积/材质全优,但协议、任务计划、WiFi、通知全部重写,协议细节(编码/JSONP 边界)要重新踩坑;单用户场景收益不成比例。
- **C# WPF + WebView2**:系统能力全原生,但同样全部重写且离开现有 Python 生态。
- **Electron**:体积/内存违背 AC-05,直接排除。
- **常驻服务 + IPC(HTTP/socket)**:违背 AC-05/06(无常驻进程);文件交接已被 v1 三层分离架构验证够用。

**依赖**(`guigui/requirements.txt`):`pywebview>=5.0`(仅 GUI 进程导入)、`pyinstaller`(仅打包)、`pytest`(仅测试);`keyring`(凭据管理器);协议层继续 stdlib `urllib`,不引 requests。

**已知代价与对策**:

- 冷启动 1~2s(Python + WebView2 初始化)。AC-08 的"≤0.6s 直达主面板"按 **窗口可见 → 主面板** 口径解释(PRD §4.2 原文即"快速苏醒 0.6s"动画语义);冷启动预算单列 ≤2s,打包后实测记录(§12)。
- Mica/Acrylic:pywebview 无一等支持。PRD §3.3 已定"伪透明烘焙"为原型基准,壳不做真 backdrop;真 Mica 列为可选增强(ctypes `DwmSetWindowAttribute`),不进首版。

## 3. 进程与自动化模型

### 3.1 执行形态(共两种,均短进程)

| 形态 | 入口 | 生命周期 |
|---|---|---|
| GUI | `guigui.exe`(无参)/ `guigui.exe guigui://view` | 用户打开才存在;关闭按钮 = 退出进程,自动化不受影响 |
| 静默执行体 | `guigui.exe --ensure` | 任务计划触发,跑完即退;GUI 打开与否无关 |

无守护、无托盘、无轮询常驻(AC-05/06)。GUI 与 ensure 之间的全部通信 = **数据目录里的文件**(§5)。

### 3.2 数据目录

`%LOCALAPPDATA%\GuiGui\`(v1 用 exe 目录,v2 改此处:Inno 装进 Program Files 后 exe 目录不可写)。

```
%LOCALAPPDATA%\GuiGui\
  config_v2.json      # 全部设置(不含密码,§5.1)
  ensure_state.json   # 跨进程运行时状态(§5.2)
  logs\YYYY-MM-DD.jsonl  # 按天日志(§5.3)
  guigui.log          # 工程运行日志(RotatingFileHandler,排查用,不进 GUI)
```

测试/便携:环境变量 `GUIGUI_DATA_DIR` 覆盖(`core/paths.py` 每次调用时读取)。

### 3.3 任务计划拓扑(任务名前缀 `GuiGui`)

| 层 | 任务 | 触发器 | 默认 |
|---|---|---|---|
| L1 起床窗口 | `GuiGui`(主任务) | Daily @ 起点 + Repetition(interval × 5 次) | 开 |
| L2 开机补登录 | `GuiGui`(同上,多触发器) | LogonTrigger(当前用户) | 开(`boot_login`,关=重建任务时去掉该触发器) |
| L5 唤醒补登录 | `GuiGui`(同上,多触发器) | EventTrigger(System / Power-Troubleshooter / EventID 1)+ Delay PT30S | **关**(`wake_login`,按 PRD §5;与契约示例值分歧见 §14) |
| L3 白天巡逻 | `GuiGui-Patrol` | TimeTrigger Once + Repetition(interval, Duration P3650D) | 关(`patrol_enabled`) |
| L4 WiFi 兜底 | 无任务 | ensure 内部策略:不可达且 `wifi_fallback_enabled` → `wifictl.connect(wifi_fallback_ssid)` → 重新探测登录 | 关 |

任务统一用**完整任务 XML + `schtasks /create /xml`** 生成(v1 用 PS cmdlets;v2 改 XML:可直接单元测试生成物,L5 EventTrigger 在 cmdlets 里没有一等支持)。Action:frozen = `(exe, "--ensure")`;dev = `(pythonw.exe, "-m guigui --ensure", StartIn=仓库根)`。设置项:AllowStartOnBatteries、DontStopIfGoingOnBatteries、StartWhenAvailable、WakeToRun、ExecutionTimeLimit **PT15M**(容纳 §3.5 等门 10min)、MultipleInstancesPolicy=IgnoreNew。Principal:当前用户 InteractiveToken(仅登录时触发——学生开机即登桌面,场景吻合;记录为已知限制)。

**版本标记**:任务 `<Description>` 写 `GuiGui rev=<tasks_rev>`;`tasks_rev` 是 config 内部字段,任何影响调度的设置变更(trigger_time/heartbeat/boot_login/wake_login/patrol_*/master)由 config.save 自动 +1。selfheal 对齐依据 = "任务存在 && rev 匹配",不再深比 XML(继承 v1 `is_windowed_task` 思路但简化)。

### 3.4 L1 窗口公式(修 v1 反向 bug)

v1 把用户时间当**窗口中心**(`window_start_from_center`),填 06:55 实际 06:25 开跑——语义反了(memory: window-formula-backwards)。v2 定义:

```
起点 start   = T − 30min(跨午夜回绕)
拍数 beats   = 6(固定,PRD §6.1 图:06:30–06:55)
步长 interval = heartbeat_minutes ∈ {5,10,15}
RepetitionDuration = (beats−1) × interval
```

T=07:00、hb=5:Daily@06:30 + 每 5min 重复、时长 25min → 拍在 06:30/35/40/45/50/55,任一拍登录成功后,后续拍被 ensure 幂等秒退(§3.6)。**"提前 30 分钟开始试"= 前半窗;T~T+30 区间无 L1 心跳**,由 L2 AtLogon(开机即补)兜底——PRD 场景里 PC 若 07:10 才开机,L1 拍本来就错过了,AtLogon 正是为"早于/晚于窗口开电脑"设计(记录于 §14 开放问题)。

### 3.5 开机等门(永不报错)

L2 触发时若网络栈未就绪(`waiting`:无任何已连接接口),ensure 每 30s 探测一次,上限 **10min**;开门(服务器可达)即走正常登录;超限静默退出记一行日志,不通知不弹错(任务时限 15min 容纳)。GUI 侧 `probe()` 返回 `waiting` 时,前端自走 bootWait 轮询 UI(PRD §4.6),壳不参与。

### 3.6 ensure 幂等与"登上就停"

| 状态(当日) | 行为 |
|---|---|
| `logged_in` 且 `last_settle_date == today` | **秒退,零日志零通知**(L1 后续拍的退场方式) |
| `logged_in` 且今日首次 | 记收工三行(§5.3)+ 置 settle + 状态翻转通知判断 |
| `not_logged_in` | 按 `login_retries × retry_seconds` 登录(§7) |
| `unreachable` | L4 兜底尝试(若启用)→ 仍不可达走假期静默状态机(§8) |

### 3.7 并发模型

- GUI 单实例:命名互斥量 `Local\GuiGui-GUI`(移植 v1 `instance.py`,含句柄泄漏修复);重复启动(含 deep link 二次唤起)直接退出。
- ensure 多实例:任务 MultipleInstances=IgnoreNew 已挡同任务并发;GUI 触发登录与 ensure 撞车的概率低,`ensure_state.json` 原子写(tempfile + `os.replace`,移植 v1)保证不写坏,last-writer-wins 可容忍(记录于 §14)。
- 桥接并发(契约 §0):pywebview 每个方法调用在独立线程执行,`login/connectWifi` 长挂不阻塞 `probe/getConfig/logs` 等查询;无需 worker 池。

## 4. 目录结构(后端拥有的部分)

```
guigui/
  __init__.py            # __version__ = "2.0.0"
  __main__.py            # CLI:--ensure | guigui://…(deep link) | 无参(GUI)
  core/
    paths.py             # 数据目录解析(LOCALAPPDATA / GUIGUI_DATA_DIR 注入)
    config.py            # config_v2.json:defaults + 枚举校验 + 原子写 + tasks_rev
    vault.py             # keyring 封装(密码只在模块内进出,永不下行)
    logstore.py          # 按天 JSONL 追加/查询/label 组装
    detect.py            # probe 三态+waiting、等门轮询
    drcom.py             # 登录/chkstatus/学号打码/运营商后缀
    wifictl.py           # 扫描/连接/当前 SSID(netsh;开放网络临时 profile)
    scheduler.py         # 任务 XML 生成 + schtasks CRUD + L1 公式 + rev 标记
    selfheal.py          # 幂等对齐(应存在/rev 匹配/应删除)
    notify.py            # Toast(PS WinRT)+ 协议激活 + 决策去重纯函数
    ensure.py            # 静默执行体编排 + 假期静默状态机
    instance.py          # GUI 单实例互斥量(ctypes)
  app/
    api.py               # GuiGuiApi:契约 11 方法(camelCase)+ 信封 + 事件发射
    gui.py               # pywebview 壳:窗口/js_api/deep link/文件监视器
    static/              # ★ 前端拥有,后端只读引用(work-split §三)
  tests/                 # pytest(见 §12)
  requirements.txt
  guigui.spec            # PyInstaller(onedir, windowed)
  build_guigui.bat       # venv + 依赖 + pyinstaller
  setup.iss              # Inno Setup(安装器)
```

## 5. 数据契约(磁盘格式;桥接层形状以契约文档为准)

### 5.1 `config_v2.json`

磁盘字段名与桥接层同名(契约 §2.6 注:后端可自行映射,此处选择**零映射**降低漂移),外加内部字段:

| 字段 | 类型/枚举 | 默认 | 说明 |
|---|---|---|---|
| `trigger_time` | `"HH:MM"` | `"07:00"` | L1 时刻 T |
| `boot_login` | bool | `true` | L2 |
| `heartbeat_minutes` | {5,10,15} | 5 | L1 步长 |
| `wake_login` | bool | **`false`** | L5(PRD §5 默认关;契约示例 true,分歧见 §14) |
| `patrol_enabled` | bool | `false` | L3 |
| `patrol_minutes` | {15,30,60} | 30 | L3 步长 |
| `wifi_fallback_enabled` | bool | `false` | L4 |
| `wifi_fallback_ssid` | str\|null | `null` | 扫描点选 |
| `login_retries` | {1,3,5} | 3 | 单轮重试次数 |
| `retry_seconds` | {5,10,30} | 5 | 单轮重试间隔 |
| `vacation_silence` | bool | `true` | 假期静默 |
| `notifications` | bool | `true` | 通知 |
| `show_gui` | bool | `true` | 显示桂桂(纯前端消费,后端只存) |
| `master` | bool | `true` | 总开关 |
| `uid` | str | `""` | 学号(明文;契约允许下行) |
| `url` | str | `"http://10.1.2.3"` | 认证服务器 |
| `server_name` | str | `"10.1.2.3"` | 显示名(状态行用) |
| `tasks_rev` | int | 0 | 调度版本号(内部) |

读写:load = defaults + 已存合并后逐项校验(移植 v1 `validate` 模式:类型错/枚举外→默认值);save = tempfile + `os.replace` 原子写;凡涉及调度字段变更自动 `tasks_rev += 1`。**密码不在此文件**(§5.4)。

### 5.2 `ensure_state.json`(运行时状态,原子写)

```jsonc
{
  "last_net_state": "up",              // up | down | failed(通知翻转判断,v1 语义)
  "last_recovered_notify_date": null,  // "YYYY-MM-DD",断→通每日一次去重(AC-04)
  "consecutive_fail": 0,               // 连续被拒拍数,≥3 触发一次通知
  "fail_notify_sent": false,           // 连败通知锁存,登录成功复位
  "unreachable_streak": 0,             // 连续不可达天数(每天首探时结算)
  "last_unreachable_date": null,       // 当日已记过不可达日志的标记(日志去重)
  "silent": false,                     // 假期静默激活(§8)
  "last_settle_date": null,            // 当日已收工标记(§3.6 秒退)
  "last_result": null                  // {date, when, time, tries, outcome} → recentResult
}
```

### 5.3 日志(`logs/YYYY-MM-DD.jsonl`)

每行 `{"ts":"HH:MM:SS","level":"ok|note|fail|silent","text":"…"}`;追加写。文案库(PRD v-log 示例对齐,学号打码在写入前完成):

| 场景 | 行 |
|---|---|
| 收工(当日首次登录成功) | `ok 网络可达` → `ok 已登录 · {打码学号}` → `note 今天到这就下班啦 ☕` |
| 开门即试 | `ok 开门即试,一次登好 ✓`(若首拍在 T 前成功) |
| 登录被拒 | `fail 登录被拒:密码可能改过了` |
| 不可达(非静默,当日首条) | `fail 连不上校园网` |
| 不可达(静默态,当日首条) | `silent 连不上,今天先不打扰,明天再试一次` |
| L4 兜底切换 | `note 服务器不可达,切到兜底网络 {ssid}` |

查询(`logs({days})`):新→旧,跳过空天;label = `今天` / `昨天 · 8月29日` / `8月28日`;某天非空且**全部 level==silent** → label 追加 ` · 假期静默`。days 默认 14 上限 90(契约 §2.9)。过滤/导出(AC-07)后端预留 `query(level=…)` 参数,UI 由前端后续补(§14)。

### 5.4 凭据

`keyring` → Windows 凭据管理器(DPAPI 背书):service `GuiGui`,username = uid。规则:**密码只经 `login()` 上行一次**;此后 ensure/API 从 vault 读;任何 API 返回与日志不含密码(契约总则)。uid 变更时旧条目删除。keyring 不可用(极端环境)→ 报 `INTERNAL`,**不回退明文落盘**。

## 6. JS 桥接 API(引用契约,不另行定义)

唯一权威 = `docs/tech/guigui-bridge-api-v1.md` v1.0.0(11 方法 + 4 事件 + 8 错误码)。实现要点:

- `app/api.py` 的 `GuiGuiApi` 类方法名**逐字使用契约 camelCase**(pywebview 原样暴露到 `window.pywebview.api.*`,前端 `GG` 适配器二级探测命中)。
- 统一信封由装饰器保证:成功 `{"ok":true,"data":…}`,异常兜底 `{"ok":false,"code":"INTERNAL"}`;**永不向 JS 抛异常**(契约 §0)。
- 事件:GUI 进程内动作直接 `window.evaluate_js("window.guiguiEmit(…)")`;**跨进程事件**(GUI 开着时外部 ensure 落日志/改状态)由壳的文件监视器翻译:轮询 `ensure_state.json` / 今日日志 / `config_v2.json` 的 mtime(2s),分别派发 `net:state` / `log:appended`(逐新行) / `schedule:changed`。诚实边界:mtime 轮询有 ≤2s 延迟,可接受(GUI 打开时的即时反馈场景本来就少)。
- `login` 长动作在调用线程内执行(pywebview 每调用一线程,天然满足并发条款);进度经 `login:progress` 事件推。
- `probe().configured` = `uid 非空 && vault 有密码`(任务就位由 saveConfig/masterToggle 后的 selfheal 保证,不在每次 probe 反复查 schtasks——查询有秒级成本)。

## 7. Dr.COM 协议模块(`core/drcom.py` + `core/detect.py`)

### 7.1 登录(移植 v1 `login.py:91-128`,生产验证参数)

```
GET {url}/drcom/login?callback=dr1003&DDDDD={quote(uid)}&upass={quote(password)}
    &0MKKey=123456&R1=0&R2=&R3=1&R6=0&para=00&v6ip=&terminal_type=1
    &lang=zh-cn&jsVersion=4.2.1&v={unix}&lang=zh
UA: Chrome/148(Win64)   Referer: {url}/   响应按 GBK 解码
JSONP 括号内 JSON:result==1 → 成功;result!=1 → 被拒(msga 为服务器原因);非 JSONP → unexpected
```

v2 变化:返回**结构化结果** `("success"|"rejected"|"unexpected", msg)` 而非 bool(契约需要区分 `AUTH_REJECTED`);不再把学号写进工程日志(改写打码版到 logstore)。

### 7.2 状态探测(detect)

- HTTP 探测 `{url}/`(5s 超时,UA 同上):title 含"注销" → `logged_in`;其他 200 → `not_logged_in`;异常 → `unreachable`(内部细分 timeout/refused,仅供日志,不进契约)。
- `waiting` 判定:`netsh interface show interface` 无任何"已连接"接口(刚开机/网卡未就绪)→ `waiting`,不做 HTTP(避免 5s 空等)。
- 当前 SSID:`netsh wlan show interfaces` 解析(移植 v1 `wifi.current_ssid`,编码改 GBK+replace 防中文 SSID 乱码)。

### 7.3 学号识别(identify,v1 没有的新能力)

登录态下 `GET {url}/drcom/chkstatus?callback=dr1003` → JSONP → `uid` 字段(PRD §4.1.1 两次实测)。仅 `logged_in`/`not_logged_in` 可达时尝试;失败回退 config.uid → `source: config` → 无则 `none`。

### 7.4 运营商后缀

PRD §4.1.1 实测记录门户下发:校园用户 `''` / 校园电信 `@dx` / 校园联通 `@lt`,默认校园用户;v1 硬编码"电信→无后缀"与服务器不符。v2:`OPERATOR_TABLE` 采用 PRD 实测值(即服务器当前配置),登录恒用裸 uid(用户为默认运营商,v1 生产验证);**运行时从门户首页拉取后缀表**列为增强不做(开放问题 §14:页面结构未取真实样张,盲解析比记录值更不可靠)。

### 7.5 学号打码

`mask_uid(uid)`:长度 >8 → 前 4 + `…` + 后 4(如 `2025…7209`);否则原样。契约 §2.3/§2.9 示例即此格式;打码在后端完成,明文不进日志、不进 API 返回。

## 8. 状态机与假期静默(AC-10)

状态迁移全部在 `ensure_state.json` 上,由每次 ensure 运行结算:

| 本次结果 | 迁移 |
|---|---|
| 可达/已登录/登录成功 | `unreachable_streak=0`、`silent=false`、`consecutive_fail=0`、`fail_notify_sent=false` |
| 不可达 | 当日首次:`streak = streak+1`(若 `last_unreachable_date==昨天`)否则 `=1`;`streak≥2 且 vacation_silence` → `silent=true` |
| 登录被拒 | `consecutive_fail+=1`;≥3 且未发过 → 失败通知一次(`fail_notify_sent=true`) |

`silent=true` 的行为约束:当日已探过一次(`last_unreachable_date==today`)→ 后续触发秒退(降到每天 1 次的实质);日志记 `silent` 级(§5.3);**不通知**(v-log 天头"假期静默"标记由 §5.3 label 规则自动产生)。回校:任一次可达结果即复位(上表第一行)。

## 9. 通知(`core/notify.py`)

- **通道**:移植 v1 PowerShell WinRT Toast(ShellExperienceHost AppId,零依赖、生产验证);升级点:toast XML 加 `activationType="protocol" launch="guigui://main|creds"`,点击唤起 GUI(§10 deep link)。
- **协议注册**:GUI 首次运行写 `HKCU\Software\Classes\guigui`(URL Protocol + shell\open\command → `"{exe}" "%1"`),仅当前用户,免管理员;安装器也会写(双保险)。
- **决策去重**(纯函数 `decide_notify`,单元测试覆盖,移植 v1 `ensure.py:23-46` 并扩展):

| 条件 | 通知 |
|---|---|
| 断→通(prev ∈ down/failed → 本次在线)且 `last_recovered_notify_date != today` | "已连上 ✓" → `guigui://main`(每日一次,AC-04) |
| `consecutive_fail ≥ 3` 且 `!fail_notify_sent` | "登录失败,密码改了?" → `guigui://creds`(一次,成功后复位) |
| 一切正常/维护中(unreachable)/静默态 | **永不通知** |

`notifications=false` 时全静音(只保留日志)。

## 10. GUI 壳(`app/gui.py`)与胶囊悬案

- pywebview 5,WebView2 后端:560×640、`frameless=True`、`resizable=False`、`easy_drag=False`(拖拽交给前端 `pywebview-drag` 类,pywebview 原生识别)、`background_color` 取前端底色(真窗口透明 WebView2 不稳定,伪透明按前端烘焙方案,**记入集成待办与前端核对**)。
- `js_api=GuiGuiApi()`;`winMinimize → window.minimize()`;`winClose → window.destroy()`(= 退出 GUI 进程)。
- **胶囊悬案裁决(方案 A)**:关闭 = 真退出,无常驻胶囊。理由:胶囊浮标是常驻进程,与 AC-05(关窗后内存 <50MB 的精神是无进程)和 AC-06(未主动打开时主进程不拉起)直接冲突;PRD §3.3 的胶囊降级为**唤回路径 = 桌面/开始菜单快捷方式 + 通知点击(guigui:// 协议)**。方案 B(独立微进程胶囊)记录不做。原型里的 `#pill` 是演示道具(前端已列入删除清单)。
- **Deep link**:启动参数 `guigui://main|creds|settings` → 壳在页面 loaded 后 `evaluate_js("window.__guigui_launch='creds'")`;前端消费该全局变量跳视图。此形状未入契约,**记入契约 §6 集成待办**。
- 单实例:互斥量 `Local\GuiGui-GUI`(§3.7)。
- 文件监视器线程(§6):2s mtime 轮询三个文件,变化→`guiguiEmit`。
- 启动时序(契约 §4):前端 `probe()` 前 v-boot 仪式照播;壳不做任何抢戏。

## 11. 打包分发

- **PyInstaller**(`guigui/guigui.spec`):onedir、console=False、name `guigui`;`guigui/app/static` 以 datas 打进包(前端定稿后;当前 dev 直接读源码目录,`GUIGUI_STATIC_DIR` 可覆盖)。单 exe 双模式:`--ensure` 在 `__main__` 分流,**不导入 pywebview**(AC-05:ensure 进程 ~20MB、秒级冷启)。
- **Inno Setup**(`guigui/setup.iss`):装 `%ProgramFiles%\GuiGui`;桌面 + 开始菜单快捷方式;注册 `guigui://` 协议(HKCU);卸载保留 `%LOCALAPPDATA%\GuiGui`(数据/日志),提示用户手删。
- **WebView2 Runtime**:壳启动前查注册表(`SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`,HKCU/HKLM 双查);缺失 → `ctypes.messagebox` 弹官方下载指引(Win11 预装,兜底而已)。
- **升级**:Inno 覆盖安装 → exe 路径不变;若安装路径变化,selfheal 的 rev/Action 校验(v1 `_action_script_exists` 机制移植:Action 指向的文件不存在 → 判坏任务重建)自动修任务。
- AC-05 实测口径:关窗后 `tasklist` 无 guigui.exe;ensure 触发时进程 RSS <50MB;空闲无 guigui 进程 = CPU 0%。

## 12. 测试与发布

### 12.1 自动化(pytest,`guigui/tests/`,mock 全部系统调用:urlopen/netsh/schtasks/powershell/keyring)

| 文件 | 覆盖 |
|---|---|
| test_config.py | 默认值合并、枚举回退、原子写、tasks_rev 递增、桥接字段白名单 |
| test_vault.py | 存/取/删/has、uid 变更清理、密码不进任何序列化 |
| test_logstore.py | 追加/按天查询/label(今天/昨天·M月D日/假期静默后缀)/days 上限/空天跳过 |
| test_detect.py | 三态 + waiting(无连接接口)、GBK title 解析、超时分类 |
| test_drcom.py | 登录成功/被拒(msga)/非 JSONP、chkstatus 解析、打码边界 |
| test_wifictl.py | 扫描解析(去重/隐藏排除/信号分档)、连接流程(profile 优先/重试/超时) |
| test_scheduler.py | **L1 公式(06:30/25min/跨午夜)**、任务 XML 生成断言(触发器组合/rev 标记/设置项)、boot_login/wake_login 开关反映、删除 |
| test_selfheal.py | 应建/应删/rev 失配重建/查询失败不误建 |
| test_notify.py | 决策去重全表(断→通每日一次/连败×3 锁存/正常不通知)、XML 转义、协议 launch 字段 |
| test_ensure.py | 全编排:收工幂等秒退、等门、被拒计数、假期静默进入/退出、L4 兜底、日志文案 |
| test_api.py | 契约形状:信封/错误码、密码永不出现在返回、事件 payload、saveConfig 增量+回显 |

### 12.2 AC 映射(手测验收表)

| AC | 验法 |
|---|---|
| AC-01 | 前夜配置 07:00;07:00 开机,AtLogon ensure 登录;`ping baidu.com` 30s 内通 |
| AC-02 | 删 `%LOCALAPPDATA%\GuiGui` 后分别模拟三态(已登录/未登录/断 WiFi)跑 GUI,无报错弹窗 |
| AC-03 | 关闭校园网 AP/断网,`scanWifi()` 返回 ≥5 SSID 带信号档;点选连接免手填 |
| AC-04 | 一天内反复断→通,通知仅 1 条;改错密码触发 ×3 后通知 1 条不刷屏 |
| AC-05 | 关窗后 `tasklist | findstr guigui` 空;ensure 运行时 RSS <50MB |
| AC-06 | 全天不打开 GUI,schtasks 触发日志显示独立短进程完成登录 |
| AC-07 | `logs({days})` 返回按天分组;过滤/导出 UI 前端补(预留参数) |
| AC-08 | 首装仪式仅一次;二次打开窗口可见 → 主面板 ≤0.6s(录屏逐帧) |
| AC-09 | 掉线→主按钮 1 步;密码被拒→改密 2 步;不可达→点 WiFi 2 步 |
| AC-10 | 模拟连续 2 天 unreachable(断 AP),第 3 天起日志每天 1 行 silent + 天头"假期静默" + 无通知;恢复 AP 自动回正常 |

### 12.3 发布流程

tests 绿 → `build_guigui.bat`(venv + spec)→ Inno → 安装到本机 → §12.2 手测表过一遍 → git tag `v2.x`。v1 在 v2 稳定运行一周前不卸载(双装共存:任务名/数据目录/协议名均不冲突)。

## 13. v1 复用 / 重写清单

| v1 来源 | → v2 | 动作 |
|---|---|---|
| `src/login.py:91-128` do_login | `core/drcom.py` | 移植,返回值 bool→结构化,日志去明文学号 |
| `src/login.py:65-88` check_auth_status | `core/detect.py` | 移植 + waiting 态 |
| `src/login.py:50-62` wait_for_network | `core/detect.py` wait_for_gate | 移植(参数改 30s/10min) |
| `src/ensure.py` decide_notify + 原子写 | `core/notify.py` + `core/ensure.py` | 移植 + 连败×3 + 每日去重 |
| `src/scheduler.py` PS CRUD/XML 解析/坏任务检测 | `core/scheduler.py` | **重构**:PS cmdlets → 任务 XML 生成;公式重写(§3.4) |
| `src/selfheal.py` reconcile 骨架 | `core/selfheal.py` | 移植,判据改 rev |
| `src/wifi.py` current_ssid/connect | `core/wifictl.py` | 移植 + scan(新)+ 开放网络 profile(新)+ 编码修正 |
| `src/notify.py` PS WinRT Toast | `core/notify.py` | 移植 + 协议激活 |
| `src/instance.py` SingleInstance | `core/instance.py` | 原样(改互斥量名) |
| `src/config.py` validate 模式 | `core/config.py` | 移植模式,schema 全新(§5.1) |
| `src/app.py`/`ui/*`/`tray.py` | — | **不移植**(GUI 全新;托盘按 PRD 废除) |
| `main.spec`/`build.bat`/`setup.iss` | `guigui/*.spec` 等 | 重写(v1 文件冻结不动) |

**v1 文档残留清理**(README autostart/--silent、CLAUDE.md auto_start):v1 全部文件冻结(work-split §三),此项留给用户在 v1 退役时处理,后端不做。

## 14. 开放问题与集成待办

**实现期裁决(已定,记录在案)**:

1. **L1 六拍止于 T−5**:T~T+30 无 L1 心跳;晚于窗口开电脑由 L2 AtLogon 覆盖(§3.4)。与 PRD §6.1 图一致("6 次全部失败 → 进入 L3","07:30 窗口结束"指外边界)。
2. **胶囊悬案** → 方案 A:关闭=真退出,唤回=快捷方式/通知点击(§10)。
3. **任务仅登录态触发**(InteractiveToken):开机未登录桌面则不跑——单用户学生场景吻合,不做 S4U。
4. **多 ensure last-writer-wins**:撞车窗口毫秒级且任务层已 IgnoreNew,不做文件锁。

**待前端/用户确认(记入契约 §6 集成待办,本文只登记)**:

5. **wake_login 默认值分歧**:PRD §5 表 = 关,契约 §2.6 示例 = `true`。后端按 PRD 实现 `false`;若前端 mock 按示例设 true,联调首屏开关态会不一致——需前端改 mock 或契约示例改注释,二选一。
6. **deep link 注入形状** `window.__guigui_launch = 'main|creds|settings'`:未入契约,建议补进契约事件/启动时序节。
7. **窗口透明/圆角**:壳用 frameless + 纯色背景;真透明 WebView2 下行为需 devshell 实测,若不支持则圆角外露直角(前端已按烘焙方案,视觉影响待联调)。

**增强 backlog(不阻塞首版)**:

8. 运营商后缀表运行时从门户拉取(§7.4)。
9. 日志过滤/导出 UI(AC-07 后端参数已预留)。
10. 真 Mica 材质(§2)。
11. `chkstatus` 62 字段中的会话信息(在线时长/流量)展示——`oltime/olflow=0xFFFFFFFF` 无限时限制,暂无消费场景。
