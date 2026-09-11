"""guigui 测试公共夹具:数据目录注入临时目录(隔离本机真实状态)。"""

import sys
from pathlib import Path

import pytest

from guigui.core import notify as _notify_mod

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# 真身留档:test_notify 里要真测 send 的用例经 _real_notify_send 恢复(它们自带 subprocess mock)
_REAL_NOTIFY_SEND = _notify_mod.send


@pytest.fixture(autouse=True)
def _toast_never_fires(monkeypatch):
    """安全网(2026-09-11 实锤教训):测试进程绝不真弹 Windows toast —
    1.6.0 把「成功也发/连不上也发」接进 ensure.settle 后,夹具只 mock 了旧的
    直发类(task_blocked/linger),settle 路径的 notify.send 裸奔,每轮 pytest
    在用户屏幕真弹一串通知。toast 唯一漏斗是 notify.send,在此全量换成 no-op
    记录器;用例自己 monkeypatch send/subprocess 的,后打补丁自然覆盖本网。"""
    fired = []
    monkeypatch.setattr(_notify_mod, "send",
                        lambda *a, **k: fired.append((a, k)))
    yield fired


@pytest.fixture
def real_notify_send(monkeypatch):
    """恢复真 notify.send(test_notify 的 send 系用例用;自带 subprocess mock)。"""
    monkeypatch.setattr(_notify_mod, "send", _REAL_NOTIFY_SEND)
    yield _REAL_NOTIFY_SEND


@pytest.fixture(autouse=True)
def tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GUIGUI_DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture(autouse=True)
def _notify_direct_reset():
    """清 notify 直发类(task_blocked 等)进程内冷却账本(1.6.0)—
    同一 pytest 进程里多个测试触发同类直发,账本不清会串场吞掉后测的 toast。"""
    from guigui.core import notify
    notify._direct_last.clear()
    yield
    notify._direct_last.clear()


@pytest.fixture(scope="session", autouse=True)
def _repo_on_path():
    """确保 `import guigui` 可用(pytest 从任意目录启动)。"""
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    yield
