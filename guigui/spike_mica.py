"""路线 A spike:Win11 Mica 玻璃配方实机验证(独立文件,不进打包/不动生产代码)。

验证叠加链,四环缺一不可:
  pywebview transparent=True(WebView2 DefaultBackgroundColor=Transparent)
  × Form.BackColor=黑(DWM 玻璃洞配方的「洞色」)
  × DwmExtendFrameIntoClientArea(-1)(黑像素 → alpha 0 → DWM 材质从洞里透出)
  × DWMWA_SYSTEMBACKDROP_TYPE = Mica/Acrylic(22H2+;DWMWA_WINDOW_CORNER_PREFERENCE=ROUND 给系统 AA 圆角)

页面自带三组开关(材质/圆角/卡片浮起或满窗),默认即候选配方;
对照:切 None 材质应看到纯黑窗(证明黑洞生效),切「直角」看到方角(证明圆角来自 DWM 而非 rgn)。
运行:python guigui/spike_mica.py
"""
import ctypes
from ctypes import wintypes

import webview

# ── DWM 常量(dwmapi.h) ─────────────────────────────
DWMWA_WINDOW_CORNER_PREFERENCE = 33   # Win11+:窗口圆角偏好
DWMWA_SYSTEMBACKDROP_TYPE = 38        # Win11 22H2+:Mica/Acrylic 材质
DWMWCP_DEFAULT, DWMWCP_ROUND = 0, 2
DWMSBT_NONE, DWMSBT_MAINWINDOW, DWMSBT_TRANSIENTWINDOW = 1, 2, 3  # 2=Mica 3=Acrylic

_BACKDROP = {"none": DWMSBT_NONE, "mica": DWMSBT_MAINWINDOW, "acrylic": DWMSBT_TRANSIENTWINDOW}


class MARGINS(ctypes.Structure):
    _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]


def _dwa(hwnd: int, attr: int, val: int, tag: str) -> None:
    v = ctypes.c_int(val)
    hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(
        wintypes.HWND(hwnd), ctypes.c_uint(attr), ctypes.byref(v), ctypes.sizeof(v))
    print(f"[spike] DwmSetWindowAttribute {tag}({attr}={val}) hr=0x{hr & 0xffffffff:08x}", flush=True)


def _apply_glass(hwnd: int, form) -> None:
    """黑洞 + 材质 + 系统圆角。BackColor=黑必须在 ExtendFrame 之前(黑=洞色)。"""
    from System.Drawing import Color   # pythonnet 已由 pywebview 初始化
    form.BackColor = Color.FromArgb(255, 0, 0, 0)
    m = MARGINS(-1, -1, -1, -1)
    hr = ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
        wintypes.HWND(hwnd), ctypes.byref(m))
    print(f"[spike] DwmExtendFrameIntoClientArea(-1) hr=0x{hr & 0xffffffff:08x}", flush=True)
    _dwa(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_MAINWINDOW, "backdrop=mica")
    _dwa(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND, "corners=round")


class SpikeApi:
    """页面开关桥:材质/圆角两档(卡片浮起或满窗是纯 CSS,不走桥)。"""

    def backdrop(self, kind: str):
        kind = kind if kind in _BACKDROP else "none"
        w = webview.windows[0]
        _dwa(w.native.Handle.ToInt64(), DWMWA_SYSTEMBACKDROP_TYPE,
             _BACKDROP[kind], f"backdrop={kind}")

    def corners(self, on: bool):
        w = webview.windows[0]
        _dwa(w.native.Handle.ToInt64(), DWMWA_WINDOW_CORNER_PREFERENCE,
             DWMWCP_ROUND if on else DWMWCP_DEFAULT, f"corners={'round' if on else 'default'}")


