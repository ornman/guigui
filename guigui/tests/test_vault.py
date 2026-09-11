"""vault:keyring 封装(伪后端替身,不碰真实凭据管理器)。"""

import pytest

from guigui.core import vault


class FakeKeyring:
    def __init__(self):
        self.store = {}
        self.broken = False

    def set_password(self, service, uid, password):
        if self.broken:
            raise RuntimeError("backend down")
        self.store[(service, uid)] = password

    def get_password(self, service, uid):
        if self.broken:
            raise RuntimeError("backend down")
        return self.store.get((service, uid))

    def delete_password(self, service, uid):
        if self.broken:
            raise RuntimeError("backend down")
        self.store.pop((service, uid), None)


class FakeAdvapi32:
    """advapi32 降级层的内存替身:同样按 TargetName(=uid@GuiGui)存。"""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.broken = False

    def write(self, target, password):
        if self.broken:
            raise OSError(1312)   # ERROR_NO_SUCH_USER 模拟系统拒绝
        self.store[target] = password

    def read(self, target):
        if self.broken:
            raise OSError(1008)
        return self.store.get(target)

    def delete(self, target):
        if self.broken:
            raise OSError(5)
        return self.store.pop(target, None) is not None


@pytest.fixture
def fake_keyring(monkeypatch):
    fk = FakeKeyring()
    monkeypatch.setattr(vault.keyring, "set_password", fk.set_password)
    monkeypatch.setattr(vault.keyring, "get_password", fk.get_password)
    monkeypatch.setattr(vault.keyring, "delete_password", fk.delete_password)
    return fk


@pytest.fixture
def fake_advapi(monkeypatch):
    """替换 vault 的 _direct_* 系列为内存桩。"""
    fa = FakeAdvapi32()
    monkeypatch.setattr(vault, "_direct_set", lambda target, pw: fa.write(target, pw))
    monkeypatch.setattr(vault, "_direct_get", lambda target: fa.read(target))
    monkeypatch.setattr(vault, "_direct_delete", lambda target: fa.delete(target))
    return fa


def test_set_get_has(fake_keyring):
    vault.set_password("2025000000001", "pw123")
    assert vault.has_password("2025000000001")
    assert vault.get_password("2025000000001") == "pw123"
    assert not vault.has_password("0000000000")


def test_delete_idempotent(fake_keyring):
    vault.set_password("u1", "p")
    vault.delete_password("u1")
    vault.delete_password("u1")  # 不存在也吞掉
    assert not vault.has_password("u1")


def test_rekey_moves_entry(fake_keyring):
    vault.set_password("old", "p1")
    vault.rekey("old", "new", "p2")
    assert vault.get_password("new") == "p2"
    assert not vault.has_password("old")


def test_backend_failure_raises_vault_error_not_plaintext(fake_keyring, fake_advapi):
    """主路坏 + 降级坏 → VaultError(纪律:永不回退明文)。"""
    fake_keyring.broken = True
    fake_advapi.broken = True
    with pytest.raises(vault.VaultError):
        vault.set_password("u", "p")


# ── P1-4:keyring 异常 → advapi32 降级 ────────────────────────────


def test_set_falls_back_to_advapi_when_keyring_broken(fake_keyring, fake_advapi):
    fake_keyring.broken = True
    vault.set_password("2025000000001", "pw123")
    assert vault.has_password("2025000000001")           # 走降级读出来
    assert vault.get_password("2025000000001") == "pw123"
    assert fake_advapi.store["2025000000001@GuiGui"] == "pw123"


def test_get_falls_back_to_advapi_when_keyring_broken(fake_keyring, fake_advapi):
    fake_advapi.store["2025000000001@GuiGui"] = "pw123"
    fake_keyring.broken = True
    assert vault.get_password("2025000000001") == "pw123"
    assert vault.has_password("2025000000001")


def test_get_returns_none_when_both_backends_fail(fake_keyring, fake_advapi):
    """读失败不抛(契约 §0 密码永不下行;读失败让上层判 None,不入强错误)。"""
    fake_keyring.broken = True
    fake_advapi.broken = True
    assert vault.get_password("u") is None
    assert vault.has_password("u") is False


def test_delete_falls_back_to_advapi_when_keyring_broken(fake_keyring, fake_advapi):
    fake_advapi.store["u1@GuiGui"] = "p"
    fake_keyring.broken = True
    vault.delete_password("u1")
    assert "u1@GuiGui" not in fake_advapi.store
    assert vault.get_password("u1") is None


def test_set_advapi32_only_writes_target_correctly(fake_keyring, fake_advapi):
    """直调路径的 TargetName 必须 = <uid>@GuiGui(与 keyring 同形状,卸载清理才能命中)。"""
    fake_keyring.broken = True
    vault.set_password("2025000000001", "pw")
    assert "2025000000001@GuiGui" in fake_advapi.store


# ── 卸载全删:枚举式清理(不依赖 config 当前学号)─────────────


def test_delete_all_matches_suffix_only():
    targets = ["2025000000001@GuiGui", "2024@GuiGui", "x@Other", "GuiGui"]
    deleted = []
    n = vault.delete_all_service_entries(
        enum_targets=lambda: targets,
        delete_target=lambda t: (deleted.append(t) or True))
    assert n == 2
    assert deleted == ["2025000000001@GuiGui", "2024@GuiGui"]


