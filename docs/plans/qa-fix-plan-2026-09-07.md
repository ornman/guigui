# 桂桂修复计划 — 2026-09-07 QA 验收审计

> 来源:2026-09-07 对话,用户以验收视角(QA)审出承诺-验证错位,agent 补充核实。
> 执行方式:新对话逐项执行。每项独立 commit(项目纪律),基准 193 测全绿。
> 视角口径:桂桂对用户的每一个「成功/完成/开启」承诺,验证链必须完整——
> 每一环同步验证?失败用户被告知?有没有出路?

## 执行约定

- 修改前先跑 `pytest`(guigui/),全绿基准;改完全绿再 commit。
- 涉及 api 返回形状/新字段 → **契约变更**:先改契约文档(版本号 1.2.0→1.3.0,新增字段向后兼容),前端 static 若消费新字段需联动(双对话分工:后端=core/壳,前端=契约+static;本 plan 默认后端先行,标注 `契约` 的项需同步契约)。
- 标注 `需实测` 的项依赖校园网环境,列在文末,不要闭门造车猜服务器行为。
- 不改本 plan 已拍板的范围之外的东西;发现新问题记录到「新发现」节,不顺手修。

---

## P0 — 承诺直接破(验收级)

### 1. 开启流程同步确认任务计划 `契约`

**问题**:提交密码开启成功页说「已开启每日自动登录」,但任务对齐丢后台线程,成功页不等待、不携带结果(`api.py:380-382` `threading.Thread(... _align_saved ...)`)。任务被安全软件拦(火绒,实机发生过)时,任务计划是**唯一触发源**,自动化整体不存在,而成功页已承诺。对照:`masterToggle` 是同步 reconcile + 被拦弹通知(`api.py:456-462`),注释自证「PS 调用秒级」——异步化没有必要。

**修法**:`_login_submitted_credential` 成功收尾处改为同步 `selfheal.reconcile(saved)`(masterToggle 同款),把 `task_ok`(及被拦时的行动指引)带进 login 成功信封;被拦时 `notify.task_blocked()` 同步弹。后台线程仅保留给 saveConfig 路径。

**验收**:模拟 schtasks 被拦(monkeypatch `scheduler.create_task` 失败),提交密码 → 返回信封含 `task_ok:false` + reason;成功页文案如实说「密码已存,但定时任务被拦」+ 重建入口;通知弹出。模拟正常建任务 → `task_ok:true`。

**测试**:test_api.py 增两个用例(被拦/在岗);现有 login 用例适配新字段。

### 2. 「已经在线」不核对在线者身份(假阳性)

**问题**:立即登录探测 LOGGED_IN 直接收工返回 `already`(`api.py:167-170`),未调 `drcom.chkstatus_uid` 核对。全屋共享会话下,在线的可能是室友账号;桂桂说「已经在线」、`settle_from_gui` 记 ok 日志、`last_result` 记成功——**别人的成功被记成用户的**。对照:提交密码路径核对了(`api.py:251` 标注线上他人学号),意识存在,分支漏了。

**修法**:`_login_stored_credential` LOGGED_IN 分支先 `chkstatus_uid` 对比 `uid`:一致 → 现行为;不一致 → 照常走 `_attempt_login`(把会话换成自己的);chkstatus 不可得 → 现行为(不阻塞)。ensure 静默路径同步检查(收工前核对,不一致时记 note 日志「线上是他人学号…」并照常走登录;与 docstring「线上他人学号如实记录」对齐)。

**验收**:mock chkstatus 返回他人学号 + 探测 logged_in → 走真登而不是 already;chkstatus 失败 → 不回退成报错,保持可用。

**测试**:test_api / test_ensure 各加用例;复用 2026-08-30 实测的 chkstatus 行为(uid/AC 字段)。

### 3. 「关」开关删任务失败无通知(幽灵任务)

