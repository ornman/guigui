"""selfheal:应建/应删/rev 失配重建/巡逻联动(mock scheduler)。"""

from guigui.core import selfheal


class FakeScheduler:
    def __init__(self):
        self.tasks: dict[str, str] = {}     # name → xml
        self.rev = 0

    def is_task_current(self, name, cfg):
        xml = self.tasks.get(name)
        return xml is not None and f'rev={cfg["tasks_rev"]}' in xml

    def query_xml(self, name):
        return self.tasks.get(name)

    def create_task(self, name, xml):
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
    fake = FakeScheduler()
    _wire(monkeypatch, fake)
    assert selfheal.reconcile(_cfg()) == (True, False)
    assert "GuiGui" in fake.tasks and "GuiGui-Patrol" not in fake.tasks


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
