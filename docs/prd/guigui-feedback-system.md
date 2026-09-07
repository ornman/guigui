# 桂桂反馈系统 PRD(系统设计)

版本:v1.0 · 2026-09-07 · 状态:方案已拍板,待实施
讨论与拍板过程见本文末「决策记录」;实测依据见附录 A。

---

## 0. 一句话定位

反馈页从「复印机」(生成诊断文本→复制→没有然后)重构为**真通道**:用户选分类、写一句话,诊断包自动采集,一键直达开发者的 GitHub issue;全链路三层容灾,断网、服务器挂、GitHub 挂都丢不了反馈。

## 1. 背景:现状三宗罪

1. **闭环断裂**:页面说「复制发给开发者」,但产品内无任何联系方式,复制完没有粘贴落点。
2. **名实不符**:入口叫「反馈」,实际只有机器诊断文本——用户没地方说「我遇到了什么」。
3. **证据蒸发**:失败瞬间证据全在(异常类型、HTTP 码、响应体、当时 SSID),全被丢弃;事后采集只能采到「现在」,采不到「早上七点」。

## 2. 数据流全景

```
[用户电脑]                        [Cloudflare 边缘]                [GitHub 私有仓]
桂桂 App
 ① 用户填:分类+一句话(+可选联系)
 ② Python 后端:信封 + 诊断包(采集自本机)
    sender_uid 由后端直附,前端不显示
 ③ urllib POST /fb ───────────→ ④ 校验/截断/限频
    UA: GuiguiDesktop/<ver>        client_id 幂等去重
    单次尝试,失败即入队            ⑤ D1 写入(存底,双槽之一)
                                   ⑥ GitHub issue(投影,双槽之二,
                                      尽力而为;失败由对账端点补)
 GG-xx 回执 ←─────────────────┘        │
                                    ┌──┴───┐
                              通知邮件   issues 网页 ← 开发者分诊/修复/close
```

- **接收端复用**:官网已部署的 `functions/fb.js`(guigui-guat.pages.dev/fb)+ D1,升级协议到 v2,不新建服务。
- **消费即 GitHub 工作流**:issue 创建 → GitHub 原生邮件通知;`problem`/`suggestion` 标签筛选;修复随下版本发布后 close。没留联系方式的用户,**发布即回复**。

## 3. 用户侧设计(前端)

### 3.1 反馈页(v-feedback 重构)

```
‹ 返回
说给桂桂听。

( 问题 )( 建议 )            ← 胶囊多选,至少一枚;选中=实心
说说具体情况(必填)           ← 占位随类别变:纯建议时换建议例句
[………………]
想被回访就留个联系(可选)     ← 只填 QQ/邮箱;学号由桂桂自动带上,不在这里显示
[………………]

▸ 诊断信息(已打码,点开可查)  ← 默认折叠;仅选「问题」时出现;纯建议无此区

[ 发送反馈 ]   复制文本       ← 主按钮 + 链接级次动作
```

- **学号后端直附(拍板)**:`contact` 框不再预填学号;后端发送时自动附 `sender_uid`(当前配置学号)。前端任何界面不显示学号明文;折叠区头部一行披露「随附:学号 2025…0001(便于找到你)」——知情权保留,界面无明文。
- **发送三态**:发送中(禁用)→ 成功 `GG-3X ✓ 已收到` → 失败转队列文案。
- **离线队列可见性**:存在待发反馈时,页面出现一行状态「有 1 条没发出去的反馈,联网自动补发」,零操作;正常态零存在感。

### 3.2 入口与文案

- 设置页「遇见问题?」行改为涵盖问题+建议的口径(实施时定稿,同信息只出现一次)。
- 日常日志视图(主页/历史)只显示 `text`,`data` 现场不可见。

## 4. 协议契约(v2)

### 4.1 请求

`POST /fb`,JSON。信封层与包体分离;幂等与限频只看信封。传输的是不带注释的纯 JSON;字段注释见 §8 逐字段表。