**问题**:`api.py:461` `if misaligned and value: notify.task_blocked()`——只有**开**失败通知;**关**时删任务失败 → 无 Toast、用户已离开 → 明早 07:00 任务照常登录。开着失败是「没动静」,关着失败是**背着用户干活**,后者更伤信任。

**修法**:删失败(misaligned and not value)同样 `notify.task_blocked()` 或新增 task_linger 文案(「关没关干净,任务还在,明早还会登录——点此处理」);schedule:changed 事件已带 task_ok,前端已有 task-row 兜底,不动。

**验收**:mock `remove_task` 失败 → masterToggle(on=false) 弹通知;信封仍如实返回。

**测试**:test_api.py masterToggle 关失败用例。

---

## P1 — 承诺弱化 / 边缘真实

### 4. 凭证库不可用:补降级 + 文案出路

**问题**:`VaultError` → INTERNAL「系统凭据管理器不可用,存不下密码」(`api.py:221` 等 7 处),无降级、无出路。「不回退明文」是纪律(v1 教训)必须保持;但 vault.py 已直调 advapi32(`CredEnumerateW/CredDeleteW`,`vault.py` delete_all_service_entries)——同一个 DLL 有 `CredWriteW/CredReadW`,keyring 库异常而凭据管理器(系统服务)还活着时,直调 = 同一保险柜换钥匙,安全属性不变。

**修法**:`vault.py` 加 advapi32 直调读写作为 keyring 失败的降级(先 keyring,`VaultError` 再直调,两者都败才抛);INTERNAL 文案改为给出路:「系统凭据管理器不可用——试试重启电脑,还不行就带着这句反馈」。

**验收**:mock keyring 抛错 + 直调成功 → 存取密码正常;两者都挂 → 报错带指引文案。

**测试**:test_vault.py 降级路径用例(mock ctypes 调用)。

### 5. 任务在岗无周期自检(自愈盲窗数周)

**问题**:selfheal 只在四处触发(saveConfig/masterToggle/login/GUI 启动)。任务被安全软件**事后**删除、exe 被挪目录(`action_target_exists` 有检测)——GUI 低频定位下盲窗可能数周,自动化已死无人知晓。「每天 07:00」是最大长期承诺,无心跳自证。

**修法**:`ensure.run()` 收尾处轻量 `scheduler.query_xml` + `action_target_exists` 查主任务在岗;失联写进 ensure_state(如 `task_lost: date`),并经现有通知去重决策弹一次「定时任务不见了」+ 指引。注意 --ensure 短进程不做 reconcile(不重建,只报告)——重建仍留给 GUI 侧,避免静默进程和管理侧抢。

**验收**:mock 任务查询失败 → state 记录 + 当日一条通知;任务在岗 → 零开销零日志。

**测试**:test_ensure.py 自检用例;注意假期静默下自检是否也压制(建议:silent 下不查,返校后再说)。

### 6. waitsec 节流三件套 `需实测`

**问题**(用户 2026-09-07 提出):服务器对频繁登录节流并**给出等待秒数**;现状只在 GUI 两处处理(`api.py:345,358`),硬编码睡 4 秒不解析服务器给的时间;ensure 静默重试循环完全无 waitsec 分支;节流拒绝若 msga 含 error2 标记会被误诊成「密码不对」(密码明明是对的)。

**修法**:
- `drcom.py`:`login()` 解析响应中的 waitsec 数值,返回 `(result, msg, waitsec)` 或 msg 中结构化携带;
- 分类优先级:`classify_rejection` 前置 waitsec 检测——「太快」永不翻译成「密码错」;
- `api._verify_login_once` / `_restore_network`:按服务器秒数等(上限封顶如 30s,超了就把剩余时间透传信封);
- `ensure._attempt_login`:重试循环遇 waitsec → 睡到时间再试,不烧重试次数。

**验收**:mock 节流响应 → 不误诊 wrong_password;ensure 循环按秒数等待;信封 message 告知「服务器让等 N 秒」。

