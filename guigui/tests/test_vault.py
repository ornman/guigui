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
