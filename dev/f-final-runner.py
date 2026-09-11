"""
F 章动态验收 runner(2026-09-11)
- F-② mock 20 scene 全场景回归
- F-②a net:state 四态 × 主要视图 ROUTE 路由格走查(与矩阵 §2 逐格对应)
- F-④ AC-1 (flash 4s 后回基线) + AC-2 (NOT_CONFIGURED 双击 login 调用 = 1) 数据化复测

用法:python dev/f-final-runner.py
前置:python -m http.server 8765 --directory guigui/app/static 已在跑

── 2026-09-11 修正记录(路由格走查方法学)────────────────────────────────
初版 runner 的路由格有两处方法错误,导致 6 格假失败:
  ① 先切源视图、再落 from 网态 —— 但「落 from 网态」本身就是一次真事件,
     configured 用户会被 hubRaise 当场调起到 v-status,于是待测的 to 事件
     其实是在 v-status 上收的,测的根本不是声明的那一格。
     修正:先落 from 网态 → 等路由走完 → 再手动导航回源视图 → 才发 to 事件。
  ② 页面全程不重载,S.hubRaised / origin 栈跨格泄漏。
     修正:每格重新 goto 场景(干净 S),且 from 网态显式决定 hubRaised 前置。
另外两处期望值校正(实现对、期望错):
  ③ 「同态 unreachable→unreachable」测的是**去重拦下**(hubRaised 已是 wait),
     矩阵 §2 明写「调起被拦 ≠ 丢事件:主页就地重渲,横幅⑧ 保留手动入口」,
     故期望=留在原视图;要测「首次调起」必须让 hubRaised 为空,即 from=logged_in。
  ④ v-guide + not_logged_in 期望原为 v-guide,与矩阵「reProbe → configured ?
     状态页 : v-form」不符;初版「通过」是采样窗口(900ms)短于
     550ms 延时 + mock probe 650~1100ms 的假绿。修正:期望 v-status,采样窗放宽。
"""
import json, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765/index.html"
DEV = "?dev=1"
CHROMIUM = r"C:\Users\ASUS\AppData\Local\ms-playwright\ms-playwright\chromium-1223\chrome-win64\chrome.exe"
EVIDENCE = Path("dev/f-final")
EVIDENCE.mkdir(parents=True, exist_ok=True)

# ── 20 个 mock 场景 + 期望落点(按 mock 头注 + 矩阵 §3 + 拍板⑪ + P1-15 启动分诊校正) ──
SCENES = [
    # (scene, 期望初始视图, 备注)
    # ── 首装未配置 ──
    ("ok",         "v-form",      "首装已连已登 → v-form firstRun"),
    ("out",        "v-form",      "首装连上未认证 → v-form login"),
    ("down",       "v-guide",     "首装不可达 → v-guide"),
    ("rejected",   "v-form",      "首装被拒 → v-form login"),
    ("bind",       "v-form",      "bind 被拒 → v-form login(警告块)"),
    ("limit",      "v-form",      "limit_users 被拒 → v-form login"),
    ("throttled",  "v-form",      "节流 → v-form note"),
    ("blocked",    "v-form",      "首装·定时任务被拦(配置前) → firstRun 落地,提交后才拦截"),
    ("fbdg",       "v-form",      "反馈降级场景 → firstRun"),
    # ── 老用户 configured ──
    ("waiting",    "v-status",    "P0-3 压平≡unreachable + 拍板⑪ 老用户系统调起状态页"),
    ("daily",      "v-main",      "日常正常 → v-main 两态①"),
    ("other",      "v-main",      "P0-6 线上他人(老用户) → 日常页(在线状态被 chkstatus 揭穿前一切正常)"),
    ("ladder_back","v-main",      "阶梯回滚(老用户) → 日常页"),
    ("ladder_fail","v-form",      "阶梯翻车(首装配置前) → v-form(因 mock 默认 configured=false)"),
    ("beforeopen", "v-status",    "锚前存入:configured+not_logged_in → 状态页 drop"),
    ("diag_ok",    "v-main",      "diag 入口:configured+logged_in → 日常"),
    ("diag_cred",  "v-status",    "diag 入口:configured+not_logged_in → 状态页 drop"),
    ("diag_task",  "v-main",      "diag 入口:configured+logged_in+taskOk=false → 日常(横幅②在场)"),
    ("diag_app",   "v-main",      "diag 入口:configured+logged_in → 日常"),
    ("streak",     "v-status",    "日常重登连败:configured+wrong_password → 启动分诊 contra"),
    ("unverified", "v-status",    "未验证+今早失败 → 启动分诊 contra"),
]