```jsonc
{
  // ══ 信封层:传输/幂等/来源识别(幂等与限频只看这一层)══

  "v": 2,                            // 协议版本;边缘端见 v=2 走新逻辑,无 v=v1 兼容
  "client_id": "8f14e45f-9a4c-…",    // UUID,入队时生成一次、终身复用——重试绝不重复入库/重复开 issue
  "sender_uid": "2025000000001",     // 后端直附(前端不显示明文);未配置学号时为空串
  "app": "desktop",                  // desktop | web(官网表单)
  "app_ver": "2.1.0",                // 桂桂版本(信封唯一出处,self 区不再重复)

  // ══ 用户输入层:反馈页上用户填/选的 ══

  "kind": ["problem"],               // ⊆ {problem, suggestion},非空,多选
  "what": "今早七点没登上,日志说登录被拒",   // 用户原话,≤120 字,唯一必填
  "contact": "",                     // QQ/邮箱,≤80,可选;学号不在这里,由信封 sender_uid 承担
  "when": "09-07 06:52",             // 自动取最近一条失败日志时间;纯建议为空串

  // ══ env · 环境区:他的机器和我的有什么不一样(两种 scope 都带)══

  "env": {
    "os": "Windows 11 26200 x64",    // 系统与内部构建号——老系统缺 API、特定版本坑,对号入座
    "clock_skew_s": 2.1,             // 用户时钟 vs 认证服务器时钟偏差(秒)——定时全乱的元凶
    "adapters": [                    // 全部网卡(含虚拟):①当时连的是不是校园网 ②有没有 VPN 抢路由
      { "name": "WiFi", "kind": "wifi", "ssid": "Campus-WiFi",
        "ip": "10.x.x.x", "up": true },
      { "name": "以太网", "kind": "ethernet", "ip": "172.16.0.1", "up": true },
      { "name": "Clash", "kind": "tun", "up": true }
                                     // kind:wifi/ethernet=物理;tun=VPN 虚拟;vm=虚拟机的
                                     // tun 在跑=流量被代理接管,登录可能没走校园网——高频真凶
    ],
    "dns": ["192.168.x.x"],          // 当前 DNS——改过/被接管 → 认证域名解析不到或解析错
    "proxy": { "system": false, "env": false },
                                     // 两处来源:system=Windows 系统代理;env=HTTP_PROXY 等。
                                     // 任一为真,桂桂的请求会被劫走
    "av": { "huorong": true, "qihoo360": false, "defender": true },
                                     // 杀软在不在跑(只报布尔,不列进程清单)——拦任务/杀进程头号原因
    "webview2": "120.0.2210.61",     // 界面引擎版本——白屏/点不动/样式崩,先查它
    "python": "3.12.8",              // 内嵌解释器版本——「我机器好好的」类差异排查用
    "errors": []                     // 本区采集器失败清单,例 ["adapters: PermissionError"]
  },

  // ══ self · 自身区:配置对不对、状态机卡哪、任务真跑了吗(两种 scope 都带)══

  "self": {
    "installed_at": "2026-08-30",    // 安装日期——刚装就坏 vs 用一月才坏,方向完全不同
    "config": {                      // 配置全文(敏感项打码)——运营商选错、兜底 WiFi 选错在这现形
      "trigger_time": "07:00", "operator": "校园电信",
      "heartbeat_minutes": 5, "boot_login": true, "wake_login": true,
      "patrol_enabled": true, "patrol_interval_minutes": 30,
      "wifi_fallback_enabled": true, "wifi_fallback_ssid": "Campus-WiFi-2",
      "vacation_silence": true, "notifications": true, "master": true
    },
    "state": {                       // 状态机快照——解释「桂桂为什么这么做」的唯一依据
      "cred_verified": false,        //   凭据被服务器验证过没;false=最近被判定密码错
      "unreachable_streak": 1,       //   连续几天连不上;≥2 天+假期静默 → 自动降频
      "maintenance_streak": 0,       //   连续几天服务器返回怪页面
      "last_result": "fail",         //   最近一次登录结果 ok|fail|silent
      "last_settle_date": "09-04"    //   最后一次登上的日期
    },
    "tasks": [                       // Windows 任务计划实查(schtasks,不是桂桂自说自话)
      { "name": "GuiGui", "registered": true,
        "last_run": "09-07 07:00:03", "last_result": "0x0" },
                                     // registered=任务还在不在(被杀软删了就 false)
                                     // last_run=系统记的上次实际运行——分诊第一刀:
                                     //   没运行=任务问题;运行了没登上=网络问题
                                     // last_result=系统结果码:0x0=正常跑完;非 0=那次没跑完
      { "name": "GuiGui-Patrol", "registered": true,
        "last_run": "09-07 07:15:00", "last_result": "0x1" }
    ],
    "proc_uptime_s": 10800,          // 本次 GUI 进程已连续运行秒数
    "errors": []
  },

  // ══ net · 网络区(实时):反馈这一刻通不通、走哪条路(仅 problem 携带)══

  "net": {
    "dns_resolved": "10.1.2.3",      // 认证域名此刻解析到的 IP;null=解析失败;怪 IP=疑似劫持
    "tcp": true,                     // 到认证服务器端口的 TCP 通断(最原始一层)
    "http": 200,                     // HTTP 探测状态码;200=服务器应答
    "latency_ms": 340,               // 探测往返耗时——慢到超时也算一种「不可达」
    "route_iface": "WiFi",           // 实际走哪块网卡(查路由表)——有 WiFi 却走 TUN,一眼锁定
    "errors": []
  },

  // ══ server · 服务器区:服务器怎么看待这个账号/这台机器(仅 problem 携带;实测 2026-09-07)══

  "server": {
    "chkstatus": {                   // 只读探测,三形态:
      "state": "no_session",         //   uid_online=会话在线(返回 uid/AC)/ no_session=HTTP 400 /
      "raw_head": ""                 //   unreachable=够不着;raw_head=响应前 120 字备查
    },
    "last_verdict": {                // 最近一次真实登录尝试的服务器判定(取自日志 data,非诊断重放)
      "ts": "09-07 06:52:11",
      "rej": "limit_users",          // 四态:error1/error2/bind/limit_users
      "msga": "Oppp error: Limit Users Err",     // 服务器原话
      "server_view_ip": "172.16.0.1",        // ss5:服务器看到的来源 IP
      "mac_hint": ["00aa00bb00cc", "00dd00ee00ff"],  // ss1/ss4:MAC 指纹
      "aolno": 6152,                 // 在线编号
      "ubind": "mac1='',ty1=0,mac2='',ty2=0,mac3='',ty3=0,mac4='',ty4=0,mac5='',ty5=0"
    },                               //   ↑ MAC 绑定策略原文
    "errors": []
  },

  // ══ logs · 日志区(带现场):那几天早上发生了什么(仅 problem 携带)══

  "logs": [                          // 最近 7 天,逐天逐条
    { "date": "09-07", "entries": [
      { "ts": "06:52:11", "level": "fail",
                                     // level:ok 成功 / note 备注 / fail 失败 / silent 假期静默
        "text": "登录被拒:这个学号已在别的设备上登录…",
                                     //   日志页显示的原句(给人读;日常界面只见它)
        "data": {                    //   机器现场(只随反馈出现):
          "ssid": "Campus-WiFi",     //     失败那一刻的无线网——是不是校园网,当场对质
          "stage": "login",          //     挂在哪步:probe/login/logout
          "tries": 2,                //     当天第几次尝试
          "http": 200,               //     HTTP 状态码
          "rej": "limit_users",      //     服务器拒绝码(四态)
          "body_head": "Oppp error: Limit Users Err"
                                     //     服务器响应正文前 80 字(已打码)——绝不存请求 URL(含密码)
        } }
    ] }
  ],
  "summary": "09-01 ✓ · 09-02 ✓ · 09-03 ✗ · 09-04 ✗ · 09-05 ✗ · 09-06 ✗ · 09-07 ✗",
                                     // 日志区一行摘要:七天成败趋势——一直好=新问题;
                                     // 一直坏=配置/环境;忽好忽坏=不稳定因素

  // ══ crashes · 崩溃区:程序自己崩过没(仅 problem 携带)══

  "crashes": [                       // 最近 3 份(全局异常钩子自动落盘,任何未捕获崩溃都在)
    { "ts": "09-06 22:11:07", "proc": "gui",
                                     // proc:gui / ensure——哪个进程崩的
      "trace": "Traceback (most recent call last):\n  File \"app/gui.py\", line 210, in _watch\n…"
    }                                // 完整堆栈——「程序本身的问题」的直接物证
  ],

  // ══ 版本对照(两种 scope 都带)══

  "latest_ver": "2.1.2"              // 官网最新版(实时查 /version.json;查不到 null)
                                     // app_ver 落后于它 → 先让用户升级,大概率白修
}
```

