"""Windows auto-start management via HKCU Run registry key."""

import logging
import winreg

from .scheduler import autostart_command

log = logging.getLogger(__name__)

_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_REG_NAME = "SchoolAutoLogin"


def enable() -> bool:
    """Register the app in HKCU Run key. Returns True on success."""
    cmd = autostart_command()
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH, 0,
                             winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, _REG_NAME, 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(key)
        log.info("Auto-start enabled: %s", cmd)
        return True
    except Exception as e:
        log.error("Failed to enable auto-start: %s", e)
        return False


def disable() -> bool:
    """Remove the app from HKCU Run key. Returns True on success."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH, 0,
                             winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, _REG_NAME)
        winreg.CloseKey(key)
        log.info("Auto-start disabled")
        return True
    except FileNotFoundError:
        log.info("Auto-start entry does not exist, nothing to remove")
        return True
    except Exception as e:
        log.error("Failed to disable auto-start: %s", e)
        return False


def is_enabled() -> bool:
    """Check if auto-start is currently enabled."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH, 0,
                             winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(key, _REG_NAME)
        winreg.CloseKey(key)
        return bool(value)
    except FileNotFoundError:
        return False
    except Exception:
        return False
