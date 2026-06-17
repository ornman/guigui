"""测试 dev 模式下任务计划命令显式指定解释器，绕开被抢占的 .py 关联。

背景：Windows UserChoice 可把 .py 关联到 VSCode（编辑器）而非 Python 解释器，
导致 dev 模式 Action=main.py 被 VSCode 拦截、进程空转
（任务触发但 Python 根本没跑，LastResult=0x41303 未运行，login.log 无新增）。
修复：dev 模式显式拼 pythonw.exe + main.py，frozen 模式保持原样。
"""

from pathlib import Path

from src import scheduler


class TestScheduledActionParts:
    """scheduled_action_parts：返回 (Execute, Argument) 供 New-ScheduledTaskAction 使用。"""

    def test_dev_uses_explicit_interpreter_for_ensure(self):
        """dev：Execute=解释器，Argument='"脚本" --ensure'，不依赖 .py 关联。"""
        exe, arg = scheduler.scheduled_action_parts("--ensure", executable="PYW", script="MAIN")
        assert exe == "PYW"
        assert arg == '"MAIN" --ensure'

    def test_frozen_exe_is_self_with_mode(self, monkeypatch):
        """frozen：Execute=exe 自身，Argument=mode（exe 自带入口，无需脚本）。"""
        monkeypatch.setattr(scheduler.sys, "frozen", True, raising=False)
        monkeypatch.setattr(scheduler.sys, "executable", r"C:\app\SchoolAutoLogin.exe")
        exe, arg = scheduler.scheduled_action_parts("--ensure")
        assert exe == r"C:\app\SchoolAutoLogin.exe"
        assert arg == "--ensure"


class TestInterpreterResolution:
    """_interpreter：dev 模式优先 pythonw.exe，缺失时回退 python.exe。"""

    def test_prefers_pythonw_when_present(self, tmp_path, monkeypatch):
        pyw = tmp_path / "pythonw.exe"
        pyw.touch()
        monkeypatch.setattr(scheduler.sys, "executable", str(tmp_path / "python.exe"))
        assert scheduler._interpreter() == str(pyw)

    def test_falls_back_to_python_when_no_pythonw(self, tmp_path, monkeypatch, caplog):
        """pythonw.exe 缺失时回退 python.exe 并记 warning（便于排查控制台黑窗）。"""
        monkeypatch.setattr(scheduler.sys, "executable", str(tmp_path / "python.exe"))
        with caplog.at_level("WARNING", logger="src.scheduler"):
            result = scheduler._interpreter()
        assert result == str(tmp_path / "python.exe")
        assert any("pythonw" in r.getMessage() for r in caplog.records)


def test_main_script_resolves_argv0(monkeypatch, tmp_path):
    """_main_script：基于 sys.argv[0] 解析为绝对路径。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(scheduler.sys, "argv", ["main.py"])
    result = scheduler._main_script()
    assert Path(result).is_absolute()
    assert result.endswith("main.py")