**纯建议瘦身规则**:仅 `problem` 在选时携带 `net / server / logs / summary / crashes`;纯建议只带 `env(基础) / self.app_ver` + 用户输入。听建议不需要网络现场。

### 4.2 响应信封(状态码表)

任何情况返回统一形状 `{ok, code, …}`;前端按 `code` 走 UX,不做任何解析猜测:

| code | HTTP | 含义 | 前端行为 |
|---|---|---|---|
| `SUBMITTED` | 200 | D1 ✓ + issue ✓ | 「已收到 ✓ GG-3X」 |
| `SUBMITTED_DEGRADED` | 200 | D1 ✓,issue 建失败(cron 会补) | 同上,无感 |
| `RATE_LIMITED` | 429 | 限频 | 入队,按 `retry_after` 退避 |
| `VALIDATION` | 400 | 字段不合法 | 表单内提示,不入队 |
| `SINK_DOWN` | 503 | D1 与 GitHub 双挂 | 入队 |
| `E_NET_OFFLINE / E_NET_DNS / E_NET_TLS / E_TIMEOUT / E_HTTP_5XX` | — | 桌面端 Python 分类 | 全部入队 |

## 5. 拒绝家族:四态(实测修正,2026-09-07)

原设计三态(error1/error2/bind)。实测发现第四态,**当前代码对它失明**(`classify_rejection` 返回 None,会被误导性地归入「密码可能改过了」文案):

| 态 | 服务器证据 | 含义 | cred_verified | data.rej |
|---|---|---|---|---|
| 账号运营商组合不存在 | `userid error1` | 组合不对 | 不动 | `error1` |
| 密码不对 | `userid error2` | 密码错 | **置假** | `error2` |
| 绑定/接入区被拦 | `bind userid error` | 密码正确但被绑定策略拦 | 不动 | `bind` |
| **已在别处登录(新)** | `result:0` + `msga:"Oppp error: Limit Users Err"` | 账号同时在线数超限 | 不动 | `limit_users` |

