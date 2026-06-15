from src.app import should_auto_start, should_minimize_to_tray


def test_auto_start_when_resilience_and_creds():
    assert should_auto_start({"resilience_enabled": True, "username": "u", "password": "p"}) is True


def test_auto_start_off_without_creds():
    assert should_auto_start({"resilience_enabled": True, "username": "", "password": ""}) is False


def test_auto_start_off_when_resilience_disabled():
    assert should_auto_start({"resilience_enabled": False, "username": "u", "password": "p"}) is False


def test_minimize_to_tray_when_resilience():
    assert should_minimize_to_tray({"resilience_enabled": True}) is True


def test_no_minimize_when_resilience_off():
    assert should_minimize_to_tray({"resilience_enabled": False}) is False
