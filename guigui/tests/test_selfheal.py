"""selfheal:应建/应删/rev 失配重建/巡逻联动/停试退避(mock scheduler)。"""

from guigui.core import ensure, selfheal


class FakeScheduler:
    def __init__(self):
        self.tasks: dict[str, str] = {}     # name → xml
        self.rev = 0
        self.block_logon_trigger = False    # 模拟安全软件拦「登录触发」任务
        self.block_all = False              # 模拟安全软件拦全部建单(ADR-0006 停试用)
        self.create_calls = 0               # 建单调用计数(停试后应停止增长)

    def is_task_current(self, name, cfg, require_logon=False):
        xml = self.tasks.get(name)
        if xml is None or f'rev={cfg["tasks_rev"]}' not in xml:
            return False
        if require_logon and "<LogonTrigger>" not in xml:
            return False
        return True

    def query_xml(self, name):
        return self.tasks.get(name)

    def create_task(self, name, xml):
        if self.block_all or (self.block_logon_trigger and "<LogonTrigger>" in xml):
            return False
        self.create_calls += 1
        self.tasks[name] = xml
        return True

    def remove_task(self, name):
        self.tasks.pop(name, None)
        return True


def _wire(monkeypatch, fake):
    monkeypatch.setattr(selfheal.scheduler, "is_task_current", fake.is_task_current)
    monkeypatch.setattr(selfheal.scheduler, "query_xml", fake.query_xml)
    monkeypatch.setattr(selfheal.scheduler, "create_task", fake.create_task)
    monkeypatch.setattr(selfheal.scheduler, "remove_task", fake.remove_task)


def _cfg(**over):
    base = {
        "master": True, "patrol_enabled": False, "tasks_rev": 1,
        "trigger_time": "07:00", "heartbeat_minutes": 5,
        "boot_login": True, "wake_login": False, "patrol_minutes": 30,
    }
    base.update(over)
    return base


def test_creates_missing_main_task(monkeypatch):
    """P1-7:master 开 + 巡逻关 → 建 GuiGui / GuiGui-Boot(boot 默认开)两个任务。"""
    fake = FakeScheduler()
    _wire(monkeypatch, fake)
    assert selfheal.reconcile(_cfg()) == (True, False)
    assert "GuiGui" in fake.tasks and "GuiGui-Boot" in fake.tasks
    assert "GuiGui-Patrol" not in fake.tasks
    assert "GuiGui-Wake" not in fake.tasks    # wake_login 默认关 → 不建
    # 主任务只含日历触发(LogonTrigger 已迁出)
    assert "<CalendarTrigger>" in fake.tasks["GuiGui"]
    assert "<LogonTrigger>" not in fake.tasks["GuiGui"]


def test_no_change_when_aligned(monkeypatch):
    fake = FakeScheduler()
    _wire(monkeypatch, fake)
    selfheal.reconcile(_cfg())
    assert selfheal.reconcile(_cfg()) == (False, False)  # 已对齐 → 幂等不动


def test_master_off_removes(monkeypatch):
    fake = FakeScheduler()
    _wire(monkeypatch, fake)
    selfheal.reconcile(_cfg())
    assert selfheal.reconcile(_cfg(master=False, tasks_rev=2)) == (True, False)
    assert fake.tasks == {}


def test_rev_bump_rebuilds(monkeypatch):
    fake = FakeScheduler()
    _wire(monkeypatch, fake)
    selfheal.reconcile(_cfg(tasks_rev=1))
    # 调度字段变化 → tasks_rev+1 → 旧任务 rev 失配 → 重建
    assert selfheal.reconcile(_cfg(tasks_rev=2)) == (True, False)
    assert "rev=2" in fake.tasks["GuiGui"]


def test_patrol_follows_switch(monkeypatch):
    fake = FakeScheduler()
    _wire(monkeypatch, fake)
    selfheal.reconcile(_cfg(patrol_enabled=True))
    assert "GuiGui-Patrol" in fake.tasks
    selfheal.reconcile(_cfg(patrol_enabled=False, tasks_rev=3))
    assert "GuiGui-Patrol" not in fake.tasks
    assert "GuiGui" in fake.tasks                          # 主任务不受巡逻开关影响


def test_wake_task_created_when_enabled(monkeypatch):
    """P1-7:wake_login=True 时建 GuiGui-Wake(独立任务,Action 带 --trigger wake)。"""
    fake = FakeScheduler()
    _wire(monkeypatch, fake)
    selfheal.reconcile(_cfg(wake_login=True, tasks_rev=2))
    assert "GuiGui-Wake" in fake.tasks
    assert "<EventTrigger>" in fake.tasks["GuiGui-Wake"]
    assert "--trigger wake" in fake.tasks["GuiGui-Wake"]


def test_create_blocked_reports_misaligned(monkeypatch):
    """建任务被安全软件拦截 → (changed=False, misaligned=True),调用方据此 toast。"""
    fake = FakeScheduler()
    _wire(monkeypatch, fake)
    monkeypatch.setattr(
        selfheal.scheduler, "create_task", lambda name, xml: False)
    changed, misaligned = selfheal.reconcile(_cfg())
    assert changed is False and misaligned is True
    assert fake.tasks == {}                                # 什么都没建成


