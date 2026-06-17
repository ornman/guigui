from src.app import should_minimize_to_tray


def test_minimize_to_tray_when_resilience():
    assert should_minimize_to_tray({"resilience_enabled": True}) is True


def test_no_minimize_when_resilience_off():
    assert should_minimize_to_tray({"resilience_enabled": False}) is False
