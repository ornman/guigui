from src import tray


def test_state_label_connected():
    assert tray.state_label("connected") == "已连接"


def test_state_label_unknown():
    assert tray.state_label("whatever") == "未知"


def test_icon_color_for_disconnected_is_muted():
    assert tray.icon_color("disconnected") == tray.MUTED


def test_icon_color_for_connected_is_accent():
    assert tray.icon_color("connected") == tray.ACCENT