PAGE = """<!DOCTYPE html><html><head><meta charset="UTF-8"><title>桂桂 spike / Mica</title><style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:transparent;height:100%}
body{display:flex;align-items:center;justify-content:center;
  font:15px/1.7 system-ui,"Microsoft YaHei",sans-serif}
.card{width:560px;height:640px;border-radius:22px;overflow:hidden;position:relative;
  border:1px solid rgba(255,255,255,.55);
  background:
    radial-gradient(420px 300px at 14% 0%, oklch(93% .05 300 / .55), transparent 70%),
    radial-gradient(460px 340px at 102% 104%, oklch(87% .07 330 / .45), transparent 70%),
    linear-gradient(168deg, oklch(92% .015 265), oklch(84% .025 285));
  box-shadow:0 24px 70px rgba(0,0,0,.5),0 2px 8px rgba(0,0,0,.3),
    inset 0 1px 0 rgba(255,255,255,.8),inset 0 -1px 0 rgba(255,255,255,.25);
  transition:all .25s}
body.bleed .card{width:100%;height:100%;border-radius:9px}
.tbar{display:flex;align-items:center;height:44px;padding:0 14px;
  border-bottom:1px solid rgba(255,255,255,.45);
  -webkit-app-region:drag}
.tbar b{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:#8a8499}
.wrap{padding:22px 26px;display:flex;flex-direction:column;gap:14px;height:596px}
h1{font-size:19px;color:#2b2740;font-weight:600}
p{color:#5a5573;font-size:13.5px}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:2px}
.row span{font-size:12px;color:#8a8499;width:44px}
button{padding:6px 12px;border-radius:9px;border:1px solid rgba(90,85,115,.35);
  background:rgba(255,255,255,.6);font:12.5px inherit;cursor:pointer;color:#2b2740}
button.on{background:#7c3aed;color:#fff;border-color:#7c3aed}
.hint{margin-top:auto;padding:10px 12px;border-radius:10px;font-size:12.5px;
  background:rgba(124,58,237,.08);color:#5a5573}
</style></head><body>
<div class="card">
  <div class="tbar"><b>桂桂 / Mica spike</b></div>
  <div class="wrap">
    <h1>玻璃配方验证页</h1>
    <p>看三件事:①四角是否抗锯齿圆角、角外透出桌面;②卡片与窗边的环带是否透出 Mica(磨砂壁纸,非黑非白);③卡片投影是否落在真玻璃上。</p>
    <div class="row"><span>材质</span>
      <button onclick="bd('none',this)">None</button>
      <button class="on" onclick="bd('mica',this)">Mica</button>
      <button onclick="bd('acrylic',this)">Acrylic</button></div>
    <div class="row"><span>圆角</span>
      <button class="on" onclick="cr(true,this)">系统8</button>
      <button onclick="cr(false,this)">直角</button></div>
    <div class="row"><span>卡片</span>
      <button class="on" onclick="cd('float',this)">浮起24</button>
      <button onclick="cd('bleed',this)">满窗</button></div>
    <div class="hint">对照逻辑:材质 None = 纯黑窗(黑洞生效);圆角直角 = 方角(圆角来自 DWM 而非裁剪);两个对照都成立,中间态才是真玻璃。</div>
  </div>
</div>
<script>
function mark(btn){btn.parentElement.querySelectorAll('button').forEach(b=>b.classList.remove('on'));btn.classList.add('on')}
function bd(k,btn){mark(btn);pywebview.api.backdrop(k)}
function cr(on,btn){mark(btn);pywebview.api.corners(on)}
function cd(m,btn){mark(btn);document.body.classList.toggle('bleed',m==='bleed')}
</script></body></html>"""


def main() -> None:
    win = webview.create_window(
        "桂桂 spike / Mica", PAGE, js_api=SpikeApi(),
        width=608, height=688,          # 卡片 560×640 + 24px 环带
        frameless=True, resizable=False, shadow=False, transparent=True, easy_drag=False)

    def _on_before_show():
        _apply_glass(win.native.Handle.ToInt64(), win.native)

    win.events.before_show += _on_before_show
    webview.start()


if __name__ == "__main__":
    main()