def test_delete_all_counts_failures():
    n = vault.delete_all_service_entries(
        enum_targets=lambda: ["a@GuiGui", "b@GuiGui"],
        delete_target=lambda t: False)
    assert n == 0


def test_delete_all_enum_failure_raises_vault_error():
    def boom():
        raise OSError("denied")

    with pytest.raises(vault.VaultError):
        vault.delete_all_service_entries(enum_targets=boom,
                                         delete_target=lambda t: True)


# ── 1.6.0 库链:备份镜像 / 重建×3 / 3 败降级 / failed ──────────


def test_set_mirrors_backup_and_state_ok(fake_keyring):
    vault.set_password("2025000000001", "pw123")
    import json as _json
    backup = _json.loads(vault.backup_path().read_text(encoding="utf-8"))
    assert backup == {"uid": "2025000000001", "password": "pw123"}
    assert vault.get_state() == vault.STATE_OK


def test_get_rebuilds_from_backup_and_recovers(fake_keyring, fake_advapi, monkeypatch):
    """两层读都抛(库坏)→ 重建轮重存后读通 → vault_state 回 ok,密码可用。"""
    vault.set_password("u1", "p1")                    # 正常期:条目 + 备份镜像
    # 模拟「读坏写好」:第 1 次读两层都抛 → 触发库链;重建轮里 _store 写得进、
    # _fetch 第 2 次起读得回
    reads = {"n": 0}

    def flaky_keyring_get(service, uid):
        raise RuntimeError("keyring lib broken")

    def flaky_direct_get(target):
        reads["n"] += 1
        if reads["n"] <= 1:
            raise OSError(1008)
        return "p1"

    monkeypatch.setattr(vault.keyring, "get_password", flaky_keyring_get)
    monkeypatch.setattr(vault, "_direct_get", flaky_direct_get)
    assert vault.get_password("u1") == "p1"
    assert vault.get_state() == vault.STATE_OK


def test_three_failed_rebuilds_degrade_to_backup(fake_keyring, fake_advapi):
    """3 轮重建全败 → 降级:备份库接管,密码照常读出,vault_state=degraded。"""
    vault.set_password("u1", "p1")
    fake_keyring.broken = True
    fake_advapi.broken = True
    assert vault.get_password("u1") == "p1"           # 备份接管,登录不断
    assert vault.get_state() == vault.STATE_DEGRADED
    # 恢复后下一次读自愈回 ok
    fake_keyring.broken = False
    fake_advapi.broken = False
    assert vault.get_password("u1") == "p1"
    assert vault.get_state() == vault.STATE_OK


def test_broken_vault_without_backup_is_failed(fake_keyring, fake_advapi):
    """库坏且无备份 → vault_state=failed(不发通知,状态可见走 diagnose)。"""
    fake_keyring.broken = True
    fake_advapi.broken = True
    assert vault.get_password("nobody") is None
    assert vault.get_state() == vault.STATE_FAILED


def test_corrupt_backup_with_broken_vault_is_failed(fake_keyring, fake_advapi):
    """库坏且备份 JSON 损坏 → failed(备份读不出就不算备份)。"""
    vault.set_password("u1", "p1")
    vault.backup_path().write_text("{corrupt", encoding="utf-8")
    fake_keyring.broken = True
    fake_advapi.broken = True
    assert vault.get_password("u1") is None
    assert vault.get_state() == vault.STATE_FAILED


def test_rebuild_serves_only_requested_uid(fake_keyring, fake_advapi, monkeypatch):
    """降级时备份 uid ≠ 请求 uid(换过学号的旧备份)→ 不串号,返回 None。"""
    vault.set_password("old-uid", "p1")
    fake_keyring.broken = True
    fake_advapi.broken = True
    assert vault.get_password("new-uid") is None
    assert vault.get_state() == vault.STATE_DEGRADED


def test_delete_password_clears_matching_backup(fake_keyring):
    """删凭据同步清备份(同 uid 才清;密码不残留磁盘)。"""
    vault.set_password("u1", "p1")
    assert vault.backup_path().exists()
    vault.delete_password("u1")
    assert not vault.backup_path().exists()


def test_rekey_keeps_new_backup_only(fake_keyring):
    """换学号:备份镜像跟随新学号;清旧条目不误删新备份。"""
    vault.set_password("old", "p1")
    vault.rekey("old", "new", "p2")
    import json as _json
    backup = _json.loads(vault.backup_path().read_text(encoding="utf-8"))
    assert backup == {"uid": "new", "password": "p2"}


def test_delete_all_service_entries_also_wipes_backup_and_state(fake_keyring):
    """卸载全删:凭据条目 + 备份库 + 状态文件一锅端。"""
    vault.set_password("u1", "p1")
    n = vault.delete_all_service_entries(enum_targets=lambda: ["u1@GuiGui"],
                                         delete_target=lambda t: True)
    assert n == 1
    assert not vault.backup_path().exists()
    assert not vault._state_path().exists()
