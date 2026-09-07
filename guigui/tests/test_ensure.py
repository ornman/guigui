"""ensure:收工幂等/等门/锚点/当拍即弹/可信度语义/假期静默/L4 兜底(全 mock + 固定时钟)。"""

import datetime as dt

from guigui.core import config, ensure, logstore

FIXED = dt.datetime(2026, 8, 31, 7, 0, 1)      # 锚后(>06:50)
BEFORE_OPEN = dt.datetime(2026, 8, 31, 6, 30)  # 锚前(<06:50,窗口期)


def _pair(r):
    """login_ex → login 两元组兼容壳(防真实网络的安全网)。"""
    return r.result, r.msg


class Harness:
    """按场景组装 mock:probe 序列 / login 序列 / chkstatus / wifi / 通知。"""

    def __init__(self, monkeypatch, *, cfg_over=None, probe_seq=None,
                 login_seq=None, connect_ok=True, password="pw123",
                 online_uid="2025000000001"):
        over = {"uid": "2025000000001"}
        over.update(cfg_over or {})
        self.cfg = config.save(dict(config.DEFAULTS, **over))
        self.probes = list(probe_seq or [{"state": "logged_in"}])
        self.logins = list(login_seq or [("success", "")])
        self.connect_calls = []
        self.gate_calls = []
        self.probe_calls = 0
        self.login_calls = 0
        self.sent = []
        self.online_uid = online_uid

        monkeypatch.setattr(ensure, "_now", lambda: self.now)
        monkeypatch.setattr(logstore, "_now", lambda: self.now)
        self.now = FIXED
        monkeypatch.setattr(ensure.vault, "get_password", lambda uid: password)
        monkeypatch.setattr(ensure.detect, "probe",
                            lambda cfg=None: self._probe())
        monkeypatch.setattr(ensure.detect, "wait_for_gate",
                            lambda *a, **k: self.gate_calls.append(1) or True)
        # login_seq 条目:2 元组 (result, msg) → payload=None/http=200;
        # 4 元组 (result, msg, payload, http) → 完整 login_ex 形态(拒绝现场 data 用)
        monkeypatch.setattr(ensure.drcom, "login_ex",
                            lambda *a, **k: self._login())
        monkeypatch.setattr(ensure.drcom, "login",
                            lambda *a, **k: _pair(self._login()))
        # 收工时线上真实学号(只读 chkstatus,PRD 4.6 他人会话如实记录)
        monkeypatch.setattr(ensure.drcom, "chkstatus_uid",
                            lambda base, timeout=5: self.online_uid)
        monkeypatch.setattr(ensure.time, "sleep", lambda s: None)
        monkeypatch.setattr(ensure.wifictl, "connect",
                            lambda ssid, timeout=90, progress=None:
                            self.connect_calls.append(ssid) or connect_ok)
        monkeypatch.setattr(ensure.notify, "send",
                            lambda t, m, launch=None: self.sent.append((t, launch)))

    def _probe(self):
        self.probe_calls += 1
        return self._pop(self.probes)

    def _login(self):
        self.login_calls += 1
        entry = self._pop(self.logins)
        if len(entry) == 2:
            entry = (entry[0], entry[1], None, 200)
        return ensure.drcom.LoginResult(*entry)

    @staticmethod
    def _pop(seq):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    def run(self):
        return ensure.run()

    def today_entries(self):
        for day in logstore.query(1):
            if day["label"] == "今天":
                return day["entries"]
        return []


def test_master_off_skips_everything(monkeypatch):
    h = Harness(monkeypatch, cfg_over={"master": False})
    called = []
    monkeypatch.setattr(ensure.detect, "probe", lambda cfg=None: called.append(1))
    assert h.run() == 0
    assert not called


def test_no_credentials_skips(monkeypatch):
    h = Harness(monkeypatch, cfg_over={"uid": ""}, password=None)
    assert h.run() == 0


def test_settle_writes_three_rows_and_state(monkeypatch):
    h = Harness(monkeypatch)
    assert h.run() == 0
    texts = [e["text"] for e in h.today_entries()]
    assert texts == ["网络可达", "已登录 · 2025…0001", "今天到这就下班啦 ☕"]
    state = ensure.load_state()
    assert state["last_settle_date"] == "2026-08-31"
    assert state["last_net_state"] == "up"
    assert state["last_result"]["outcome"] == "ok"
    assert h.sent == []                      # 首跑在线不通知


def test_settle_idempotent_same_day(monkeypatch):
    h = Harness(monkeypatch)
    h.run()
    h.run()                                  # 同日第二拍:秒退
    assert len(h.today_entries()) == 3