- `limit_users` 用户文案方向:「这个学号已在别的设备上登录(比如在别处登过没下线),那边下线后桂桂会自动登好」。**不冤枉密码**原则:与 bind 同待遇,绝不动 cred_verified、不触发改密提示。
- `limit_users` 的响应还携带服务器视角现场(`ss5` 服务器看到的来源 IP、`ss1/ss4` MAC 指纹、`aolno`、`ubind` 绑定策略),进日志 `data` 与 server 区(见 §8)。

## 6. 服务端设计(/fb v2,Cloudflare Pages Function + D1)

### 6.1 写入路径(双槽容灾)

1. 校验(§4.1 各字段类型/长度)→ 截断入库尺寸;
2. `client_id` 幂等:UNIQUE 约束,重复提交返回**原** GG-xx,不重复开 issue;
3. **D1 先写**(存底,永丢不了);
4. **issue 后建**(尽力):调 GitHub API `POST /repos/{repo}/issues`,标题 `[反馈·问题] GG-3X · <what 前 40 字>`,标签 `problem`/`suggestion` 预建,正文由 fb.js 从结构化包渲染(分区、长日志折 `<details>`)——**issue 版式改边缘端即时生效,不等客户端升级**;
5. D1 挂 → 跳过 3 直接建 issue(记 `storage=issue_only`);双挂 → `SINK_DOWN`。

### 6.2 限频(四层,设计规模 4 万装机)

| 层 | 限额 | 挡什么 |
|---|---|---|
| per `client_id` | 30 条/时 | 单台装机刷屏(含队列补发自然限额) |
| per IP · 桌面标记(GuiguiDesktop UA + 合法 client_id) | 300 条/时 | 校园 NAT 灾情挤兑:4 千人灾情日 × 十个出口 IP,单人 30 + 出口 300,足够放行灾情、挡住单 IP 洪水 |
| per IP · 匿名(网页表单) | 8 条/时 | 最低信任层 |
| payload | Content-Length > 64KB 早拒(不进 JSON 解析);字段限额照 §4.1 | 大包炸弹 |

429 一律带 `retry_after`;桌面端收 429 → 入队退避,不丢。

### 6.5 GitHub 集成(鉴权 · 错误映射 · issue 预算)

**鉴权**:fb.js 持 fine-grained PAT(仅目标仓、仅 Issues 读写权限、90 天有效期),存 Cloudflare secret `GH_PAT`,只存在服务端,任何响应/日志不下发。轮换:`wrangler secret put GH_PAT` 一次,对账端点随即追平积压。过期不致丢——见映射表。

**GitHub 错误 → 本系统信封映射(fb.js 按此实现,不变量:GitHub 的任何失败都不失败用户请求)**:

| GitHub 侧 | fb.js 行为 | 用户侧信封 |
|---|---|---|
| 2xx | 记 `issue_id` | `SUBMITTED` |
| 401(PAT 无效/过期) | issue=null;失败计数 +1 | `SUBMITTED_DEGRADED` |
| 403(secondary rate limit) | issue=null;尊重 `Retry-After` | `SUBMITTED_DEGRADED` |
| 404(仓不存在/PAT 范围错) | issue=null;**PAT 配置类故障打标**(见报警路径) | `SUBMITTED_DEGRADED` |
| 5xx / timeout(5s) | issue=null | `SUBMITTED_DEGRADED` |
| **issue 预算耗尽** | **不发起 GitHub 调用** | `SUBMITTED_DEGRADED` |

**issue 预算闸(DoS 设计的核心)**:D1 写入便宜,issue 创建昂贵(耗 PAT 配额、生成邮件、刷屏)。`ISSUE_BUDGET_PER_HOUR`(默认 500,环境变量可调)——超预算的反馈**只进 D1**(存底不丢),由对账端点在预算内匀速补建。效果:无论入口被打多少,issue 洪水物理不可能;灾情日 4000 条积压 ≈ 8 小时追平,反馈延迟但永不丢。

**PAT 失效的报警路径**(注意 meta-issue 也开不了时的兜底):连续 issue 失败 ≥10 → 在 D1 写 `alert` 行,`/fb/list` 健康区红字暴露 `gh_broken: true`——开一次管理页就能看见,不依赖 GitHub 自身。

### 6.6 安全设计与威胁清单

**身份模型(诚实声明)**:桂桂零账号,反馈**没有鉴权身份**。`sender_uid` 是自报线索(可被伪造,代价=一条假反馈),`client_id` 是装机标识不是身份,**任何地方不得把学号当鉴权用**。接受此模型的原因:反馈是信息通道不是交易通道,最坏后果是 issue 污染,由限频+预算+人工分诊兜住。

