# 意外恢复系统 实施计划（Resilience Implementation Plan）

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务执行。步骤用 `- [ ]` 复选框跟踪。

**Goal:** 让校园网自动登录工具在意外情况（关机/睡眠唤醒/白天掉线/进程崩溃/任务被删）下都能自主恢复登录。

**Architecture:** 混合——Windows 任务计划做保底（多触发器：登录时 + 每 15min 心跳 + 每天 06:55，都跑幂等的 `--ensure`），叠加开机后常驻托盘的守护进程做秒级断网重连；自愈通过"自启注册表 ↔ 任务计划"互为兜底实现。设计稿见 `docs/superpowers/specs/2026-06-15-resilience-design.md`。

**Tech Stack:** Python 3.12、customtkinter、**pystray + Pillow（新增）**、PyInstaller、Inno Setup、pytest。互斥量用 `ctypes`（标准库，不引 pywin32）。

---

## 文件结构

**新建：**
- `src/instance.py` — 单实例锁：Win32 命名互斥量（ctypes），含 `SingleInstance` 与 `tray_is_running()` 探测。
- `src/ensure.py` — `--ensure` 心跳：纯函数决策 `plan()` + 执行编排 `run()`。
- `src/selfheal.py` — 自修复：把自启/任务按 config 意图幂等对齐。
- `src/tray.py` — 系统托盘（pystray + Pillow），状态驱动图标 + 菜单。
- `tests/test_instance.py`、`tests/test_ensure.py`、`tests/test_selfheal.py`、`tests/test_tray.py`、`tests/test_scheduler_resilience.py`。

**修改：**
- `src/config.py` — 新增 `resilience_enabled`、`heartbeat_interval_minutes`；`polling_enabled` 默认改 `true`。
- `src/login.py` — `attempt_login` 加 `skip_wifi` 参数（心跳不做 WiFi 切换）。
- `src/scheduler.py` — 新增 `create_scheduled_task_multi()`、`is_legacy_task()`。
- `src/app.py` — 启动即自动登录 + 自动开轮询 + 启动自愈；关窗最小化到托盘。
- `main.py` — `--ensure` 分发；GUI 模式加单实例守卫。
- `main.spec` / `build.bat` — 打包 pystray/Pillow + 托盘图标。

---

## Phase A — 无头心跳骨干（不依赖 GUI，单独可交付，修掉"任务被错过"类问题）

### Task 1: 配置新增字段 + polling 默认改开

**Files:**
- Modify: `src/config.py`（`_DEFAULTS`、`_VALIDATORS`）
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_config.py`）

```python
def test_defaults_include_resilience_fields():
    from src import config
    d = config.validate({})
    assert d["resilience_enabled"] is True
    assert d["heartbeat_interval_minutes"] == 15
    assert d["polling_enabled"] is True  # 默认改为开


def test_heartbeat_interval_invalid_falls_back():
    from src import config
    d = config.validate({"heartbeat_interval_minutes": 0})
    assert d["heartbeat_interval_minutes"] == 15
    d = config.validate({"heartbeat_interval_minutes": "x"})
    assert d["heartbeat_interval_minutes"] == 15


def test_resilience_enabled_must_be_bool():
    from src import config
    d = config.validate({"resilience_enabled": "yes"})
    assert d["resilience_enabled"] is True  # 非布尔 → 回退默认 True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_config.py -v`
Expected: FAIL（KeyError / 值不符）

- [ ] **Step 3: 实现**（修改 `src/config.py`）

`_DEFAULTS` 中把 `"polling_enabled": False` 改为 `True`，并新增两项：

```python
    "polling_enabled": True,
    "polling_interval_seconds": 30,
    "scheduled_login_enabled": False,
    "scheduled_login_time": "06:55",
    "auto_start": False,
    "notification_enabled": True,
    "resilience_enabled": True,
    "heartbeat_interval_minutes": 15,
```

`_VALIDATORS` 末尾追加（注意：`polling_enabled` 的校验 lambda 不变，仍 `lambda v: True`）：

```python
    ("resilience_enabled", bool, lambda v: True, _DEFAULTS["resilience_enabled"]),
    ("heartbeat_interval_minutes", int, lambda v: v >= 1, _DEFAULTS["heartbeat_interval_minutes"]),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_config.py -v`
Expected: PASS（全部用例）

- [ ] **Step 5: 提交**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat: 配置新增 resilience_enabled/heartbeat_interval，polling 默认改开"
```

---

### Task 2: 单实例锁（Win32 命名互斥量，ctypes）

**Files:**
- Create: `src/instance.py`
- Test: `tests/test_instance.py`

- [ ] **Step 1: 写失败测试**

```python
from unittest.mock import MagicMock
from src import instance


def test_acquire_when_no_existing_mutex():
    # create 返回非零 handle、last_error=0 → 抢到
    fake_create = MagicMock(return_value=(42, 0))
    si = instance.SingleInstance(create_func=fake_create)
    assert si.acquire() is True
    fake_create.assert_called_once()


def test_acquire_fails_when_already_exists():
    fake_create = MagicMock(return_value=(42, 183))  # ERROR_ALREADY_EXISTS
    si = instance.SingleInstance(create_func=fake_create)
    assert si.acquire() is False


