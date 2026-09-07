"""selfheal:应建/应删/rev 失配重建/巡逻联动(mock scheduler)。"""

from guigui.core import selfheal


class FakeScheduler:
    def __init__(self):
        self.tasks: dict[str, str] = {}     # name → xml
        self.rev = 0
        self.block_logon_trigger = False    # 模拟安全软件拦「登录触发」任务

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
        if self.block_logon_trigger and "<LogonTrigger>" in xml:
            return False
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
