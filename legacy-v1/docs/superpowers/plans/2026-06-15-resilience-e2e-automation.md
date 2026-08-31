# 意外恢复系统 端到端自动化测试方案（Task 12 Automation）

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development 或 superpowers:executing-plans 逐任务执行。步骤用 `- [ ]` 复选框跟踪。
>
> 本方案承接 `2026-06-15-resilience.md` 的 Task 12。原 Task 12 是纯人工 e2e 清单；本方案把**可自动化的部分**抽成真实子系统集成测试，**不可自动化的部分**（重启/睡眠/手动注销）保留人工验证并给出代理校验项。

## 目标

用真实 Windows 子系统（任务计划 / 注册表 / 互斥量 / 子进程）验证 resilience 五层在真实环境下的行为，补上单测里全部用 mock 跳过的"真实注册/真实对齐"环节。

## 范围

### ✅ 可自动化（真实子系统，可逆）

| 场景 | 自动化测试 | 验证什么 |
|---|---|---|
| L3 多触发器注册 | `test_multi_trigger_task_registers_real_triggers` | 真实 `schtasks` 注册：三触发器（登录/心跳/每日）+ `--ensure` + `IgnoreNew` |
| ④a 任务被删 → 自愈重建 | `test_selfheal_rebuilds_deleted_task` | 删任务 → `reconcile_scheduler` → 任务重现（非 legacy） |
| 旧任务迁移 | `test_selfheal_migrates_legacy_task` | `--silent` 任务 → `reconcile_scheduler` → 迁移成 `--ensure` |
| ④b 自启被删 → 自愈重建 | `test_selfheal_reenables_deleted_autostart` | 删 Run 键 → `reconcile_autostart` → Run 键重现 |
| L2/L4 单实例互斥量 | `test_single_instance_mutex_blocks_second_holder` | 真实 Win32 互斥量跨 `SingleInstance` 实例互斥 |
| `--ensure` 独立可跑 | `test_ensure_subprocess_exits_zero` | `python main.py --ensure` 子进程退出码 0 |

### ❌ 不可自动化（人工，附代理项）

| 场景 | 为何不能自动化 | 代理校验（已由自动化覆盖） |
|---|---|---|
| ① 开机/重启（AtLogOn 实际点火） | 需真实重启 | `test_multi_trigger_task_registers_real_triggers` 校验 `<LogonTrigger>` 已注册 |
| ① 睡眠/唤醒 | 需物理合盖/唤醒 | 轮询线程逻辑已由 `test_login.py` 覆盖；唤醒后轮询恢复是 OS 行为 |
| ② 认证页手动注销后重连 | 需真网络 + 浏览器点"注销" | `attempt_login`/`skip_wifi` 已由 `test_login.py` 覆盖 |
| ③ 杀进程后等 15min 调度器点火 | 需一个在跑的 GUI + 真实等待 | `test_ensure_subprocess_exits_zero`（心跳可跑）+ 单测覆盖 `_spawn_tray_detached` 决策 |

## 安全机制

- **默认跳过**：`tests/test_e2e_resilience.py` 模块级 `pytest.mark.skipif(not os.environ.get("RUN_E2E"))`。裸 `pytest` 仍是 69 用例，不碰真实系统。
- **显式运行**：`set RUN_E2E=1 && python -m pytest tests/test_e2e_resilience.py -v`
- **每个测试可逆**：用 `clean_task` / `clean_autostart` fixture，`yield` 前后都清理（删任务、删 Run 键），不在开发机留痕。
- **互斥量隔离**：单实例测试用独立名字 `Local\SchoolAutoLogin-E2E-Test`，不与真实实例冲突。
- **无需管理员权限**：当前用户任务计划 + HKCU Run 键都不需要提权。

> ⚠️ 运行前确认：测试会用真实 `schtasks`/`reg` 操作本机的 `SchoolAutoLogin` 任务和 `HKCU\...\Run\SchoolAutoLogin` 键。fixture 会清理，但若中途中断可能残留——残留无害（下次运行或卸载会清）。