def test_release_is_idempotent():
    fake_create = MagicMock(return_value=(42, 0))
    si = instance.SingleInstance(create_func=fake_create)
    si.acquire()
    si.release()
    si.release()  # 重复释放不报错
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_instance.py -v`
Expected: FAIL（`ModuleNotFoundError: src.instance`）

- [ ] **Step 3: 实现 `src/instance.py`**

```python
"""单实例锁：Win32 命名互斥量（ctypes 实现，无 pywin32 依赖）。

进程退出（含崩溃）时 OS 自动回收互斥量，不会留死锁。
"""

import ctypes
import logging
from ctypes import wintypes

log = logging.getLogger(__name__)

_MUTEX_NAME = "Local\\SchoolAutoLogin-Instance"
_ERROR_ALREADY_EXISTS = 183

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _default_create_mutex(name: str) -> tuple[int, int]:
    """调用 Win32 CreateMutexW，返回 (handle, last_error)。"""
    handle = _kernel32.CreateMutexW(None, False, name)
    return int(handle or 0), ctypes.get_last_error()


class SingleInstance:
    """持有命名互斥量；acquire 返回是否抢到（本进程是否为主实例）。"""

    def __init__(self, name: str = _MUTEX_NAME, create_func=None):
        self._name = name
        self._create = create_func or _default_create_mutex
        self._handle: int | None = None

    def acquire(self) -> bool:
        handle, err = self._create(self._name)
        if not handle:
            log.error("CreateMutex 失败: err=%d", err)
            return False
        if err == _ERROR_ALREADY_EXISTS:
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle:
            _kernel32.CloseHandle(self._handle)
            self._handle = None


def tray_is_running(name: str = _MUTEX_NAME, create_func=None) -> bool:
    """探测托盘是否在跑：尝试抢互斥量，抢不到=有人在跑。抢到则立即释放。"""
    si = SingleInstance(name, create_func=create_func)
    got = si.acquire()
    if got:
        si.release()
        return False
    return True
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_instance.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/instance.py tests/test_instance.py
git commit -m "feat: 新增单实例锁（Win32 命名互斥量）"
```

---

### Task 3: attempt_login 加 skip_wifi 参数

**Files:**
- Modify: `src/login.py:131-175`（`attempt_login`）
- Test: `tests/test_login.py`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_login.py`）

```python
@patch("src.login.wifi", new=None)  # 占位，下面真正 patch
def test_attempt_login_skip_wifi_returns_unreachable(monkeypatch):
    """skip_wifi=True 且服务器不可达时，不碰 WiFi、不等网络，直接返回 unreachable。"""
    from src import login
    # check_auth_status 返回 unreachable
    monkeypatch.setattr(login, "check_auth_status", lambda: "unreachable")
    called = {"wifi": False, "wait": False}
    import src.wifi as wifi_mod
    monkeypatch.setattr(wifi_mod, "connect", lambda ssid: called.__setitem__("wifi", True))
    monkeypatch.setattr(login, "wait_for_network", lambda *a, **k: called.__setitem__("wait", True))

    result = login.attempt_login({"wifi_ssid": "campus", "username": "u", "password": "p"},
                                 skip_wifi=True)
    assert result == "unreachable"
    assert called["wifi"] is False
    assert called["wait"] is False
```

> 注：去掉测试顶部那行 `@patch(...)` 占位，实际用 `monkeypatch`。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_login.py -k skip_wifi -v`
Expected: FAIL（`TypeError: attempt_login() got unexpected keyword 'skip_wifi'`）

- [ ] **Step 3: 实现**（修改 `src/login.py` 的 `attempt_login`）

签名改为 `def attempt_login(cfg: dict, skip_wifi: bool = False) -> str:`，并把 WiFi 分支改为：

```python
    # Step 2: If unreachable, try WiFi switch as remediation（心跳 skip_wifi 时不做）
    if status == "unreachable":
        if cfg.get("wifi_ssid") and not skip_wifi:
            from . import wifi
            log.info("Server unreachable, switching WiFi to '%s'...", cfg["wifi_ssid"])
            wifi.connect(cfg["wifi_ssid"])
        if not wait_for_network():
            return "unreachable"
```

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `pytest tests/test_login.py -v`
Expected: PASS（新用例 + 原有用例全过）

- [ ] **Step 5: 提交**

```bash
git add src/login.py tests/test_login.py
git commit -m "feat: attempt_login 支持 skip_wifi（心跳不做 WiFi 切换）"
```

---

### Task 4: 任务计划多触发器 + 旧任务检测

**Files:**
- Modify: `src/scheduler.py`
- Test: `tests/test_scheduler_resilience.py`

- [ ] **Step 1: 写失败测试**

```python
from unittest.mock import patch, MagicMock
from src import scheduler


def _capture_ps(func):
    """捕获传给 powershell 的 -Command 字符串。"""
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return MagicMock(returncode=0, stderr="", stdout="")

    return captured, fake_run


def test_create_multi_task_has_three_triggers_and_ensure_arg():
    captured, fake = _capture_ps(scheduler.create_scheduled_task_multi)
    with patch("subprocess.run", side_effect=fake):
        scheduler.create_scheduled_task_multi("06:55", interval_minutes=15)
    ps = " ".join(captured["cmd"])
    assert "--ensure" in ps
    assert "-AtLogOn" in ps
    assert "RepetitionInterval" in ps
    assert "New-TimeSpan -Minutes 15" in ps
    assert "-Daily -At '06:55:00'" in ps
    assert "IgnoreNew" in ps  # 防止重叠实例堆积