def test_early_success_uses_open_door_line(monkeypatch):
    h = Harness(monkeypatch, cfg_over={"trigger_time": "09:00"})  # 07:00 成功 < 09:00
    h.run()
    assert h.today_entries()[-1]["text"] == "开门即试,一次登好 ✓"


def test_rejected_notifies_immediately_once_per_day(monkeypatch):
    """AC-13:开门后被拒当拍即弹(不再等 3 次),每日 ≤1。"""
    h = Harness(monkeypatch, probe_seq=[{"state": "not_logged_in"}],
                login_seq=[("rejected", "userid error2")])
    h.run()
    assert len(h.sent) == 1 and h.sent[0][1] == "guigui://creds"
    state = ensure.load_state()
    assert state["fail_notify_date"] == "2026-08-31"
    assert h.today_entries()[-1]["text"] == "登录被拒:密码不对,改一下再试"
    h.run()                                          # 同日第二拍:不再弹
    assert len(h.sent) == 1


def test_success_resets_fail_gate(monkeypatch):
    h = Harness(monkeypatch, probe_seq=[{"state": "not_logged_in"}],
                login_seq=[("rejected", "userid error2")])
    h.run()
    assert ensure.load_state()["fail_notify_date"] == "2026-08-31"
    h.probes = [{"state": "not_logged_in"}]
    h.logins = [("success", "")]
    h.run()
    state = ensure.load_state()
    assert state["fail_notify_date"] is None and state["maintenance_streak"] == 0


def test_before_anchor_rejection_quarantined(monkeypatch):
    """AC-12:06:50 前被拒 — 只记「还没开门」,不判失败/不通知/不清可信度/单发收手。"""
    st = ensure.load_state(); st["cred_verified"] = True; ensure.save_state(st)
    h = Harness(monkeypatch, probe_seq=[{"state": "not_logged_in"}],
                login_seq=[("rejected", "userid error2")])
    h.now = BEFORE_OPEN
    h.run()
    assert [e["text"] for e in h.today_entries()] == ["还没开门(06:50 前),等下一拍"]
    assert h.sent == []                                # 不通知
    assert h.login_calls == 1                          # 锚前被拒不重试(对墙敲门无意义)
    state = ensure.load_state()
    assert state["cred_verified"] is True              # 不冤枉密码
    assert state["last_result"] is None                # 不判失败


def test_before_anchor_unreachable_waits_for_open(monkeypatch):
    """锚前不可达同样只记「还没开门」,不进假期静默状态机(防窗口期误累计)。"""
    h = Harness(monkeypatch, probe_seq=[{"state": "unreachable"}])
    h.now = BEFORE_OPEN
    h.run()
    state = ensure.load_state()
    assert state["unreachable_streak"] == 0
    assert state["last_unreachable_date"] is None
    assert h.today_entries()[-1]["text"] == "还没开门(06:50 前),等下一拍"


def test_bind_and_error1_keep_cred_verified(monkeypatch):
    """§7.3:置假仅 error2 一条路;bind / error1 不冤枉密码(但依旧当拍即弹)。"""
    st = ensure.load_state(); st["cred_verified"] = True; ensure.save_state(st)
    h = Harness(monkeypatch, probe_seq=[{"state": "not_logged_in"}],
                login_seq=[("rejected", "bind userid error")])
    h.run()
    assert ensure.load_state()["cred_verified"] is True
    assert any("自助服务平台" in e["text"] for e in h.today_entries())
    assert len(h.sent) == 1                            # 明确被拒仍即时通知
    st = ensure.load_state(); st["cred_verified"] = True; ensure.save_state(st)
    h2 = Harness(monkeypatch, probe_seq=[{"state": "not_logged_in"}],
                 login_seq=[("rejected", "userid error1")])
    h2.run()
    assert ensure.load_state()["cred_verified"] is True
    assert any("学号或运营商" in e["text"] for e in h2.today_entries())


def test_unknown_rejection_passthrough_keeps_verified(monkeypatch):
    """不认识的拒绝原文进日志,可信度不动(不猜)。"""
    st = ensure.load_state(); st["cred_verified"] = True; ensure.save_state(st)
    h = Harness(monkeypatch, probe_seq=[{"state": "not_logged_in"}],
                login_seq=[("rejected", "奇怪的新错误")])
    h.run()
    assert ensure.load_state()["cred_verified"] is True
    assert h.today_entries()[-1]["text"] == "登录被拒:奇怪的新错误"


def test_maintenance_page_three_beats_then_notify(monkeypatch):
    """维护页:连续 ≥3 拍才弹(点开看主面板),每日一次。"""
    h = Harness(monkeypatch, probe_seq=[{"state": "not_logged_in"}],
                login_seq=[("unexpected", "维护页")])
    h.run(); h.run()
    assert h.sent == []
    h.run()
    assert len(h.sent) == 1 and h.sent[0][1] == "guigui://main"
    h.run()
    assert len(h.sent) == 1


