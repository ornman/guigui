# -*- coding: utf-8 -*-
"""walkthrough-5 分支动态验证(临时脚本,不提交):
T1: 设置页 7 个 .sw 开关均为 button,Tab 可聚焦、Enter 触发(含 .on 状态视觉:轨道背景色非透明)
T4: formDirty 修正 —
  4a: daily(老用户)→ openDetail('v-form') 学号被预填 → unreachable → 应调起 v-status
  4b: 填密码 → unreachable → 留 v-form(豁免仍工作)
  4c: 首装空表单(无预填)键入学号 → unreachable → 留页(用户真键入豁免)
"""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright

CHROME = r"C:\Users\ASUS\AppData\Local\ms-playwright\ms-playwright\chromium-1223\chrome-win64\chrome.exe"
BASE = "http://127.0.0.1:8767/index.html?dev=1&scene="
results = []

def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (" | " + detail if detail else ""))

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME, headless=True)

    # ── T1:设置页开关 button 化 + Tab/Enter ──────────────────────────
    pg = browser.new_page()
    pg.goto(BASE + "daily", wait_until="networkidle")
    pg.evaluate("openDetail('v-settings')")
    pg.wait_for_timeout(300)
    sws = pg.evaluate("""() => [...document.querySelectorAll('#v-settings .sw')].map(el => ({
        tag: el.tagName, type: el.getAttribute('type'), id: el.id || '', cfg: el.dataset.cfg || ''
    }))""")
    check("T1-1 设置页 .sw 共 7 个", len(sws) == 7, json.dumps(sws, ensure_ascii=False))
    check("T1-2 全部为 <button type=button>", all(s['tag'] == 'BUTTON' and s['type'] == 'button' for s in sws))
    # Tab 遍历:从返回键开始 Tab 应能逐一到达 7 开关;Enter 触发 toggleCfg
    first = pg.query_selector('#v-settings .sw')
    first.focus()
    tag_focused = pg.evaluate("document.activeElement.tagName")
    check("T1-3 开关可编程聚焦", tag_focused == 'BUTTON')
    # Enter 触发:boot_login 初始 on(daily 场景 config),Enter 后应翻为 off
    sw_boot = pg.query_selector('[data-cfg="boot_login"]')
    before = pg.evaluate("document.querySelector('[data-cfg=\\'boot_login\\']').classList.contains('on')")
    sw_boot.focus()
    pg.keyboard.press("Enter")
    after = pg.evaluate("document.querySelector('[data-cfg=\\'boot_login\\']').classList.contains('on')")
    check("T1-4 Enter 触发 toggleCfg(class 翻转)", before is True and after is False, "on=%s -> on=%s" % (before, after))
    # 轨道背景非透明(按钮化后轨道没丢)
    bg = pg.evaluate("""getComputedStyle(document.querySelector('[data-cfg=\\'wake_login\\']')).backgroundColor""")
    check("T1-5 关态轨道背景非透明", bg not in ("rgba(0, 0, 0, 0)", "transparent"), bg)
    bgon = pg.evaluate("""(() => {
        const el = document.querySelector('[data-cfg=\\'vacation_silence\\']'); // 初始 on
        return getComputedStyle(el).backgroundColor})()""")
    check("T1-6 开态轨道背景为强调色(oklch 计算值)", bgon == "oklch(0.58 0.15 295)", bgon)
    # 尺寸不变形
    box = pg.evaluate("""(() => {const r = document.querySelector('[data-cfg=\\'wake_login\\']').getBoundingClientRect();
        return [r.width, r.height]})()""")
    check("T1-7 开关几何 38x22 不变形", abs(box[0]-38) < 1.5 and abs(box[1]-22) < 1.5, str(box))
    # Tab 自然遍历:从返回键起连按 Tab,7 个开关应全部逐一获得焦点(中间可能穿过其他控件)
    pg.evaluate("document.querySelector('#v-settings .back').focus()")
    seen, guard = set(), 0
    while len(seen) < 7 and guard < 60:
        pg.keyboard.press("Tab")
        got = pg.evaluate("(() => {const a = document.activeElement;"
                          "return a && a.classList.contains('sw') ? (a.dataset.cfg || a.id) : null})()")
        if got: seen.add(got)
        guard += 1
    check("T1-8 Tab 自然遍历覆盖全部 7 开关", len(seen) == 7, "seen=%s tabs=%d" % (sorted(seen), guard))
    pg.close()

    # ── T4a:预填学号不算键入 → unreachable 调起 v-status ─────────────
    pg = browser.new_page()
    pg.goto(BASE + "daily", wait_until="networkidle")
    pg.wait_for_timeout(1500)   # 等 firstRun 仪式分流进 v-main
    pg.evaluate("openDetail('v-form')")
    pg.wait_for_timeout(600)    # 等 identify 预填
    sid = pg.evaluate("$('f-sid').value")
    check("T4-1 学号被 identify 自动预填", sid != "", repr(sid))
    dirty = pg.evaluate("formDirty()")
    check("T4-2 仅预填时 formDirty()=false", dirty is False, "formDirty=%s" % dirty)
    pg.evaluate("GGMock._setNet('unreachable')")
    pg.wait_for_timeout(600)
    cur = pg.evaluate("currentView()")
    check("T4-3 预填态 unreachable → 调起 v-status", cur == 'v-status', cur)
    pg.close()

    # ── T4b:填密码(真键入)→ unreachable 留 v-form ───────────────────
    pg = browser.new_page()
    pg.goto(BASE + "daily", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    pg.evaluate("openDetail('v-form')")
    pg.wait_for_timeout(600)
    pg.fill("#f-pwd", "user-typed-secret")
    dirty = pg.evaluate("formDirty()")
    check("T4-4 键入密码后 formDirty()=true", dirty is True)
    pg.evaluate("GGMock._setNet('unreachable')")
    pg.wait_for_timeout(600)
    cur = pg.evaluate("currentView()")
    check("T4-5 键入密码 unreachable → 留 v-form(豁免工作)", cur == 'v-form', cur)
    bar = pg.evaluate("$('form-status-bar').className")
    check("T4-6 状态行就地转 danger", 'danger' in bar, bar)
    pg.close()

    # ── T4c:用户改学号(≠预填)也算键入;手动清空学号算键入 ──────────
    pg = browser.new_page()
    pg.goto(BASE + "daily", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    pg.evaluate("openDetail('v-form')")
    pg.wait_for_timeout(600)
    pre = pg.evaluate("S.formPrefill.sid")
    pg.fill("#f-sid", "999999999")
    d1 = pg.evaluate("formDirty()")
    pg.fill("#f-sid", "")
    d2 = pg.evaluate("formDirty()")
    check("T4-7 改学号→dirty / 清空→dirty", d1 is True and d2 is True,
          "prefill=%r changed=%s cleared=%s" % (pre, d1, d2))
    pg.evaluate("GGMock._setNet('unreachable')")
    pg.wait_for_timeout(600)
    cur = pg.evaluate("currentView()")
    check("T4-8 清空学号(动过)unreachable → 留 v-form", cur == 'v-form', cur)
    pg.close()

    # ── T4d(回归):首装空表单、无预填、纯键入学号 → unreachable 留页 ──
    pg = browser.new_page()
    pg.goto(BASE + "ok", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    pg.evaluate("goSetup()") if False else None
    # ok 场景会走首装;直接开 v-form(login 语境)不触发预填的场景不易构造,
    # 用 daily 但抢在 identify 回填前手动填学号 → 基准为空 → 全部内容算键入
    pg.evaluate("openDetail('v-form'); $('f-sid').value='777777';")
    pg.wait_for_timeout(600)  # identify 回来但字段非空,不再预填、基准保持 ''
    base = pg.evaluate("S.formPrefill.sid")
    dirty = pg.evaluate("formDirty()")
    check("T4-9 抢先键入时基准为空、内容算键入", base == "" and dirty is True,
          "base=%r dirty=%s" % (base, dirty))
    pg.close()

    browser.close()

fails = [r for r in results if not r[1]]
print("\n== %d/%d PASS ==" % (len(results)-len(fails), len(results)))
sys.exit(1 if fails else 0)
