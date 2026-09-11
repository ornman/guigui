# 桂桂后端业务系统架构审计与评分(2026-09-11)

- **视角**:架构选型级(技术选型/集成方式/机制设计的系统性风险),代码级瑕疵降级附录 A,不进评分。
- **方法**:16 个外部进程调用点逐点 grep + 精读核实;关键可行性用项目 venv 实测探针(COM 迟绑定);子代理广度扫查的结论全部经人工抽查后才入册。所有引用均为本次一手核实(file:line)。
- **范围**:`guigui/core/`(13 模块,~3,000 行)+ `guigui/app/`(api/gui/instance)+ 壳与分发(build_guigui.bat / guigui.spec / setup.iss)。测试规模 279(pytest collect 实数)。

---

## 0. 结论先行

后端存在**一个系统性选型反模式 + 两个全局放大器**:

> **反模式 S1:「把系统 API 当外部命令调」** —— 16 个调用点把 schtasks、powershell、tasklist、ipconfig、route、netsh 六种系统二进制当 SDK 用。其中三处(schtasks 建任务、powershell×2)是杀软行为引擎的高敏特征(T1053.005 / LOLBin 滥用);tasklist 匹配杀软进程名是教科书级「侦察」行为。这不是某处代码写错,是集成方式的一致性选型——所以每一处都要按同一个原则改(进程内 API 优先),见 ADR-0001/0002/0003。
>
> **放大器 S2:全链未签名** —— PyInstaller exe 与 Inno 安装器均无签名(build_guigui.bat 无 signtool、setup.iss 无 SignTool 配置)。未签名是所有行为特征的「分母」:同样的行为,签名与否决定它是「正规软件」还是「可疑持久化」。2026-09-07 三杠杆(放行/安装期建任务/签名)中唯一未动的就是签名。见 ADR-0005。
>
> **放大器 S3:持久化触发面** —— 默认配置落 2 个任务(日历 6 拍 + **登录触发**);登录触发是持久化评分最高项。opt-in 再 +2(唤醒触发 + 15/30/60 分钟心跳巡逻,巡逻 Duration 写 P3650D 十年)。机制本身是 2026-09-07 拍板「计划任务不动」,本审计不推翻机制,只收暴露面:被拒后无降级路径、无退避,Wake 任务被拦即无限重试。见 ADR-0006。

同时必须如实记录:凭据架构、前后端桥、状态对齐三处选型**优于同体量产品的普遍水准**(见 §3 C/D/G 域),这部分不是客套,是「哪些决策不要动」的边界。

**加权总分 5.8 / 10**(架构选型视角;ADR-0001~0006 全部落地后预计 7.9)。

---

## 1. 系统架构地图(现状)

```
任务计划程序(4 任务,per-user)──拉起──▶ guigui.exe --ensure --trigger <拍>
   GuiGui(日历 6 拍,默认)                 │ 短进程:无守候、无常驻
   GuiGui-Boot(登录触发,默认)             ├─ detect.py   route print → 默认路由判定
   GuiGui-Wake(唤醒触发,opt-in)           ├─ wifictl.py  netsh wlan ×5(探测/连接/profile)
   GuiGui-Patrol(心跳巡逻,opt-in)         ├─ drcom.py    urllib → http://10.1.2.3(明文,协议固有)
                                           ├─ vault.py    keyring → advapi32 CredWriteW(无明文回退)
GUI(pywebview/WebView2,js_api 原生桥,     ├─ ensure.py   状态机 + 原子写 state
    零监听端口)                            ├─ notify.py   powershell → WinRT Toast + guigui://
   ├─ saveConfig/masterToggle/启动          ├─ selfheal.py reconcile(rev 对齐,幂等)
   └─ rebuildTask(用户点击,3 连试)        └─ scheduler.py schtasks /create /delete /query ×3
分发:PyInstaller onedir(未签名)→ Inno per-user(未签名)→ 运行时建任务
```

## 2. 评分卡(架构域)

| 域 | 权重 | 得分 | 判断 |
|---|---|---|---|
| A 系统集成方式(外部命令 vs 进程内 API) | 25% | **3** | 16 调用点 / 6 种二进制;3 处高敏;同一病灶,须按同一原则统一改 |
| B 调度与持久化架构 | 15% | **5** | 机制选型正确(per-user 任务计划,免管理员、可被用户审计);触发面无收敛、失败无退避 |
| C 凭据与数据架构 | 15% | **9** | 凭据管理器双路(keyring 主 + advapi32 直调),拒绝明文回退;三处原子写;日志红线成体系 |
| D 前后端桥与进程模型 | 15% | **8** | js_api 原生桥零监听端口(无 CSRF/绑定面);短进程模型符合「低频不托盘」定位;扣分:每拍行为特征密集(netsh→HTTP→落盘 × 心跳) |
| E 打包与分发架构 | 15% | **4** | 未签名是全局放大器;方向正确的部分:per-user 安装/onedir/无 UPX/AppMutex/卸载问询数据 |
| F 可观测性架构 | 5% | **6** | 诊断包结构化、分区容错好;采集层 5 处 shell-out 拖累 |
| G 工程治理(契约/测试/矩阵) | 10% | **8** | 279 测 + F 章动态验收 21/21 + tasks_rev 自增对齐纪律;扣分:mock 侧曾藏 pwd=null 自洽 bug,mock≠真机教训在案,真机项(锚点窗口/bind 解绑/返校日)未闭环 |

