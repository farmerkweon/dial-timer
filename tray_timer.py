# -*- coding: utf-8 -*-
"""
Tray Timer  —  사각 바디 다이얼 타이머 (0~99분)

  * 트레이(알림영역) 상주 프로그램
  * 사진의 원형 다이얼 / 방사형 빨간 눈금 / 7-세그먼트 LCD 재현 (외곽 베젤 없음)
  * 오작동 방지를 위해 시작/정지는 반드시  Ctrl + 클릭
  * 숫자 아래 HELP / HIDE 버튼

구조 (I/O와 로직 분리)
  TimerCore     : 순수 상태 머신 (UI/시간표시 무관, 테스트 가능)
  TrayTimerUI   : tkinter 렌더링 + 입력 처리
  TrayIcon      : pystray 트레이 아이콘 (별도 스레드)
  AlarmPlayer   : winsound 알람 (별도 스레드)
  Settings      : JSON 영속화

실행:  pythonw tray_timer.py     (콘솔 없이)
"""

from __future__ import annotations

import ctypes
import json
import math
import os
import sys
import threading
import time
import tkinter as tk
import webbrowser

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

APP_NAME = "Dial Timer"
APP_VERSION = "1.0.1"
APP_URL = "https://foxnail.kr"
APP_COPYRIGHT = "© 2026 foxnail.kr · All rights reserved"

# 도움말 하단 응원 섹션에서 여는 링크
URL_LOTTO_SUDOKU = "https://play.google.com/store/apps/details?id=com.foxnail.lotto_sudoku"
URL_ART_GRID = "https://play.google.com/store/apps/details?id=com.artgrid.app.free"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _config_path() -> str:
    """
    설정 파일 위치.

    설치본은 Program Files 같은 쓰기 금지 폴더에서 실행되므로
    실행 파일 옆이 아니라 %APPDATA%\\DialTimer 에 저장한다.
    """
    base = os.environ.get("APPDATA") or os.path.join(
        os.path.expanduser("~"), ".config")
    folder = os.path.join(base, "DialTimer")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        return os.path.join(BASE_DIR, "timer_config.json")   # 최후 수단
    return os.path.join(folder, "timer_config.json")


CONFIG_PATH = _config_path()

HELP_LANGS = ("ko", "en")


def _default_help_lang() -> str:
    """도움말 기본 언어는 Windows 표시 언어를 따른다."""
    if sys.platform == "win32":
        try:
            LANG_KOREAN = 0x12
            ui = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "ko" if (ui & 0x3FF) == LANG_KOREAN else "en"
        except (AttributeError, OSError):
            pass
    return "en"

MIN_MINUTES = 0
MAX_MINUTES = 99
DEFAULT_MINUTES = 5

OPACITY_MIN = 0.30           # 완전히 안 보이는 상태는 막는다
OPACITY_MAX = 1.00
OPACITY_STEP = 0.05
OPACITY_PRESETS = (100, 90, 80, 70, 60, 50, 40, 30)

TICK_COUNT = 60              # 다이얼 방사형 눈금 개수
TICK_LENGTH = 11.0           # 눈금 바 길이 (디자인 단위)
UI_SCALE = 0.65              # 시계 전체 크기 배율 (도움말 팝업에는 영향 없음)
ALARM_TIMEOUT_SEC = 60       # 알람 자동 정지

# 색
C_TRANSPARENT = "#ff00fe"    # 창 배경 투명 키컬러 (Windows 전용) — 원 밖은 완전 투명
C_DIAL_BG = "#141414"        # 다이얼 검정
C_DIAL_EDGE = "#3a3a3a"
C_TICK_ON = "#d81f26"        # 남은 시간 눈금 (빨강)
C_TICK_OFF = "#000000"       # 지나간 눈금
C_LCD_ON = "#f2f2f2"         # 켜진 세그먼트
C_LCD_OFF = "#242424"        # 꺼진 세그먼트 (실제 LCD 느낌)
C_LABEL = "#8a8a8a"
C_BTN = "#9a9a9a"
C_BTN_HOVER = "#ffffff"
C_HINT = "#d81f26"
C_ALARM = "#ff2b2b"

# 7-세그먼트 매핑
SEGMENTS = {
    "0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg",
    "5": "acdfg", "6": "acdefg", "7": "abc", "8": "abcdefg", "9": "abcdfg",
    "-": "g", " ": "",
}
SLANT = 0.08                 # 숫자 기울기


# ---------------------------------------------------------------------------
# 설정 영속화
# ---------------------------------------------------------------------------