def test_is_legacy_task_detects_silent():
    fake = MagicMock(returncode=0, stdout="<Task><Actions>...--silent...</Actions></Task>")
    with patch("subprocess.run", return_value=fake):
        assert scheduler.is_legacy_task() is True


def test_is_legacy_task_false_for_new_ensure_task():
    fake = MagicMock(returncode=0, stdout="<Task>...--ensure...</Task>")
    with patch("subprocess.run", return_value=fake):
        assert scheduler.is_legacy_task() is False


def test_is_legacy_task_false_when_missing():
    fake = MagicMock(returncode=1, stdout="")
    with patch("subprocess.run", return_value=fake):
        assert scheduler.is_legacy_task() is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_scheduler_resilience.py -v`
Expected: FAIL（属性不存在）

- [ ] **Step 3: 实现**（追加到 `src/scheduler.py`）

```python
def create_scheduled_task_multi(time_str: str, interval_minutes: int = 15) -> bool:
    """创建多触发器任务：登录时 + 每 N 分钟心跳 + 每天 time_str。都跑 --ensure。

    Returns True on success.
    """
    if not _TIME_RE.match(time_str):
        log.error("Invalid time format (expected HH:MM): %r", time_str)
        return False

    exe = _ps_escape(exe_path())
    task = _ps_escape(TASK_NAME)
    ps = (
        "$action = New-ScheduledTaskAction "
        f"-Execute {exe} -Argument '--ensure'; "
        "$tLogon = New-ScheduledTaskTrigger -AtLogOn; "
        "$tRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date) "
        f"-RepetitionInterval (New-TimeSpan -Minutes {int(interval_minutes)}) "
        "-RepetitionDuration (New-TimeSpan -Days 3650); "
        f"$tDaily = New-ScheduledTaskTrigger -Daily -At '{time_str}:00'; "
        "$settings = New-ScheduledTaskSettingsSet "
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-StartWhenAvailable -WakeToRun "
        "-ExecutionTimeLimit (New-TimeSpan -Minutes 5) "
        "-MultipleInstances IgnoreNew; "
        f"Register-ScheduledTask -TaskName {task} "
        "-Action $action -Trigger @($tLogon, $tRepeat, $tDaily) "
        "-Settings $settings -Force"
    )
    try:
        r = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            log.info("Multi-trigger task created: %s (every %dmin + logon + daily %s)",
                     TASK_NAME, interval_minutes, time_str)
            return True
        log.error("Failed to create multi-trigger task: %s", r.stderr.strip())
        return False
    except Exception as e:
        log.error("Scheduler error: %s", e)
        return False


def is_legacy_task() -> bool:
    """旧任务跑 --silent（单触发器），新版跑 --ensure（多触发器）。"""
    try:
        r = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME, "/xml"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return False
        return "--silent" in r.stdout and "--ensure" not in r.stdout
    except Exception:
        return False
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_scheduler_resilience.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/scheduler.py tests/test_scheduler_resilience.py
git commit -m "feat: 任务计划支持多触发器（登录/心跳/每日）+ 旧任务检测"
```

---

### Task 5: 自修复（自启 + 任务计划幂等对齐）

**Files:**
- Create: `src/selfheal.py`
- Test: `tests/test_selfheal.py`

- [ ] **Step 1: 写失败测试**

```python
from unittest.mock import patch
from src import selfheal


def test_should_autostart_when_resilience_on():
    assert selfheal.should_autostart_be_enabled({"resilience_enabled": True, "auto_start": False}) is True


def test_should_not_autostart_when_both_off():
    assert selfheal.should_autostart_be_enabled({"resilience_enabled": False, "auto_start": False}) is False


def test_reconcile_autostart_enables_when_missing():
    with patch("src.autostart.is_enabled", return_value=False), \
         patch("src.autostart.enable") as enable:
        changed = selfheal.reconcile_autostart({"resilience_enabled": True})
    assert changed is True
    enable.assert_called_once()


def test_reconcile_autostart_noop_when_aligned():
    with patch("src.autostart.is_enabled", return_value=True), \
         patch("src.autostart.enable") as enable:
        changed = selfheal.reconcile_autostart({"resilience_enabled": True})
    assert changed is False
    enable.assert_not_called()


def test_reconcile_scheduler_recreates_when_missing():
    with patch("src.scheduler.get_scheduled_task_info",
               return_value={"exists": False}), \
         patch("src.scheduler.is_legacy_task", return_value=False), \
         patch("src.scheduler.create_scheduled_task_multi") as create:
        changed = selfheal.reconcile_scheduler(
            {"resilience_enabled": True, "scheduled_login_enabled": True,
             "scheduled_login_time": "06:55", "heartbeat_interval_minutes": 15})
    assert changed is True
    create.assert_called_once_with("06:55", 15)


def test_reconcile_scheduler_migrates_legacy():
    with patch("src.scheduler.get_scheduled_task_info",
               return_value={"exists": True}), \
         patch("src.scheduler.is_legacy_task", return_value=True), \
         patch("src.scheduler.create_scheduled_task_multi") as create:
        changed = selfheal.reconcile_scheduler(
            {"resilience_enabled": True, "scheduled_login_enabled": True,
             "scheduled_login_time": "07:00", "heartbeat_interval_minutes": 20})
    assert changed is True
    create.assert_called_once_with("07:00", 20)


