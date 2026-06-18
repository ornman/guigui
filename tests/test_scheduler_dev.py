"""测试 dev 模式下任务计划命令显式指定解释器，绕开被抢占的 .py 关联。

背景：Windows UserChoice 可把 .py 关联到 VSCode（编辑器）而非 Python 解释器，
导致 dev 模式 Action=main.py 被 VSCode 拦截、进程空转
（任务触发但 Python 根本没跑，LastResult=0x41303 未运行，login.log 无新增）。
修复：dev 模式显式拼 pythonw.exe + main.py，frozen 模式保持原样。
"""

from pathlib import Path
from unittest.mock import patch

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


def test_main_script_falls_back_when_argv_is_dash_c(monkeypatch, tmp_path):
    """``python -c`` 模式下 argv[0]=='-c'，_main_script 不得 resolve 成 ``<cwd>\\-c``。

    历史 bug：曾因 ``python -c "..."`` 触发部署，sys.argv[0]=='-c' 被 resolve 成
    ``<cwd>\\-c`` 并写进任务 Action，导致任务每次触发都启动失败（返回码 2、零日志）。
    应回退到基于本模块位置定位的项目根 main.py。
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(scheduler.sys, "argv", ["-c"])
    result = scheduler._main_script()
    assert result.endswith("main.py")
    assert "-c" not in result
    # 回退路径必须指向真实存在的 main.py
    assert Path(result).exists()


class TestWindowedTaskDetection:
    """is_windowed_task：结构标签齐全 之外，Action 脚本路径必须真实存在。

    历史 bug：仅检查 ``--ensure``/``<LogonTrigger>``/``CalendarTrigger+Repetition`` 标签，
    坏任务（Action 指向不存在的 ``-c`` 文件）恰好标签齐全，被误判「已对齐」，
    self-heal 永不重建，故障任务长期苟活。
    """

    @staticmethod
    def _xml(arguments: str) -> str:
        """构造一个结构标签齐全的核心窗口任务 XML（Action/Arguments 可定制）。"""
        return (
            "<Task><Actions><Exec><Command>pythonw.exe</Command>"
            f"<Arguments>{arguments}</Arguments></Exec></Actions>"
            "<Triggers>"
            "<LogonTrigger><Enabled>true</Enabled></LogonTrigger>"
            "<CalendarTrigger><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>"
            "<Repetition><Interval>PT15M</Interval></Repetition>"
            "</CalendarTrigger>"
            "</Triggers></Task>"
        )

    def test_rejects_when_action_script_missing(self):
        """Action 指向不存在的脚本（如历史 -c 污染）→ 即使结构标签齐全也判 False。"""
        xml = self._xml(r'"C:\nonexistent\-c" --ensure')
        with patch("src.scheduler._task_xml", return_value=xml):
            assert scheduler.is_windowed_task() is False

    def test_accepts_when_action_script_exists(self):
        """Action 指向真实存在的 main.py → True。"""
        main_py = Path(scheduler.__file__).resolve().parent.parent / "main.py"
        xml = self._xml(f'"{main_py}" --ensure')
        with patch("src.scheduler._task_xml", return_value=xml):
            assert scheduler.is_windowed_task() is True