**加权 = 3×.25 + 5×.15 + 9×.15 + 8×.15 + 4×.15 + 6×.05 + 8×.10 = 5.8 / 10**

修复后推演:A→8(COM/WinRT/WMI 落地,余 netsh 有保留理由)、B→7(退避+降级)、E→8(签名)⇒ **7.9 / 10**。剩余缺口是协议固有明文(R8)与真机验收欠账。

## 3. 各域论据(一手证据)

### A. 系统集成方式 —— 3/10(最严重)

外部进程调用点穷举(grep 全量,逐点核过):

| 调用点 | 二进制 | 杀软敏感度 |
|---|---|---|
| scheduler.py:255/275/292(create/delete/query) | schtasks | **高**:未签名 exe 起 schtasks /create /f /xml = T1053.005 模板 |
| notify.py:68(全部 Toast 含自救指引) | powershell `-ExecutionPolicy Bypass` | **高**:经典拦截特征;且自救链单点(S4) |
| diagnostics.py:332(Get-ScheduledTaskInfo) | powershell | **中高**:第二处 powershell |
| diagnostics.py:223(tasklist + 匹配 hipsdaemon/360tray/msmpeng,diagnostics.py:215-219) | tasklist | **高(侦察特征)**:枚举进程并匹配杀软名,教科书反侦察目标 |
| diagnostics.py:120/169(ipconfig /all) | ipconfig | 低(只读) |
| detect.py:40(route print -4)、diagnostics.py:426 | route | 低(只读) |
| wifictl.py:42/56/88/157/200(show/add profile/connect) | netsh | 中:LOLBin;心跳巡逻开启时 15/30/60 分钟一次的 netsh→HTTP→落盘模式,行为画像接近僵尸节点心跳 |

反向证据(该反模式代价已被实测过):scheduler.py:317-321 注释在案——2026-08-31 火绒严格模式拦「未知程序注册登录触发任务」,同 XML 去掉 LogonTrigger 即放行。**已经为这个选型付过一次拦截成本,并靠降级而非换通道消化**。

### B. 调度与持久化架构 —— 5/10

- 选对的部分:per-user Task Scheduler(免管理员、用户可在 taskschd.msc 审计、无服务进程内存常驻);声明式意图 + `tasks_rev` 自增(config.py:155-158)+ 幂等对齐(selfheal.reconcile);任务命令行与 XML 不含任何凭据(scheduler.py:60-77,学号/密码运行时从 config/vault 读)。
- 欠缺的部分:① Wake 任务(EventTrigger)被拒**无降级路径**——selfheal.py:44-52 降级只认 LogonTrigger,Wake 被拦 = misaligned 常亮,每次 reconcile 无限重试;② 无退避:GUI 启动(gui.py:290-311)、每次 saveConfig(api.py:538-541)、masterToggle、rebuildTask 3 连轮(api.py:589-593)都会全量重试建任务——拦截环境下等于周期性向杀软示威;③ 巡逻 Duration P3650D(scheduler.py:35)+ WakeToRun=true(scheduler.py:103)属观感/评分加分项。
- 边界说明:默认仅 2 任务(boot_login=True/wake=False/patrol=False,config.py:70-78),触发面描述按默认口径,不夸大。

### C. 凭据与数据架构 —— 9/10(不要动的部分)

- vault.py:100-138:主路 keyring(DPAPI 背书)→ 降级 advapi32 CredWriteW/CredReadW 直调,**VaultError 明文拒绝落盘**(vault.py:25-26);无自造加密、无 key 文件。
- 原子写三处:config(config.py:161-165 mkstemp+os.replace)、state、feedback 队列。
- 日志红线成体系:LoginResult 结构性排除请求 URL(drcom.py:198-208)、_fail_data 只存响应字段(ensure.py:282-310)、scrub_uids/mask_uid 全链、崩溃堆栈过洗。
- 已知悉项:明文 uid 在 config(用户目录内,接受);`upass=` GET 明文上行(drcom.py:183-195)为 Dr.COM 协议固有,校园网链路可见——记录在案,不可整改(R8)。

### D. 前后端桥与进程模型 —— 8/10

