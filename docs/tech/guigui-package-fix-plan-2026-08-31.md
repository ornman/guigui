# 桂桂打包产物审计修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 2026-08-31 打包产物审计的 P1×1 + P2×3 + 顺手 P3×2(报告见 `docs/tech/guigui-package-audit-2026-08-31.md`)。

**Architecture:** 全部为后端/壳层修复,前端零改动(深链热路径复用既有全局 `applyLaunch()`)。安装器只加一行 `AppMutex`;api.py 抽出 `_align_saved` 统一三个调用点的「已配置守卫」;深链二实例走 pending 文件 + 既有 FileWatcher 2s 轮询;凭据清理改枚举式全删(ctypes `CredEnumerateW`,可注入桩测试)。

**Tech Stack:** Python 3.12 / pywebview 6.2.1 / keyring 25.7.0 / pytest / Inno Setup 6。测试环境即 Windows 实机(conftest 已用 `GUIGUI_DATA_DIR` 隔离数据目录)。

**背景速览(给零上下树的工程师):**

- 桂桂 = 校园网自动登录工具;`guigui.exe` 双模式:GUI(pywebview 无边框窗)与 `--ensure`(计划任务触发的静默短进程)。
- 计划任务 GuiGui/GuiGui-Patrol 由 `selfheal.reconcile(cfg)` 幂等对齐(存在性 + rev + Action 目标)。
- 首装流程(前端 `enableDaily`,index.html:826):先 `saveConfig({trigger_time})` 后 `login({sid,password})`。login 存完凭据之前 uid 为空。
- 契约纪律:密码只进 keyring(`vault.py`,服务名 `GuiGui`,凭据管理器目标名 `学号@GuiGui`);API/日志/诊断全打码。
- 单实例锁:命名互斥量 `Local\GuiGui-GUI`(`app/instance.py`)。

---

### Task 1: P1 — setup.iss 加 AppMutex(GUI 运行中禁止安装/卸载)

**Files:**
- Modify: `guigui/setup.iss`([Setup] 段,插在 `PrivilegesRequired=lowest` 之后)

- [ ] **Step 1: 加 AppMutex 行**

在 `guigui/setup.iss` 第 22 行 `PrivilegesRequired=lowest` 之后插入(保持其余不动):

```ini
; GUI 正在跑时,安装/卸载先提示关闭桂桂(互斥量定义见 app/instance.py;
; 不加则 exe 被占用,卸载残留文件、升级报「文件被使用」)
AppMutex=Local\GuiGui-GUI
```