def test_reconcile_scheduler_removes_when_disabled():
    with patch("src.scheduler.get_scheduled_task_info",
               return_value={"exists": True}), \
         patch("src.scheduler.remove_scheduled_task") as remove:
        changed = selfheal.reconcile_scheduler(
            {"resilience_enabled": False, "scheduled_login_enabled": False})
    assert changed is True
    remove.assert_called_once()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_selfheal.py -v`
Expected: FAIL（`ModuleNotFoundError: src.selfheal`）

- [ ] **Step 3: 实现 `src/selfheal.py`**

```python
"""自修复：把任务计划 / 自启注册表按 config 意图幂等对齐。

只在"缺失 / 规格不符 / 状态不符"时动手，不覆盖用户的对齐状态。
自启与任务计划互为兜底：任一存活即可重建另一个。
"""

import logging

from . import autostart, scheduler

log = logging.getLogger(__name__)


def should_autostart_be_enabled(cfg: dict) -> bool:
    """resilience 开 或 auto_start 开 → 自启应为开。"""
    return bool(cfg.get("resilience_enabled", True) or cfg.get("auto_start"))


def should_task_be_enabled(cfg: dict) -> bool:
    """scheduled_login 开 或 resilience 开 → 多触发器任务应为开。"""
    return bool(cfg.get("scheduled_login_enabled", False)
                or cfg.get("resilience_enabled", True))


def reconcile_autostart(cfg: dict) -> bool:
    """对齐自启注册表，返回是否做了改动。"""
    want = should_autostart_be_enabled(cfg)
    current = autostart.is_enabled()
    if want and not current:
        autostart.enable()
        log.info("Self-heal: 重新开启自启")
        return True
    if not want and current:
        autostart.disable()
        log.info("Self-heal: 关闭自启")
        return True
    return False


def reconcile_scheduler(cfg: dict) -> bool:
    """对齐任务计划（缺失→重建 / 旧版→迁移 / 应关却存在→删除），返回是否改动。"""
    want = should_task_be_enabled(cfg)
    info = scheduler.get_scheduled_task_info()
    time_str = cfg.get("scheduled_login_time", "06:55")
    interval = cfg.get("heartbeat_interval_minutes", 15)
    if want and not info.get("exists"):
        scheduler.create_scheduled_task_multi(time_str, interval)
        log.info("Self-heal: 重建任务计划")
        return True
    if want and info.get("exists") and scheduler.is_legacy_task():
        scheduler.create_scheduled_task_multi(time_str, interval)
        log.info("Self-heal: 迁移旧任务到多触发器")
        return True
    if not want and info.get("exists"):
        scheduler.remove_scheduled_task()
        log.info("Self-heal: 删除任务计划")
        return True
    return False
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_selfheal.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/selfheal.py tests/test_selfheal.py
git commit -m "feat: 自修复——按 config 意图幂等对齐自启/任务计划"
```

---

### Task 6: ensure 心跳（决策 plan + 编排 run）

**Files:**
- Create: `src/ensure.py`
- Test: `tests/test_ensure.py`

- [ ] **Step 1: 写失败测试**

```python
from unittest.mock import patch
from src import ensure


def test_plan_logs_in_when_not_logged_in():
    ctx = ensure.EnsureContext(auth_status="not_logged_in", tray_alive=True,
                               cfg={"resilience_enabled": True})
    p = ensure.plan(ctx)
    assert p.should_login is True


def test_plan_skips_login_when_logged_in():
    ctx = ensure.EnsureContext(auth_status="logged_in", tray_alive=True,
                               cfg={"resilience_enabled": True})
    assert ensure.plan(ctx).should_login is False


def test_plan_spawns_tray_when_resilience_and_dead():
    ctx = ensure.EnsureContext(auth_status="logged_in", tray_alive=False,
                               cfg={"resilience_enabled": True})
    assert ensure.plan(ctx).should_spawn_tray is True


def test_plan_no_spawn_when_resilience_off():
    ctx = ensure.EnsureContext(auth_status="logged_in", tray_alive=False,
                               cfg={"resilience_enabled": False})
    assert ensure.plan(ctx).should_spawn_tray is False


def test_run_orchestrates_login_spawn_reconcile_and_quiet_when_nothing_recovered():
    cfg = {"resilience_enabled": True, "username": "u", "password": "p",
           "notification_enabled": True, "scheduled_login_time": "06:55",
           "heartbeat_interval_minutes": 15}
    with patch("src.ensure.config") as mcfg, \
         patch("src.ensure.login_mod") as mlogin, \
         patch("src.ensure.instance") as minst, \
         patch("src.ensure.selfheal") as mheal, \
         patch("src.ensure.notify") as mnotify, \
         patch("src.ensure._spawn_tray_detached") as mspawn:
        mcfg.load.return_value = cfg
        mlogin.check_auth_status.return_value = "logged_in"
        minst.tray_is_running.return_value = True  # 托盘在跑，不拉起
        code = ensure.run()
    assert code == 0
    mspawn.assert_not_called()
    mnotify.send.assert_not_called()  # 没发生恢复 → 静默
    mheal.reconcile_autostart.assert_called_once()