# 视图 id 列表(主视图)
VIEWS = ["v-boot","v-form","v-success","v-status","v-guide","v-main","v-log","v-settings","v-feedback","v-diag"]

# ── ROUTE 路由格走查表(矩阵 §2 逐格)──
# (源视图, 前置网态 from, 待测事件 to, 期望落点, form 预置, 备注)
#   form 预置:'clear'=清空表单(空表单格)/ 'dirty'=键入学号(A3 豁免格)/ None=不动
#   前置网态 from 同时决定 hubRaised 前置:
#     logged_in   → hubRaised=null(测「首次调起」)
#     unreachable → hubRaised='wait'(测「同问题去重拦下」)
#     not_logged_in → hubRaised='drop'
ROUTE_GRID = [
    # ── v-main 行(矩阵 §2:调起 / 去重拦下就地重渲 / logged_in 清旗)──
    ("v-main","logged_in","logged_in","v-main",None,        "MAIN_NET 原地重渲"),
    ("v-main","unreachable","unreachable","v-main",None,    "同问题去重拦下 → 就地重渲(P1-13 两态 + 横幅⑧)"),
    ("v-main","unreachable","logged_in","v-main",None,      "网恢复 → 清 hubRaised,横幅⑧随消,留页"),
    ("v-main","unreachable","not_logged_in","v-status",None,"换问题(wait→drop)照弹 → 调起状态页"),
    # ── v-guide 行(未配置落点;configured 在此页 wait 不抢,恢复走 reProbe 漏斗)──
    ("v-guide","unreachable","unreachable","v-guide",None,  "等网落点:重复不可达留页"),
    ("v-guide","unreachable","logged_in","v-main",None,     "guideDaily:550ms 后回日常"),
    ("v-guide","unreachable","not_logged_in","v-status",None,"guideReprobe → reProbe → configured → 状态页 drop(P0-7)"),
    # ── v-form 行(A3 formDirty 豁免 / 空表单 configured → 调起)──
    ("v-form","logged_in","unreachable","v-status","clear", "空表单 + configured → HUB_WAIT 首次调起"),
    ("v-form","unreachable","unreachable","v-form","clear", "空表单但同问题已调起 → 去重拦下留页"),
    ("v-form","logged_in","unreachable","v-form","dirty",   "A3 拍板④:已键入不被拽走"),
    ("v-form","unreachable","logged_in","v-form","clear",   "FORM_NET:状态行就地刷新,留页"),
    # ── v-status 行(在页迁移)──
    ("v-status","unreachable","not_logged_in","v-status",None,"statusNetMood:wait→drop 就地换境"),
    ("v-status","not_logged_in","logged_in","v-main",None,  "statusResolved:清旗回日常"),
    # ── 「其他」行(v-success / v-log / v-feedback / v-settings / v-diag)──
    ("v-success","logged_in","unreachable","v-status",None, "「其他」行:configured 断网 → 调起状态页(P0-7 含保存页)"),
    ("v-log","logged_in","unreachable","v-status",None,     "「其他」行:调起"),
    ("v-feedback","logged_in","unreachable","v-status",None,"「其他」行:调起"),
    ("v-settings","logged_in","unreachable","v-status",None,"「其他」行:调起"),
    ("v-diag","logged_in","unreachable","v-status",None,    "「其他」行:调起(体检在跑也照调)"),
]

