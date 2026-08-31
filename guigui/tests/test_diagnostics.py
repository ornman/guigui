"""diagnostics:反馈诊断文本 — 段落完整/打码纪律/任务分支。"""

import pytest

from guigui.core import diagnostics


class FakeDiag:
    def __init__(self, monkeypatch, *, uid="2025000000001", has_pw=True,
                 probe=None, main_xml=None, patrol_xml=None):
        from guigui.core import config
        config.save(dict(config.DEFAULTS, uid=uid))
        self.cfg = config.load()
        monkeypatch.setattr(diagnostics.detect, "probe",
                            lambda cfg=None: probe or {"state": "logged_in", "ssid": "Campus-WiFi"})
        monkeypatch.setattr(diagnostics.vault, "has_password", lambda u: has_pw)
        monkeypatch.setattr(diagnostics.scheduler, "query_xml",
                            lambda name: main_xml if name == "GuiGui" else patrol_xml)
        monkeypatch.setattr(diagnostics.drcom, "mask_uid", lambda u: (u[:4] + "…" + u[-4:]) if len(u) > 8 else u)


@pytest.fixture
def diag(monkeypatch):
    return FakeDiag(monkeypatch)


def test_text_has_all_sections(diag):
    text = diagnostics.build_text()
    for marker in ("诊断信息", "生成时间", "系统:", "── 网络 ──", "── 配置 ──",
                   "── 自动化任务 ──", "最近日志", "登录时间", "总开关"):
        assert marker in text


def test_uid_masked_password_never_present(diag, monkeypatch):
    from guigui.core import vault
    monkeypatch.setattr(vault, "get_password", lambda uid: "SECRET-PW-XYZ")
    text = diagnostics.build_text()
    assert "2025…0001" in text
    assert "2025000000001" not in text          # 明文学号不出现
    assert "SECRET-PW-XYZ" not in text          # 密码永不出现


def test_task_status_branches(monkeypatch):
    FakeDiag(monkeypatch,
             main_xml="<Description>GuiGui v2 automation rev=3</Description>",
             patrol_xml=None)
    text = diagnostics.build_text()
    assert "GuiGui:已注册(rev=3)" in text
    assert "GuiGui-Patrol:未注册" in text


def test_credentials_line_variants(monkeypatch):
    FakeDiag(monkeypatch, uid="", has_pw=False)
    assert "学号:未配置" in diagnostics.build_text()
    FakeDiag(monkeypatch, uid="2025000000001", has_pw=False)
    assert "凭据未保存" in diagnostics.build_text()


def test_recent_logs_included(diag):
    from guigui.core import logstore
    logstore.append("ok", "网络可达")
    logstore.append("fail", "登录被拒:密码可能改过了")
    text = diagnostics.build_text()
    assert "[今天" in text and "网络可达" in text and "登录被拒" in text


def test_no_logs_placeholder(diag):
    assert "(暂无日志)" in diagnostics.build_text()
