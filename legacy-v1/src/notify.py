"""Windows Toast 通知 —— 通过 PowerShell 调用 WinRT API。"""

import logging
import subprocess

log = logging.getLogger(__name__)


def _xml_escape(text: str) -> str:
    """对文本进行 XML 实体转义，防止 Toast 模板注入。

    先转义五个 XML 特殊字符，再将高位字符（> 127）转为
    ``&#xHH;`` 十六进制实体，确保 GBK/UTF-8 混合环境下不乱码。
    """
    text = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
    return "".join(f"&#x{ord(c):X};" if ord(c) > 127 else c for c in text)


def send(title: str, message: str) -> None:
    """发送 Windows Toast 桌面通知。

    通过 PowerShell 调用 WinRT ``ToastNotificationManager`` 显示通知，
    使用 ShellExperienceHost 的 AppId 作为通知通道（无需单独注册）。

    Args:
        title: 通知标题（会经过 XML 转义）。
        message: 通知正文（会经过 XML 转义）。

    注意：
        - 超时时间 10 秒，超时或失败只记录日志，不抛异常。
        - 通知功能仅在 Windows 10+ 可用。
    """
    t, m = _xml_escape(title), _xml_escape(message)
    # PowerShell 脚本：加载 WinRT 类型 → 构建 Toast XML → 显示通知
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager,"
        " Windows.UI.Notifications, ContentType=WindowsRuntime]|Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom,"
        " ContentType=WindowsRuntime]|Out-Null;"
        f'$t=\'<toast duration="long"><visual><binding template="ToastGeneric">'
        f"<text>{t}</text><text>{m}</text>"
        '</binding></visual></toast>\';'
        "$x=New-Object Windows.Data.Xml.Dom.XmlDocument;"
        "$x.LoadXml($t);"
        "$toast=[Windows.UI.Notifications.ToastNotification]::new($x);"
        '[Windows.UI.Notifications.ToastNotificationManager]'
        '::CreateToastNotifier("Microsoft.Windows.ShellExperienceHost_cw5n1h2txyewy!App")'
        ".Show($toast)"
    )
    try:
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            log.warning("Notification failed (rc=%d): %s",
                        result.returncode, result.stderr.strip())
    except subprocess.TimeoutExpired:
        log.warning("Notification timed out")
    except Exception as e:
        log.warning("Notification error: %s", e)