- 生产零监听端口:api.py 是 pywebview js_api 原生桥,无 HTTP 面(唯一 server 在 devshell.py,仅 dev、127.0.0.1 随机端口,不进打包);无 CSRF/DNS rebinding 面。
- deep link 视图白名单(__main__.py:55-58)、单实例互斥(instance.py + AppMutex 与卸载器配合 setup.iss:25)。
- 短进程模型(任务计划拉起、跑完即退)符合「GUI 低频不托盘」拍板;代价是自愈只能靠「下次拍/GUI 打开」——已被 task_lost 每日一拍(ensure.py:224-243)覆盖任务侧,**凭据侧无对等检查**(vault 读不到时整拍静默跳过,ensure.py:327-330)——见附录 A-4。

### E. 打包与分发架构 —— 4/10

- 未签名(grep signtool/authenticode 全仓零命中):exe 与安装器双双未签,S2。
- 方向正确的:PrivilegesRequired=lowest(setup.iss:22)、onedir + 无 UPX(spec)、AppMutex 防文件占用卸载残留、卸载问询数据 + 先 exe 后删目录的凭据清理顺序(setup.iss:76-100)。
- 缺口:卸载器只删 2/4 任务(setup.iss:48-51)——默认配置下卸载即残留指向已删 exe 的**登录触发**幽灵任务(产品事故级,ADR-0004);无安装期建任务(三杠杆之二,但由未签名 exe 执行收益存疑,归入 ADR-0005 一并权衡)。

### F. 可观测性架构 —— 6/10

诊断包(diagnose)结构化分区、单区失败不塌(_collect_env 逐区容错,diagnostics.py:251-262)是亮点;拖累项全在采集方式(见 A 域表)。last_run/last_result 依赖 powershell(diagnostics.py:319-339),ADR-0001 顺手消灭。

### G. 工程治理 —— 8/10

契约版本治理(1.6.0)、279 测、F 章动态验收 runner(21/21 + 路由格 18/18 + AC 2/2)、矩阵同步义务——纪律在。扣分:真机欠账(锚点窗口期实测、bind 解绑补测、返校日实跑)与 mock 自洽 bug 前科(mock pwd=null,2026-09-11 已修)。

## 4. 风险登记册(选型级)→ ADR 映射

| # | 风险 | 级别 | 去处 |
|---|---|---|---|
| R1 | schtasks.exe 子进程建任务(T1053.005 特征,火绒已实测拦过) | 高 | **ADR-0001(已批准·待实施)** |
| R2 | 通知全链 powershell,含自救指引单点(powershell 被拦→指引发不出) | 高 | **ADR-0002(提议)** |
| R3 | 诊断采集 shell-out 全家桶;tasklist 匹配杀软进程名 = 侦察特征 | 中高 | **ADR-0003(提议)** |
| R4 | 全链未签名(全局放大器) | 高 | **ADR-0005(待拍板·预算)** |
| R5 | 卸载漏删 GuiGui-Boot/GuiGui-Wake → 幽灵登录任务 | 中高(产品事故级) | **ADR-0004(纯执行)** |
| R6 | Wake 无降级 + reconcile 无退避(拦截环境下无限重试) | 中 | **ADR-0006(提议·含文案拍板)** |
| R7 | 凭据侧无在岗自检(vault 失联→07:00 承诺静默死亡) | 中 | 审计建议项(附录 A-4;实施前文案过目) |
| R8 | Dr.COM 明文 HTTP 密码上行 | 中(协议固有) | 记录在案,不可整改 |

## 5. 与既有拍板的边界(本审计不推翻)

- 2026-09-07「计划任务机制不动」:维持 per-user Task Scheduler **机制**;ADR-0001 只换传输层(COM vs 子进程),任务结构/触发器拍板全部不动。
- 2026-09-06 Qt 迁移已否(内存同量级):WebView2 栈维持;该栈带来的 pythonnet 反而是 ADR-0001/0002/0003 的零新增依赖底座(实测探针已验)。
- 「GUI 低频不托盘」「WiFi 扫描点选不手填」「杀软三杠杆」框架维持;三杠杆中签名(ADR-0005)与放行(已有 task_blocked 指引)在册,安装期建任务在 ADR-0005 内一并权衡。

## 附录 A:代码级瑕疵(不进评分,顺手可修)

1. wifictl.py:133-150:SSID 经 `.replace("{name}", ssid)` 塞入 WLAN profile 模板,无 XML 转义——畸形 SSID 最坏致 netsh 报错,健壮性项。
2. scheduler.py:251-269 / wifictl.py:153-166:delete=False 临时文件在进程被终结时残留 %TEMP%(内容无凭据,泄露面小)。
3. vault.py:32 `CRED_PERSIST_LOCAL_MACHINE` 命名易误读(与 keyring WinVault 同款,语义为「机器存活期」非「全局共享」),建议注释澄清。
4. 凭据在岗自检缺口(正文 D 域/R7):建议复用 task_lost 每日一拍模式加 cred check,文案过目后实施。