---

## 文件结构

**新建：** `tests/test_e2e_resilience.py`

---

## Task 1: 创建 e2e 测试文件骨架 + 安全守卫

**Files:** Create `tests/test_e2e_resilience.py`

- [ ] **Step 1: 写文件**（含模块级 skip 守卫 + 两个清理 fixture）

```python
"""端到端集成测试：真实 Windows 子系统（任务计划/注册表/互斥量/子进程）。

这些测试会修改真实的任务计划和注册表，默认跳过。
运行：set RUN_E2E=1 && python -m pytest tests/test_e2e_resilience.py -v
"""

import os
import subprocess
import sys

import pytest

from src import scheduler, selfheal, instance, autostart

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_E2E"),
    reason="E2E 测试改动真实任务计划/注册表；设置 RUN_E2E=1 后运行",
)

_TEST_MUTEX = "Local\\SchoolAutoLogin-E2E-Test"


@pytest.fixture
def clean_task():
    """每个测试前后确保 SchoolAutoLogin 任务计划不存在。"""
    scheduler.remove_scheduled_task()
    yield
    scheduler.remove_scheduled_task()


@pytest.fixture
def clean_autostart():
    """每个测试前后确保自启注册表键不存在。"""
    autostart.disable()
    yield
    autostart.disable()
```

- [ ] **Step 2: 确认默认跳过**

Run: `python -m pytest tests/test_e2e_resilience.py -v`
Expected: collected 0 items / 全部 skipped（因无 RUN_E2E），且 `python -m pytest -q` 仍是 69 用例。

---

## Task 2: 多触发器任务真实注册校验（L3）

- [ ] **Step 1: 追加测试**

```python
def test_multi_trigger_task_registers_real_triggers(clean_task):
    """真实注册多触发器任务，校验 XML 含三触发器 + --ensure + IgnoreNew。"""
    assert scheduler.create_scheduled_task_multi("06:55", 5) is True

    r = subprocess.run(
        ["schtasks", "/query", "/tn", scheduler.TASK_NAME, "/xml"],
        capture_output=True, text=True, timeout=15,
    )
    assert r.returncode == 0
    xml = r.stdout
    assert "--ensure" in xml            # 跑 --ensure，非 --silent
    assert "<LogonTrigger>" in xml      # 登录时触发器（① 开机代理）
    assert "<Repetition>" in xml        # 心跳重复触发器（③ 看门狗代理）
    assert "<CalendarTrigger>" in xml   # 每日触发器
    assert "IgnoreNew" in xml           # 防重叠实例堆积
    assert scheduler.is_legacy_task() is False
```

- [ ] **Step 2: 运行**（需 RUN_E2E）

Run: `set RUN_E2E=1 && python -m pytest tests/test_e2e_resilience.py::test_multi_trigger_task_registers_real_triggers -v`
Expected: PASS（任务真实注册、XML 含全部断言项、测试后任务被清理）。

> **若失败排查**：`RepetitionDuration (New-TimeSpan -Days 3650)` 在个别 Windows 版本可能被拒（计划自审已知风险）。若 `create_scheduled_task_multi` 返回 False，看 `login.log` 的 stderr，必要时把 3650 改小或换 `([TimeSpan]::MaxValue)`，记入验证记录。

---

## Task 3: 场景 ④a — 任务被删 → 自愈重建

- [ ] **Step 1: 追加测试**

```python
def test_selfheal_rebuilds_deleted_task(clean_task):
    """场景 ④a：删掉任务计划后，reconcile_scheduler 重建（多触发器 --ensure）。"""
    cfg = {"resilience_enabled": True, "scheduled_login_enabled": False,
           "scheduled_login_time": "06:55", "heartbeat_interval_minutes": 5}
    assert not scheduler.get_scheduled_task_info()["exists"]

    changed = selfheal.reconcile_scheduler(cfg)

    assert changed is True
    assert scheduler.get_scheduled_task_info()["exists"] is True
    assert scheduler.is_legacy_task() is False
```

