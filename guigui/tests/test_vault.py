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


@pytest.fixture
def fake_keyring(monkeypatch):
    fk = FakeKeyring()
    monkeypatch.setattr(vault.keyring, "set_password", fk.set_password)
    monkeypatch.setattr(vault.keyring, "get_password", fk.get_password)
    monkeypatch.setattr(vault.keyring, "delete_password", fk.delete_password)
    return fk


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


def test_backend_failure_raises_vault_error_not_plaintext(fake_keyring):
    fake_keyring.broken = True
    with pytest.raises(vault.VaultError):
        vault.set_password("u", "p")