results = {"scenes": [], "routes": [], "ac": {}}

def current_view(page):
    """返回当前 .v.on(可见)视图 id"""
    return page.evaluate("""()=>{
      const v=document.querySelector('.v.on');
      return v?v.id:null;
    }""")

def hub_state(page):
    return page.evaluate("()=>({hubRaised:S.hubRaised,mood:S.statusMood,net:(S.lastNet||{}).state,dirty:formDirty()})")

def goto(page, scene):
    """加载指定 scene 并等 probe/firstRun 流水线落点稳定(最长 6s)"""
    page.goto(f"{BASE}{DEV}&scene={scene}", wait_until="domcontentloaded")
    # 等到 v-boot 的 .on 状态消失才认 stable
    for _ in range(60):
        if page.evaluate("()=>{const b=document.getElementById('v-boot');return !b||!b.classList.contains('on')}"):
            break
        page.wait_for_timeout(100)
    page.wait_for_timeout(400)  # 额外缓冲让 hubRaise / renderBanners 收尾

def enter_view(page, view):
    """把当前会话导航到指定源视图(模拟用户手动进入);已在该页则不动。
       不重置 S —— hubRaised 由 from 网态决定,是路由格的前置条件之一。"""
    if current_view(page) == view:
        return
    if view == "v-main":
        page.evaluate("goDaily()")
        page.wait_for_timeout(500)
        return
    if view == "v-status":
        page.evaluate("enterStatus((S.lastNet||{}).state==='unreachable'?'wait':'drop')")
        page.wait_for_timeout(500)
        return
    # 详情视图统一从日常页进(openDetail 记来路,与真实用户路径一致)
    page.evaluate("goDaily()")
    page.wait_for_timeout(450)
    page.evaluate(f"openDetail('{view}')")
    page.wait_for_timeout(900)   # 250ms 转场 + loadLogs/identify 等进场异步