| 威胁 | 对策 |
|---|---|
| DoS 打 `/fb`(应用层刷请求) | §6.2 四层限频 + §6.5 预算闸;L3/L4 由 Cloudflare 原生吸收 |
| issue 洪水(打穿限频后污染仓/耗配额) | 预算闸硬顶;标签服务端固定,payload 永不决定 label |
| Markdown/HTML 注入(issue 正文里的链接、图片、反引号) | fb.js 渲染时用户字符串一律入代码字面量(反引号/角括号转义),诊断包整体入 fenced block;标题清洗(去控制字符/反引号,截 40 字) |
| 学号/日志泄露 | **仓必须私有**(硬约束,见 §12);D1 仅 ADMIN_KEY 可读;学号在包内打码、仅 sender_uid 明文,且只进私有仓与 D1 |
| 密钥泄露 | GH_PAT/ADMIN_KEY/CRON_KEY 全走 Cloudflare secret;ADMIN_KEY 高熵随机 + 可轮换;`/fb/list` 的 key 走查询串(单人使用可接受,浏览器历史残留为已知限制,后续可改 header 鉴权) |
| 密码进诊断 | 不变量:登录 URL(含 `upass=`)永不入包;config 采集即打码;崩溃堆栈只含源码行不含实参 |
| 中间人 | 全链 HTTPS;桌面端 Python 校验证书(urllib 默认),无降级 |
| CORS 滥用 | 不开 CORS:桌面端是 Python 服务间直发(无浏览器源),网页表单同源 fetch——没有需要放松的源 |
| 重放同 client_id | 即幂等设计本身(返回原 GG-xx),不是漏洞是特性 |
| version.json 投毒 | 静态文件,仅仓维护者可改;诊断只读不执行 |

### 6.7 容量账(4 万装机上限)

| 场景 | 量 | 各层余量 |
|---|---|---|
| 常态 | ~4–40 条/天(0.01–0.1%/天) | 全层忽略不计 |
| 灾情日(10% 用户当天反馈) | ~4000 条,集中于 1–2 小时 | `/fb` 请求 4k/h ≪ CF 免费层 10 万/天;D1 写 4k/天 ≪ 10 万/天;issue 预算 500/h → 积压 8h 内追平;邮件通知建议在 GitHub 设置改「按批次汇总」 |
| 恶意定向 | 见 §6.5/6.6 | 限频四层 + 预算闸;打不掉的是免费额度,不是数据 |
| 存储 | 峰值 ~84MB/灾情日(21KB×4000) | D1 库 500MB 级;**保留策略:90 天清理**,处理完的行可删(issue 已是持久投影),wrangler 脚本执行 |

### 6.3 对账端点 + 管道自监控(修正:不押注定时触发能力)

- **`POST /fb/reconcile?key=CRON_KEY`**——调度器无关:Pages 定时触发配置、独立 Worker cron、甚至手动 curl 都能调。不把容灾押注在某个平台的 cron 特性上。
- 行为:扫 `issue_id IS NULL` 的行 → 逐条补建 issue → 幂等,可随时重跑,重复调用无副作用(PAT 换新后一次调用即追平全部积压)。
- 积压报警节流:**复用同仓已 OPEN 的 meta-issue 追加评论**,不每次新开——防「报警本身刷屏」。无 OPEN 的 meta-issue 才新建。
- `/fb/list?key=` 增加 `{pending_issues, last_insert_at}` 健康字段;
- `GET /version.json`:静态文件,`{latest, released_at, notes?}`,诊断包 `latest_ver` 与桌面端更新检查共用。

另两条服务端不变量(实现与测试都以此为准):

- **幂等竞态**:并发同 `client_id` → 依赖 UNIQUE 约束,插入冲突时反查既有行返回**原** GG-xx,绝不报错、绝不开第二条 issue。
- **D1 不可达路径的编号**:双槽之一(D1)挂时走 issue 直建,该反馈无 D1 行,回执编号取 `GH-<issue 号>` 前缀区分;此类反馈以 issue 为唯一存底,后续无对账义务(对账只管「D1 有行、issue 缺失」的方向)。

### 6.4 D1 迁移

```sql
ALTER TABLE fb ADD COLUMN kind TEXT DEFAULT 'problem';
ALTER TABLE fb ADD COLUMN client_id TEXT;
ALTER TABLE fb ADD COLUMN sender_uid TEXT;
ALTER TABLE fb ADD COLUMN app_ver TEXT;
ALTER TABLE fb ADD COLUMN issue_id INTEGER;
ALTER TABLE fb ADD COLUMN diag_json TEXT;   -- 结构化包全文
CREATE UNIQUE INDEX IF NOT EXISTS fb_client ON fb(client_id);
```

旧网页表单(无 `v` 字段)走 v1 兼容路径:kind 默认 problem,diag_json 为 null,原 `log` 列照旧——过渡期不坏。

## 7. 桌面端设计

### 7.1 模块与接口(深模块设计)