- [ ] **Step 2: 运行**

Run: `set RUN_E2E=1 && python -m pytest tests/test_e2e_resilience.py::test_selfheal_rebuilds_deleted_task -v`
Expected: PASS。

---

## Task 4: 旧任务迁移

- [ ] **Step 1: 追加测试**

```python
def test_selfheal_migrates_legacy_task(clean_task):
    """旧 --silent 任务被 reconcile_scheduler 迁移成 --ensure 多触发器。"""
    cfg = {"resilience_enabled": True, "scheduled_login_enabled": True,
           "scheduled_login_time": "06:55", "heartbeat_interval_minutes": 5}
    assert scheduler.create_scheduled_task("06:55") is True   # legacy --silent
    assert scheduler.is_legacy_task() is True

    changed = selfheal.reconcile_scheduler(cfg)

    assert changed is True
    assert scheduler.is_legacy_task() is False
```

- [ ] **Step 2: 运行**

Run: `set RUN_E2E=1 && python -m pytest tests/test_e2e_resilience.py::test_selfheal_migrates_legacy_task -v`
Expected: PASS。

---

## Task 5: 场景 ④b — 自启被删 → 自愈重建

- [ ] **Step 1: 追加测试**

```python
def test_selfheal_reenables_deleted_autostart(clean_autostart):
    """场景 ④b：删掉自启注册表后，reconcile_autostart 重建（resilience 开）。"""
    cfg = {"resilience_enabled": True, "auto_start": False}
    assert autostart.is_enabled() is False

    changed = selfheal.reconcile_autostart(cfg)

    assert changed is True
    assert autostart.is_enabled() is True
```

- [ ] **Step 2: 运行**

Run: `set RUN_E2E=1 && python -m pytest tests/test_e2e_resilience.py::test_selfheal_reenables_deleted_autostart -v`
Expected: PASS（测试后 Run 键被清理）。

---

## Task 6: 单实例互斥量跨实例互斥（L2/L4）

- [ ] **Step 1: 追加测试**

```python
def test_single_instance_mutex_blocks_second_holder():
    """真实 Win32 互斥量：A 持有时 B 抢不到；A 释放后 C 可抢。"""
    si1 = instance.SingleInstance(name=_TEST_MUTEX)
    assert si1.acquire() is True
    try:
        si2 = instance.SingleInstance(name=_TEST_MUTEX)
        assert si2.acquire() is False          # 被阻塞
    finally:
        si1.release()

    si3 = instance.SingleInstance(name=_TEST_MUTEX)
    assert si3.acquire() is True               # 释放后可抢
    si3.release()
```

- [ ] **Step 2: 运行**

Run: `set RUN_E2E=1 && python -m pytest tests/test_e2e_resilience.py::test_single_instance_mutex_blocks_second_holder -v`
Expected: PASS。

---

## Task 7: --ensure 子进程独立可跑（L4 心跳）

- [ ] **Step 1: 追加测试**

```python
def test_ensure_subprocess_exits_zero():
    """真实跑 python main.py --ensure，退出码 0（心跳可独立运行）。"""
    r = subprocess.run(
        [sys.executable, "main.py", "--ensure"],
        capture_output=True, timeout=60,
    )
    assert r.returncode == 0
```

- [ ] **Step 2: 运行**

Run: `set RUN_E2E=1 && python -m pytest tests/test_e2e_resilience.py::test_ensure_subprocess_exits_zero -v`
Expected: PASS。

> **注意**：若 `config.json` 配了真实凭据且本机在校园网，`--ensure` 会真去 `10.1.2.3` 探测/登录（≤60s）。不在校园网则 `check_auth_status` 5s 超时返回 `unreachable`，仍退出 0。若超时，临时清空 `config.json` 的 `username`/`password` 再跑。