**实测依赖**:节流 msga 的真实形状(含不含 error 标记、waitsec 字段名)需校园网环境触发一次——见文末。

### 7. 返校日「每天只探 1 次」全天压制 `需拍板口径`

**问题**:`ensure.py:239` `silent and last_unreachable_date == today` → 进门即退,**不分触发来源**。返校日第一拍若恰好网未就绪(刚开机 WiFi 没连上)→ 记入「今天已探」→ 当天所有拍(含开机 L2/唤醒 L5/巡逻)全秒退 → 当天不登录,日志只有一条 silent,用户查不出原因。AC-10「每天只探 1 次」是刻意条款,但这个组合后果可能未被预期。

**修法(建议,需用户拍板)**:silent 状态下,由**开机(LogonTrigger)/唤醒(EventTrigger)触发**的拍豁免压制(返校必然伴随开机/唤醒,天然恢复点);「每天 1 次」字面保留给日历拍。实现:--ensure 增加 `--trigger boot|wake|calendar|patrol` 参数,scheduler.py 三个 Trigger 的 Action Arguments 分别带上;ensure.run 按参数豁免。

**验收**:mock silent 状态 + boot 触发 → 正常探测不秒退;calendar 触发 → 维持秒退(AC-10 不破)。

**测试**:test_ensure / test_scheduler 各加用例;XML 参数变化注意 tasks_rev 兼容(旧任务无参数 → 视为 calendar,不强制重建)。

---

## P2 — 低概率 / 卫生项

### 8. guigui:// 协议注册失败,通知点击无响应

`register_protocol` 失败只记日志(`notify.py:137+`)→ 通知照常弹,点击无声无息。修法:注册失败时通知降级(不设 activationType protocol,纯展示)或首次启动 GUI 检测注册状态给一次性提示。低优先级。

### 9. identify 回填防误抓提示

`identify()` chkstatus 优先(`api.py:123-134`),共享会话下可能回填室友学号;验证阶梯兜底不入库,但 UX 困惑。修法:identify 信封加 `confidence` 或 source 标注,首装表单识别结果旁一句「检测自当前网络会话,确认是你自己的学号」(前端文案,`契约` 轻量)。

### 10. 架构 backlog(本轮评审记录,暂不动)

- 错过 L1 窗口(6 拍)且保底层全关 → 当天无兜底:考虑设置页在用户关光所有触发层时给一句事实提醒(不做强制)。
- `_attempt_login` 重试节奏 api.py / ensure.py 两份实现:抽到 core 单一来源。
- WebView2 缺失安装器只提示不代装(`setup.iss:68`):评估内置 bootstrapper 离线包的体积代价。
- 卸载 `--clear-creds` 不清 guigui:// 协议注册表项。
- `notify.register_protocol` dev 分支用 `sys.executable` 可能闪控制台黑框。

---

## 需用户配合的实测项(校园网环境)

1. **waitsec 节流 msga**:连续快速登录(注销→立即登录循环)触发节流,记录 `guigui.log` 里完整 msga 原文(字段名、含不含 error 标记、秒数格式)→ 喂给 P1-6。
2. **bind 解绑补测**(历史遗留,业务重梳理备忘):测试账号 bind error 解绑后补测三态闭环。

## 新发现(执行时若遇到,记录于此,不顺手修)

- (2026-09-07 P0 执行中)rebuildTask 在 master 关 + 删任务失败时弹的是 `task_blocked()`(创建被拦文案),语义错位 — 应弹 task_linger;P0-3 修的是 `_reconcile_and_report` 共用路径(masterToggle/login/saveConfig),rebuildTask 自带 reconcile 未走共用函数,待下一轮收口。
- (2026-09-07 P0 执行中)master 开 + 首装未完成时,`schedule:changed` 仍推 `task_ok:true`(守卫跳过建任务,但事件声称在岗;taskStatus() 查询则如实 false)— 瞬态不一致,前端任务行下次刷新自愈;要修需引入第三态,涉及契约,暂记。