class Settings:
    """창 위치·마지막 설정값을 JSON으로 보존."""

    DEFAULTS = {"minutes": DEFAULT_MINUTES, "x": None, "y": None,
                "muted": False, "topmost": True, "opacity": 1.0,
                "help_lang": None}          # None = 시스템 언어로 결정

    def __init__(self, path: str):
        self._path = path
        self._data = dict(self.DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as fp:
                loaded = json.load(fp)
            if isinstance(loaded, dict):
                self._data.update({k: v for k, v in loaded.items()
                                   if k in self.DEFAULTS})
        except (OSError, ValueError):
            pass  # 설정이 없거나 깨졌으면 기본값 사용

    def save(self) -> None:
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fp:
                json.dump(self._data, fp, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)          # 원자적 저장
        except OSError:
            pass

    def get(self, key):
        return self._data.get(key, self.DEFAULTS.get(key))

    def set(self, key, value) -> None:
        self._data[key] = value


# ---------------------------------------------------------------------------
# 순수 타이머 로직
# ---------------------------------------------------------------------------

class TimerCore:
    """
    타이머 상태 머신.  UI를 전혀 모른다.

    state: 'idle' | 'running' | 'paused' | 'finished'
    """

    def __init__(self, minutes: int = DEFAULT_MINUTES):
        self.set_minutes = self._clamp(minutes)
        self.total = self.set_minutes * 60
        self._remaining = float(self.total)
        self._deadline = 0.0
        self.state = "idle"

    # -- 조회 -------------------------------------------------------------
    @staticmethod
    def _clamp(minutes: int) -> int:
        return max(MIN_MINUTES, min(MAX_MINUTES, int(minutes)))

    @property
    def running(self) -> bool:
        return self.state == "running"

    def remaining_seconds(self) -> float:
        """실시간 잔여 초 (running이면 monotonic 기준으로 계산)."""
        if self.state == "running":
            return max(0.0, self._deadline - time.monotonic())
        return max(0.0, self._remaining)

    def display_seconds(self) -> int:
        """표시용 정수 초 (올림 — 5:00 설정 직후 4:59로 보이지 않게)."""
        return int(math.ceil(self.remaining_seconds() - 1e-6))

    def fraction(self) -> float:
        """남은 비율 0.0~1.0 (다이얼 눈금용)."""
        if self.total <= 0:
            return 0.0
        return max(0.0, min(1.0, self.remaining_seconds() / self.total))

    # -- 조작 -------------------------------------------------------------
    def apply_minutes(self, minutes: int) -> None:
        """설정값 변경 → 항상 정지 상태로 리셋."""
        self.set_minutes = self._clamp(minutes)
        self.total = self.set_minutes * 60
        self._remaining = float(self.total)
        self._deadline = 0.0
        self.state = "idle"

    def adjust_minutes(self, delta: int) -> None:
        self.apply_minutes(self.set_minutes + delta)

    def start(self) -> bool:
        if self.state == "running":
            return False
        if self.remaining_seconds() <= 0:
            return False                      # 0분은 시작 불가
        self._deadline = time.monotonic() + self.remaining_seconds()
        self.state = "running"
        return True

    def pause(self) -> None:
        if self.state != "running":
            return
        self._remaining = self.remaining_seconds()
        self.state = "paused"

    def toggle(self) -> bool:
        """시작/일시정지 토글. 실제로 상태가 바뀌면 True."""
        if self.state == "running":
            self.pause()
            return True
        return self.start()

    def reset(self) -> None:
        self._remaining = float(self.total)
        self._deadline = 0.0
        self.state = "idle"

    def poll(self) -> bool:
        """주기 호출. 이번 호출에서 '완주'했으면 True."""
        if self.state == "running" and self.remaining_seconds() <= 0:
            self._remaining = 0.0
            self.state = "finished"
            return True
        return False


# ---------------------------------------------------------------------------
# 알람
# ---------------------------------------------------------------------------

class AlarmPlayer:
    """winsound 비프를 별도 스레드에서 반복. 없으면 조용히 무시."""

    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> None:
        self.stop()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread = None

    def _run(self) -> None:
        try:
            import winsound
        except ImportError:
            return
        stop = self._stop
        deadline = time.monotonic() + ALARM_TIMEOUT_SEC
        while not stop.is_set() and time.monotonic() < deadline:
            for freq in (1046, 1318, 1046):
                if stop.is_set():
                    return
                try:
                    winsound.Beep(freq, 160)
                except RuntimeError:
                    return
                if stop.wait(0.06):
                    return
            if stop.wait(0.9):
                return


# ---------------------------------------------------------------------------
# 트레이 아이콘
# ---------------------------------------------------------------------------

class TrayIcon:
    """
    pystray 래퍼.  콜백은 모두 tk 스레드로 넘긴다(스레드 안전).
    """

    def __init__(self, app: "TrayTimerUI"):
        self._app = app
        self._icon = None
        self._last_key = None
        self._font = None

    # -- 이미지 -----------------------------------------------------------
    def _load_font(self, size: int):
        from PIL import ImageFont
        for name in ("arialbd.ttf", "seguisb.ttf", "arial.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    def _render(self, text: str, fraction: float, alarm: bool):
        from PIL import Image, ImageDraw
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((0, 0, size - 1, size - 1), fill=(20, 20, 20, 255))

        color = (255, 60, 60, 255) if alarm else (216, 31, 38, 255)
        # PIL 각도는 3시 방향이 0이고 시계방향이 +. 12시(-90)에서 시계방향으로 채운다.
        if fraction >= 0.999:
            d.ellipse((2, 2, size - 3, size - 3), fill=color)
        elif fraction > 0:
            d.pieslice((2, 2, size - 3, size - 3), start=-90,
                       end=-90 + 360.0 * fraction, fill=color)
        d.ellipse((13, 13, size - 14, size - 14), fill=(20, 20, 20, 255))

        if self._font is None:
            self._font = self._load_font(30)
        box = d.textbbox((0, 0), text, font=self._font)
        d.text(((size - (box[2] - box[0])) / 2 - box[0],
                (size - (box[3] - box[1])) / 2 - box[1]),
               text, font=self._font, fill=(255, 255, 255, 255))
        return img

    # -- 수명주기 ---------------------------------------------------------
    def start(self) -> None:
        import pystray
        from pystray import MenuItem as Item

        menu = pystray.Menu(
            Item("보이기 / 숨기기", self._on_toggle_window, default=True),
            Item("시작 / 일시정지", self._on_toggle_run),
            Item("리셋", self._on_reset),
            pystray.Menu.SEPARATOR,
            Item("소리 끄기", self._on_mute,
                 checked=lambda _i: self._app.muted),
            Item("항상 위", self._on_topmost,
                 checked=lambda _i: self._app.topmost),
            Item("투명도", pystray.Menu(*[
                Item(f"{pct}%", self._make_opacity(pct), radio=True,
                     checked=lambda _i, p=pct:
                         abs(self._app.opacity - p / 100.0) < 0.005)
                for pct in OPACITY_PRESETS])),
            pystray.Menu.SEPARATOR,
            Item("도움말", self._on_help),
            Item("종료", self._on_quit),
        )
        self._icon = pystray.Icon(APP_NAME, self._render("--", 0.0, False),
                                  APP_NAME, menu)
        threading.Thread(target=self._icon.run, daemon=True).start()

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None

    def update(self, text: str, fraction: float, alarm: bool, tip: str) -> None:
        """표시가 실제로 달라졌을 때만 갱신 (CPU 절약)."""
        if self._icon is None:
            return
        key = (text, int(fraction * TICK_COUNT), alarm)
        if key == self._last_key:
            self._icon.title = tip
            return
        self._last_key = key
        try:
            self._icon.icon = self._render(text, fraction, alarm)
            self._icon.title = tip
        except Exception:
            pass

    # -- 콜백 (pystray 스레드 → tk 스레드) --------------------------------
    def _post(self, fn):
        self._app.post(fn)

    def _on_toggle_window(self, *_):
        self._post(self._app.toggle_window)

    def _on_toggle_run(self, *_):
        self._post(self._app.action_toggle)

    def _on_reset(self, *_):
        self._post(self._app.action_reset)

    def _on_mute(self, *_):
        self._post(self._app.action_mute)

    def _on_topmost(self, *_):
        self._post(self._app.action_topmost)

    def _make_opacity(self, pct: int):
        """투명도 프리셋 메뉴 콜백 생성 (pct를 조기 바인딩)."""
        def handler(*_):
            self._post(lambda: self._app.set_opacity(pct / 100.0))
        return handler

    def _on_help(self, *_):
        self._post(self._app.show_help)

    def _on_quit(self, *_):
        self._post(self._app.quit_app)


# ---------------------------------------------------------------------------
# 화면 좌표 (DPI 배율 반영)
# ---------------------------------------------------------------------------

class Geometry:
    """
    다이얼 좌표를 DPI 배율에 맞춰 계산.

    안쪽 원반(disc)이 숫자·버튼을 담는 고정 크기이고,
    눈금 링과 바깥 테두리는 그 위에 얹히는 구조다.
    따라서 TICK_LENGTH를 줄이면 창 크기까지 같이 줄어든다.
    """

    DISC = 103.0        # 숫자·HELP/HIDE가 들어가는 안쪽 원반 반지름
    DISC_GAP = 5.0      # 원반과 눈금 사이 간격
    RIM = 4.0           # 눈금 바깥의 검은 테두리 폭
    MARGIN = 4.0        # 창 가장자리 여백 (안티에일리어싱 여유)

    def __init__(self, scale: float):
        self.dpi = scale                 # 창/폰트용 (시계 축소와 무관)
        s = self.s = scale * UI_SCALE    # 다이얼용

        self.disc_radius = self.DISC * s
        self.tick_inner = self.disc_radius + self.DISC_GAP * s
        self.tick_end = self.tick_inner + TICK_LENGTH * s
        self.tick_outer = self.tick_end + self.RIM * s      # 다이얼 바깥 원

        self.size = int(round(2 * (self.tick_outer + self.MARGIN * s)))
        self.cx = self.cy = self.size / 2.0

        self.digit_w = 30 * s
        self.digit_h = 50 * s
        self.digit_t = 7.5 * s
        self.digit_gap = 6 * s
        self.colon_w = 12 * s
        self.colon_gap = 8 * s

        self.digits_cy = self.cy - 6 * s
        self.icon_cy = self.cy - 62 * s
        self.btn_cy = self.cy + 58 * s
        self.hint_cy = self.cy + 80 * s

    def px(self, v: float) -> float:
        """다이얼 기준 픽셀 (UI_SCALE 반영)."""
        return v * self.s

    def dpi_px(self, v: float) -> float:
        """창·폰트 기준 픽셀 (UI_SCALE 영향 없음)."""
        return v * self.dpi


# ---------------------------------------------------------------------------
# 도움말 팝업
# ---------------------------------------------------------------------------

class HelpWindow(tk.Toplevel):
    """
    도움말 팝업 창.

    다이얼 안에 겹쳐 그리면 원에 갇혀 글자가 작고 읽기 힘들어서
    제목표시줄이 있는 독립 창으로 분리했다. 이 창이 떠 있어도
    타이머는 그대로 동작한다.
    """

    TEXT = {
        "ko": {
            "window": "도움말",
            "title": "사용법",
            "subtitle": f"0 ~ 99분 다이얼 타이머   v{APP_VERSION}",
            "close": "닫기",
            "hint": "Esc 로 닫기",
            "toggle": "English",
            "sections": [
                ("시작 · 정지", "실수로 눌리지 않도록 Ctrl을 함께 누릅니다", [
                    ("Ctrl + 좌클릭", "시작 / 일시정지"),
                    ("Ctrl + 우클릭", "리셋"),
                    ("그냥 클릭", "아무 동작 안 함 (안내만 표시)"),
                    ("Space  /  R", "시작·일시정지  /  리셋"),
                ]),
                ("시간 설정", "0 ~ 99분", [
                    ("마우스 휠", "1분씩 조절"),
                    ("Shift + 휠", "10분씩 조절"),
                    ("숫자키 0~9", "두 자리 직접 입력"),
                    ("Backspace", "입력한 숫자 지우기"),
                ]),
                ("창 · 소리 · 투명도", "", [
                    ("다이얼 드래그", "창 이동"),
                    ("HIDE  /  Esc", "트레이로 숨기기"),
                    ("Ctrl + 휠", "투명도 조절 (30~100%)"),
                    ("[  /  ]", "투명도 낮추기 / 높이기"),
                    ("M", "알람 소리 켜기 / 끄기"),
                    ("T", "항상 위 토글"),
                ]),
                ("트레이 아이콘", "남은 시간이 숫자와 빨간 원호로 표시됩니다", [
                    ("더블클릭", "창 보이기 / 숨기기"),
                    ("우클릭", "메뉴 (시작 · 리셋 · 투명도 · 종료)"),
                ]),
            ],
            "support": {
                "title": "만든 사람 응원하기",
                "intro": "이 시계가 도움이 되셨다면, 개발자를 위해 아래 앱을 "
                         "핸드폰에 설치하고 즐겨주세요.",
                "apps": [("로또 스도쿠", URL_LOTTO_SUDOKU),
                         ("아트 그리드", URL_ART_GRID)],
                "store": "Google Play",
                "note": "여력이 되면 아이폰 사용자를 위해서도 만들어 보겠습니다.",
                "share": "이 앱들이 마음에 드신다면, 앱의 공유 버튼을 이용해 "
                         "주위 지인들에게도 전해주세요.",
            },
        },
        "en": {
            "window": "Help",
            "title": "How to use",
            "subtitle": f"0 – 99 minute dial timer   v{APP_VERSION}",
            "close": "Close",
            "hint": "Press Esc to close",
            "toggle": "한국어",
            "sections": [
                ("Start · Stop", "Hold Ctrl so it can't be clicked by accident", [
                    ("Ctrl + Left click", "Start / Pause"),
                    ("Ctrl + Right click", "Reset"),
                    ("Plain click", "Does nothing (shows a hint)"),
                    ("Space  /  R", "Start·Pause  /  Reset"),
                ]),
                ("Set the time", "0 – 99 min", [
                    ("Mouse wheel", "1 minute steps"),
                    ("Shift + wheel", "10 minute steps"),
                    ("Number keys 0–9", "Type two digits"),
                    ("Backspace", "Delete a typed digit"),
                ]),
                ("Window · Sound · Opacity", "", [
                    ("Drag the dial", "Move the window"),
                    ("HIDE  /  Esc", "Hide to tray"),
                    ("Ctrl + wheel", "Opacity (30–100%)"),
                    ("[  /  ]", "Less / more opaque"),
                    ("M", "Alarm sound on / off"),
                    ("T", "Always on top"),
                ]),
                ("Tray icon", "Shows the time left as a number and a red arc", [
                    ("Double click", "Show / hide the window"),
                    ("Right click", "Menu (start · reset · opacity · quit)"),
                ]),
            ],
            "support": {
                "title": "Support the developer",
                "intro": "If this timer helped you, please install these apps "
                         "on your phone and enjoy them.",
                "apps": [("Lotto Sudoku", URL_LOTTO_SUDOKU),
                         ("Art Grid", URL_ART_GRID)],
                "store": "Google Play",
                "note": "If I get the chance, I'd like to build iPhone "
                        "versions too.",
                "share": "If you like them, please pass them on to people "
                         "around you with the share button inside the app.",
            },
        },
    }

    BG = "#1a1a1a"
    CARD = "#242424"
    FG_TITLE = "#ffffff"
    FG_KEY = "#e8565c"
    FG_VAL = "#d8d8d8"
    FG_DIM = "#8a8a8a"
    FG_LINK = "#6fa8ff"
    FG_LINK_HOVER = "#a8ccff"
    LINE = "#383838"
    SUPPORT_BG = "#1f2320"
    STORE_BG = "#2b6a4b"
    STORE_BG_HOVER = "#357f5a"

    def __init__(self, app: "TrayTimerUI"):
        super().__init__(app.root)
        self._app = app
        self._px = app.g.dpi_px
        self._lang = app.help_lang

        self.configure(bg=self.BG)
        self.resizable(False, False)
        self.attributes("-topmost", True)

        self._build()
        self.update_idletasks()
        self._place_beside(app)

        self.protocol("WM_DELETE_WINDOW", app._close_help)
        self.bind("<Escape>", lambda _e: app._close_help())
        self.focus_force()

    @property
    def _t(self) -> dict:
        return self.TEXT[self._lang]

    def _toggle_lang(self) -> None:
        """한국어 ↔ English. 선택은 저장해서 다음에도 유지한다."""
        self._lang = "en" if self._lang == "ko" else "ko"
        self._app.set_help_lang(self._lang)
        for child in self.winfo_children():
            child.destroy()
        self._build()
        self.update_idletasks()
        # 언어에 따라 폭이 달라지므로 위치는 두고 크기만 다시 맞춘다
        self.geometry(f"{self.winfo_reqwidth()}x{self.winfo_reqheight()}")

    # -- 폰트 (포인트 대신 픽셀(-N)로 지정해 DPI 이중 확대를 피한다) --------
    def _font(self, px: float, bold: bool = False):
        return ("Malgun Gothic", -int(self._px(px)),
                "bold" if bold else "normal")

    def _build(self) -> None:
        p, t = self._px, self._t
        self.title(f"{APP_NAME} — {t['window']}")

        root = tk.Frame(self, bg=self.BG,
                        padx=int(p(18)), pady=int(p(14)))
        root.pack(fill="both", expand=True)

        head = tk.Frame(root, bg=self.BG)
        head.pack(fill="x", pady=(0, int(p(10))))
        tk.Button(head, text=t["toggle"], command=self._toggle_lang,
                  bg=self.CARD, fg=self.FG_VAL, activebackground="#333333",
                  activeforeground="#ffffff", relief="flat", bd=0,
                  font=self._font(10, True), cursor="hand2",
                  padx=int(p(12)), pady=int(p(3))).pack(side="right", anchor="n")
        titles = tk.Frame(head, bg=self.BG)
        titles.pack(side="left", anchor="w")
        tk.Label(titles, text=t["title"], bg=self.BG, fg=self.FG_TITLE,
                 font=self._font(16, True), anchor="w").pack(fill="x")
        tk.Label(titles, text=t["subtitle"], bg=self.BG, fg=self.FG_DIM,
                 font=self._font(10), anchor="w").pack(fill="x",
                                                       pady=(int(p(2)), 0))

        # 세로로 쌓으면 화면 아래로 넘쳐서 2단으로 배치한다.
        body = tk.Frame(root, bg=self.BG)
        body.pack(fill="both", expand=True)
        for col in (0, 1):
            body.columnconfigure(col, weight=1, uniform="help")
        for i, (title, note, rows) in enumerate(t["sections"]):
            self._section(body, title, note, rows).grid(
                row=i // 2, column=i % 2, sticky="nsew",
                padx=(0, int(p(12))) if i % 2 == 0 else (0, 0),
                pady=(0, int(p(10))))

        self._support(root)
        self._footer(root)

    def _support(self, parent) -> None:
        """도움말 맨 아래 응원 배너 (좌우 단 전체 폭)."""
        p, t = self._px, self._t["support"]
        card = tk.Frame(parent, bg=self.SUPPORT_BG,
                        padx=int(p(14)), pady=int(p(11)))
        card.pack(fill="x")

        head = tk.Frame(card, bg=self.SUPPORT_BG)
        head.pack(fill="x")
        tk.Label(head, text="♥", bg=self.SUPPORT_BG, fg=self.FG_KEY,
                 font=self._font(12, True)).pack(side="left",
                                                 padx=(0, int(p(6))))
        tk.Label(head, text=t["title"], bg=self.SUPPORT_BG,
                 fg=self.FG_TITLE, font=self._font(11, True)).pack(side="left")

        tk.Label(card, text=t["intro"], bg=self.SUPPORT_BG, fg=self.FG_VAL,
                 font=self._font(10), anchor="w",
                 justify="left").pack(fill="x", pady=(int(p(6)), int(p(8))))

        apps = tk.Frame(card, bg=self.SUPPORT_BG)
        apps.pack(fill="x")
        for name, url in t["apps"]:
            self._store_button(apps, name, t["store"], url)

        tk.Label(card, text=t["note"], bg=self.SUPPORT_BG, fg=self.FG_DIM,
                 font=self._font(10), anchor="w",
                 justify="left").pack(fill="x", pady=(int(p(9)), 0))
        tk.Label(card, text=t["share"], bg=self.SUPPORT_BG, fg=self.FG_DIM,
                 font=self._font(10), anchor="w",
                 justify="left").pack(fill="x", pady=(int(p(2)), 0))

    def _store_button(self, parent, name: str, store: str, url: str) -> None:
        p = self._px
        btn = tk.Frame(parent, bg=self.STORE_BG, cursor="hand2",
                       padx=int(p(14)), pady=int(p(7)))
        btn.pack(side="left", padx=(0, int(p(10))))
        top = tk.Label(btn, text=name, bg=self.STORE_BG, fg="#ffffff",
                       font=self._font(11, True), cursor="hand2")
        top.pack(anchor="w")
        sub = tk.Label(btn, text=f"▶  {store}", bg=self.STORE_BG,
                       fg="#9fd0b0", font=self._font(9), cursor="hand2")
        sub.pack(anchor="w")

        def open_it(_e=None):
            self._open_url(url)

        def enter(_e=None):
            for w in (btn, top, sub):
                w.configure(bg=self.STORE_BG_HOVER)

        def leave(_e=None):
            for w in (btn, top, sub):
                w.configure(bg=self.STORE_BG)

        for w in (btn, top, sub):
            w.bind("<Button-1>", open_it)
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)

    def _footer(self, parent) -> None:
        p = self._px
        tk.Frame(parent, bg=self.LINE, height=1).pack(
            fill="x", pady=(int(p(14)), int(p(10))))

        bar = tk.Frame(parent, bg=self.BG)
        bar.pack(fill="x")
        tk.Button(bar, text=self._t["close"], command=self._app._close_help,
                  bg=self.CARD, fg=self.FG_VAL, activebackground="#333333",
                  activeforeground="#ffffff", relief="flat", bd=0,
                  font=self._font(11, True), cursor="hand2",
                  padx=int(p(18)), pady=int(p(5))).pack(side="right")

        link = tk.Label(bar, text=APP_URL, bg=self.BG, fg=self.FG_LINK,
                        font=self._font(11, True), cursor="hand2")
        link.pack(side="left", anchor="w")
        link.bind("<Button-1>", self._open_site)
        link.bind("<Enter>", lambda _e: link.configure(fg=self.FG_LINK_HOVER))
        link.bind("<Leave>", lambda _e: link.configure(fg=self.FG_LINK))

        tk.Label(parent, text=f"{APP_COPYRIGHT} · {self._t['hint']}",
                 bg=self.BG, fg=self.FG_DIM, font=self._font(9),
                 anchor="w").pack(fill="x", pady=(int(p(8)), 0))

    def _open_site(self, _event=None) -> None:
        self._open_url(APP_URL)

    @staticmethod
    def _open_url(url: str) -> None:
        try:
            webbrowser.open_new_tab(url)
        except Exception:                     # 브라우저가 없어도 창은 살아있게
            pass

    def _section(self, parent, title, note, rows) -> tk.Frame:
        """한 섹션(제목 + 카드)을 담은 프레임을 만들어 돌려준다."""
        p = self._px
        box = tk.Frame(parent, bg=self.BG)

        head = tk.Frame(box, bg=self.BG)
        head.pack(fill="x", pady=(0, int(p(4))))
        tk.Frame(head, bg=self.FG_KEY, width=int(p(3)),
                 height=int(p(12))).pack(side="left", padx=(0, int(p(7))))
        tk.Label(head, text=title, bg=self.BG, fg=self.FG_TITLE,
                 font=self._font(11, True)).pack(side="left")
        if note:
            tk.Label(head, text=note, bg=self.BG, fg=self.FG_DIM,
                     font=self._font(9)).pack(side="left", padx=(int(p(7)), 0))

        card = tk.Frame(box, bg=self.CARD,
                        padx=int(p(11)), pady=int(p(7)))
        card.pack(fill="both", expand=True)
        card.columnconfigure(0, minsize=int(p(104)))
        for i, (key, val) in enumerate(rows):
            tk.Label(card, text=key, bg=self.CARD, fg=self.FG_KEY,
                     font=self._font(11, True), anchor="e").grid(
                row=i, column=0, sticky="e", pady=int(p(1)))
            tk.Label(card, text=val, bg=self.CARD, fg=self.FG_VAL,
                     font=self._font(11), anchor="w").grid(
                row=i, column=1, sticky="w", padx=(int(p(12)), 0),
                pady=int(p(1)))
        return box

    def _place_beside(self, app: "TrayTimerUI") -> None:
        """
        타이머 옆에 띄우되 화면 밖으로 나가지 않게 보정.

        geometry()가 정하는 건 '클라이언트' 크기라, 제목표시줄과 작업표시줄
        높이를 빼고 계산하지 않으면 창 아래쪽이 화면 밖으로 잘린다.
        """
        p = self._px
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        gap = int(p(12))
        chrome = int(p(46))          # 제목표시줄
        reserve = int(p(56))         # 작업표시줄 여유

        tx, ty, ts = app.root.winfo_x(), app.root.winfo_y(), app.g.size
        x = tx + ts + gap
        if x + w > sw:                       # 오른쪽에 자리 없으면 왼쪽
            x = tx - w - gap
        y = ty + ts // 2 - h // 2

        x = max(0, min(x, sw - w))
        y = max(chrome, min(y, sh - reserve - h))
        self.geometry(f"{w}x{h}+{x}+{y}")


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

class TrayTimerUI:
    """tkinter 렌더링 + 입력 처리 + 전체 조립."""

    def __init__(self):
        self.settings = Settings(CONFIG_PATH)
        self.core = TimerCore(int(self.settings.get("minutes")))
        self.alarm = AlarmPlayer()

        self.muted = bool(self.settings.get("muted"))
        self.topmost = bool(self.settings.get("topmost"))
        self.opacity = self._clamp_opacity(self.settings.get("opacity"))
        lang = self.settings.get("help_lang")
        self.help_lang = lang if lang in HELP_LANGS else _default_help_lang()

        self._alarm_active = False
        self._blink = False
        self._hint = ""
        self._hint_until = 0.0
        self._hover = None            # 'help' | 'hide' | None
        self._help_win = None         # 도움말 팝업 (HelpWindow | None)
        self._typed = ""              # 숫자 직접입력 버퍼
        self._typed_until = 0.0
        self._drag_origin = None
        self._drag_moved = False
        self._hidden = False
        self._quitting = False

        self._build_window()
        self.tray = TrayIcon(self)
        self.tray.start()
        self._render()
        self._schedule_tick()

    # -- 창 ---------------------------------------------------------------
    def _build_window(self) -> None:
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)          # 테두리 없는 창
        self.root.attributes("-topmost", self.topmost)
        try:
            self.root.wm_attributes("-transparentcolor", C_TRANSPARENT)
        except tk.TclError:
            pass                                   # Windows 외 환경
        self._apply_opacity()

        scale = self._dpi_scale()
        self.g = Geometry(scale)
        size = self.g.size

        x = self.settings.get("x")
        y = self.settings.get("y")
        if x is None or y is None or not self._on_screen(x, y, size):
            x = self.root.winfo_screenwidth() - size - int(40 * scale)
            y = self.root.winfo_screenheight() - size - int(120 * scale)
        self.root.geometry(f"{size}x{size}+{int(x)}+{int(y)}")

        self.canvas = tk.Canvas(self.root, width=size, height=size,
                                bg=C_TRANSPARENT, highlightthickness=0,
                                bd=0, cursor="hand2")
        self.canvas.pack(fill="both", expand=True)

        self._bind_events()
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.root.after(120, self.root.focus_force)

    def _dpi_scale(self) -> float:
        try:
            dpi = self.root.winfo_fpixels("1i")
            return max(1.0, min(2.5, dpi / 96.0))
        except tk.TclError:
            return 1.0

    def _on_screen(self, x, y, size) -> bool:
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        return -size + 60 < x < sw - 60 and -20 < y < sh - 60

    def _bind_events(self) -> None:
        c = self.canvas
        c.bind("<Button-1>", self._on_left_down)
        c.bind("<B1-Motion>", self._on_left_drag)
        c.bind("<ButtonRelease-1>", self._on_left_up)
        c.bind("<Button-3>", self._on_right_down)
        c.bind("<Motion>", self._on_motion)
        c.bind("<Leave>", self._on_leave)
        c.bind("<MouseWheel>", self._on_wheel)
        c.bind("<Double-Button-1>", lambda e: "break")

        r = self.root
        r.bind("<KeyPress>", self._on_key)
        r.bind("<Escape>", lambda e: self._escape())

    # -- 스레드 안전 호출 --------------------------------------------------
    def post(self, fn) -> None:
        """다른 스레드에서 tk 작업을 예약."""
        try:
            self.root.after(0, fn)
        except (RuntimeError, tk.TclError):
            pass

    # -----------------------------------------------------------------
    # 입력 처리
    # -----------------------------------------------------------------
    CTRL_MASK = 0x0004

    @staticmethod
    def _ctrl(event) -> bool:
        return bool(event.state & TrayTimerUI.CTRL_MASK)

    @staticmethod
    def _shift(event) -> bool:
        return bool(event.state & 0x0001)

    def _region(self, x: float, y: float) -> str:
        """클릭 좌표 → 영역 판정."""
        if self._in_rect(x, y, self._help_rect()):
            return "help"
        if self._in_rect(x, y, self._hide_rect()):
            return "hide"
        if math.hypot(x - self.g.cx, y - self.g.cy) <= self.g.tick_outer:
            return "dial"
        return "outside"

    @staticmethod
    def _in_rect(x, y, rect) -> bool:
        x0, y0, x1, y1 = rect
        return x0 <= x <= x1 and y0 <= y <= y1

    def _on_left_down(self, event) -> None:
        self.root.focus_force()
        region = self._region(event.x, event.y)

        if region == "help":
            self.show_help()
            return
        if region == "hide":
            self.hide_window()
            return
        if region != "dial":
            return
        if self._alarm_active:
            self._stop_alarm()
            self.core.reset()
            self._flash("STOP")
            self._render()
            return
        if self._ctrl(event):
            self.action_toggle()
            return
        # Ctrl 없는 클릭은 시작/정지를 하지 않는다(오작동 방지).
        # 대신 드래그하면 창 이동, 움직이지 않고 떼면 안내 문구만 띄운다.
        self._drag_origin = (event.x_root - self.root.winfo_x(),
                             event.y_root - self.root.winfo_y())
        self._drag_moved = False

    DRAG_THRESHOLD = 4

    def _on_left_drag(self, event) -> None:
        if self._drag_origin is None:
            return
        dx, dy = self._drag_origin
        nx, ny = event.x_root - dx, event.y_root - dy
        if not self._drag_moved:
            if (abs(nx - self.root.winfo_x()) < self.DRAG_THRESHOLD and
                    abs(ny - self.root.winfo_y()) < self.DRAG_THRESHOLD):
                return
            self._drag_moved = True
        self.root.geometry(f"+{nx}+{ny}")

    def _on_left_up(self, _event) -> None:
        if self._drag_origin is None:
            return
        self._drag_origin = None
        if self._drag_moved:
            self.settings.set("x", self.root.winfo_x())
            self.settings.set("y", self.root.winfo_y())
            self.settings.save()
        else:
            self._flash("Ctrl + Click")
            self._render()

    def _on_right_down(self, event) -> None:
        if self._region(event.x, event.y) != "dial":
            return
        if self._alarm_active:
            self._stop_alarm()
            self.core.reset()
            self._render()
            return
        if self._ctrl(event):
            self.action_reset()
        else:
            self._flash("Ctrl + R-Click")
            self._render()

    def _on_motion(self, event) -> None:
        hover = None
        region = self._region(event.x, event.y)
        if region in ("help", "hide"):
            hover = region
        if hover != self._hover:
            self._hover = hover
            self._render()

    def _on_leave(self, _event) -> None:
        if self._hover is not None:
            self._hover = None
            self._render()

    def _on_wheel(self, event) -> None:
        if self._ctrl(event):                       # Ctrl+휠 = 투명도
            self.adjust_opacity(OPACITY_STEP if event.delta > 0
                                else -OPACITY_STEP)
            return
        step = 10 if self._shift(event) else 1
        delta = step if event.delta > 0 else -step
        self._stop_alarm()
        self.core.adjust_minutes(delta)
        self._remember_minutes()
        self._flash(f"{self.core.set_minutes} MIN")
        self._render()

    def _on_key(self, event) -> None:
        key = event.keysym.lower()
        if key == "space":
            self.action_toggle()
        elif key == "r":
            self.action_reset()
        elif key == "h":
            self._close_help() if self._help_open else self.show_help()
        elif key == "m":
            self.action_mute()
        elif key == "t":
            self.action_topmost()
        elif key == "bracketleft":
            self.adjust_opacity(-OPACITY_STEP)
        elif key == "bracketright":
            self.adjust_opacity(OPACITY_STEP)
        elif key in ("up", "right"):
            self._on_wheel(_FakeWheel(120, event.state))
        elif key in ("down", "left"):
            self._on_wheel(_FakeWheel(-120, event.state))
        elif key == "backspace":
            self._typed = self._typed[:-1]
            self._typed_until = time.monotonic() + 2.0
            self._apply_typed()
        elif len(event.char) == 1 and event.char.isdigit():
            now = time.monotonic()
            if now > self._typed_until:
                self._typed = ""
            self._typed = (self._typed + event.char)[-2:]
            self._typed_until = now + 2.0
            self._apply_typed()

    def _apply_typed(self) -> None:
        self._stop_alarm()
        minutes = int(self._typed) if self._typed else 0
        self.core.apply_minutes(minutes)
        self._remember_minutes()
        self._flash(f"{minutes} MIN")
        self._render()

    def _escape(self) -> None:
        if self._help_open:
            self._close_help()
        else:
            self.hide_window()

    # -----------------------------------------------------------------
    # 액션
    # -----------------------------------------------------------------
    def action_toggle(self) -> None:
        if self._alarm_active:
            self._stop_alarm()
            self.core.reset()
            self._render()
            return
        if self.core.toggle():
            self._flash("START" if self.core.running else "PAUSE")
        else:
            self._flash("SET TIME")     # 0분이라 시작 불가
        self._render()

    def action_reset(self) -> None:
        self._stop_alarm()
        self.core.reset()
        self._flash("RESET")
        self._render()

    def action_mute(self) -> None:
        self.muted = not self.muted
        self.settings.set("muted", self.muted)
        self.settings.save()
        if self.muted:
            self.alarm.stop()
        self._flash("MUTE" if self.muted else "SOUND")
        self._render()

    @staticmethod
    def _clamp_opacity(value) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return OPACITY_MAX
        return max(OPACITY_MIN, min(OPACITY_MAX, round(v, 2)))

    def _apply_opacity(self) -> None:
        """알람 중에는 놓치지 않도록 강제로 불투명하게."""
        alpha = OPACITY_MAX if self._alarm_active else self.opacity
        try:
            self.root.attributes("-alpha", alpha)
        except tk.TclError:
            pass

    def set_opacity(self, value: float) -> None:
        self.opacity = self._clamp_opacity(value)
        self._apply_opacity()
        self.settings.set("opacity", self.opacity)
        self.settings.save()
        self._flash(f"{int(round(self.opacity * 100))}% OPAQUE")
        self._render()

    def adjust_opacity(self, delta: float) -> None:
        self.set_opacity(self.opacity + delta)

    def set_help_lang(self, lang: str) -> None:
        if lang not in HELP_LANGS:
            return
        self.help_lang = lang
        self.settings.set("help_lang", lang)
        self.settings.save()

    def action_topmost(self) -> None:
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        self.settings.set("topmost", self.topmost)
        self.settings.save()
        self._flash("TOP ON" if self.topmost else "TOP OFF")
        self._render()

    def _remember_minutes(self) -> None:
        self.settings.set("minutes", self.core.set_minutes)
        self.settings.save()

    @property
    def _help_open(self) -> bool:
        return self._help_win is not None

    def show_help(self) -> None:
        """도움말을 별도 팝업 창으로 띄운다 (이미 떠 있으면 앞으로)."""
        if self._help_win is not None:
            self._help_win.lift()
            self._help_win.focus_force()
            return
        self._help_win = HelpWindow(self)
        self._render()

    def _close_help(self) -> None:
        if self._help_win is None:
            return
        win, self._help_win = self._help_win, None
        try:
            win.destroy()
        except tk.TclError:
            pass
        self._render()

    def hide_window(self) -> None:
        self._hidden = True
        self.root.withdraw()

    def show_window(self) -> None:
        self._hidden = False
        self.root.deiconify()
        self.root.attributes("-topmost", self.topmost)
        self.root.after(60, self.root.focus_force)

    def toggle_window(self) -> None:
        self.hide_window() if not self._hidden else self.show_window()

    def quit_app(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.alarm.stop()
        self._close_help()
        self.settings.set("x", self.root.winfo_x())
        self.settings.set("y", self.root.winfo_y())
        self.settings.save()
        self.tray.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _flash(self, text: str) -> None:
        self._hint = text
        self._hint_until = time.monotonic() + 1.4

    def _stop_alarm(self) -> None:
        if self._alarm_active:
            self._alarm_active = False
            self.alarm.stop()
            self._apply_opacity()

    # -----------------------------------------------------------------
    # 메인 루프 (100ms)
    # -----------------------------------------------------------------
    def _schedule_tick(self) -> None:
        if not self._quitting:
            self.root.after(100, self._tick)

    def _tick(self) -> None:
        if self._quitting:
            return
        if self.core.poll():                 # 방금 0에 도달
            self._alarm_active = True
            if not self.muted:
                self.alarm.start()
            self.show_window()
            self._apply_opacity()            # 알람은 반투명이어도 또렷하게
        if self._alarm_active:
            self._blink = int(time.monotonic() * 2.5) % 2 == 0
        self._render()
        self._update_tray()
        self._schedule_tick()

    def _update_tray(self) -> None:
        secs = self.core.display_seconds()
        if self._alarm_active:
            text, tip = "!", f"{APP_NAME} — 시간 종료"
        elif secs >= 60:
            text = str(int(math.ceil(secs / 60.0)))
            tip = f"{APP_NAME} — {secs // 60:02d}:{secs % 60:02d} 남음"
        else:
            text = str(secs)
            tip = f"{APP_NAME} — {secs}초 남음"
        state_kr = {"idle": "대기", "running": "동작중",
                    "paused": "일시정지", "finished": "종료"}[self.core.state]
        self.tray.update(text, self.core.fraction(), self._alarm_active,
                         f"{tip} ({state_kr})")

    # -----------------------------------------------------------------
    # 렌더링
    # -----------------------------------------------------------------
    def _render(self) -> None:
        c, g = self.canvas, self.g
        c.delete("all")

        self._draw_dial()
        self._draw_digits()
        self._draw_labels()
        self._draw_buttons()
        self._draw_hint()

    def _rounded_rect(self, x0, y0, x1, y1, r, **kw):
        """create_polygon(smooth) 기반 둥근 사각형."""
        pts = []
        for cx, cy, a0 in ((x1 - r, y0 + r, 0), (x1 - r, y1 - r, 90),
                           (x0 + r, y1 - r, 180), (x0 + r, y0 + r, 270)):
            for i in range(9):
                a = math.radians(a0 - 90 + i * (90 / 8))
                pts += [cx + r * math.cos(a), cy + r * math.sin(a)]
        return self.canvas.create_polygon(pts, smooth=False, **kw)

    # -- 다이얼 + 방사형 눈금 ---------------------------------------------
    def _draw_dial(self) -> None:
        c, g = self.canvas, self.g
        cx, cy, r = g.cx, g.cy, g.tick_outer

        c.create_oval(cx - r, cy - r, cx + r, cy + r,
                      fill=C_DIAL_BG, outline=C_DIAL_EDGE,
                      width=max(1, g.px(1.5)))

        frac = self.core.fraction()
        lit = int(math.ceil(frac * TICK_COUNT - 1e-9))
        on_color = C_ALARM if (self._alarm_active and self._blink) else C_TICK_ON

        step = 360.0 / TICK_COUNT
        half = math.radians(step * 0.36)           # 눈금 두께(각도)
        r_in, r_out = g.tick_inner, g.tick_end

        for i in range(TICK_COUNT):
            if i >= lit and not self._alarm_active:
                continue                           # 지나간 눈금은 검정 배경 그대로
            if self._alarm_active and not self._blink:
                continue
            mid = math.radians(-90 + i * step)
            a0, a1 = mid - half, mid + half
            pts = [cx + r_in * math.cos(a0), cy + r_in * math.sin(a0),
                   cx + r_out * math.cos(a0), cy + r_out * math.sin(a0),
                   cx + r_out * math.cos(a1), cy + r_out * math.sin(a1),
                   cx + r_in * math.cos(a1), cy + r_in * math.sin(a1)]
            c.create_polygon(pts, fill=on_color, outline="")

        rd = g.disc_radius
        c.create_oval(cx - rd, cy - rd, cx + rd, cy + rd,
                      fill=C_DIAL_BG, outline="#ffffff",
                      width=max(1, g.px(1.2)))

    # -- 7-세그먼트 숫자 ---------------------------------------------------
    def _draw_digits(self) -> None:
        g = self.g
        secs = self.core.display_seconds()
        mm, ss = min(99, secs // 60), secs % 60
        text = f"{mm:02d}{ss:02d}"

        # 알람 중에는 숫자 전체가 점멸, 그 외에는 항상 표시(콜론만 점멸)
        show = self._blink if self._alarm_active else True

        total_w = 4 * g.digit_w + 2 * g.digit_gap + 2 * g.colon_gap + g.colon_w
        x = g.cx - total_w / 2.0
        top = g.digits_cy - g.digit_h / 2.0

        color = C_ALARM if (self._alarm_active and self._blink) else C_LCD_ON
        for idx, ch in enumerate(text):
            self._draw_seven_seg(x, top, ch, color if show else C_LCD_OFF)
            x += g.digit_w
            if idx == 0:
                x += g.digit_gap
            elif idx == 1:
                x += g.colon_gap
                self._draw_colon(x, top, color if show else C_LCD_OFF)
                x += g.colon_w + g.colon_gap
            elif idx == 2:
                x += g.digit_gap

    def _draw_seven_seg(self, x, y, ch, color) -> None:
        g = self.g
        w, h, t = g.digit_w - g.px(2), g.digit_h, g.digit_t
        on = SEGMENTS.get(ch, "")
        half = h / 2.0
        specs = {
            "a": ("h", x, y),
            "b": ("v", x + w - t, y),
            "c": ("v", x + w - t, y + half),
            "d": ("h", x, y + h - t),
            "e": ("v", x, y + half),
            "f": ("v", x, y),
            "g": ("h", x, y + half - t / 2.0),
        }
        # 세그먼트끼리 모서리가 겹치므로 '꺼진 것 → 켜진 것' 순서로 두 번 그린다.
        # (한 번에 그리면 나중에 그려진 꺼진 세그먼트가 켜진 획을 잘라먹는다.)
        for lit_pass in (False, True):
            for name, (kind, sx, sy) in specs.items():
                if (name in on) != lit_pass:
                    continue
                pts = (self._h_seg(sx, sy, w, t) if kind == "h"
                       else self._v_seg(sx, sy, half, t))
                self.canvas.create_polygon(self._slant(pts, y, h),
                                           fill=color if lit_pass else C_LCD_OFF,
                                           outline="")

    @staticmethod
    def _h_seg(x, y, length, t):
        h = t / 2.0
        return [(x + h, y), (x + length - h, y), (x + length, y + h),
                (x + length - h, y + t), (x + h, y + t), (x, y + h)]

    @staticmethod
    def _v_seg(x, y, length, t):
        h = t / 2.0
        return [(x + h, y), (x + t, y + h), (x + t, y + length - h),
                (x + h, y + length), (x, y + length - h), (x, y + h)]

    @staticmethod
    def _slant(pts, top, height):
        """아래를 고정하고 위를 오른쪽으로 밀어 LCD 특유의 기울기를 만든다."""
        out = []
        for px, py in pts:
            out += [px + (top + height - py) * SLANT, py]
        return out

    def _draw_colon(self, x, top, color) -> None:
        g = self.g
        d = g.px(6)
        blink = True
        if self.core.running:
            blink = int(time.monotonic() * 2) % 2 == 0
        col = color if blink else C_LCD_OFF
        for fy in (0.30, 0.70):
            cy = top + g.digit_h * fy
            cx = x + g.colon_w / 2.0 + (top + g.digit_h - cy) * SLANT
            self.canvas.create_oval(cx - d / 2, cy - d / 2,
                                    cx + d / 2, cy + d / 2,
                                    fill=col, outline="")

    # -- 라벨 / 아이콘 -----------------------------------------------------
    def _draw_labels(self) -> None:
        c, g = self.canvas, self.g
        base = g.digits_cy + g.digit_h / 2.0 + g.px(2)
        total_w = 4 * g.digit_w + 2 * g.digit_gap + 2 * g.colon_gap + g.colon_w
        left = g.cx - total_w / 2.0
        f = ("Arial", max(6, int(g.px(7))), "bold")
        c.create_text(left + g.digit_w * 1.55, base, text="M",
                      fill=C_LABEL, font=f, anchor="n")
        c.create_text(left + total_w - g.digit_w * 0.45, base, text="S",
                      fill=C_LABEL, font=f, anchor="n")
        self._draw_speaker(g.cx, g.icon_cy)

    def _draw_speaker(self, cx, cy) -> None:
        c, g = self.canvas, self.g
        u = g.px(1)
        col = "#4a4a4a" if self.muted else C_LABEL
        c.create_polygon(cx - 7 * u, cy - 3 * u, cx - 3 * u, cy - 3 * u,
                         cx + 1 * u, cy - 7 * u, cx + 1 * u, cy + 7 * u,
                         cx - 3 * u, cy + 3 * u, cx - 7 * u, cy + 3 * u,
                         fill=col, outline="")
        if self.muted:
            c.create_line(cx + 3 * u, cy - 5 * u, cx + 9 * u, cy + 5 * u,
                          fill="#7a2a2a", width=max(1, int(1.6 * u)))
            c.create_line(cx + 9 * u, cy - 5 * u, cx + 3 * u, cy + 5 * u,
                          fill="#7a2a2a", width=max(1, int(1.6 * u)))
        else:
            for i, rr in enumerate((4, 7)):
                c.create_arc(cx + 1 * u - rr * u, cy - rr * u,
                             cx + 1 * u + rr * u, cy + rr * u,
                             start=-55, extent=110, style="arc",
                             outline=col, width=max(1, int(1.2 * u)))

    # -- HELP / HIDE 버튼 --------------------------------------------------
    def _btn_font(self):
        return ("Arial", max(7, int(self.g.px(9))), "bold")

    def _help_rect(self):
        g = self.g
        w, h = g.px(46), g.px(20)
        cx = g.cx - g.px(26)
        return (cx - w / 2, g.btn_cy - h / 2, cx + w / 2, g.btn_cy + h / 2)

    def _hide_rect(self):
        g = self.g
        w, h = g.px(46), g.px(20)
        cx = g.cx + g.px(26)
        return (cx - w / 2, g.btn_cy - h / 2, cx + w / 2, g.btn_cy + h / 2)

    def _draw_buttons(self) -> None:
        for name, rect, label in (("help", self._help_rect(), "HELP"),
                                  ("hide", self._hide_rect(), "HIDE")):
            self._draw_button(name, rect, label)
        g = self.g
        self.canvas.create_line(g.cx, g.btn_cy - g.px(7),
                                g.cx, g.btn_cy + g.px(7),
                                fill="#3a3a3a", width=1)

    def _draw_button(self, name, rect, label) -> None:
        c, g = self.canvas, self.g
        x0, y0, x1, y1 = rect
        active = self._hover == name
        if active:
            self._rounded_rect(x0, y0, x1, y1, g.px(6),
                               fill="#2b2b2b", outline="")
        c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=label,
                      fill=C_BTN_HOVER if active else C_BTN,
                      font=self._btn_font())

    # -- 상태 힌트 ---------------------------------------------------------
    def _draw_hint(self) -> None:
        g = self.g
        if time.monotonic() < self._hint_until:
            text, color = self._hint, C_HINT
        elif self._alarm_active:
            text, color = "TIME UP", C_ALARM
        elif self.core.state == "running":
            text, color = "RUNNING", "#6a6a6a"
        elif self.core.state == "paused":
            text, color = "PAUSED", "#6a6a6a"
        else:
            text, color = f"SET {self.core.set_minutes:02d} MIN", "#5a5a5a"
        self.canvas.create_text(g.cx, g.hint_cy, text=text, fill=color,
                                font=("Arial", max(6, int(g.px(8))), "bold"))

    # -----------------------------------------------------------------
    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            self.alarm.stop()
            self.tray.stop()


class _FakeWheel:
    """키보드 화살표를 휠 이벤트처럼 다루기 위한 어댑터."""

    def __init__(self, delta: int, state: int):
        self.delta = delta
        self.state = state


# ---------------------------------------------------------------------------

_MUTEX_HANDLE = None          # 프로세스가 살아있는 동안 유지되어야 한다


def _acquire_single_instance() -> bool:
    """
    이미 실행 중이면 False.

    설치본은 시작프로그램으로도 뜨기 때문에, 막지 않으면
    트레이 아이콘이 두 개 생기고 설정 파일을 서로 덮어쓴다.
    """
    global _MUTEX_HANDLE
    if sys.platform != "win32":
        return True
    ERROR_ALREADY_EXISTS = 183
    k32 = ctypes.windll.kernel32
    _MUTEX_HANDLE = k32.CreateMutexW(None, False, "DialTimer.SingleInstance")
    return k32.GetLastError() != ERROR_ALREADY_EXISTS


def _enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # System DPI aware
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def main() -> int:
    if sys.platform == "win32":
        _enable_dpi_awareness()
        if not _acquire_single_instance():
            ctypes.windll.user32.MessageBoxW(
                None,
                f"{APP_NAME} 이(가) 이미 실행 중입니다.\n"
                "작업표시줄 알림 영역(트레이)을 확인하세요.",
                APP_NAME, 0x40)          # MB_ICONINFORMATION
            return 0
    TrayTimerUI().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
