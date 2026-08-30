"""guigui 测试公共夹具:数据目录注入临时目录(隔离本机真实状态)。"""

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(autouse=True)
def tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GUIGUI_DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture(scope="session", autouse=True)
def _repo_on_path():
    """确保 `import guigui` 可用(pytest 从任意目录启动)。"""
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    yield
