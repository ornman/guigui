"""--ensure 静默执行体 — 探测 → 必要时登录 → 状态翻转才通知 + 假期静默状态机。

移植 v1 src/ensure.py 骨架(原子写 state);v2 新增:
等门(waiting→轮询 30s/上限 10min)、L4 WiFi 兜底、假期静默
(连续 48h 不可达 → 每天只探 1 次不通知,silent 级日志)、
收工幂等(last_settle_date,后续拍秒退)、last_result(recentResult 数据源)。
2026-09-06 重梳理:开门锚点 06:50(锚前失败三不管)、被拒当拍即弹、
凭证可信度仅 error2 置假、线上他人学号如实记录并换回自己的(QA P0-2:
别人的成功不冒领)、日志 >90 天清理。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import tempfile
import time

from . import config, detect, drcom, logstore, notify, scheduler, vault, wifictl
from . import paths

log = logging.getLogger(__name__)

_now = dt.datetime.now  # 测试可注入

# 开门锚点(PRD 4.5/4.6,校园实测:认证服务器每天 06:50 前不接受登录)。
# 非用户配置 — 是校园侧事实;锚点行为待真机窗口期复核(PRD 8.5.3)。
ANCHOR_TIME = (6, 50)


def before_anchor(when: dt.datetime | None = None) -> bool:
    """当前时刻是否在当日开门锚点(06:50)之前。"""
    when = when or _now()
    return (when.hour, when.minute) < ANCHOR_TIME


def _default_state() -> dict:
    return {
        "last_net_state": None,          # up | down | failed | None(首跑)
        "last_recovered_notify_date": None,
        "fail_notify_date": None,        # 当拍即弹的每日闸(AC-13)
        "maintenance_streak": 0,         # 维护页(格式不认识)连续拍数
        "maintenance_notify_date": None,
        "unreachable_streak": 0,
        "last_unreachable_date": None,
        "silent": False,
        "last_settle_date": None,
        "last_result": None,             # {date, time, tries, outcome}
        "cred_verified": False,          # 凭证是否经服务器真验证(仅 error2 置假,§7.3)
        "task_lost_notify_date": None,   # 定时任务失联通知每日闸(QA P1-5)
    }


def load_state() -> dict:
    state = _default_state()
    p = paths.state_path()
    if p.exists():
        try:
            state.update(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("ensure: 读状态失败(%s),从头记", e)
    return state


def save_state(state: dict) -> None:
    """原子写(tempfile + os.replace,v1 移植);失败只记日志。"""
    p = paths.state_path()
    tmp = None
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp", prefix=".state_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp, p)
    except OSError as e:
        log.warning("ensure: 状态持久化失败: %s", e)
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _is_early(cfg: dict, when: dt.datetime | None = None) -> bool:
    """成功时刻早于设定时间 T(首拍提前登好 →「开门即试」行,§5.3)。"""
    when = when or _now()
    h, m = (int(x) for x in cfg["trigger_time"].split(":"))
    return (when.hour, when.minute) < (h, m)


def _attempt_login(cfg: dict, uid: str, password: str):
    """单轮登录:retries 次 × retry_seconds 间隔。返回 (最终分类, 尝试次数, msg, verdict)。

    verdict = 最后一次 login_ex 完整结果(拒绝现场入日志 data 用,PRD §4.1)。
    锚前(06:50 前)被拒直接收手 — 门都没开,重试只是对着墙敲门(绝不暴力尝试)。
    节流(QA P1-6):服务器让等 waitsec → 按其秒数睡(封顶 WAITSEC_CAP),不烧
    retry 次数 — 节流不是密码错,理应让节流完整到期再判失败。"""
    result, msg = drcom.UNREACHABLE, ""
    tries = 0
    verdict = None
    for i in range(max(1, cfg["login_retries"])):
        tries += 1
        verdict = drcom.login_ex(cfg["url"], uid, password,
                                 cfg.get("operator", "校园用户"))
        result, msg = verdict.result, verdict.msg
        if result == drcom.SUCCESS:
            break
        if result == drcom.REJECTED and before_anchor():
            break
        # 节流分支(QA P1-6):不计入重试节奏,直接睡到服务器让的时间再试
        if (result == drcom.REJECTED
                and drcom.classify_rejection(msg, waitsec=verdict.waitsec,
                                             payload=verdict.payload)
                == drcom.REJ_THROTTLED):
            wait = min(verdict.waitsec or drcom.WAITSEC_CAP, drcom.WAITSEC_CAP)
            time.sleep(wait)
            continue
        if i < cfg["login_retries"] - 1:
            time.sleep(cfg["retry_seconds"])
    return result, tries, msg, verdict


def _probe_with_gate(cfg: dict) -> dict:
    """探测;waiting 时先等门(开门后重探),等不到按不可达收线。"""
    net = detect.probe(cfg)
    if net["state"] == detect.WAITING:
        log.info("ensure: 网络栈未就绪,门口等门…")
        detect.wait_for_gate(cfg=cfg)
        net = detect.probe(cfg)
        if net["state"] == detect.WAITING:
            net = {"state": detect.UNREACHABLE, "detail": "gate-timeout"}
    return net


def _ensure_online(cfg: dict, uid: str, password: str, allow_fallback: bool = True):
    """把网络推到「已登录」。返回 ("settled", tries, "", None)
    | ("rejected", tries, msg, verdict) | ("unexpected", tries, msg, verdict)
    | ("unreachable", 0, "", None)。

    unreachable 时按 L4 策略切兜底 WiFi 后重试一轮(仅一次,防循环)。
    """
    net = _probe_with_gate(cfg)
    if net["state"] == detect.LOGGED_IN:
        # 全屋共享会话:在线的可能是室友账号 — 收工前核对线上学号,
        # 别人的成功不冒领;不一致如实记一笔并把会话换成自己的
        # (chkstatus 不可得 → 不阻塞,照常收工)
        online = drcom.chkstatus_uid(cfg["url"])
        if online and online != uid:
            logstore.append(
                "note",
                f"线上是 {drcom.mask_uid(online)}(不是配置的学号),换回自己的",
                when=_now())
            net = {"state": detect.NOT_LOGGED_IN, "detail": "session-takeover"}
        else:
            return "settled", 0, "", None
    if net["state"] == detect.NOT_LOGGED_IN:
        result, tries, msg, verdict = _attempt_login(cfg, uid, password)
        if result == drcom.SUCCESS:
            return "settled", tries, "", None
        if result == drcom.REJECTED:
            return "rejected", tries, msg, verdict
        if result == drcom.UNEXPECTED:
            return "unexpected", tries, msg, verdict
        # 登录请求整体不可达 → 落到 L4
    if allow_fallback and cfg.get("wifi_fallback_enabled") and cfg.get("wifi_fallback_ssid"):
        ssid = cfg["wifi_fallback_ssid"]
        logstore.append("note", f"服务器不可达,切到兜底网络 {ssid}", when=_now())
        if wifictl.connect(ssid):
            return _ensure_online(cfg, uid, password, allow_fallback=False)
    return "unreachable", 0, "", None


def _settle_rows(cfg: dict, uid: str, tries: int) -> None:
    """当日首次成功:网络可达 / 已登录·打码(线上他人学号如实记录)/ 开门即试或收工(§5.3)。"""
    logstore.append("ok", "网络可达", when=_now())
    shown_uid = uid
    if tries == 0:
        # 桂桂没动手就在线:查线上真实学号(只读 chkstatus);正常路径线上
        # 已核对是本人(_ensure_online),此处兜底展示/竞态时如实记录(4.6)
        online = drcom.chkstatus_uid(cfg["url"])
        if online:
            shown_uid = online
            if online != uid:
                logstore.append("note", f"线上的是 {drcom.mask_uid(online)}(不是配置的学号,只记录)",
                                when=_now())
    logstore.append("ok", f"已登录 · {drcom.mask_uid(shown_uid)}", when=_now())
    if _is_early(cfg):
        logstore.append("ok", "开门即试,一次登好 ✓", when=_now())
    else:
        logstore.append("note", "今天到这就下班啦 ☕", when=_now())


def _apply_notify(cfg: dict, state: dict, *, connected: bool,
                  outcome: str | None = None) -> None:
    """去重决策 + 发送 + 状态合并(connected 分支由调用方先置好其他键)。

    锚前分支不会走到这(run() 已提前收线);此处 outcome 仅传失败形态。
    """
    kind, updates = notify.decide_notify(
        state.get("last_net_state"), connected=connected,
        outcome=outcome, before_anchor=False,
        maintenance_streak=state.get("maintenance_streak", 0),
        last_recovered_date=state.get("last_recovered_notify_date"),
        fail_notify_date=state.get("fail_notify_date"),
        maintenance_notify_date=state.get("maintenance_notify_date"),
        today=_today(),
    )
    state.update(updates)
    if kind and cfg.get("notifications", True):
        if kind == notify.RECOVERED:
            notify.send("已连上 ✓", "网络回来了", notify.LAUNCH_MAIN)
        elif kind == notify.MAINTENANCE:
            notify.send("桂桂一直登不上", "点开看看", notify.LAUNCH_MAIN)
        else:
            notify.send("登录失败,密码改了?", "点这里改一下密码", notify.LAUNCH_CREDS)


def _today() -> str:
    return _now().strftime("%Y-%m-%d")


def _check_task_in_place(state: dict, cfg: dict, today: str) -> None:
    """任务在岗自检(QA P1-5):主任务被拦/丢失/挪走时如实记录 + 每日弹一次。

    触发条件:不在假期静默同日(那路径本就跑不到这里);master 关时不自检
    (run 早就 return 了,这里的 cfg.master 必然 True)。
    设计原则:--ensure 短进程**只报告不重建**(plan §67)。rebuild 是 GUI 侧
    rebuildTask(契约 §2.14)的职责,避免静默进程和管理侧抢,也不在静默
    路径里和 selfheal 互锁。
    """
    if state.get("silent"):
        return
    xml = scheduler.query_xml(scheduler.TASK_MAIN)
    if xml is not None and scheduler.action_target_exists(xml):
        return
    # 任务失联:仅记日期 + 每日一拍(去重靠 task_lost_notify_date,避免连拍刷屏)
    if state.get("task_lost_notify_date") != today:
        state["task_lost_notify_date"] = today
        if cfg.get("notifications", True):
            notify.task_lost()


def _persist(state: dict, cfg: dict, today: str) -> int:
    """落盘 + 任务在岗自检(QA P1-5)+ 必要时再落一次。统一收尾,run() 五个分支都用。"""
    save_state(state)
    prev = state.get("task_lost_notify_date")
    _check_task_in_place(state, cfg, today)
    if state.get("task_lost_notify_date") != prev:
        save_state(state)
    return 0


def _apply_settle(cfg: dict, state: dict, today: str, uid: str, tries: int) -> None:
    """当日首次成功:收工三行 + 计数复位 + last_result + 通知判断(不落盘)。"""
    _settle_rows(cfg, uid, tries)
    state.update({
        "last_settle_date": today,
        "fail_notify_date": None, "maintenance_streak": 0,
        "maintenance_notify_date": None,
        "unreachable_streak": 0, "silent": False,
        "last_result": {"date": today, "time": _now().strftime("%H:%M"),
                        "tries": tries, "outcome": "ok"},
    })
    _apply_notify(cfg, state, connected=True, outcome=None)


def settle_from_gui(cfg: dict, uid: str, tries: int) -> None:
    """GUI 登录成功后的收工入口 — 与 ensure 同一套日志/状态/通知语义。

    同日已收工则不动(手动重登不重复写收工行)。
    """
    state = load_state()
    today = _today()
    if state.get("last_settle_date") == today:
        return
    _apply_settle(cfg, state, today, uid, tries)
    save_state(state)


def _fail_data(kind: str | None, verdict, tries: int) -> dict | None:
    """拒绝现场(PRD §4.1 logs 区 data / §8 server.last_verdict 的数据源)。

    红线:只存服务器响应字段,请求 URL(含 upass=)永不入 data;
    limit_users 现场四件(ss5/ss1/ss4/aolno/ubind)有才带。"""
    if verdict is None:
        return None
    p = verdict.payload if isinstance(verdict.payload, dict) else {}
    data: dict = {
        "stage": "login",
        "tries": tries,
        "http": verdict.http,
        "rej": drcom.REJ_CODE.get(kind),
        "body_head": drcom.scrub_uids(str(verdict.msg or "")[:80]) or None,
    }
    try:
        data["ssid"] = wifictl.current_ssid()
    except Exception:
        pass
    if p.get("ss5"):
        data["server_view_ip"] = p["ss5"]
    mac = [p[k] for k in ("ss1", "ss4") if p.get(k)]
    if mac:
        data["mac_hint"] = mac
    if p.get("aolno") is not None:
        data["aolno"] = p["aolno"]
    if p.get("ubind"):
        data["ubind"] = drcom.scrub_uids(p["ubind"])
    return {k: v for k, v in data.items() if v is not None}


def run(trigger: str = "calendar") -> int:
    """静默主流程;任何分支结束前统一落 state(原子写)。

    trigger ∈ {"calendar", "boot", "wake", "patrol"},scheduler 通过
    --trigger <name> 在 Action Arguments 传入(无效值按 calendar 处理)。
    P1-7 返校日豁免:boot/wake 触发时,silent 同日压制不生效(返校日天然伴随
    开机/唤醒,应作为恢复点正常探测);calendar/patrol 维持字面秒退。
    """
    if trigger not in ("calendar", "boot", "wake", "patrol"):
        trigger = "calendar"
    cfg = config.load()
    if not cfg.get("master"):
        return 0
    uid = cfg.get("uid") or ""
    password = vault.get_password(uid) if uid else None
    if not uid or not password:
        log.info("ensure: 未配置凭据,跳过")
        return 0

    state = load_state()
    today = _today()

    # 假期静默同日:进门即退,零探测请求(AC-10「每天只探 1 次」的字面兑现)
    # 但开机/唤醒触发属于返校日天然恢复点,豁免压制(QA P1-7)。
    if (state.get("silent") and state.get("last_unreachable_date") == today
            and trigger not in ("boot", "wake")):
        return 0

    # 日志卫生:每拍顺带清一次 >90 天的日志文件(AC-18,只动桂桂自己目录)
    logstore.cleanup_old()

    outcome, tries, msg, verdict = _ensure_online(cfg, uid, password)

    if outcome == "settled":
        if state.get("last_settle_date") == today:
            return 0  # 登上就停:后续拍零日志零通知(任务在岗已在首拍查过)
        _apply_settle(cfg, state, today, uid, tries)
        if tries > 0:
            state["cred_verified"] = True  # 真登录成功 = 凭证经服务器验证
        return _persist(state, cfg, today)

    # 开门锚点(AC-12):06:50 前的被拒/不可达一律只算「还没开门」—
    # 不判失败、不计数、不通知、不动 cred_verified、不进假期静默状态机
    if before_anchor():
        logstore.append("note", "还没开门(06:50 前),等下一拍", when=_now())
        return _persist(state, cfg, today)

    if outcome in ("rejected", "unexpected"):
        kind = (drcom.classify_rejection(msg, waitsec=verdict.waitsec,
                                         payload=verdict.payload)
                if outcome == "rejected" else None)
        # 节流(QA P1-6):服务器让等几秒再试,不是密码错也不进失败闸;
        # _attempt_login 已按 waitsec 睡过,这里仅记一笔 note + 结束当拍,
        # 下次任务计划触发会重试
        if outcome == "rejected" and kind == drcom.REJ_THROTTLED:
            wait = min(verdict.waitsec or drcom.WAITSEC_CAP, drcom.WAITSEC_CAP)
            logstore.append("note",
                            f"服务器让等 {wait} 秒再试(节流,非密码错)",
                            when=_now())
            state["last_result"] = {"date": today, "time": _now().strftime("%H:%M"),
                                    "tries": tries, "outcome": "throttled"}
            return _persist(state, cfg, today)
        if outcome == "rejected":
            text = "登录被拒:" + drcom.rejection_text(kind, msg or "密码可能改过了")
            state["maintenance_streak"] = 0
        else:
            text = "认证服务器返回了不认识的格式"
            state["maintenance_streak"] = state.get("maintenance_streak", 0) + 1
        logstore.append("fail", text, when=_now(),
                        data=_fail_data(kind, verdict, tries))
        # 凭证可信度(§7.3):置假仅一条路 — 服务器明确说密码不对(error2);
        # error1/bind/维护页/节流都不冤枉密码
        if outcome == "rejected" and kind == drcom.REJ_WRONG_PASSWORD:
            state["cred_verified"] = False
        state["last_result"] = {"date": today, "time": _now().strftime("%H:%M"),
                                "tries": tries, "outcome": "fail"}
        _apply_notify(cfg, state, connected=False, outcome=outcome)
        return _persist(state, cfg, today)

    # unreachable:假期静默状态机(AC-10)
    if state.get("last_unreachable_date") != today:
        prev = state.get("last_unreachable_date")
        yesterday = (_now() - dt.timedelta(days=1)).strftime("%Y-%m-%d")
        streak = state.get("unreachable_streak", 0) + 1 if prev == yesterday else 1
        silent = bool(cfg.get("vacation_silence", True)) and streak >= 2
        if silent:
            logstore.append("silent", "连不上,今天先不打扰,明天再试一次", when=_now())
        else:
            logstore.append("fail", "连不上校园网", when=_now())
        state.update({
            "unreachable_streak": streak,
            "last_unreachable_date": today,
            "silent": silent,
            "last_result": {"date": today, "time": _now().strftime("%H:%M"),
                            "tries": 0, "outcome": "silent" if silent else "fail"},
        })
    # 同日后续拍:不重复记日志/不更新 last_result,只走通知判断(永不通知)
    _apply_notify(cfg, state, connected=False, outcome=None)
    return _persist(state, cfg, today)