设计语言:接口 = 调用方必须知道的一切(签名 + 不变量 + 顺序约束 + 错误模式);深模块 = 小接口背后藏大量行为,复杂度不给调用方。依赖单向:`api → feedback → diagnostics / crashlog / logstore`。

**`core/feedback.py` — 深模块,本系统的杠杆点**

接口只有 3 个方法:

```python
submit(feedback) -> Outcome      # 用户点「发送反馈」
pump() -> list[Outcome]          # 到期补发;GUI 打开/网络恢复/ensure 拍上都会调
status() -> QueueStatus          # 待发条数 + 最老一条年龄(供 UI 状态行)
```

`Outcome` 与 §4.2 线上状态码一一对应(桥层零翻译):`Submitted(id)` / `SubmittedDegraded(id)` / `Queued(code, next_attempt_at)` / `Rejected(detail)`(仅 VALIDATION,不入队)。

不变量(接口的一部分,调用方需要知道的全部):

1. **用户提交的反馈,要么送达、要么留在本机直到送达**——调用方永不需要「再问一次」;发送失败、入队、退避、补发全部在模块内。
2. **投递 at-least-once,服务端按 client_id exactly-once** ⇒ 队列无需跨进程锁:`pump()` 可被 GUI 进程与 `--ensure` 进程并发调用而安全(双发被服务端幂等吸收)。GUI 关着时 ensure 拍也能补发。
3. **client_id 在入队时生成一次、终身复用**;已送达条目经原子重写(temp+rename)移出队列。
4. 退避表 30s/5min/30min/次日;单次尝试 timeout 8s、**不原地重试**——重试是队列的事,不是调用链的事。

内部 seam(不出接口):transport adapter(生产 urllib / 测试 fake——两个 adapter,真 seam)、clock adapter(退避计时注入,沿用 logstore `_now` 模式)。
顺序约束:一次用户动作只调一次 `submit`(前端禁用按钮;若双发,是两条独立反馈,服务端不去重——去重只管「同一条的补发」)。
deletion test:删掉它,发送/重试/幂等/退避/队列复杂度会在 api.py、GUI 启动钩子、ensure 拍三处各冒一份——它在挣钱。

**`core/diagnostics.py` — 内容模块**

接口 2 个方法:`collect(scope) -> dict`、`render(bundle) -> str`(预览文本;issue 排版权在边缘端,两渲染器不重叠——预览渲染数据,issue 渲染版式)。
瘦身规则(纯建议不带 net/server/logs/crashes)住在**实现里**,调用方不过滤;不变量:**bundle 构造上无密文**——打码在采集时完成,render 与边缘端永不脱敏。7 个采集器是内部 seam:各自 try/except,失败写该区 `errors` 字段,不传染。

**`core/crashlog.py` — 微接口模块**

接口:`install()`(GUI 与 ensure 两进程启动各调一次)+ `recent(n)`(供 diagnostics 采集)。实现:双 excepthook、记录进程身份、封顶轮转。

**`app/api.py` — 桥 seam(适配器角色)**

3 个桥方法(`feedbackSend` / `feedbackDiag` / `feedbackPendingStatus`)是 core 接口向契约信封的翻译;职责就是信封形状本身,不是浅模块。契约 1.3.0,方法 14→17。

### 7.2 服务端模块同律(fb.js)

- 纯函数:`validate(payload)`(字段+限额)/ `render_issue(bundle)`(版式);
- Adapter:D1 绑定(miniflare 本地可测)/ GitHub API(best-effort,5s 超时,任何异常 → null);
- handler 只做编排与读 secrets;
- 不变量:issue 失败永不失败请求;同 client_id 返回同 GG-xx;v1 载荷按默认值映射。

### 7.3 诊断采集红线

1. **绝不发起真实登录/注销**(全屋共享会话红线)。诊断只做被动/只读探测:chkstatus、TCP/HTTP 探测、DNS 解析、路由表、任务计划查询。`server` 区的登录判定证据来自**用户真实尝试留下的日志 data**,不是诊断重放。
2. **登录请求 URL 永不入包**(URL 含明文密码 `upass=`);data 只存服务器响应字段。
3. 崩溃文件只随用户主动反馈出门,永不静默上传。
4. 打码在采集时完成:mask_uid 对任何含学号字符串生效,出机器即净数据;边缘端无脱敏逻辑。
5. 所见即所发的数据层承诺:预览与发送渲染自同一份 dict;`sender_uid` 为唯一例外(用户拍板:前端不显示,折叠区打码披露)。

## 8. 诊断包逐字段表(七区)

完整注解版 JSON 见附录 B(与 §4.1 同源)。各区回答一类病:

| 区 | 回答 | 关键字段 |
|---|---|---|
| `env` 环境 | 他的机器和我的有什么不一样 | os / clock_skew_s / adapters(kind=tun=VPN 抢路由) / dns / proxy(system+env) / av(杀软布尔) / webview2 / python |
| `self` 自身 | 配置对不对、状态机卡哪、任务真跑了吗 | app_ver / installed_at / config(打码) / state{cred_verified, unreachable_streak, …} / tasks{registered, last_run, last_result}(schtasks 实查) / proc_uptime_s |
| `net` 网络(实时) | 此刻通不通、走哪条路 | dns_resolved / tcp / http / latency_ms / route_iface |
| `server` 服务器(账号状态,**新**) | 服务器怎么看待这个账号/这台机器 | 见下 |
| `logs`+`summary` | 那几天早上发生了什么 | fail 行带 `data{ssid, stage, tries, http, rej, body_head}`;七天成败一行摘要 |
| `crashes` 崩溃 | 程序自己崩过没 | ts + 完整 trace(最近 3 份) |
| 版本对照 | 是不是早修了的老问题 | latest_ver(查 /version.json) |

### server 区(chkstatus 三形态 + 最近判定,形态实测见附录 A)

```jsonc
"server": {
  "chkstatus": { "state": "no_session" },        // 三形态:uid_online(返回 uid/AC)/
                                                 //          no_session(HTTP 400)/
                                                 //          unreachable
  "last_verdict": {                              // 最近一次真实登录尝试的服务器判定(取自日志 data)
    "ts": "09-07 06:52:11", "rej": "limit_users",
    "msga": "Oppp error: Limit Users Err",
    "server_view_ip": "172.16.0.1",          // ss5:服务器看到的来源 IP
    "mac_hint": ["00aa00bb00cc", "00dd00ee00ff"],// ss1/ss4
    "aolno": 6152, "ubind": "mac1='',ty1=0,…" } }
```

## 9. 容灾矩阵(验收自检表)

| 故障 | 检测 | 兜底 | 用户看到 |
|---|---|---|---|
| 用户没网 | E_NET_OFFLINE | 本地队列+退避补发 | 「已存本地,联网自动补发」 |
| Cloudflare/D1 挂 | 503 / DEGRADED | 队列 或 issue 直建 | 无感或「稍后自动」 |
| GitHub 挂 / PAT 过期 | issue_id NULL | 对账端点补建 + meta-issue 评论报警 | 完全无感 |
| 双挂 | SINK_DOWN | 队列保留 | 「已存本地」 |
| 重复提交 | client_id UNIQUE | 返回原 GG-xx | 不出重复 |
| 挤兑(全校同炸) | 四层限频 | 桌面 30/client_id/h + 300/IP/h;issue 预算闸顶住投影层 | 稍后自动,不丢 |
| 诊断采集器失败 | in-band errors 字段 | 该区缺失其余照发 | 发送不受阻 |
| 旧版网页表单 | v1 兼容路径 | 原逻辑照跑 | 无感 |

## 10. 验收标准

- **AC-F1** 选「问题」提交,10s 内收到 `SUBMITTED` + GG-xx;issue 落私有仓:标题含分类+编号+摘要,标签正确,正文含七区全包;开发者邮箱收到通知。
- **AC-F2** 纯建议提交:包体无 `net/server/logs/summary/crashes`;issue 标签仅 `suggestion`。
- **AC-F3** 断网提交:立即入队,页面出现待发行;恢复网络后自动补发成功,GG-xx 回执,开发者侧仅一条 issue。
- **AC-F4** 同 client_id 重发:边缘端返回原 GG-xx,D1/issue 均不重复。
- **AC-F5** 人为使某采集器抛错:包内该区 `errors` 字段如实记录,提交成功。
- **AC-F6** 学号不出现在任何前端界面明文;issue 正文与 D1 有 sender_uid;反馈页折叠区有打码披露行。
- **AC-F7** PAT 失效后用户提交:仍 `SUBMITTED`(D1 成功),cron 报警 meta-issue,换 PAT 后积压自动补建 issue。
- **AC-F8** `limit_users` 态(实测可稳定复现,见附录 A):日志文案为「已在别的设备登录」方向,**不**出现「密码可能改过了」;`data.rej="limit_users"`;cred_verified 不被置假。
- **AC-F9** chkstatus 无会话(HTTP 400)被归类为 `no_session`,不产生异常日志。
- **AC-F10** 四层限频生效(30/client_id/h、桌面 300/IP/h、匿名 8/IP/h、64KB 早拒),429 带 retry_after。
- **AC-F15** issue 预算闸:预算耗尽后提交仍 `SUBMITTED_DEGRADED` 入 D1,不丢;对账端点在预算内匀速补建。
- **AC-F16** 注入防护:what/contact 含反引号、链接、HTML 时,issue 渲染为字面量(代码 span/fenced block),标签永远服务端固定。
- **AC-F11** 后端全模块单测通过(测试走模块接口,不测内部);mock(?dev=1)覆盖全部响应 code 与样例诊断包 fixture;现有测试全绿。
- **AC-F12** v1 网页表单提交照常入库(向后兼容)。
- **AC-F13** GUI 与 ensure 双进程并发 `pump()`:服务端仅产生单条 D1 行与单条 issue(client_id 幂等吸收双发)。
- **AC-F14** `/fb/reconcile` 重复调用幂等(补建不重复);meta-issue 报警走评论追加,不刷屏。

