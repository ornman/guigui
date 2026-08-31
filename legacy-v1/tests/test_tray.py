from src import tray


def test_state_label_connected():
    assert tray.state_label("connected") == "已连接"


def test_state_label_unknown():
    assert tray.state_label("whatever") == "未知"


def test_icon_color_for_disconnected_is_muted():
    assert tray.icon_color("disconnected") == tray.MUTED


def test_icon_color_for_connected_is_accent():
    assert tray.icon_color("connected") == tray.ACCENT


def test_tray_menu_builds_without_live_icon():
    """Tray 构造 + _menu() 在无活动图标时也能成功（覆盖导入/API 回归）。"""
    t = tray.Tray(lambda: None, lambda: None, lambda: None, lambda: "idle")
    menu = t._menu()
    assert menu is not None
