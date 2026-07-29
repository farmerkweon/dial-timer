# -*- coding: utf-8 -*-
"""TimerCore 단위 테스트 (UI 없이 로직만 검증)."""

import sys
import time

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from tray_timer import TimerCore, MAX_MINUTES  # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        FAILED.append(name)


print("[T1] 초기 상태")
c = TimerCore(5)
check("set=5min", c.set_minutes == 5)
check("total=300s", c.total == 300)
check("display=300", c.display_seconds() == 300, c.display_seconds())
check("state=idle", c.state == "idle")
check("fraction=1.0", abs(c.fraction() - 1.0) < 1e-9)

print("[T2] 범위 클램프 0~99")
c.apply_minutes(-5);  check("하한 0", c.set_minutes == 0)
c.apply_minutes(120); check("상한 99", c.set_minutes == MAX_MINUTES)
c.apply_minutes(99);  check("99분=5940s", c.total == 5940)

print("[T3] 0분은 시작 불가")
c.apply_minutes(0)
check("start()=False", c.start() is False)
check("state 유지", c.state == "idle")
check("fraction=0", c.fraction() == 0.0)

print("[T4] 시작/일시정지/재개")
c.apply_minutes(1)
check("start()=True", c.start() is True)
check("running", c.running)
time.sleep(0.35)
c.pause()
check("paused", c.state == "paused")
left = c.remaining_seconds()
check("경과 반영(0.3~0.5s 감소)", 59.5 < left < 59.75, round(left, 3))
time.sleep(0.25)
check("일시정지 중 정지", abs(c.remaining_seconds() - left) < 1e-6)
c.toggle()
check("toggle로 재개", c.running)
c.toggle()
check("toggle로 정지", c.state == "paused")

print("[T5] 리셋")
c.reset()
check("remaining 복원", c.display_seconds() == 60)
check("state=idle", c.state == "idle")

print("[T6] 완주 감지")
c.apply_minutes(1)
c.start()
c._deadline = time.monotonic() - 0.01     # 강제 만료
check("poll()=True (1회)", c.poll() is True)
check("state=finished", c.state == "finished")
check("poll() 재호출은 False", c.poll() is False)
check("remaining=0", c.remaining_seconds() == 0.0)
check("음수 없음", c.display_seconds() == 0)

print("[T7] 표시 올림 (5:00이 4:59로 안 보이게)")
c.apply_minutes(5)
c.start()
time.sleep(0.05)
check("display=300", c.display_seconds() == 300, c.display_seconds())

print("[T8] 동작 중 설정 변경 시 정지+리셋")
c.apply_minutes(10)
check("state=idle", c.state == "idle")
check("total=600", c.total == 600)
c.adjust_minutes(-3)
check("adjust -3 → 7분", c.set_minutes == 7)

print("[T9] fraction 단조 감소")
c.apply_minutes(1)
c.start()
f1 = c.fraction()
time.sleep(0.2)
f2 = c.fraction()
check("f1 > f2", f1 > f2, (round(f1, 4), round(f2, 4)))
check("0<=f<=1", 0.0 <= f2 <= 1.0)

print()
if FAILED:
    print("실패:", FAILED)
    sys.exit(1)
print("전체 통과")