## 11. 实施切片

| 切片 | 内容 | 完成标志 |
|---|---|---|
| S1 主链路 | 协议 v2 + 状态码信封 + client_id 幂等 + D1 迁移 + issue 投影 + 前端表单/三态/回执 | AC-F1/F2/F4/F12 |
| S2 容灾 | 本地队列+补发 + 限频修正 + E_NET_* 分类 | AC-F3/F10 |
| S3 诊断包 | 七区采集(含 server 区/chkstatus 三形态)+ 崩溃捕获 + /version.json + 四态拒绝修复 | AC-F5/F8/F9 |
| S4 对账 | `/fb/reconcile` 端点 + meta-issue 评论报警 + /fb/list 健康 | AC-F7/F14 |

每片独立可测可交付;S1 完成反馈已可用,后面全是加固。

## 12. 待定项

- **仓的决策(2026-09-07 拍板:方案 A)**:`ornman/guigui-site` **转私有**,反馈 issue 挂此仓;PAT 仅此仓 Issues 写;官网开源意愿搁置。issue 正文可含学号明文(sender_uid)与完整诊断。
- 官网表单加分类胶囊/接 v2:后续独立任务(site 发布仓),本轮不碰。
- 是否在设置页给用户一个「查看账号在服务器上的状态」只读入口(server 区能力的产品化露出):待定。

---

## 附录 A:实测记录(2026-09-07,测试床)

- 环境:网口直插墙口(172.16.0.1,主机路由 10.1.2.3/32 钉网口 IF18),与全屋 WiFi 会话隔离;账号 = 全屋当前在线账号(经 WiFi chkstatus 同 uid)。
- 序列:只读探测 → 一次登录 → 只读复查,间隔 ≥4s,无注销。
- **登录响应(已在别处登录态,JSONP 全文,密码不在响应中)**:

```json
{"result":0,"wopt":0,"msg":1,"uid":"2025000000001","hidm":0,"hidn":-5,
 "ss5":"172.16.0.1","ss6":"10.1.2.3","vid":0,"ss1":"00aa00bb00cc",
 "ss4":"00dd00ee00ff","cvid":0,"pvid":0,"hotel":0,"aolno":9999,"eport":-1,
 "eclass":1,"ubind":"mac1='',ty1=0,mac2='',ty2=0,mac3='',ty3=0,mac4='',ty4=0,mac5='',ty5=0",
 "msga":"Oppp error: Limit Users Err"}
```

- **判定**:`result:0` + `msga:"Oppp error: Limit Users Err"` = 账号同时在线数超限(已在别处登录);`classify_rejection()` 现状返回 None(四态修复依据)。
- **chkstatus 无会话形态**:墙口未认证时 `/drcom/chkstatus` 返回 HTTP 400(归类 `no_session` 依据)。
- 复查:墙口仍 `not_logged_in`,拒绝无残留,金丝雀干净。

## 附录 B:请求结构全文

即 §4.1 的注解版 JSON(信封/输入 + env/self/net/server/logs+summary/crashes/latest_ver,逐字段「是什么/从哪来/诊断什么用」)。它是契约的唯一正本:实施时原样拆成 `docs/tech/guigui-bridge-api-v1.md` §2.15 附表,`fb.js` 校验规则、`render_issue` 版式、mock 样例包 fixture 均以此为准,三处不得各写一份。

## 决策记录(拍板链)

1. 反馈动作=复制诊断(契约 1.1.0)→ 本轮推翻:重构为真通道(用户拍板「彻底重构」)。
2. 分类=问题/建议,**多选**(胶囊);纯建议不带诊断区(自动规则,无开关)。
3. 接收端=GitHub issue 投影 + D1 存底;邮件/网页/close 全走 GitHub 原生能力。
4. 学号=后端直附 sender_uid,前端不显示,折叠区打码披露(用户拍板 2026-09-07)。
5. 服务器状态区入包;拒绝四态(limit_users 实测新增);诊断绝不真实登录/注销。
6. 诊断=结构化包而非文本 blob;issue 排版权在边缘端;采集失败 in-band。
7. 容灾三层(本地队列/双槽写入/对账 cron)+ 状态码信封 + 校园 NAT 限频修正。
8. 纯建议瘦身、诊断折叠、离线纯复制降级(不加 mailto)、标题「说给桂桂听。」、日志截断保头保尾——均按推荐通过。
9. 设计规模上限 4 万装机;安全/容量成章(§6.5–6.7):issue 预算闸为 DoS 核心,身份模型=自报线索永不作鉴权。
10. 仓=方案 A:guigui-site 转私有(2026-09-07 用户拍板)。