def test_waiting_then_gate_opens_then_settle(monkeypatch):
    h = Harness(monkeypatch, probe_seq=[{"state": "waiting"}, {"state": "logged_in"}])
    h.run()
    assert h.gate_calls                                # 等门被触发
    assert len(h.today_entries()) == 3                 # 开门即登,收工


def test_vacation_silence_two_days(monkeypatch):
    h = Harness(monkeypatch, probe_seq=[{"state": "unreachable"}])
    h.run()                                             # 第 1 天:普通不可达
    day1 = [e["text"] for e in h.today_entries()]
    assert day1 == ["连不上校园网"]
    assert ensure.load_state()["unreachable_streak"] == 1
    # 第 2 天(昨天有不可达记录)→ streak=2 → 静默
    h.now = FIXED + dt.timedelta(days=1)
    h.run()
    assert ensure.load_state()["silent"] is True
    days = logstore.query(2)
    labels = [d["label"] for d in days]
    assert any(l.endswith("· 假期静默") for l in labels)
    # 同日第 2 拍:不再记日志
    n_before = len([e for d in logstore.query(2) for e in d["entries"]])
    h.run()
    n_after = len([e for d in logstore.query(2) for e in d["entries"]])
    assert n_before == n_after


def test_silence_recovers_next_day(monkeypatch):
    h = Harness(monkeypatch, probe_seq=[{"state": "unreachable"}])
    h.run()                                             # 第 1 天:普通不可达
    h.now = FIXED + dt.timedelta(days=1)
    h.run()                                             # 第 2 天 → 静默
    assert ensure.load_state()["silent"] is True
    h.now = FIXED + dt.timedelta(days=2)                # 第 3 天回校 → 恢复
    h.probes = [{"state": "logged_in"}]
    h.run()
    state = ensure.load_state()
    assert state["silent"] is False and state["unreachable_streak"] == 0


def test_silent_same_day_beat_probes_nothing(monkeypatch):
    """AC-10:静默日同日后续拍零探测(每天只探 1 次的字面兑现)。"""
    h = Harness(monkeypatch, probe_seq=[{"state": "unreachable"}])
    h.run()
    h.now = FIXED + dt.timedelta(days=1)
    h.run()                                             # 进入静默
    n_probes = h.probe_calls
    h.run()                                             # 同日下一拍
    assert h.probe_calls == n_probes                    # 一发探测都没发


def test_recovered_notify_once_per_day(monkeypatch):
    h = Harness(monkeypatch, probe_seq=[{"state": "unreachable"}])
    h.run()                                             # down,无通知
    assert h.sent == []
    h.probes = [{"state": "logged_in"}]
    h.run()                                             # 断→通:通知一次
    assert len(h.sent) == 1 and h.sent[0][1] == "guigui://main"
    h.run()                                             # 同日:不再
    assert len(h.sent) == 1


def test_l4_fallback_connects_then_settles(monkeypatch):
    h = Harness(monkeypatch, cfg_over={"wifi_fallback_enabled": True,
                                       "wifi_fallback_ssid": "Campus-5G"},
                probe_seq=[{"state": "unreachable"}, {"state": "logged_in"}])
    h.run()
    assert h.connect_calls == ["Campus-5G"]
    texts = [e["text"] for e in h.today_entries()]
    assert "服务器不可达,切到兜底网络 Campus-5G" in texts
    assert "已登录 · 2025…0001" in texts


def test_l4_disabled_by_default(monkeypatch):
    h = Harness(monkeypatch, probe_seq=[{"state": "unreachable"}])
    h.run()
    assert h.connect_calls == []


def test_operator_forwarded_to_login(monkeypatch):
    h = Harness(monkeypatch, cfg_over={"operator": "校园电信"},
                probe_seq=[{"state": "not_logged_in"}], login_seq=[("success", "")])
    calls = []
    monkeypatch.setattr(ensure.drcom, "login_ex",
                        lambda *a, **k: calls.append(a)
                        or ensure.drcom.LoginResult("success", "", None, 200))
    h.run()
    assert calls, "drcom.login_ex 应被调用"
    args = calls[0]
    assert args[0] == "http://10.1.2.3" and args[1] == "2025000000001" and args[2] == "pw123"
    assert args[3] == "校园电信"                 # 第 4 参 = 配置里的运营商


def test_cred_verified_true_after_real_login(monkeypatch):
    h = Harness(monkeypatch, probe_seq=[{"state": "not_logged_in"}],
                login_seq=[("success", "")])     # 真登录成功 → tries>0
    h.run()
    assert ensure.load_state()["cred_verified"] is True