def test_run_spawns_tray_and_notifies_when_recovered():
    cfg = {"resilience_enabled": True, "username": "u", "password": "p",
           "notification_enabled": True, "scheduled_login_time": "06:55",
           "heartbeat_interval_minutes": 15}
    with patch("src.ensure.config") as mcfg, \
         patch("src.ensure.login_mod") as mlogin, \
         patch("src.ensure.instance") as minst, \
         patch("src.ensure.selfheal") as mheal, \
         patch("src.ensure.notify") as mnotify, \
         patch("src.ensure._spawn_tray_detached") as mspawn:
        mcfg.load.return_value = cfg
        mlogin.check_auth_status.return_value = "not_logged_in"
        mlogin.attempt_login.return_value = "success"
        minst.tray_is_running.return_value = False  # 托盘没活 → 拉起
        code = ensure.run()
    assert code == 0
    mlogin.attempt_login.assert_called_once()
    mspawn.assert_called_once()
    mnotify.send.assert_called_once()  # 发生恢复 → 通知


def test_run_skips_when_no_credentials():
    with patch("src.ensure.config") as mcfg:
        mcfg.load.return_value = {"username": "", "password": ""}
        assert ensure.run() == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_ensure.py -v`
Expected: FAIL（`ModuleNotFoundError: src.ensure`）

- [ ] **Step 3: 实现 `src/ensure.py`**

```python
"""`--ensure` 心跳：幂等登录 + 看门狗 + 自修复。

由任务计划的多触发器调用。默认静默——仅当真发生恢复（重新登录 / 拉起托盘）时才通知。
"""

import logging
import subprocess
import sys
from dataclasses import dataclass

from . import config, instance, login as login_mod, notify, selfheal
from .scheduler import exe_path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnsureContext:
    auth_status: str
    tray_alive: bool
    cfg: dict


@dataclass
class EnsureActions:
    should_login: bool
    should_spawn_tray: bool
    should_reconcile_autostart: bool = True


def plan(ctx: EnsureContext) -> EnsureActions:
    """纯函数：给定上下文，决定本次心跳要做哪些动作。"""
    resilience = bool(ctx.cfg.get("resilience_enabled", True))
    return EnsureActions(
        should_login=(ctx.auth_status == "not_logged_in"),
        should_spawn_tray=(resilience and not ctx.tray_alive),
        should_reconcile_autostart=True,
    )


def _spawn_tray_detached() -> None:
    """detached 拉起 GUI/托盘进程，使任务计划不被阻塞。"""
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    target = [exe_path()]  # frozen=exe，dev=解析后的入口
    if not getattr(sys, "frozen", False):
        target = [sys.executable, str(exe_path())]
    subprocess.Popen(target, creationflags=flags, close_fds=True)
    log.info("Ensure: detached tray spawned")


def run() -> int:
    """心跳主流程，返回退出码（0=正常）。"""
    cfg = config.load()
    if not cfg.get("username") or not cfg.get("password"):
        log.warning("Ensure: 未配置凭据，跳过")
        return 0

    auth = login_mod.check_auth_status()
    log.info("Ensure: auth=%s", auth)
    tray_alive = instance.tray_is_running()

    actions = plan(EnsureContext(auth, tray_alive, cfg))
    recovered = False

    if actions.should_login:
        result = login_mod.attempt_login(cfg, skip_wifi=True)  # 心跳不做 WiFi 切换
        recovered = (result == "success")

    if actions.should_spawn_tray:
        _spawn_tray_detached()
        recovered = True

    if actions.should_reconcile_autostart:
        selfheal.reconcile_autostart(cfg)

    if recovered and cfg.get("notification_enabled", True):
        notify.send("校园网自动恢复", "已重新登录 / 拉起守护进程")

    return 0
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_ensure.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/ensure.py tests/test_ensure.py
git commit -m "feat: --ensure 心跳（幂等登录+看门狗+自修复，决策与执行分离）"
```

---

### Task 7: main.py 接入 --ensure 与单实例守卫

**Files:**
- Modify: `main.py`
- Test: 无新增（分发逻辑薄；靠 Task 6 已测的 `ensure.run()` + 手动验证）

- [ ] **Step 1: 实现**（修改 `main.py` 的 `main()`）

在函数开头、`--silent` 分支之前插入 `--ensure` 分发；GUI 分支加单实例守卫：

```python
def main():
    """程序入口：``--ensure`` 心跳 / ``--silent`` 一次性 / 否则 GUI。"""
    if "--ensure" in sys.argv:
        from src import ensure
        try:
            sys.exit(ensure.run())
        except Exception:
            log.exception("Ensure mode crashed")
            sys.exit(1)
        return

    if "--silent" in sys.argv:
        try:
            run_silent()
        except SystemExit:
            raise
        except Exception as e:
            # ...现有崩溃处理不变...
            log.exception("Silent mode crashed")
            import re
            safe_msg = re.sub(r'''['"$`()]''', '', str(e))[:200]
            subprocess.run([
                "powershell", "-Command",
                f'[System.Windows.Forms.MessageBox]::Show('
                f'"校园网自动登录失败：{safe_msg}", "SchoolAutoLogin")',
            ], timeout=10)
        return

    # GUI 模式：单实例守卫
    from src.instance import SingleInstance
    si = SingleInstance()
    if not si.acquire():
        log.info("已有实例运行，退出")
        return
    try:
        import customtkinter as ctk
        ctk.set_appearance_mode("dark")
        from src.app import App
        App().mainloop()
    finally:
        si.release()
