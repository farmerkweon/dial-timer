# -*- coding: utf-8 -*-
"""
입력 처리 통합 테스트.

실제 Tk 창을 띄운 뒤 이벤트 객체를 만들어 핸들러에 직접 주입한다.
(OS 마우스를 뺏지 않으면서 클릭 게이팅·히트영역·휠·키를 모두 검증)
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import tray_timer as T  # noqa: E402

FAILED = []
CTRL = T.TrayTimerUI.CTRL_MASK
SHIFT = 0x0001


def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        FAILED.append(name)


class Ev:
    """tkinter 이벤트 대역."""

    def __init__(self, x=0, y=0, state=0, char="", keysym="", delta=0,
                 x_root=0, y_root=0):
        self.x, self.y, self.state = x, y, state
        self.char, self.keysym, self.delta = char, keysym, delta
        self.x_root, self.y_root = x_root, y_root


T._enable_dpi_awareness()
app = T.TrayTimerUI()
app.root.update()
g = app.g
CX, CY = int(g.cx), int(g.cy)


def pump():
    app.root.update_idletasks()
    app.root.update()


print("[I1] 다이얼 영역 판정")
check("중앙 = dial", app._region(CX, CY) == "dial")
ring_r = (g.tick_inner + g.tick_end) / 2          # 눈금 바 한가운데
check("눈금링 = dial", app._region(CX, int(CY - ring_r)) == "dial")
check("눈금 길이 = TICK_LENGTH",
      abs((g.tick_end - g.tick_inner) / g.s - T.TICK_LENGTH) < 1e-6,
      round((g.tick_end - g.tick_inner) / g.s, 3))
check("원 밖 = outside", app._region(4, 4) == "outside")
hx = (app._help_rect()[0] + app._help_rect()[2]) / 2
hy = (app._help_rect()[1] + app._help_rect()[3]) / 2
check("HELP 히트", app._region(int(hx), int(hy)) == "help", (int(hx), int(hy)))
dx = (app._hide_rect()[0] + app._hide_rect()[2]) / 2
check("HIDE 히트", app._region(int(dx), int(hy)) == "hide")
check("HELP/HIDE 영역 안 겹침", app._help_rect()[2] < app._hide_rect()[0])

print("[I2] Ctrl 없는 클릭은 시작하지 않는다 (오작동 방지)")
app.core.apply_minutes(5)
app._on_left_down(Ev(x=CX, y=CY, state=0, x_root=1000, y_root=1000))
check("state 그대로 idle", app.core.state == "idle", app.core.state)
app._on_left_up(Ev())
check("안내 문구 표시", app._hint == "Ctrl + Click", app._hint)
pump()

print("[I3] Ctrl + 클릭 = 시작 / 다시 누르면 일시정지")
app._on_left_down(Ev(x=CX, y=CY, state=CTRL))
check("running", app.core.running, app.core.state)
app._on_left_down(Ev(x=CX, y=CY, state=CTRL))
check("paused", app.core.state == "paused", app.core.state)

print("[I4] Ctrl 없는 우클릭은 리셋하지 않는다")
app.core.apply_minutes(5)
app.core.start()
time.sleep(0.25)
app._on_right_down(Ev(x=CX, y=CY, state=0))
check("running 유지", app.core.running, app.core.state)
app._on_right_down(Ev(x=CX, y=CY, state=CTRL))
check("Ctrl+우클릭 → idle", app.core.state == "idle", app.core.state)
check("잔여 복원 300s", app.core.display_seconds() == 300)

print("[I5] 휠로 0~99분 조절")
app.core.apply_minutes(5)
app._on_wheel(Ev(delta=120, state=0))
check("휠 업 +1 → 6", app.core.set_minutes == 6)
app._on_wheel(Ev(delta=-120, state=0))
check("휠 다운 -1 → 5", app.core.set_minutes == 5)
app._on_wheel(Ev(delta=120, state=SHIFT))
check("Shift+휠 +10 → 15", app.core.set_minutes == 15)
for _ in range(12):
    app._on_wheel(Ev(delta=120, state=SHIFT))
check("상한 99 고정", app.core.set_minutes == 99, app.core.set_minutes)
for _ in range(12):
    app._on_wheel(Ev(delta=-120, state=SHIFT))
check("하한 0 고정", app.core.set_minutes == 0, app.core.set_minutes)

print("[I6] 숫자키 직접 입력 (0~99)")
app._on_key(Ev(char="4", keysym="4"))
app._on_key(Ev(char="5", keysym="5"))
check("45분", app.core.set_minutes == 45, app.core.set_minutes)
app._on_key(Ev(char="9", keysym="9"))
check("3자리 → 뒤 2자리(59)", app.core.set_minutes == 59, app.core.set_minutes)
app._on_key(Ev(char="", keysym="BackSpace"))
check("백스페이스 → 5", app.core.set_minutes == 5, app.core.set_minutes)

print("[I7] 키보드 단축키")
app.core.apply_minutes(3)
app._on_key(Ev(char=" ", keysym="space"))
check("Space 시작", app.core.running)
app._on_key(Ev(char="r", keysym="r"))
check("R 리셋", app.core.state == "idle")
before = app.muted
app._on_key(Ev(char="m", keysym="m"))
check("M 음소거 토글", app.muted != before)
app._on_key(Ev(char="m", keysym="m"))
top = app.topmost
app._on_key(Ev(char="t", keysym="t"))
check("T 항상위 토글", app.topmost != top)
app._on_key(Ev(char="t", keysym="t"))

print("[I7b] 투명도")
app.set_opacity(1.0)
check("초기 100%", abs(app.opacity - 1.0) < 1e-6)
app._on_wheel(Ev(delta=-120, state=CTRL))
check("Ctrl+휠 다운으로 낮아짐",
      abs(app.opacity - (1.0 - T.OPACITY_STEP)) < 1e-6, app.opacity)
check("Ctrl+휠은 분을 바꾸지 않는다", app.core.set_minutes == 3,
      app.core.set_minutes)
app._on_wheel(Ev(delta=120, state=CTRL))
check("Ctrl+휠 업으로 복귀", abs(app.opacity - 1.0) < 1e-6, app.opacity)
app._on_key(Ev(char="[", keysym="bracketleft"))
check("[ 키로 낮아짐", app.opacity < 1.0)
app._on_key(Ev(char="]", keysym="bracketright"))
check("] 키로 높아짐", abs(app.opacity - 1.0) < 1e-6)
for _ in range(30):
    app.adjust_opacity(-T.OPACITY_STEP)
check("하한 고정", abs(app.opacity - T.OPACITY_MIN) < 1e-6, app.opacity)
for _ in range(30):
    app.adjust_opacity(T.OPACITY_STEP)
check("상한 고정", abs(app.opacity - T.OPACITY_MAX) < 1e-6, app.opacity)
app.set_opacity(0.6)
check("실제 창에 반영",
      abs(float(app.root.attributes("-alpha")) - 0.6) < 0.02,
      app.root.attributes("-alpha"))
check("설정 저장됨", T.Settings(T.CONFIG_PATH).get("opacity") == 0.6)
check("이상값은 100%로", app._clamp_opacity("abc") == T.OPACITY_MAX)
app.set_opacity(1.0)

print("[I8] HELP 팝업 / HIDE 버튼")
app._on_left_down(Ev(x=int(hx), y=int(hy), state=0))
pump()
check("HELP 팝업 열림", app._help_open)
check("팝업 창 실제 존재",
      app._help_win is not None and app._help_win.winfo_exists())
hw = app._help_win
check("팝업 크기 충분", hw.winfo_width() > 300 and hw.winfo_height() > 300,
      (hw.winfo_width(), hw.winfo_height()))
# 제목표시줄 포함해도 화면 안에 들어와야 잘리지 않는다
check("팝업이 화면 안 (잘림 없음)",
      hw.winfo_rootx() >= 0 and hw.winfo_rooty() >= 0 and
      hw.winfo_rootx() + hw.winfo_width() <= hw.winfo_screenwidth() and
      hw.winfo_rooty() + hw.winfo_height() <= hw.winfo_screenheight(),
      (hw.winfo_rootx(), hw.winfo_rooty(),
       hw.winfo_width(), hw.winfo_height(),
       hw.winfo_screenwidth(), hw.winfo_screenheight()))
app._on_left_down(Ev(x=int(hx), y=int(hy), state=0))
pump()
check("이미 열려있으면 중복 생성 안 함", app._help_win is hw)
check("도움말 중에도 타이머 동작", app._region(CX, CY) == "dial")
print("  -- 한/영 전환 --")
before_lang = hw._lang
check("기본 언어가 ko/en 중 하나", before_lang in T.HELP_LANGS, before_lang)
w_before = hw.winfo_reqwidth()
hw._toggle_lang()
pump()
check("언어 바뀜", hw._lang != before_lang, hw._lang)
check("앱에도 반영", app.help_lang == hw._lang)
check("설정 저장됨", T.Settings(T.CONFIG_PATH).get("help_lang") == hw._lang)
check("전환 후에도 창 살아있음", hw.winfo_exists())
check("전환 후 크기 재계산", hw.winfo_reqwidth() > 300, hw.winfo_reqwidth())
titles = [s[0] for s in T.HelpWindow.TEXT[hw._lang]["sections"]]
check("영/한 섹션 수 동일",
      len(T.HelpWindow.TEXT["ko"]["sections"]) ==
      len(T.HelpWindow.TEXT["en"]["sections"]) == 4)
check("각 섹션 항목 수 동일",
      all(len(a[2]) == len(b[2]) for a, b in
          zip(T.HelpWindow.TEXT["ko"]["sections"],
              T.HelpWindow.TEXT["en"]["sections"])))
hw._toggle_lang()
pump()
check("되돌리기", hw._lang == before_lang)

app._on_key(Ev(char="h", keysym="h"))
pump()
check("H 키로 닫힘", not app._help_open)
check("창 파괴됨", not hw.winfo_exists())
app.show_help(); pump()
check("다시 열면 언어 유지", app._help_win._lang == before_lang)
app._close_help(); pump()
app._on_left_down(Ev(x=int(dx), y=int(hy), state=0))
pump()
check("HIDE → 창 숨김", app._hidden)
check("실제로 withdrawn", app.root.state() == "withdrawn", app.root.state())
app.show_window()
pump()
check("트레이에서 복귀", not app._hidden and app.root.state() == "normal")

print("[I9] 0분이면 시작 불가 + 안내")
app.core.apply_minutes(0)
app._on_left_down(Ev(x=CX, y=CY, state=CTRL))
check("여전히 idle", app.core.state == "idle")
check("SET TIME 안내", app._hint == "SET TIME", app._hint)

print("[I10] 알람 중 아무 Ctrl+클릭 = 정지 후 리셋")
app.core.apply_minutes(2)
app.core.start()
app.core._deadline = time.monotonic() - 0.01
app._tick()
check("알람 진입", app._alarm_active)
check("finished", app.core.state == "finished")
app._on_left_down(Ev(x=CX, y=CY, state=0))    # 알람 중엔 Ctrl 없이도 정지
check("알람 해제", not app._alarm_active)
check("리셋됨", app.core.state == "idle" and app.core.display_seconds() == 120)

print("[I11] 드래그 임계값 — 살짝 흔들려도 창이 튀지 않는다")
app.core.apply_minutes(5)
x0, y0 = app.root.winfo_x(), app.root.winfo_y()
app._on_left_down(Ev(x=CX, y=CY, state=0, x_root=x0 + CX, y_root=y0 + CY))
app._on_left_drag(Ev(x_root=x0 + CX + 2, y_root=y0 + CY + 1))
pump()
check("2px 이동 무시", app.root.winfo_x() == x0 and app.root.winfo_y() == y0,
      (app.root.winfo_x() - x0, app.root.winfo_y() - y0))
app._on_left_drag(Ev(x_root=x0 + CX + 40, y_root=y0 + CY + 30))
pump()
check("40px 이동 반영", abs(app.root.winfo_x() - (x0 + 40)) <= 2, app.root.winfo_x() - x0)
app._on_left_up(Ev())
app.root.geometry(f"+{x0}+{y0}")
app.settings.set("x", x0)
app.settings.set("y", y0)
app.settings.save()

print("[I12] 설정 영속화")
app.core.apply_minutes(23)
app._remember_minutes()
s2 = T.Settings(T.CONFIG_PATH)
check("minutes 저장됨", s2.get("minutes") == 23, s2.get("minutes"))

print("[I13] 렌더링 예외 없음 (전 상태)")
try:
    for minutes in (0, 1, 45, 99):
        app.core.apply_minutes(minutes)
        app._render(); pump()
        app.core.start(); app._render(); pump()
        app.core.pause(); app._render(); pump()
    app._alarm_active = True
    for blink in (True, False):
        app._blink = blink; app._render(); pump()
    app._alarm_active = False
    app.show_help(); pump()
    app._close_help(); pump()
    check("모든 상태 렌더 성공", True)
except Exception as exc:  # noqa: BLE001
    check("모든 상태 렌더 성공", False, repr(exc))

app.quit_app()
print()
if FAILED:
    print("실패:", FAILED)
    sys.exit(1)
print("전체 통과")