def main():
    print(">>> F 章动态验收开始", flush=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM, headless=True)
        ctx = browser.new_context(viewport={"width":1280,"height":820})
        page = ctx.new_page()

        # ─── F-② mock 20 场景回归 ───
        print("\n[F-②] mock 20 scene 全场景回归", flush=True)
        for scene, expect_view, note in SCENES:
            goto(page, scene)
            actual = current_view(page)
            ok = (actual == expect_view)
            results["scenes"].append({
                "scene": scene, "expect": expect_view, "actual": actual,
                "ok": ok, "note": note
            })
            mark = "✓" if ok else "✗"
            print(f"  {mark} scene={scene:12s} expect={expect_view:10s} actual={actual or 'NONE':10s} | {note}", flush=True)
            if not ok:
                page.screenshot(path=str(EVIDENCE / f"scene-{scene}.png"))

        # ─── F-②a ROUTE 路由格走查 ───
        print("\n[F-②a] net:state 路由格走查(每格独立重载 daily 场景,杜绝跨格泄漏)", flush=True)
        for src_view, from_state, to_state, expect_view, form_pre, note in ROUTE_GRID:
            # 1. 干净重载(daily:configured + logged_in + hubRaised=null)
            goto(page, "daily")
            # 2. 先落前置网态 —— 这一拍本身会按 ROUTE 走(configured 会被调起),
            #    它决定的是「格子的前置条件」(hubRaised / mainState),不是被测事件
            page.evaluate(f"GGMock._setNet('{from_state}','Campus-WiFi')")
            page.wait_for_timeout(1500)
            # 3. 手动导航回源视图(模拟用户从状态页「带横幅回日常」再点开详情)
            enter_view(page, src_view)
            # 4. 表单预置(空表单格 / A3 已键入格)
            if form_pre == "clear":
                page.evaluate("$('f-sid').value='';$('f-pwd').value=''")
            elif form_pre == "dirty":
                page.evaluate("$('f-sid').value='2025010203';$('f-pwd').value=''")
            pre = hub_state(page)
            pre_view = current_view(page)
            # 5. 发被测事件
            page.evaluate(f"GGMock._setNet('{to_state}','Campus-WiFi')")
            page.wait_for_timeout(2400)   # reProbe(550+probe 650~1100)+ 转场 250 的最坏情况
            actual = current_view(page)
            ok = (actual == expect_view and pre_view == src_view)
            results["routes"].append({
                "src": src_view, "from": from_state, "to": to_state,
                "expect": expect_view, "actual": actual, "ok": ok,
                "pre_view": pre_view, "pre_state": pre,
                "post_state": hub_state(page), "form_pre": form_pre, "note": note
            })
            mark = "✓" if ok else "✗"
            print(f"  {mark} {src_view:11s}[{form_pre or '-':5s}] {from_state:13s}→{to_state:13s} "
                  f"expect={expect_view:10s} actual={actual or 'NONE':10s} | {note}", flush=True)
            if not ok:
                page.screenshot(path=str(EVIDENCE / f"route-{src_view}-{from_state}-to-{to_state}-{form_pre or 'x'}.png"))

        # ─── F-④ AC-1 flash 4s 生命周期采样 ───
        # AC-1 语义(A1 反馈生命周期):主页瞬时反馈挂满 4s 不被基线回填吃掉,到期自动回基线。
        # 初版用 out 场景 + submitLadder 采样 —— 那条路落 v-success 终态页,
        # 根本不写 main-lede(首装链的成功归彩带页),故恒 0ms。
        # 修正:走 A1 真正的生效路径 —— daily(已配置已存密码)+ 网掉到 not_logged_in
        # → 回日常页 → quickLogin() 真成功 → flashMainLede('刚刚把网帮你接回来啦 ✓'),
        # 同时 mock 登录成功会推 net:state(logged_in) 触发 renderMain/renderMainData
        # 基线回填 —— 正是 A1 要挡住的那一下(实测 82ms 出现/162ms 被吞的回归点)。
        print("\n[F-④ AC-1] flash 生命周期(挂满 4s 不被基线吃 + 到期回基线)数据化复测", flush=True)
        goto(page, "daily")
        page.evaluate("GGMock._setNet('not_logged_in','Campus-WiFi')")
        page.wait_for_timeout(1500)          # 系统调起 v-status(drop)
        page.evaluate("goDaily()")           # 「带横幅回日常」
        page.wait_for_timeout(600)
        # 高精度记录:MutationObserver 抓 main-lede 每次文本变更的时刻
        page.evaluate("""()=>{
          window.__lede=[];
          const el=document.getElementById('main-lede');
          window.__t0=performance.now();
          window.__lede.push({t:0,text:el.textContent});
          new MutationObserver(()=>{
            window.__lede.push({t:Math.round(performance.now()-window.__t0),text:el.textContent});
          }).observe(el,{childList:true,characterData:true,subtree:true});
        }""")
        page.evaluate("quickLogin()")
        # 100ms 轮询做旁证(与 MutationObserver 互相印证)
        samples = []
        start = time.time()
        for _ in range(80):   # 8 秒
            text = page.evaluate("()=>{const e=document.getElementById('main-lede');return e?e.textContent:''}")
            samples.append({"t_ms": int((time.time()-start)*1000), "text": text})
            page.wait_for_timeout(100)
        mut = page.evaluate("window.__lede")
        FLASH = "刚刚把网帮你接回来啦 ✓"
        # flash 出现时刻 → 之后第一次变成别的文本的时刻 = 实际挂载时长
        appear = next((m["t"] for m in mut if m["text"] == FLASH), None)
        revert = None
        if appear is not None:
            revert = next((m["t"] for m in mut if m["t"] > appear and m["text"] != FLASH), None)
        duration = (revert - appear) if (appear is not None and revert is not None) else 0
        # 轮询旁证:flash 文本被采到的首末样本跨度
        poll_hits = [s["t_ms"] for s in samples if s["text"] == FLASH]
        poll_span = (max(poll_hits) - min(poll_hits)) if len(poll_hits) > 1 else 0
        eaten = (appear is not None and revert is not None and duration < 1000)   # A1 回归:被基线秒吞
        ac1_ok = (appear is not None and revert is not None
                  and 3950 <= duration <= 4600          # 4s ±(定时器抖动/渲染)
                  and samples[-1]["text"] != FLASH)     # 到期确实回了基线
        results["ac"]["AC-1"] = {
            "flash_text": FLASH,
            "appear_ms": appear, "revert_ms": revert,
            "duration_ms": duration,
            "poll_span_ms": poll_span,
            "baseline_after": samples[-1]["text"],
            "mutations": mut,
            "baseline_eaten": eaten,
            "ok": ac1_ok,
            "expect": "flash 挂满 4000ms(±,不被 renderMain/setAuto 基线回填吃掉)后自动回基线",
            "note": "路径:daily + net not_logged_in → 日常页 quickLogin 真成功 → flashMainLede"
        }
        print(f"  {'✓' if ac1_ok else '✗'} flash 挂载 {duration}ms(出现 {appear}ms → 回基线 {revert}ms;"
              f"轮询旁证跨度 {poll_span}ms;到期基线='{samples[-1]['text']}')", flush=True)
        if not ac1_ok:
            page.screenshot(path=str(EVIDENCE / "ac1-flash.png"))

        # ─── F-④ AC-2 NOT_CONFIGURED 双击 login 调用计数 ───
        # 场景:out(未配置、库里无密码)→ 主页 quickLogin 走 login({}) → NOT_CONFIGURED。
        # 双击主页唯一动作按钮,setBusy 防重应只放行一次 login 调用。
        print("\n[F-④ AC-2] NOT_CONFIGURED 双击 login 调用计数", flush=True)
        page.evaluate("localStorage.clear()")
        goto(page, "out")
        page.evaluate("GGMock._setNet('not_logged_in','Campus-WiFi')")
        page.wait_for_timeout(600)
        page.evaluate("openDetail('v-main')")   # 首装场景手动切主页,模拟日常重登入口
        page.wait_for_timeout(500)
        page.evaluate("""
          window.__loginCount = 0;
          const orig = window.GG.api.login;
          window.GG.api.login = function(...args){ window.__loginCount++; return orig.apply(this, args); };
        """)
        page.evaluate("quickLogin(); quickLogin();")   # 同一拍双击
        page.wait_for_timeout(1200)
        count = page.evaluate("window.__loginCount")
        ac2_ok = (count == 1)
        results["ac"]["AC-2"] = {
            "login_calls_after_double_click": count,
            "ok": ac2_ok,
            "expect": "1",
            "note": "NOT_CONFIGURED 场景双击 quickLogin,setBusy 防重(期望=1)"
        }
        print(f"  {'✓' if ac2_ok else '✗'} 双击 quickLogin login 调用 {count} 次 (期望=1)", flush=True)

        browser.close()

    # ── 汇总 ──
    scene_pass = sum(1 for s in results["scenes"] if s["ok"])
    route_pass = sum(1 for r in results["routes"] if r["ok"])
    ac_pass = sum(1 for v in results["ac"].values() if v["ok"])
    print(f"\n{'='*70}\n汇总: scene {scene_pass}/{len(results['scenes'])}, "
          f"route {route_pass}/{len(results['routes'])}, AC {ac_pass}/{len(results['ac'])}\n{'='*70}", flush=True)
    (EVIDENCE / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n证据目录: {EVIDENCE}/", flush=True)
    print(f"详细结果: {EVIDENCE}/results.json", flush=True)
    sys.exit(0 if (scene_pass==len(results["scenes"]) and route_pass==len(results["routes"]) and ac_pass==len(results["ac"])) else 1)

if __name__ == "__main__":
    main()