```

> 保留现有 `run_silent()`、`if __name__ == "__main__": main()` 不变。

- [ ] **Step 2: 冒烟测试（dev 模式）**

Run: `python main.py --ensure`
Expected: 日志输出 `Ensure: auth=...`，正常退出（code 0）。再跑一次确认不报错。

- [ ] **Step 3: 跑全量回归**

Run: `pytest -q`
Expected: PASS（全部既有 + 新增用例）

- [ ] **Step 4: 提交**

```bash
git add main.py
git commit -m "feat: main 接入 --ensure 心跳分发 + GUI 单实例守卫"
```

> **Phase A 完成**：此时 `--ensure` + 多触发器任务 + 自愈已可用。即使不做 Phase B，今天 06-15 这类"任务被错过"也能被"登录时 + 每 15min 心跳"兜住。

---

## Phase B — 常驻托盘（秒级断网重连 + 关窗最小化）

### Task 8: 系统托盘模块（pystray + Pillow）

**Files:**
- Create: `src/tray.py`
- Test: `tests/test_tray.py`

- [ ] **Step 1: 写失败测试**（只测纯逻辑：状态标签、图标颜色选择）

```python
from src import tray


def test_state_label_connected():
    assert tray.state_label("connected") == "已连接"


def test_state_label_unknown():
    assert tray.state_label("whatever") == "未知"


def test_icon_color_for_disconnected_is_muted():
    assert tray.icon_color("disconnected") == tray.MUTED


def test_icon_color_for_connected_is_accent():
    assert tray.icon_color("connected") == tray.ACCENT
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_tray.py -v`
Expected: FAIL（`ModuleNotFoundError: src.tray`）

- [ ] **Step 3: 实现 `src/tray.py`**

```python
"""系统托盘：pystray + Pillow。状态驱动图标 + 右键菜单。

UI 更新由调用方驱动（update_state）；本模块不直接访问 GUI 线程。
"""

import logging

from PIL import Image, ImageDraw
import pystray

log = logging.getLogger(__name__)

ACCENT = (124, 58, 237, 255)   # #7c3aed
MUTED = (68, 68, 68, 255)      # #444444

_LABELS = {"connected": "已连接", "disconnected": "断网", "busy": "登录中…", "idle": "待命"}


def state_label(state: str) -> str:
    return _LABELS.get(state, "未知")


def icon_color(state: str):
    return MUTED if state == "disconnected" else ACCENT


def _make_icon(color) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle([10, 10, 54, 54], fill=color)
    return img


