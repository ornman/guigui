"""WiFi 管理 —— 通过 netsh 命令切换无线网络。"""

import logging
import subprocess
import time

log = logging.getLogger(__name__)


def current_ssid() -> str | None:
    """获取当前连接的 WiFi SSID，未连接或出错时返回 None。

    解析 ``netsh wlan show interfaces`` 输出，匹配 ``SSID : xxx`` 行，
    排除 ``BSSID`` 行避免误匹配。
    """
    try:
        r = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        for line in r.stdout.splitlines():
            line = line.strip()
            # 排除 BSSID 行，只匹配当前连接的 SSID
            if line.startswith("SSID") and "BSSID" not in line and ":" in line:
                return line.split(":", 1)[1].strip() or None
    except Exception as e:
        log.warning("Cannot detect Wi-Fi: %s", e)
    return None


def _find_profile(target_ssid: str) -> str | None:
    """在已保存的 WiFi 配置文件列表中查找 *target_ssid*。

    部分系统需要通过 profile 名称连接而非 SSID，此方法确保使用
    正确的 profile 名称。找不到时返回 None（后续会 fallback 到 SSID）。
    """
    try:
        r = subprocess.run(
            ["netsh", "wlan", "show", "profiles"],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        for line in r.stdout.splitlines():
            if ":" not in line:
                continue
            name = line.split(":", 1)[1].strip()
            if name == target_ssid:
                return name
    except Exception as e:
        log.warning("Cannot list WiFi profiles: %s", e)
    return None


def connect(target_ssid: str, retries: int = 3, wait: int = 30) -> bool:
    """切换到 *target_ssid* 指定的 WiFi 网络。

    流程：检查是否已连接 → 查找 profile → 执行 netsh connect →
    轮询等待连接成功。

    Args:
        target_ssid: 目标 WiFi 名称。
        retries: 最大重试次数。
        wait: 每次重试后等待连接的最大秒数。

    Returns:
        True 表示连接成功，False 表示失败。
    """
    cur = current_ssid()
    if cur == target_ssid:
        log.info("Already on '%s'", target_ssid)
        return True

    log.info("Switching to '%s'...", target_ssid)
    # 优先使用已保存的 profile 名称，找不到则直接用 SSID
    profile = _find_profile(target_ssid) or target_ssid

    for attempt in range(1, retries + 1):
        log.info("WiFi connect attempt %d/%d", attempt, retries)
        try:
            subprocess.run(
                ["netsh", "wlan", "connect", f"ssid={target_ssid}", f"name={profile}"],
                capture_output=True, text=True, timeout=15,
            )
        except Exception as e:
            log.error("netsh failed: %s", e)
            continue

        # 每 3 秒轮询一次，检查是否已成功切换
        deadline = time.time() + wait
        while time.time() < deadline:
            time.sleep(3)
            if current_ssid() == target_ssid:
                log.info("Connected to '%s'", target_ssid)
                return True

    log.warning("Failed to connect to '%s'", target_ssid)
    return False
