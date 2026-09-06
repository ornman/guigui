# 桂桂 · PRD 业务重梳理实施计划(2026-09-06 晚)

> 依据:PRD af19e1b(验证阶梯 4.1.2 / 开门锚点 06:50 / 通知当拍即弹 / 横幅纪律两态 /
> 改凭据闭环 / AC-11~19)+ flows/ 三图。已落地的部分(阶梯骨架 6770249、运营商四项
> e97a4b2、verified 地基 d569e86)不在本计划内;本文只列**重梳理新增行为的差距**。

## 纪律

- 全桩测试,零真实网络(学校侧风控未知);测试随行为改写——PRD 推翻的旧行为
  (连败×3 通知、rejected 一刀切清 verified)连测试一起换代。
- 契约改动 bump 1.1.1 → 1.2.0 并登记变更记录(契约 §0 铁规);mock.js 是可执行规范,同步。
- 前端只改 `static/index.html` 内联脚本 + `app-overrides` 之内允许的 CSS;
  bot/字体/视图结构不动。逐模块 git 提交。

## 差距与落法

### B1 拒绝三态分类(AC-19)→ drcom.py
- 新纯函数 `classify_rejection(msg)` → `wrong_password|wrong_account|bound|None`
  (子串判定:`bind userid error`→bound;`userid error2`→wrong_password;
  `userid error1`→wrong_account;其余 None=不认识,原文展示不猜)。
- 三态人话文案单一来源(后端拼好,前端直显):
  error1=「学号或运营商选错了,核对一下」;error2=「密码不对,改一下再试」;
  bind=「密码是对的,但这个账号被绑在别处/受限 — 去自助服务平台看看绑定」。

### B2 06:50 开门锚点(AC-12)→ ensure.py
- 常量 `ANCHOR_TIME="06:50"`(校园实测,非用户配置)。
- 锚前(now < 06:50 当日时钟)被拒/不可达:只记一行日志「还没开门,等下一拍」;
  不计数、不通知、不动 cred_verified、last_result 不写 fail。

### B3 通知决策换代(AC-13 + 4.5)→ notify.py + ensure.py
- `decide_notify` 重写为 PRD 4.5 语义的纯函数:
  - 开门后**明确被拒**(error1/2/bind 任一)→ **当拍即弹**,每日 ≤1 次
    (状态键 `fail_notify_date`);toast 文案按 PRD 原文「登录失败,密码改了?」→ guigui://creds。
  - 维护页(格式不认识)→ 连续 ≥3 拍才弹「桂桂一直登不上,点开看看」→ guigui://main,
    每日 ≤1 次(`maintenance_streak`/`maintenance_notify_date`)。
  - 断→通每日 1 次(保留 v1 语义)。
  - 锚前一切失败/不可达 → 永不通知。
- 旧 `consecutive_fail>=3` 模型与 `fail_notify_sent` 退役。

### B4 凭证可信度语义(§7.3)→ ensure.py
- 置假仅一条路:error2(wrong_password)。error1/bind/维护页/锚前/不可达 → 保持不变。
- 置真不变:真登成功(tries>0)。

### B5 线上他人学号如实记录(§4.6)→ ensure.py + api.py
- ensure 收工(tries=0)时 chkstatus 抓线上真实学号:是本人 → 现行收工行;
  是他人 → 追加一行「线上的是 …(不是配置学号)」,照常收工,不横幅不通知。
- api 阶梯注销前查 chkstatus:线上非本人 → `login:progress` 事件
  `{phase:"logging_out", online_uid:"6503…21"}`,前端等待行如实注明
  「现在线上的是 …,验证时会先注销它」(4.1.2 原文)。

### B6 假期静默同日早退(AC-10)→ ensure.py
- `silent=True` 且 `last_unreachable_date==today` → run() 进门即退,
  零探测请求(每天只探 1 次的字面兑现)。

### B7 日志 >90 天清理(AC-18)→ logstore.py
- `cleanup_old(keep_days=90)`:删 logs/ 下文件名日期早于阈值的 .jsonl,只动桂桂目录。
- 接线:ensure.run() 每拍顺带(静默早退分支除外)。

### B8 任务在岗可见(AC-17)→ api.py + 契约 + 前端
- 契约 1.2.0:`taskStatus()` → `{ok: bool}`(主任务在岗=存在+rev匹配+目标存在);
  `rebuildTask()` → 用户点击触发 reconcile 后回 `{ok, changed}`(仅点击重建,8.5.2);
  `schedule:changed` 载荷扩 `task_ok`(契约 §6 预留票兑现)。