---

## Task 8: 全量 e2e + 回归

- [ ] **Step 1: 跑全部 e2e**

Run: `set RUN_E2E=1 && python -m pytest tests/test_e2e_resilience.py -v`
Expected: 7 passed。

- [ ] **Step 2: 确认默认套件不受影响**

Run: `python -m pytest -q`
Expected: 69 passed（e2e 被 skip，不进入默认计数）。

- [ ] **Step 3: 提交**

```bash
git add tests/test_e2e_resilience.py
git commit -m "test: 新增 resilience 端到端集成测试（真实 schtasks/注册表/互斥量，默认 skip）"
```

---

## Task 9: 人工验证记录（不可自动化的 4 项）

> 自动化跑完后，以下 4 项仍需真人操作。逐项做、把结果填到下方表格。

- [ ] **① 开机/重启**：重启电脑 → 登录后 ≤1min 内 `login.log` 出现 `Ensure: auth=` 且网络通。
- [ ] **① 睡眠/唤醒**：合盖睡眠 → 唤醒 → ≤30s 内托盘轮询重连，日志 `Poll: reconnected`。
- [ ] **② 白天掉线**：登录后在认证页手动"注销" → ≤30s 内托盘自动重连 + 一次通知。
- [ ] **③ 进程崩溃**：任务管理器结束 SchoolAutoLogin 进程 → ≤15min 后任务计划心跳拉起（日志 `Ensure: detached tray spawned`）。

**验证记录：**

| 场景 | 日期 | 结果（通过/失败） | 备注 |
|---|---|---|---|
| ① 重启 | | | |
| ① 睡眠/唤醒 | | | |
| ② 手动注销重连 | | | |
| ③ 崩溃恢复 | | | |
| ④a 任务被删（自动化）| | | 已由 `test_selfheal_rebuilds_deleted_task` 覆盖 |
| ④b 自启被删（自动化）| | | 已由 `test_selfheal_reenables_deleted_autostart` 覆盖 |

---

## Self-Review（方案自审）

**1. 覆盖核对：**
- L3 多触发器真实注册 → Task 2 ✓
- ④a/④b 自愈重建（删任务/删自启）→ Task 3 / Task 5 ✓
- 旧任务迁移 → Task 4 ✓
- L2/L4 单实例互斥量 → Task 6 ✓
- L4 心跳独立可跑 → Task 7 ✓
- ①/②/③ 不可自动化 → Task 9 人工 + 代理校验 ✓

**2. 安全性：**
- 默认 skip（无 `RUN_E2E` 不跑）→ Task 1 守卫 ✓
- 每测试 fixture 清理（task / autostart）→ 不留痕 ✓
- 互斥量用独立名 → 不冲突 ✓
- 无需提权 ✓

**3. 已知风险：**
- `RepetitionDuration -Days 3650` 个别 Windows 版本可能拒（见 Task 2 排查）。
- `--ensure` 子进程若在校园网+真实凭据下会真登录（Task 7 注意）。
- e2e 用真实 `exe_path()`（dev 模式=main.py），注册的任务 action 是 `main.py --ensure`——开发态 schtasks 注册校验没问题，但该任务**实际点火**需 `.py` 文件关联；真实点火验证在打包 exe 后做（人工 ③）。

---

## 执行交接

计划已写入 `docs/superpowers/plans/2026-06-15-resilience-e2e-automation.md`。
按用户全局规则，**不在本会话自动执行**——请在新会话中执行（`/clear` 后说"执行 e2e 自动化计划"）。执行方式：

1. **Subagent-Driven**（推荐）— superpowers:subagent-driven-development，Task 1→8 逐个派 subagent。
2. **Inline** — superpowers:executing-plans，本会话批量执行。

Task 1–8 是自动化（机器跑），Task 9 是人工（你跑）。建议 Task 1–8 先全绿，再做人肉 Task 9。
