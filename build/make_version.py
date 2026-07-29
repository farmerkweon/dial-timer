# -*- coding: utf-8 -*-
"""
PyInstaller용 버전 리소스 파일 생성기.

exe 속성 → 자세히 에 제품 이름·버전·저작권이 뜨게 한다.
버전은 tray_timer.py의 APP_VERSION에서 읽어오므로 손으로 두 곳을
고치다 어긋나는 일이 없다.
"""

import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "tray_timer.py")
OUT = os.path.join(BASE, "build", "version_info.txt")

TEMPLATE = """\
# 자동 생성 파일 — build/make_version.py 가 만든다. 직접 고치지 말 것.
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v0}, {v1}, {v2}, 0),
    prodvers=({v0}, {v1}, {v2}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '041204B0',
        [StringStruct('CompanyName', 'foxnail.kr'),
         StringStruct('FileDescription', '{desc}'),
         StringStruct('FileVersion', '{ver}.0'),
         StringStruct('InternalName', 'DialTimer'),
         StringStruct('LegalCopyright',
                      'Copyright (c) 2026 foxnail.kr. MIT License.'),
         StringStruct('OriginalFilename', 'DialTimer.exe'),
         StringStruct('ProductName', '{name}'),
         StringStruct('ProductVersion', '{ver}.0')])
    ]),
    VarFileInfo([VarStruct('Translation', [0x0412, 1200])])
  ]
)
"""


def read_const(name: str) -> str:
    with open(SRC, "r", encoding="utf-8") as fp:
        text = fp.read()
    m = re.search(rf'^{name}\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        raise SystemExit(f"{SRC} 에서 {name} 를 찾지 못했습니다")
    return m.group(1)


def main() -> int:
    name = read_const("APP_NAME")
    ver = read_const("APP_VERSION")
    parts = ver.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise SystemExit(f"APP_VERSION 형식이 x.y.z 가 아닙니다: {ver}")

    text = TEMPLATE.format(
        v0=parts[0], v1=parts[1], v2=parts[2], ver=ver, name=name,
        desc=f"{name} — 0~99분 다이얼 타이머 / dial timer",
    )
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(f"saved {OUT}  (version {ver})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