- 前端设置页系统组加两行:「账号与密码」→ v-login(改密闭环入口,AC-14);
  「定时任务」→ 在岗 ✓ / 被拦,点此重建。

### B9 锚前提交存未验证(§4.1.2)→ api.py
- 提交新密码被拒且 now<06:50:不判密码错误,存 verified=False,
  回 `{result:"stored", verified:false, reason:"before_open"}`,前端走成功页但无庆祝粒子,
  lede=「还没到开门时间(06:50),密码先存着,明早第一次自动登录会真验证」。

### F1 按钮等待态(AC-11)→ index.html
- `setBusy(btn,on,text)` 通用件:置灰禁用 + CSS 旋转图标 + 文案「验证中…」;
  应用到 v-ok「开启每日自动登录」/ v-login「立即登录」/ v-main「立即重新登录」。
  等待期间提交行上方 micro-line 如实播报(验证中/正在注销当前会话,断几秒/他人学号注明)。

### F2 拒绝三态内联文案(AC-19)→ index.html
- AUTH_REJECTED 信封带 `reason`;v-ok 用 pwd-warn、v-login 用 login-err 按三态渲染;
  reason 缺省时显示后端 message 原文(不猜)。

### F3 横幅纪律两态(AC-15)→ index.html + 契约
- 契约 1.2.0:`recentResult` 响应扩 `verified: bool`。
- 主页两条横幅(其余永无):①`configured && !verified` →「密码还没验证过 — 去改一下」;
  ②`outcome==='fail' && when==='今早'` →「今早没登上 — 去改一下」。点击直达 v-login;
  改对(真登成功→verified)即消失。log:appended 事件触发 recentResult 重拉。

### F4 主按钮三态修复(AC-16)→ index.html
- `#main-btn` onclick 由写死的 quickLogin() 改为 mainAction()(函数早已存在未接线);
  三态文案与行为一一对应,不可达态不再误发登录。

### F5 改凭据闭环(AC-14)→ index.html
- v-login 学号回填现状可用;提交走同一阶梯(后端已具);换学号时(A≠B)提交前
  内联确认「学号将从 A 改为 B,密码会迁移到新学号」(防手滑,二次点击才提交)。

### T 测试
- test_drcom:classify_rejection 四态 + 三态文案来源。
- test_ensure:锚前被拒(06:30)三不管;锚后被拒当拍即弹+每日一次;error2 清 verified、
  bind/error1 不清;维护 ≥3 拍弹 main;他人学号收工行;静默同日早退(零探测);
  日志清理。
- test_notify:decide_notify 新签名全分支。
- test_api:三态 reason、before_open 存未验证、taskStatus/rebuildTask、
  recentResult.verified、logging_out 事件。
- mock.js 同步新方法/字段;全量回归。

## 实施顺序

B1 → B3+B2+B4+B5+B6(ensure/notify 一次改齐)→ B7 → B8+B9(api+契约)→
F1~F5(前端)→ mock 同步 → 测试换代 → 全量回归。

## 完成销项(2026-09-06 晚,全部落地)

| 块 | 提交 | 状态 |
|---|---|---|
| 计划 | dea910c | ✓ |
| B1~B9 后端(drcom/ensure/notify/logstore/api)+ 测试换代 169→190 | 5a018c8 | ✓ 全绿 |
| 契约 1.2.0 + mock(bind/other/unverified 场景) | 42a19da | ✓ |
| F1~F5 前端(等待态/三态/横幅/主按钮/改密闭环/设置两行) | 96018ad | ✓ |

- AC 覆盖:AC-10(静默同日零探测)/AC-11(等待态+庆祝只给真成功)/AC-12(锚点三不管)/
  AC-13(当拍即弹每日1)/AC-14(改密闭环+换学号确认)/AC-15(横幅两态)/AC-16(mainAction
  接线,out=一键)/AC-17(taskStatus+rebuildTask+设置行)/AC-18(cleanup_old)/AC-19(三态
  reason+文案源)。AC-20 已由 e97a4b2 親先落地。
- 实施中的裁量:锚前被拒**单发收手**(_attempt_login 提前 break,绝不暴力尝试);
  维护通知每日≤1(PRD 未定上限,按防刷屏原则);横幅两态可同时出现(各自独立事实);
  他人学号收工仍照常收工(4.6 只记录不打扰);庆典彩带仅 verified===true 时撒。
- 待真机验证:AC-12 锚点窗口期行为(明早 06:30~06:50 测试床可测);
  bind 账号解绑后跑一遍首装阶梯(scene=other 已可在 dev 预演)。
