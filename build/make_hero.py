# -*- coding: utf-8 -*-
"""
릴리즈 노트용 시계 이미지 생성기.

실제 앱을 큰 배율로 띄워 화면을 캡처한 뒤, 원 바깥을 잘라내
'시계만 남은' 투명 배경 PNG를 만든다. (별도 렌더러를 만들지 않으므로
실제 화면과 100% 같은 그림이 나온다)
"""

import os
import sys
import time

sys.path.insert(0, r"E:\IBANK\timer")
os.chdir(r"E:\IBANK\timer")

from PIL import Image, ImageDraw, ImageGrab      # noqa: E402

import tray_timer as T                            # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else r"E:\IBANK\timer\docs"
RENDER_SCALE = 3.4          # 화면에 들어가는 선에서 최대한 크게
os.makedirs(OUT, exist_ok=True)

T.UI_SCALE = RENDER_SCALE
T._enable_dpi_awareness()

app = T.TrayTimerUI()
app.root.update()
# 캡처가 배경에 방해받지 않도록 화면 좌상단으로 옮긴다
app.root.geometry("+40+40")
app.root.update()

SHOTS = []


def capture(tag: str) -> str:
    app.root.update_idletasks()
    app.root.update()
    time.sleep(0.35)
    app.root.update()

    x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
    size = app.g.size
    img = ImageGrab.grab(bbox=(x, y, x + size, y + size),
                         all_screens=True).convert("RGBA")

    # 다이얼 원 바깥을 완전 투명으로 (PC 화면이 한 픽셀도 안 남게)
    ss = 4
    mask = Image.new("L", (size * ss, size * ss), 0)
    r = app.g.tick_outer * ss
    c = (size * ss) / 2.0
    ImageDraw.Draw(mask).ellipse((c - r, c - r, c + r, c + r), fill=255)
    img.putalpha(mask.resize((size, size), Image.LANCZOS))

    path = os.path.join(OUT, f"{tag}.png")
    img.save(path)
    print("saved", path, img.size)
    SHOTS.append(path)
    return path


def step_idle():
    app.core.apply_minutes(25)
    app._render()
    capture("clock-idle")


def step_running():
    app.core.apply_minutes(45)
    app.core.start()
    app.core._deadline = time.monotonic() + 45 * 60 * 0.62 + 34
    app._render()
    capture("clock-running")


def step_alarm():
    app.core.apply_minutes(0)
    app._alarm_active = True
    app._blink = True
    app._render()
    capture("clock-alarm")
    app._alarm_active = False


def step_done():
    app.quit_app()


for i, fn in enumerate([step_idle, step_running, step_alarm, step_done]):
    app.root.after(500 + i * 900, fn)
app.root.mainloop()
print("done", len(SHOTS), "images")