def test_remove_blocked_reports_misaligned(monkeypatch):
    fake = FakeScheduler()
    _wire(monkeypatch, fake)
    selfheal.reconcile(_cfg())
    monkeypatch.setattr(
        selfheal.scheduler, "remove_task", lambda name: False)
    changed, misaligned = selfheal.reconcile(_cfg(master=False, tasks_rev=2))
    assert changed is False and misaligned is True


def test_degraded_registration_when_logon_blocked(monkeypatch):
    """P1-7:安全软件拦登录触发 → GuiGui-Boot 降级(无 LogonTrigger),GuiGui 不受影响。"""
    fake = FakeScheduler()
    fake.block_logon_trigger = True
    _wire(monkeypatch, fake)
    changed, misaligned = selfheal.reconcile(_cfg())     # boot_login=True
    assert changed is True and misaligned is False       # 降级成功,不算失配
    # GuiGui-Boot 被降级(无 LogonTrigger),GuiGui(日历)未受影响
    assert "<LogonTrigger>" not in fake.tasks["GuiGui-Boot"]
    assert "CalendarTrigger" in fake.tasks["GuiGui"]     # 每日触发还在


def test_degraded_task_upgrades_after_unblock(monkeypatch):
    """P1-7:GuiGui-Boot 降级任务不算最新;放行后下一次对齐自动升级回含 LogonTrigger。"""
    fake = FakeScheduler()
    fake.block_logon_trigger = True
    _wire(monkeypatch, fake)
    selfheal.reconcile(_cfg())
    fake.block_logon_trigger = False                      # 安全软件放行
    changed, _ = selfheal.reconcile(_cfg())               # rev 未变仍要重建
    assert changed is True
    assert "<LogonTrigger>" in fake.tasks["GuiGui-Boot"]  # 已升级回完整版


# ── ADR-0006 停试退避(2026-09-12 拍板:阈值 3)──────────────


def test_three_consecutive_failures_stop_retry(monkeypatch):
    """ADR-0006:同任务连续 3 次建立失败 → 停试降级,后续 reconcile 零建单。"""
    fake = FakeScheduler()
    fake.block_all = True
    _wire(monkeypatch, fake)
    cfg = _cfg(boot_login=False, wake_login=True)         # 意图 = 主任务 + 唤醒
    for i in (1, 2):
        assert selfheal.reconcile(cfg) == (False, True)
        assert ensure.load_state()["task_fail_streak"]["GuiGui"] == i
    selfheal.reconcile(cfg)                               # 第 3 败:达阈值
    streaks = ensure.load_state()["task_fail_streak"]
    assert streaks["GuiGui"] == 3 and streaks["GuiGui-Wake"] == 3
    assert selfheal.degraded_tasks() == ["GuiGui", "GuiGui-Wake"]
    n = fake.create_calls
    changed, misaligned = selfheal.reconcile(cfg)         # 第 4 次:停试,零建单
    assert (changed, misaligned) == (False, True)
    assert fake.create_calls == n                         # 没再向杀软交建单
    assert selfheal.degraded_tasks() == ["GuiGui", "GuiGui-Wake"]


def test_rebuild_clears_streak_and_recovers(monkeypatch):
    """恢复入口 = 用户动作:clear_fail_streaks 清零后全量重试即建成、账本归空。"""
    fake = FakeScheduler()
    fake.block_all = True
    _wire(monkeypatch, fake)
    cfg = _cfg(boot_login=False, wake_login=False)        # 只主任务
    for _ in range(3):
        selfheal.reconcile(cfg)
    assert selfheal.degraded_tasks() == ["GuiGui"]
    selfheal.clear_fail_streaks()                         # rebuildTask 先做的清零
    assert selfheal.degraded_tasks() == []
    fake.block_all = False                                # 杀软放行
    assert selfheal.reconcile(cfg) == (True, False)
    assert "GuiGui" in fake.tasks
    assert ensure.load_state()["task_fail_streak"] == {}


def test_task_current_clears_streak(monkeypatch):
    """任务在岗(外部恢复/他人修好)= 连败清零,不冤枉持续拦。"""
    fake = FakeScheduler()
    fake.block_all = True
    _wire(monkeypatch, fake)
    cfg = _cfg(boot_login=False, wake_login=False)
    selfheal.reconcile(cfg)                               # 1 败
    assert ensure.load_state()["task_fail_streak"] == {"GuiGui": 1}
    fake.block_all = False
    fake.tasks["GuiGui"] = f'<Task rev={cfg["tasks_rev"]}><Command>x</Command></Task>'
    assert selfheal.reconcile(cfg) == (False, False)      # 在岗:零改动零失配
    assert ensure.load_state()["task_fail_streak"] == {}


def test_old_state_without_streak_key_is_safe(monkeypatch):
    """旧 ensure_state(无 task_fail_streak 键)→ reconcile 照常工作不炸(向后兼容)。"""
    import json

    from guigui.core import paths
    fake = FakeScheduler()
    _wire(monkeypatch, fake)
    p = paths.state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"last_net_state": "up"}), encoding="utf-8")
    assert selfheal.reconcile(_cfg()) == (True, False)
    assert ensure.load_state()["task_fail_streak"] == {}