def test_cred_verified_false_on_error2(monkeypatch):
    h = Harness(monkeypatch, probe_seq=[{"state": "not_logged_in"}],
                login_seq=[("rejected", "userid error2")])
    h.run()
    assert ensure.load_state()["cred_verified"] is False


def test_cred_verified_default_false_when_already_online(monkeypatch):
    assert ensure.load_state()["cred_verified"] is False   # 全新状态 = 未验证
    h = Harness(monkeypatch)                               # 默认 probe=logged_in → tries=0
    h.run()
    assert ensure.load_state()["cred_verified"] is False   # 在线存入未验证,不翻 True


def test_settle_other_uid_recorded_not_disturbing(monkeypatch):
    """QA P0-2:线上是别人的学号 → 不冒领收工;记一笔并把会话换回自己的。"""
    h = Harness(monkeypatch, online_uid="2025090270999",
                login_seq=[("success", "")])
    h.run()
    texts = [e["text"] for e in h.today_entries()]
    assert any(t.startswith("线上是 2025…0999") for t in texts)   # 如实记一笔
    assert h.login_calls == 1                       # 真登录换会话,不是白收工
    assert "已登录 · 2025…0001" in texts            # 收工行是本人学号
    state = ensure.load_state()
    assert state["last_result"]["outcome"] == "ok"
    assert state["last_result"]["tries"] == 1
    assert state["cred_verified"] is True           # 换回自己的 = 真验证过
    assert h.sent == []                             # 换成功,不打扰


def test_settle_other_uid_rejected_reports_honestly(monkeypatch):
    """换会话被拒(如密码改过)→ 按被拒语义走全链(日志+当拍即弹),不假装成功。"""
    h = Harness(monkeypatch, online_uid="2025090270999",
                login_seq=[("rejected", "userid error2")])
    h.run()
    state = ensure.load_state()
    assert state["last_result"]["outcome"] == "fail"
    assert len(h.sent) == 1 and h.sent[0][1] == "guigui://creds"
    assert ensure.load_state()["cred_verified"] is False


def test_online_identity_unknown_settles_without_blocking(monkeypatch):
    """chkstatus 不可得 → 不阻塞,照常收工(可用性优先)。"""
    h = Harness(monkeypatch, online_uid=None)
    h.run()
    assert h.login_calls == 0
    assert "已登录 · 2025…0001" in [e["text"] for e in h.today_entries()]


# ── 拒绝现场入日志 data(S3,AC-F8/§4.1 logs 区)────────────

_LIMIT_PAYLOAD = {
    "result": 0, "uid": "2025000000001",
    "ss5": "172.16.0.1", "ss1": "00aa00bb00cc", "ss4": "00dd00ee00ff",
    "aolno": 6152, "ubind": "mac1='',ty1=0",
    "msga": "Oppp error: Limit Users Err",
}


def test_limit_users_full_chain(monkeypatch):
    """AC-F8:文案「已在别的设备登录」方向;cred_verified 不置假;
    data.rej=limit_users;服务器视角现场四件齐;URL(upass)永不入 data。"""
    st = ensure.load_state(); st["cred_verified"] = True; ensure.save_state(st)
    h = Harness(monkeypatch, probe_seq=[{"state": "not_logged_in"}],
                login_seq=[("rejected", "Oppp error: Limit Users Err",
                            _LIMIT_PAYLOAD, 200)])
    h.run()
    assert ensure.load_state()["cred_verified"] is True      # 不冤枉密码
    fails = [e for e in h.today_entries() if e["level"] == "fail"]
    assert len(fails) == 1
    text = fails[0]["text"]
    assert "别的设备" in text and "密码可能改过了" not in text
    d = fails[0]["data"]
    assert d["rej"] == "limit_users" and d["stage"] == "login"
    assert d["body_head"] == "Oppp error: Limit Users Err"
    assert d["server_view_ip"] == "172.16.0.1"
    assert d["mac_hint"] == ["00aa00bb00cc", "00dd00ee00ff"]
    assert d["aolno"] == 6152 and "mac1=" in d["ubind"]
    assert d["http"] == 200 and d["tries"] >= 1
    assert "upass" not in str(d) and "2025000000001" not in str(d)  # 红线


def test_error2_rejection_still_resets_cred_verified(monkeypatch):
    """对照:error2 仍是唯一置假路径,data.rej=error2。"""
    st = ensure.load_state(); st["cred_verified"] = True; ensure.save_state(st)
    h = Harness(monkeypatch, probe_seq=[{"state": "not_logged_in"}],
                login_seq=[("rejected", "userid error2", {"msga": "userid error2"}, 200)])
    h.run()
    assert ensure.load_state()["cred_verified"] is False
    d = [e for e in h.today_entries() if e["level"] == "fail"][0]["data"]
    assert d["rej"] == "error2"
    assert "server_view_ip" not in d                        # 普通拒绝无现场四件