说明:Inno 对 AppMutex 里的名字做 OpenMutex 探测,`Local\GuiGui-GUI` 与
`app/instance.py:16` 的 `_MUTEX_NAME` 逐字一致(含 `Local\` 前缀)。该指令
同时约束安装器与卸载器。功能验证在 Task 7 实机清单第 2 项。

- [ ] **Step 2: Commit**

```bash
git add guigui/setup.iss
git commit -m "fix(install): AppMutex=Local\\GuiGui-GUI — GUI 运行中安装/卸载先提示关闭,不再撞 exe 文件锁(审计 P1)"
```

---

### Task 2: P2-2 — 任务对齐加「已配置」守卫(saveConfig/login/masterToggle 三处统一)

**Files:**
- Modify: `guigui/app/api.py`(saveConfig 约 209-236 行、login 约 103-162 行、masterToggle 约 240-254 行)
- Test: `guigui/tests/test_api.py`(文件头部 imports + 文件尾部追加测试)

背景:e247c7c 只给 GUI 启动对齐(`gui.py:_reconcile_on_start`)加了
「uid+密码齐才建任务」守卫,api 侧漏了。首装表单一改时间就在用户还没
交密码时建出任务;同时必须补上反面:login 存完凭据后要触发首次对齐,
否则加了守卫后首装将永远建不出任务(第二天不自动登录)。

- [ ] **Step 1: 写失败测试**

`guigui/tests/test_api.py` 头部 imports 区(第 3 行 `import json` 之后)加:

```python
import time
```

文件末尾追加:

```python
# ── 任务对齐守卫:首装未完成不建任务;login 存凭据后首建 ──────


def _wait_for(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_save_config_unconfigured_skips_task_creation(monkeypatch):
    c = Ctx(monkeypatch, cfg_over={"uid": ""})
    out = c.api.saveConfig({"trigger_time": "06:45"})
    assert out["ok"] is True
    # schedule:changed 无条件推(对齐函数已跑完),此刻 reconcile 应未被调
    assert _wait_for(
        any(t == "schedule:changed" for t, _ in parse_emitted(c.window)))
    assert c.reconciled == []


def test_login_with_password_triggers_alignment(ctx):
    ctx.probe_state = {"state": "not_logged_in", "ssid": "x", "detail": ""}
    ctx.login_seq = [("success", "")]
    out = ctx.api.login({"sid": "2025000000001", "password": "pw"})
    assert out["ok"] is True
    assert _wait_for(lambda: ctx.reconciled == [True])


def test_master_toggle_unconfigured_skips_create(monkeypatch):
    c = Ctx(monkeypatch, cfg_over={"uid": ""})
    out = c.api.masterToggle(True)
    assert out["ok"] is True and out["data"]["master"] is True
    assert c.reconciled == []
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd C:/Users/ASUS/auto-login && .venv-guigui/Scripts/python.exe -m pytest guigui/tests/test_api.py -q
```

Expected: `test_save_config_unconfigured_skips_task_creation` FAIL
(`ctx.reconciled == [True]`,守卫不存在);`test_login_with_password_triggers_alignment`
PASS(现状 login 不对齐,但该测试此刻碰巧通过是因为无守卫时 saveConfig
不对——注意此测试在 Step 3 实现后必须仍 PASS,若现在也 FAIL 属正常,
记录实际输出即可);`test_master_toggle_unconfigured_skips_create` FAIL。

- [ ] **Step 3: 实现 `_align_saved` 并重接三个调用点**

`guigui/app/api.py` — 在 `attach_window` 方法之后、`# ── 事件` 注释之前,
插入新方法:

```python
    def _align_saved(self, saved: dict) -> None:
        """后台对齐任务计划(saveConfig / login 共用)。

        守卫:首装未完成(uid 空或密码未存)时不建任务 —— 任务属于
        「开启每日自动登录」那一步,由 login 存完凭据后首次对齐;
        master 关 → 删任务不受守卫影响。"""
        misaligned = False
        try:
            if saved.get("master", True) and not (
                    saved.get("uid") and vault.has_password(saved["uid"])):
                log.info("api: 首装未完成,暂不建任务(等 login 存凭据后再对齐)")
            else:
                _, misaligned = selfheal.reconcile(saved)
        except Exception:
            log.exception("api: selfheal 对齐失败")
            misaligned = bool(saved.get("master", True))
        if misaligned and saved.get("master", True):
            notify.task_blocked()
        self._emit("schedule:changed",
                   {"master": saved["master"], "trigger_time": saved["trigger_time"]})
```

`saveConfig` 内:把原来的 `def _align(): ...` 整块(约 224-235 行)与
`threading.Thread(target=_align, daemon=True).start()` 替换为:

```python
        threading.Thread(target=lambda: self._align_saved(saved),
                         daemon=True, name="guigui-align").start()
```

`login` 内:密码分支的 `cfg = config.save({**cfg, "uid": uid})` 之后
(仍在该分支内)插入:

```python
                # 首次存好凭据 = 「开启每日自动登录」落地,任务此刻才属于
                # 用户(首装单行道终点);reconcile 幂等,已配置时零成本。
                threading.Thread(target=lambda: self._align_saved(cfg),
                                 daemon=True, name="guigui-align").start()
```

`masterToggle` 内:把 `# 语义重(建/删任务):同步做完再回话` 之后的
`_, misaligned = selfheal.reconcile(saved)` 替换为:

```python
            if value and not (saved.get("uid") and vault.has_password(saved["uid"])):
                misaligned = False   # 首装未完成不建任务(与 _align_saved 同口径)
            else:
                _, misaligned = selfheal.reconcile(saved)
```

- [ ] **Step 4: 跑测试确认通过(含全量回归)**

```bash
cd C:/Users/ASUS/auto-login && .venv-guigui/Scripts/python.exe -m pytest guigui/tests -q
```

Expected: 全部 PASS(原 125 + 新 3 = 128)。

- [ ] **Step 5: Commit**

```bash
git add guigui/app/api.py guigui/tests/test_api.py
git commit -m "fix(api): 任务对齐三处统一加已配置守卫 — saveConfig/masterToggle 未配置不建任务,login 存完凭据后台首建;首装单行道口径与启动对齐一致(审计 P2-2)"
```

---

### Task 3: P2-1 — 深链二实例转发(pending 文件 + 激活旧窗口,前端零改动)

**Files:**
- Modify: `guigui/app/api.py`(`_emit` 重构出 `_eval`)
- Modify: `guigui/app/gui.py`(常量、`_forward_deep_link`/`_activate_existing_window`、FileWatcher 消费、run() 接线)
- Test: `guigui/tests/test_gui.py`(新建)

关键事实(已核实):index.html 内联脚本非 IIFE,`applyLaunch` 是全局函数,
`window.__guigui_launch='creds';applyLaunch()` 可直接经 evaluate_js 走
与冷启动完全相同的导航;app.js 的 `window.guiguiEmit` 不经手此路径。
故本任务**不改任何前端文件**。

- [ ] **Step 1: 写失败测试(新文件 `guigui/tests/test_gui.py`)**

```python
"""gui:深链转发落盘 + FileWatcher pending 消费(纯文件/JS 层)。

窗口激活(_activate_existing_window)是 Win32 实操,不入单测,
由 Task 7 实机清单第 3 项覆盖。"""

import json
import time

from guigui.app import gui as gui_mod
from guigui.app.gui import FileWatcher, PENDING_VIEW_NAME, _forward_deep_link
from guigui.core import paths


class StubApi:
    def __init__(self):
        self.js = []

    def _emit(self, type_, payload):
        self.js.append(("emit", type_, payload))

    def _eval(self, js):
        self.js.append(("eval", js))


def _write_pending(view, age=0.0):
    p = paths.data_dir() / PENDING_VIEW_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"view": view, "ts": time.time() - age}),
                 encoding="utf-8")
    return p


def test_forward_deep_link_writes_pending_file(monkeypatch):
    monkeypatch.setattr(gui_mod, "_activate_existing_window", lambda: None)
    _forward_deep_link("creds")
    item = json.loads((paths.data_dir() / PENDING_VIEW_NAME)
                      .read_text(encoding="utf-8"))
    assert item["view"] == "creds"
    assert time.time() - item["ts"] < 5


def test_watcher_consumes_pending_view():
    api = StubApi()
    w = FileWatcher(api)
    _write_pending("creds")
    w._check_pending_view()
    assert not (paths.data_dir() / PENDING_VIEW_NAME).exists()   # 消费即删
    assert any(kind == "eval" and "creds" in js and "applyLaunch" in js
               for kind, js in api.js)


def test_watcher_drops_stale_pending_view():
    api = StubApi()
    w = FileWatcher(api)
    _write_pending("creds", age=gui_mod.PENDING_VIEW_TTL + 10)
    w._check_pending_view()
    assert api.js == []
    assert not (paths.data_dir() / PENDING_VIEW_NAME).exists()


def test_watcher_drops_invalid_view():
    api = StubApi()
    w = FileWatcher(api)
    _write_pending("evil")                    # 白名单外
    w._check_pending_view()
    assert api.js == []
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd C:/Users/ASUS/auto-login && .venv-guigui/Scripts/python.exe -m pytest guigui/tests/test_gui.py -q
```

Expected: collection ERROR(`PENDING_VIEW_NAME`/`_forward_deep_link` 不存在)。

- [ ] **Step 3: 实现**

**api.py**:把 `_emit` 方法整体替换为(新增 `_eval`,`_emit` 变薄):

```python
    def _eval(self, js: str) -> None:
        w = self._window
        if w is None:
            return
        try:
            w.evaluate_js(js)
        except Exception as e:
            log.warning("api: JS 执行失败(%s)", e)

    def _emit(self, type_: str, payload: dict) -> None:
        self._eval(
            f"window.guiguiEmit && window.guiguiEmit("
            f"{json.dumps(type_)}, {json.dumps(payload, ensure_ascii=False)})")
```

**gui.py**:

(a) 常量区(`WATCH_INTERVAL = 2.0` 之后)加:

```python
PENDING_VIEW_NAME = "pending_view.json"   # 深链二实例 → 主实例的接力文件
PENDING_VIEW_TTL = 120.0                  # 超龄视为残留,静默丢弃
```

(b) `_inject_launch` 之后加两个函数:

```python
def _activate_existing_window() -> None:
    """把已在跑的桂桂窗口拉到前台(深链二实例用);失败只记日志。"""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "桂桂 / GuiGui")
        if hwnd:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)          # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
    except Exception as e:
        log.warning("gui: 激活已有窗口失败: %s", e)


def _forward_deep_link(view: str) -> None:
    """单实例抢锁失败时的深链转发:pending 文件 + 激活旧窗口。

    主实例 FileWatcher 2s 轮询消费 pending 文件并注入 applyLaunch;
    带 ts 是为了丢弃「GUI 关闭前没消费完」的隔夜残留。"""
    import time as _time

    try:
        p = paths.data_dir() / PENDING_VIEW_NAME
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"view": view, "ts": _time.time()}),
                     encoding="utf-8")
    except OSError as e:
        log.warning("gui: 深链转发落盘失败: %s", e)
    _activate_existing_window()
```

(c) `FileWatcher.run` 的轮询块加一行:

```python
            try:
                self._check_config()
                self._check_state()
                self._check_today_log()
                self._check_pending_view()
```

(d) `FileWatcher` 类内(`_check_today_log` 之后)加方法:

```python
    def _check_pending_view(self) -> None:
        """深链转发文件:消费即删;过期/白名单外静默丢弃。"""
        import time as _time

        p = paths.data_dir() / PENDING_VIEW_NAME
        try:
            if not p.exists():
                return
            raw = p.read_text(encoding="utf-8")
            p.unlink()
        except OSError:
            return
        try:
            item = json.loads(raw)
            view = item.get("view")
            fresh = _time.time() - float(item.get("ts") or 0) <= PENDING_VIEW_TTL
        except (ValueError, TypeError):
            return
        if fresh and view in ("main", "creds", "settings"):
            # 与冷启动同一条路:壳注入 __guigui_launch → applyLaunch 消费
            self.api._eval(
                f"window.__guigui_launch={json.dumps(view)};"
                "applyLaunch&&applyLaunch()")
```

(e) `run()` 里抢锁失败分支替换为:

```python
    lock = instance.SingleInstance()
    if not lock.acquire():
        log.info("gui: 已有实例在跑,本次启动退出")
        if view:
            _forward_deep_link(view)   # 通知点击落到已开的 GUI 时不再石沉大海
        return 0
```

- [ ] **Step 4: 跑测试确认通过(全量)**

```bash
cd C:/Users/ASUS/auto-login && .venv-guigui/Scripts/python.exe -m pytest guigui/tests -q
```

Expected: 全部 PASS(128 + 4 = 132)。

- [ ] **Step 5: Commit**

```bash
git add guigui/app/api.py guigui/app/gui.py guigui/tests/test_gui.py
git commit -m "feat(gui): 深链二实例转发 — pending 文件+激活旧窗口,FileWatcher 消费后走既有 applyLaunch;GUI 已开时点通知不再无响应(审计 P2-1)"
```

---

### Task 4: P2-3 — 卸载凭据清理改枚举式全删(<学号>@GuiGui 一网打尽)

**Files:**
- Modify: `guigui/core/vault.py`(模块尾追加)
- Modify: `guigui/__main__.py`(--clear-creds 分支)
- Test: `guigui/tests/test_vault.py`(末尾追加)

- [ ] **Step 1: 写失败测试**

`guigui/tests/test_vault.py` 末尾追加:

```python
# ── 卸载全删:枚举式清理(不依赖 config 当前学号)─────────────


def test_delete_all_matches_suffix_only():
    targets = ["2025000000001@GuiGui", "2024@GuiGui", "x@Other", "GuiGui"]
    deleted = []
    n = vault.delete_all_service_entries(
        enum_targets=lambda: targets,
        delete_target=lambda t: (deleted.append(t) or True))
    assert n == 2
    assert deleted == ["2025000000001@GuiGui", "2024@GuiGui"]


def test_delete_all_counts_failures():
    n = vault.delete_all_service_entries(
        enum_targets=lambda: ["a@GuiGui", "b@GuiGui"],
        delete_target=lambda t: False)
    assert n == 0


def test_delete_all_enum_failure_raises_vault_error():
    def boom():
        raise OSError("denied")

    with pytest.raises(vault.VaultError):
        vault.delete_all_service_entries(enum_targets=boom,
                                         delete_target=lambda t: True)
```

(文件头若未 `import pytest` 则补上。)

- [ ] **Step 2: 跑测试确认失败**

```bash
cd C:/Users/ASUS/auto-login && .venv-guigui/Scripts/python.exe -m pytest guigui/tests/test_vault.py -q
```

Expected: 3 FAIL(`delete_all_service_entries` 不存在)。

- [ ] **Step 3: 实现**

`guigui/core/vault.py` 头部 imports 区补:

```python
import ctypes
from ctypes import wintypes
```

模块末尾追加:

```python
# ── 卸载全删(枚举式)────────────────────────────────────


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_CRED_TYPE_GENERIC = 1


def _enum_targets_default() -> list[str]:
    """枚举当前用户全部凭据目标名(keyring 无枚举 API,直接走 advapi32)。"""
    advapi32 = ctypes.windll.advapi32
    count = wintypes.DWORD()
    pcreds = ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))()
    if not advapi32.CredEnumerateW(None, 0, ctypes.byref(count),
                                   ctypes.byref(pcreds)):
        raise OSError(ctypes.get_last_error())
    try:
        return [pcreds[i].contents.TargetName for i in range(count.value)]
    finally:
        advapi32.CredFree(pcreds)


def _delete_target_default(target: str) -> bool:
    return bool(ctypes.windll.advapi32.CredDeleteW(
        target, _CRED_TYPE_GENERIC, 0))


def delete_all_service_entries(enum_targets=None, delete_target=None) -> int:
    """删除凭据管理器中本服务全部条目(目标名 <学号>@GuiGui)。

    卸载「彻底清理」用:不依赖 config 当前学号,历史遗留条目一并清。
    返回删除条数;枚举失败抛 VaultError(调用方回退逐条删);
    单条删除失败不挡其余。enum/delete 可注入,便于单测。"""
    enum_targets = enum_targets or _enum_targets_default
    delete_target = delete_target or _delete_target_default
    suffix = "@" + _SERVICE
    try:
        targets = list(enum_targets())
    except Exception as e:
        raise VaultError(f"凭据枚举失败: {e}") from e
    deleted = 0
    for target in targets:
        if target and target.endswith(suffix):
            try:
                if delete_target(target):
                    deleted += 1
            except Exception:
                continue
    return deleted
```

`guigui/__main__.py` 的 `--clear-creds` 分支整体替换为:

```python
    if "--clear-creds" in argv:
        # 卸载器「彻底清理」用:枚举凭据管理器中 <学号>@GuiGui 全部条目;
        # 枚举失败(罕见)回退删当前配置学号;无配置/无凭据静默成功
        from guigui.core import config, vault

        uid = config.load().get("uid") or ""
        try:
            vault.delete_all_service_entries()
        except Exception:
            if uid:
                try:
                    vault.delete_password(uid)
                except Exception:
                    pass
        return 0
```

- [ ] **Step 4: 跑测试确认通过(全量)**

```bash
cd C:/Users/ASUS/auto-login && .venv-guigui/Scripts/python.exe -m pytest guigui/tests -q
```

Expected: 全部 PASS(132 + 3 = 135)。

- [ ] **Step 5: Commit**

```bash
git add guigui/core/vault.py guigui/__main__.py guigui/tests/test_vault.py
git commit -m "fix(uninstall): 凭据清理改枚举式全删 — CredEnumerate 扫 *@GuiGui 逐条删,不再只认 config 当前学号;枚举失败回退旧路径(审计 P2-3)"
```

---

### Task 5: P3-6 — login 凭据读出提到循环外 + 空值防线

**Files:**
- Modify: `guigui/app/api.py`(login 重试循环)
- Test: `guigui/tests/test_api.py`(末尾追加)

- [ ] **Step 1: 写失败测试**

`guigui/tests/test_api.py` 末尾追加:

```python
# ── login:凭据单次读出 + 空值防线 ─────────────────────────


def test_login_reads_vault_once_across_retries(ctx, monkeypatch):
    ctx.probe_state = {"state": "not_logged_in", "ssid": "x", "detail": ""}
    ctx.login_seq = [("rejected", "x"), ("rejected", "x"), ("success", "")]
    calls = []
    monkeypatch.setattr(api_mod.vault, "get_password",
                        lambda uid: (calls.append(uid) or "pw"))
    out = ctx.api.login({})
    assert out["ok"] is True and out["data"]["attempts"] == 3
    assert len(calls) == 1                    # 旧实现每轮重读(3 次)


def test_login_vault_read_failure_maps_not_configured(ctx, monkeypatch):
    ctx.probe_state = {"state": "not_logged_in", "ssid": "x", "detail": ""}
    monkeypatch.setattr(api_mod.vault, "get_password", lambda uid: None)
    out = ctx.api.login({})
    assert out["code"] == "NOT_CONFIGURED"    # 旧实现 INTERNAL(quote(None) 炸)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd C:/Users/ASUS/auto-login && .venv-guigui/Scripts/python.exe -m pytest guigui/tests/test_api.py -q
```

Expected: `test_login_reads_vault_once_across_retries` FAIL(calls==3);
`test_login_vault_read_failure_maps_not_configured` FAIL(code==INTERNAL)。

- [ ] **Step 3: 实现**

`login` 里,if/else 凭据分支结束之后、`self._emit("login:progress",
{"phase": "probe"})` 之前插入:

```python
            stored = vault.get_password(uid)
            if not stored:
                return _err(NOT_CONFIGURED, "还没存过密码,先填一次")
```

重试循环内的请求行改为用 `stored`:

```python
                result, msg = drcom.login(cfg["url"], uid, stored)
```

(即原 `vault.get_password(uid)` 从循环体内移除。)

- [ ] **Step 4: 跑测试确认通过(全量)**

```bash
cd C:/Users/ASUS/auto-login && .venv-guigui/Scripts/python.exe -m pytest guigui/tests -q
```

Expected: 全部 PASS(135 + 2 = 137)。

- [ ] **Step 5: Commit**

```bash
git add guigui/app/api.py guigui/tests/test_api.py
git commit -m "fix(api): login 凭据读出提到重试循环外 — 重试不再每轮碰 keyring;读出为空明确 NOT_CONFIGURED,堵 quote(None) 路径(审计 P3-6)"
```

---

### Task 6: P3-7 — SetWindowRgn 失败时 DeleteObject(keeper 重贴不再泄 GDI)

**Files:**
- Modify: `guigui/app/gui.py`(`_apply_rounded_region`)

- [ ] **Step 1: 修代码**

`_apply_rounded_region` 末尾两行(`CreateRoundRectRgn` 赋值与 `SetWindowRgn`)
替换为:

```python
        hrgn = ctypes.windll.gdi32.CreateRoundRectRgn(
            0, 0, form.ClientSize.Width + 1, form.ClientSize.Height + 1,
            r * 2, r * 2)
        if not user32.SetWindowRgn(hwnd, hrgn, True):
            # 成功后 region 归系统;失败必须自删,keeper 每 1.5s 重贴会累积泄漏
            ctypes.windll.gdi32.DeleteObject(hrgn)
```

(无单测 — 纯 Win32 句柄路径,由实机冒烟覆盖。)

- [ ] **Step 2: 全量测试回归**

```bash
cd C:/Users/ASUS/auto-login && .venv-guigui/Scripts/python.exe -m pytest guigui/tests -q
```

Expected: 137 PASS(纯增分支,不破旧测)。

- [ ] **Step 3: Commit**

```bash
git add guigui/app/gui.py
git commit -m "fix(gui): SetWindowRgn 失败时 DeleteObject — 圆角 keeper 每 1.5s 重贴,持续失败不再累积泄漏 GDI region(审计 P3-7)"
```

---

### Task 7: 重建安装包 + 实机验证清单

**Files:** 无源码改动(构建 + 人工验证)。

- [ ] **Step 1: 全链路重建**

```bash
cd C:/Users/ASUS/auto-login && cmd //c guigui\\build_guigui.bat
```

Expected: `TESTS PASSED` → `=== BUILD OK: dist\guigui\guigui.exe ===` →
`installer: guigui\Output\guigui-setup-2.0.0.exe`(时间戳新于本次改动)。

- [ ] **Step 2: 实机清单(逐项打勾,结果记入 Task 8 的文档更新)**

1. 装新包 → GUI 正常开窗(冒烟:圆角/导航/探网)。
2. **AppMutex**:桂桂开着 → 重跑安装器 → 应弹「请关闭桂桂再继续」类提示
   (而非文件占用重试框);卸载器同理。
3. **深链转发**:桂桂开着(日常页)→ Win+R 执行
   `dist\guigui\guigui.exe "guigui://creds"` → ≤2s 内既有窗口前置并跳
   登录页;再试 `guigui://settings` 同理。
4. **首装任务时机**:删 `%LOCALAPPDATA%\GuiGui` → 装新包 → 首装页改时间
   但**先不交密码** → `schtasks /query /tn GuiGui` 应报「找不到」→ 交密码
   成功后再查,任务应出现(Rev 与 config.tasks_rev 一致)。
5. **凭据全删**:控制面板凭据管理器手工造一条遗留 `旧学号@GuiGui` →
   卸载选「彻底清理」→ 凭据管理器里所有 `*@GuiGui` 全部消失。
6. `schtasks /query /tn GuiGui-Patrol` 行为不变(默认关时不存在)。

- [ ] **Step 3: Commit(仅当清单发现回归需改码,回到对应 Task)**

无回归则本任务无提交。

---

### Task 8: 审计报告回写状态

**Files:**
- Modify: `docs/tech/guigui-package-audit-2026-08-31.md`(结论速览表加一列或表下加一行)

- [ ] **Step 1: 表格下追加修复状态块**

```markdown
## 修复落地(2026-08-31,计划见 guigui-package-fix-plan-2026-08-31.md)

- P1 AppMutex ✅ Task 1(setup.iss)
- P2 deep link 转发 ✅ Task 3(pending 文件 + applyLaunch,前端零改动)
- P2 saveConfig 守卫 ✅ Task 2(三处统一 + login 后首建)
- P2 凭据枚举全删 ✅ Task 4(CredEnumerate 扫 *@GuiGui)
- P3 login 循环外读凭据 ✅ Task 5;P3 GDI 泄漏 ✅ Task 6
- P3 其余(日志轮转竞态/GBK 边缘/WebView2 注册表检测/toast 冷启)维持记录在案
- 实机清单 6 项结果:____(Task 7 Step 2 勾选记录)
```

(实机清单结果如实回填,失败的项写明现象与去向。)

- [ ] **Step 2: Commit**

```bash
git add docs/tech/guigui-package-audit-2026-08-31.md
git commit -m "docs(audit): 审计报告回写修复状态 — P1+P2 全落地,P3×2 顺手修,实机清单 6 项结果"
```

---

## Self-Review 记录

- **覆盖核对**:审计 P1→Task 1;P2-1→Task 3;P2-2→Task 2;P2-3→Task 4;P3-6→Task 5;P3-7→Task 6;P3-5/8/9/10 明确不修(报告已记录理由)。无缺项。
- **占位符扫描**:无 TBD/TODO;所有代码块为最终形态;实机清单第 6 项为「行为不变」的防回归断言而非占位。
- **类型一致性**:`_align_saved(self, saved: dict)` 签名在 Task 2 定义、Task 3/5 未再引用,无漂移;`_eval(self, js: str)` 在 Task 3 定义并同任务内被 FileWatcher 使用;`delete_all_service_entries(enum_targets, delete_target)` 定义与测试注入参数名一致;测试计数 125→128→132→135→137 逐 Task 递增无冲突。
- **风险点**:Task 2 是行为变更(首装建任务时机从「改时间时」推迟到「交密码后」),依赖 Task 7 清单第 4 项实测兜底;Task 3 的 `FindWindowW` 按窗口标题匹配,与 `webview.create_window("桂桂 / GuiGui", ...)` 标题逐字一致。
