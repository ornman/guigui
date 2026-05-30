"""Windows toast notification via PowerShell WinRT."""

import subprocess


def _xml_escape(text: str) -> str:
    text = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
    return "".join(f"&#x{ord(c):X};" if ord(c) > 127 else c for c in text)


def send(title: str, message: str) -> None:
    t, m = _xml_escape(title), _xml_escape(message)
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
    subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True,
    )