class Tray:
    """托盘控制器。回调：on_show / on_login / on_quit；get_state 返回当前状态字符串。"""

    def __init__(self, on_show, on_login, on_quit, get_state):
        self._on_show = on_show
        self._on_login = on_login
        self._on_quit = on_quit
        self._get_state = get_state
        self._icon: pystray.Icon | None = None

    def _menu(self):
        return pystray.Menu(
            pystray.MenuItem("打开主界面", lambda *_: self._on_show(), default=True),
            pystray.MenuItem("立即登录", lambda *_: self._on_login()),
            pystray.MenuItem(lambda _: f"状态：{state_label(self._get_state())}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda *_: self._on_quit()),
        )

    def start(self):
        """阻塞运行（请在 daemon 线程里调用）。"""
        self._icon = pystray.Icon("SchoolAutoLogin", _make_icon(ACCENT),
                                  "SchoolAutoLogin", self._menu())
        self._icon.run()

    def stop(self):
        if self._icon:
            self._icon.stop()
            self._icon = None

    def update_state(self, state: str):
        if self._icon:
            self._icon.icon = _make_icon(icon_color(state))
            self._icon.update_menu()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_tray.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/tray.py tests/test_tray.py
git commit -m "feat: 系统托盘模块（pystray，状态驱动）"
```

---

### Task 9: app 启动即自动登录 + 自动轮询 + 启动自愈

**Files:**
- Modify: `src/app.py`
- Test: `tests/test_app_resilience.py`

- [ ] **Step 1: 写失败测试**（测纯决策函数，避免依赖 GUI）

```python
from src.app import should_auto_start, should_minimize_to_tray


def test_auto_start_when_resilience_and_creds():
    assert should_auto_start({"resilience_enabled": True, "username": "u", "password": "p"}) is True


def test_auto_start_off_without_creds():
    assert should_auto_start({"resilience_enabled": True, "username": "", "password": ""}) is False


def test_auto_start_off_when_resilience_disabled():
    assert should_auto_start({"resilience_enabled": False, "username": "u", "password": "p"}) is False


def test_minimize_to_tray_when_resilience():
    assert should_minimize_to_tray({"resilience_enabled": True}) is True


def test_no_minimize_when_resilience_off():
    assert should_minimize_to_tray({"resilience_enabled": False}) is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_app_resilience.py -v`
Expected: FAIL（函数不存在）

- [ ] **Step 3: 实现**（修改 `src/app.py`）

文件顶部 import 区追加：

```python
from . import selfheal
from .tray import Tray
```

在 `class App` 之前新增模块级决策函数：

```python
def should_auto_start(cfg: dict) -> bool:
    """启动即自动登录 + 自动轮询的条件：resilience 开 且 有凭据。"""
    return bool(cfg.get("resilience_enabled", True)
                and cfg.get("username") and cfg.get("password"))


def should_minimize_to_tray(cfg: dict) -> bool:
    """关窗行为：resilience 开 → 最小化到托盘；否则正常退出。"""
    return bool(cfg.get("resilience_enabled", True))
```

在 `App.__init__` 末尾（`self.protocol(...)` 之后）追加启动钩子：

```python
        # ── L1 自主启动 + L5 启动自愈 ──
        self._tray: Tray | None = None
        if should_auto_start(self._cfg):
            self.after(0, self._auto_login_on_launch)
        # 启动自愈：对齐任务计划/自启（互为兜底的上半边）
        try:
            selfheal.reconcile_scheduler(self._cfg)
            selfheal.reconcile_autostart(self._cfg)
        except Exception as e:
            log.warning("Startup self-heal error: %s", e)
```

新增方法（放在 `_start_polling` 附近）：

```python
    def _auto_login_on_launch(self):
        """启动即触发一次登录，并在 resilience 下持续轮询。"""
        if self._cfg.get("resilience_enabled", True) or self._cfg.get("polling_enabled"):
            self._start_polling()
        # 后台登录一次
        threading.Thread(target=self._login_worker, args=(self._cfg.copy(),),
                         daemon=True).start()

    def _current_state(self) -> str:
        """供托盘读取的当前状态。"""
        return getattr(self._status, "_state", "idle")

    def _ensure_tray(self):
        """启动托盘守护线程（幂等）。"""
        if self._tray is None:
            self._tray = Tray(
                on_show=self._show_from_tray,
                on_login=self._do_login,
                on_quit=self._quit_from_tray,
                get_state=self._current_state,
            )
            threading.Thread(target=self._tray.start, daemon=True).start()

    def _show_from_tray(self):
        self.after(0, lambda: (self.deiconify(), self.lift(), self.focus_force()))

    def _quit_from_tray(self):
        self.after(0, self._real_quit)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_app_resilience.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/app.py tests/test_app_resilience.py
git commit -m "feat: app 启动即自动登录+轮询，启动自愈对齐任务/自启"
```

---

### Task 10: 关窗最小化到托盘 + 托盘生命周期

**Files:**
- Modify: `src/app.py`（`_on_close`、新增 `_real_quit`）

- [ ] **Step 1: 实现**（替换 `_on_close`，新增 `_real_quit`）

```python
    def _on_close(self):
        """关窗行为：resilience 开 → 隐藏到托盘并保活；否则真正退出。"""
        if should_minimize_to_tray(self._cfg):
            self._ensure_tray()
            self.withdraw()  # 隐藏窗口，进程保活继续轮询
            if self._cfg.get("notification_enabled", True):
                from . import notify
                notify.send("SchoolAutoLogin", "已在后台运行，断网自动重连")
        else:
            self._real_quit()

    def _real_quit(self):
        """真正退出：停轮询 + 停托盘 + 销毁窗口。"""
        self._stop_polling()
        if self._tray is not None:
            self._tray.stop()
            self._tray = None
        self.destroy()
```

- [ ] **Step 2: 让轮询在重连时更新托盘图标（避免通知刷屏）**

修改 `_poll_worker` 中"重连成功"分支，加状态转换限流（仅状态变化时通知）。在 `App.__init__` 增加：

```python
        self._last_notified_state: str | None = None
```

修改 `_poll_worker` 末尾 connected 分支为（替换原 `self.after(0, lambda: self._status.set_state("connected"))` 的几处）——抽一个统一回调：

```python
    def _set_state(self, state: str):
        """统一状态更新：UI + 托盘 + 限流通知。"""
        self._status.set_state(state)
        if self._tray:
            self._tray.update_state(state)
        # 通知限流：仅在状态从断网→已连接等转换时通知
        if state == "connected" and self._last_notified_state != "connected":
            if self._cfg.get("notification_enabled", True):
                notify.send("校园网", "已连接")
            self._last_notified_state = "connected"
        elif state == "disconnected":
            self._last_notified_state = "disconnected"
```

然后把 `_poll_worker` / `_done` 里所有 `self._status.set_state("x")` 替换为 `self.after(0, lambda: self._set_state("x"))`，并删除其中直接 `notify.send` 的重复调用（由 `_set_state` 统一负责，避免抖动刷屏）。

> 注意：`_do_login`→`_login_worker`→`_done` 链路里的成功通知也改走 `_set_state("connected")`，保证单一通知出口。

- [ ] **Step 3: 冒烟测试**

Run: `python main.py`
手动：填好凭据 → 关窗 → 应隐藏到托盘 + 弹"后台运行"通知；托盘右键"打开主界面"恢复窗口；"退出"真正退出。
Expected: 托盘图标出现，关窗不退出进程，日志持续轮询。

- [ ] **Step 4: 提交**

```bash
git add src/app.py
git commit -m "feat: 关窗最小化到托盘 + 通知限流（状态转换才通知）"
```

---

## Phase C — 打包 + 端到端验证

### Task 11: 打包配置（pystray/Pillow + 托盘图标）

**Files:**
- Modify: `main.spec`、`build.bat`
- Create: `assets/icon.ico`（若无；可用 Pillow 现场生成一个最小 ico 作占位，后续替换）

- [ ] **Step 1: 安装新依赖**

Run: `pip install pystray Pillow`
确认 `python -c "import pystray, PIL; print('ok')"` 输出 `ok`。

- [ ] **Step 2: 更新 `main.spec`**

在 PyInstaller `Analysis` 的 `hiddenimports` 加：

```python
    hiddenimports=["pystray._win32", "PIL"],
```

并在 `collect_data_files` 区追加（customtkinter 已有的旁边）：

```python
    datas=collect_data_files("customtkinter") + collect_data_files("PIL"),
```

> 如有 `assets/icon.ico`，可在 EXE 的 `icon='assets/icon.ico'` 指定（托盘图标在运行时由 Pillow 生成，不强制依赖外部文件）。

- [ ] **Step 3: 更新 `build.bat` 的依赖安装行**

把 `pip install pyinstaller customtkinter`（或等价行）改为：

```bat
pip install pyinstaller customtkinter pystray Pillow
```

- [ ] **Step 4: 一键打包验证**

Run: `build.bat`
Expected: 产出 `dist/SchoolAutoLogin.exe`（或 `installer_output/...exe`），无 PyInstaller import 报错。

- [ ] **Step 5: 冒烟打包产物**

Run: `dist\SchoolAutoLogin.exe --ensure`
Expected: 与 dev 模式一致，正常退出 code 0。

- [ ] **Step 6: 提交**

```bash
git add main.spec build.bat
git commit -m "build: 打包纳入 pystray/Pillow"
```

---

### Task 12: 端到端手动验证（四场景）

> 这些无法自动化，按清单逐项人肉验证并记录结果到本文件下方。

- [ ] **场景 ① 开机/重启/登录**：重启电脑 → 登录后 ≤1min 内 `login.log` 出现 `Ensure: auth=...` 且网络已通。
- [ ] **场景 ① 睡眠/唤醒**：合盖睡眠 → 唤醒 → ≤30s 内托盘轮询重连，日志出现 `Poll: reconnected`。
- [ ] **场景 ② 白天掉线**：登录后在认证页手动"注销" → ≤30s 内托盘自动重连 + 一次通知。
- [ ] **场景 ③ 进程崩溃**：任务管理器结束 SchoolAutoLogin 进程 → ≤15min 后任务计划心跳拉起托盘进程（`Ensure: detached tray spawned`）。
- [ ] **场景 ④ 任务被删（自启存活）**：`schtasks /delete /tn SchoolAutoLogin /f` → 双击 exe 启动 → 启动自愈重建任务（日志 `Self-heal: 重建任务计划`）。
- [ ] **场景 ④ 自启被删（任务存活）**：删注册表 Run 键 → 等 ≤15min 心跳 → 日志 `Self-heal: 重新开启自启`。

**验证记录：**
- （在此填写每项的日期 / 结果）

---

## Self-Review（计划自审）

**1. Spec 覆盖核对：**
- L1 自主启动 → Task 9 ✓
- L2 托盘常驻 → Task 8 + 10 ✓
- L3 多触发器任务 → Task 4 ✓
- L4 看门狗（心跳即看门狗）→ Task 6（`should_spawn_tray`）✓
- L5 自修复（互为兜底）→ Task 5（autostart）+ Task 9（scheduler，启动侧）✓
- 四场景 → Task 12 ✓
- 配置变更（resilience/heartbeat/polling 默认）→ Task 1 ✓
- `--ensure` 轻量 import（不拖 customtkinter）→ Task 7（`from src import ensure` 在 GUI import 之前）✓
- 通知限流（状态转换才通知）→ Task 10（`_set_state`）✓
- 心跳不做 WiFi 切换 → Task 3（`skip_wifi`）+ Task 6（调用传 `skip_wifi=True`）✓
- 旧任务迁移 → Task 4（`is_legacy_task`）+ Task 5（迁移分支）✓

**2. 占位符扫描：** 无 TBD/TODO；每步均有可执行代码或命令。

**3. 类型一致性核对：**
- `attempt_login(cfg, skip_wifi=False)` —— Task 3 定义，Task 6 调用一致 ✓
- `create_scheduled_task_multi(time_str, interval_minutes)` —— Task 4 定义，Task 5 调用一致 ✓
- `reconcile_autostart(cfg)` / `reconcile_scheduler(cfg)` —— Task 5 定义，Task 6/9 调用一致 ✓
- `tray_is_running()` —— Task 2 定义，Task 6 调用一致 ✓
- `should_auto_start` / `should_minimize_to_tray` —— Task 9 定义，Task 9/10 调用一致 ✓
- `SingleInstance(create_func=)` —— Task 2 定义，Task 7 使用默认 ✓

**已识别风险（执行时留意）：**
- `New-ScheduledTaskTrigger -Once ... -RepetitionDuration (New-TimeSpan -Days 3650)`：约 10 年；若个别 Windows 版本不接受超大值，回退用 `-RepetitionDuration ([TimeSpan]::MaxValue)` 或拆成 `-Daily` + repetition。Task 4 打包后需实际注册一次确认。
- `_spawn_tray_detached` 在 dev 模式用 `[sys.executable, exe_path()]`：`exe_path()` 在非 frozen 下返回 `Path(sys.argv[0])`，需确认其解析为 `main.py` 绝对路径（Task 7 冒烟时验证）。
- 托盘 `pystray.Icon.run()` 阻塞，必须在 daemon 线程跑（Task 10 的 `_ensure_tray` 已用 daemon 线程）。

---

## 执行交接

计划已写入 `docs/superpowers/plans/2026-06-15-resilience.md`。
按用户全局规则，**不在本会话自动执行**——请在新会话中执行。执行方式：

1. **Subagent-Driven（推荐）** — 用 superpowers:subagent-driven-development，每任务一个新 subagent，任务间审查。
2. **Inline Execution** — 用 superpowers:executing-plans，本会话批量执行 + 检查点。

建议从 Phase A 开始（Task 1→7），单独就能修掉"任务被错过"类问题；Phase B/C 随后推进。
