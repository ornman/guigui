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
                                      尽力而为;失败由 cron 对账补)
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
{ "v": 2,
  "client_id": "8f14e45f-…",       // UUID,幂等键
  "sender_uid": "2025000000001",    // 后端直附(前端不显示);纯数字或空
  "app": "desktop", "app_ver": "2.1.0",
  "kind": ["problem"],              // ⊆ {problem, suggestion},非空
  "what": "今早没登上…",             // ≤120 字,必填
  "contact": "",                    // ≤80,可选(QQ/邮箱)
  "when": "09-07 06:52",            // 自动取最近失败日志时间;纯建议为空

  "env":    { …环境区… },
  "self":   { …自身区… },
  "net":    { …网络区(实时)… },
  "server": { …服务器区(账号状态)… },
  "logs":   [ …日志区(带现场)… ],
  "summary": "09-05 ✓ · 09-06 ✗ · 09-07 ✗",
  "crashes":[ …崩溃区… ],
  "latest_ver": "2.1.2" }
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

### 6.2 限频修正(校园 NAT 挤兑)

现行 8 条/IP/时在校园共享出口下会把灾情反馈掐死(真出事那天人人来反馈,第 9 人起全 429)。修正:桌面端(UA=GuiguiDesktop + 合法 client_id)30 条/IP/时;网页表单维持 8。429 一律带 `retry_after`。

### 6.3 对账 cron + 管道自监控

- Pages cron 定时扫 `issue_id IS NULL` 的行补建 issue(PAT 换新后自动追平);
- cron 发现积压 → 在同仓给自己开 meta-issue「反馈管道积压 N 条」——用管道自己报警管道故障;
- `/fb/list?key=` 增加 `{pending_issues, last_insert_at}` 健康字段;
- `GET /version.json`:静态文件,`{latest, released_at, notes?}`,诊断包 `latest_ver` 与桌面端更新检查共用。

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

### 7.1 模块划分(依赖单向:api → feedback → diagnostics/crashlog/logstore)

| 模块 | 职责 |
|---|---|
| `core/crashlog.py`(新) | `sys.excepthook` + `threading.excepthook` → `crashes/*.log`(只落盘,绝不自动上传) |
| `core/diagnostics.py`(重写) | `collect() -> dict`(七区采集,打码在采集时完成)+ `render_text(dict)`(预览渲染);采集器失败 in-band:该区写 `"errors": ["adapters: PermissionError"]` 其余照发 |
| `core/feedback.py`(新) | 发送/状态码分类/待发队列/退避补发;纯逻辑全可单测 |
| `app/api.py`(薄桥) | 契约 1.3.0:`feedbackSend` / `feedbackDiag` / `feedbackPendingStatus`(方法 14→17),返回值一律 §4.2 信封 |

### 7.2 本地待发队列(L1 容灾)

- 文件:`pending_feedback.jsonl`(原子写:temp+rename);每条=完整请求载荷 + created_at + attempts;
- 单次发送尝试 timeout 8s,**不原地重试**——重试是队列的事:退避 30s/5min/30min/次日;
- 补发触发:app 启动、`net:state` 恢复在线事件、设置页打开;
- `client_id` 保证补发绝不重复入库/重复开 issue。

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
| GitHub 挂 / PAT 过期 | issue_id NULL | cron 对账补建 + meta-issue 报警 | 完全无感 |
| 双挂 | SINK_DOWN | 队列保留 | 「已存本地」 |
| 重复提交 | client_id UNIQUE | 返回原 GG-xx | 不出重复 |
| 挤兑(全校同炸) | 修正后限频 | 30/IP/h(桌面)+ 入队退避 | 稍后自动,不丢 |
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
- **AC-F10** 桌面端 30 条/IP/时、网页端 8 条/IP/时,429 带 retry_after。
- **AC-F11** 后端全模块单测通过;mock(?dev=1)覆盖全部响应 code 与样例诊断包 fixture;现有测试全绿。
- **AC-F12** v1 网页表单提交照常入库(向后兼容)。

## 11. 实施切片

| 切片 | 内容 | 完成标志 |
|---|---|---|
| S1 主链路 | 协议 v2 + 状态码信封 + client_id 幂等 + D1 迁移 + issue 投影 + 前端表单/三态/回执 | AC-F1/F2/F4/F12 |
| S2 容灾 | 本地队列+补发 + 限频修正 + E_NET_* 分类 | AC-F3/F10 |
| S3 诊断包 | 七区采集(含 server 区/chkstatus 三形态)+ 崩溃捕获 + /version.json + 四态拒绝修复 | AC-F5/F8/F9 |
| S4 对账 | cron 补 issue + meta-issue 报警 + /fb/list 健康 | AC-F7 |

每片独立可测可交付;S1 完成反馈已可用,后面全是加固。

## 12. 待定项

- **GitHub 私有仓名**:建议新建 `ornman/guigui-feedback`(只放反馈 issue,干净;PAT 最小授权=仅此仓 issues 写)。
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

## 附录 B:请求结构注解版(与 §4.1 同源,落契约文档时原样带走)

见 2026-09-07 对话定稿的逐字段注解 JSON(信封/输入/env/self/net/logs+summary/crashes/latest_ver 七区,每字段「是什么/从哪来/诊断什么用」三问注释);随实施进 `docs/tech/guigui-bridge-api-v1.md` §2.15 附表。

## 决策记录(拍板链)

1. 反馈动作=复制诊断(契约 1.1.0)→ 本轮推翻:重构为真通道(用户拍板「彻底重构」)。
2. 分类=问题/建议,**多选**(胶囊);纯建议不带诊断区(自动规则,无开关)。
3. 接收端=GitHub issue 投影 + D1 存底;邮件/网页/close 全走 GitHub 原生能力。
4. 学号=后端直附 sender_uid,前端不显示,折叠区打码披露(用户拍板 2026-09-07)。
5. 服务器状态区入包;拒绝四态(limit_users 实测新增);诊断绝不真实登录/注销。
6. 诊断=结构化包而非文本 blob;issue 排版权在边缘端;采集失败 in-band。
7. 容灾三层(本地队列/双槽写入/对账 cron)+ 状态码信封 + 校园 NAT 限频修正。
8. 纯建议瘦身、诊断折叠、离线纯复制降级(不加 mailto)、标题「说给桂桂听。」、日志截断保头保尾——均按推荐通过。
