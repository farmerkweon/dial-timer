# -*- coding: utf-8 -*-
"""
도움말 응원 섹션에 넣을 QR 이미지 생성기.

원본(sudoku.png / artgrid.png)은 제목 글자와 여백이 넓어 그대로 줄이면
QR 한 모듈이 2px 남짓이 되고, 게다가 원본 모듈 크기(7px)가 표시 크기와
정수배로 떨어지지 않아 축소할 때 모듈 경계가 회색으로 뭉개진다.
(실측: 96~180px 구간을 훑으면 크기에 따라 디코딩이 되었다 안 되었다 한다.)

그래서 원본 픽셀을 리샘플링하지 않는다. 모듈 중심을 읽어 29x29 격자를
그대로 복원한 뒤, 한 모듈 = 정수 픽셀로 다시 그린다. 산출물의 한 변이
모듈 수의 정수배이므로, 표시할 때도 모듈 수의 배수로만 줄이면
NEAREST 로 정확히 떨어져 어떤 배율에서도 또렷하다.

  산출물 구성(모듈 단위):  테두리 1 + 여백 3 + QR 29 + 여백 3 + 테두리 1 = 37

실행:  py build\\make_qr_assets.py
"""

import os
import sys

from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "assets")

SOURCES = [("sudoku.png", "qr-sudoku.png"),
           ("artgrid.png", "qr-artgrid.png")]

MODULES = 29          # QR 한 변의 모듈 수 (version 3)
QUIET = 4             # QR 규격이 요구하는 흰 여백 (모듈). 줄이면 인식률이 떨어진다
BORDER = 1            # 색 테두리 두께 (모듈). 여백 바깥이라 여백을 잠식하지 않는다
EDGE_MODULES = BORDER + QUIET + MODULES + QUIET + BORDER   # = 39
MODULE_PX = 8         # 산출물의 모듈 한 변(px) → 37 * 8 = 296px
LOGO_MODULES = 7      # 가운데 로고를 옮겨 붙일 정사각 크기 (모듈)

DARK = 100            # 이보다 어두우면 검은 모듈
SAT = 60              # 채도가 이보다 크면 유채색(테두리)


def _is_colored(p) -> bool:
    r, g, b = p
    return (max(r, g, b) - min(r, g, b)) > SAT and max(r, g, b) > 120


def find_qr(im: Image.Image):
    """
    색 테두리 안쪽에서 QR 본체의 바운딩 박스와 모듈 크기를 찾는다.

    제목 글자가 유채색인 원본(파란 'LottoSudoku')도 있어서, 테두리는
    가로 범위로 잡고 세로는 정사각으로 되맞춘다.
    """
    px = im.load()
    w, h = im.size

    xs = [x for x in range(w) for y in range(h) if _is_colored(px[x, y])]
    ys = [y for y in range(h) for x in range(w) if _is_colored(px[x, y])]
    fx0, fx1, fy1 = min(xs), max(xs), max(ys)
    fy0 = fy1 - (fx1 - fx0)                      # 테두리는 정사각

    # 테두리 안쪽(흰 여백 포함)에서 검은 픽셀의 경계 = QR 본체
    inner = [(x, y)
             for y in range(fy0, fy1 + 1)
             for x in range(fx0, fx1 + 1)
             if sum(px[x, y]) / 3 < DARK and not _is_colored(px[x, y])]
    qxs = [x for x, _ in inner]
    qys = [y for _, y in inner]
    x0, x1, y0, y1 = min(qxs), max(qxs), min(qys), max(qys)

    size = max(x1 - x0 + 1, y1 - y0 + 1)
    module = size / MODULES
    if not (5.0 <= module <= 12.0):
        raise SystemExit(f"모듈 크기가 이상합니다: {module:.2f}px "
                         f"(QR {size}px / {MODULES}모듈)")
    return x0, y0, size, module


def read_grid(im: Image.Image, x0: int, y0: int, module: float):
    """모듈 중심 픽셀을 읽어 29x29 흑백 격자로 복원한다."""
    px = im.load()
    grid = []
    for row in range(MODULES):
        line = []
        for col in range(MODULES):
            cx = int(x0 + (col + 0.5) * module)
            cy = int(y0 + (row + 0.5) * module)
            line.append(sum(px[cx, cy]) / 3 < DARK)
        grid.append(line)
    return grid


def border_color(im: Image.Image):
    """테두리에서 가장 많이 쓰인 유채색을 대표색으로 삼는다."""
    px = im.load()
    w, h = im.size
    counts = {}
    for y in range(h):
        for x in range(w):
            p = px[x, y]
            if _is_colored(p):
                counts[p] = counts.get(p, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]


def build(im: Image.Image) -> Image.Image:
    x0, y0, size, module = find_qr(im)
    grid = read_grid(im, x0, y0, module)
    color = border_color(im)

    edge = EDGE_MODULES * MODULE_PX
    out = Image.new("RGB", (edge, edge), color)          # 테두리색으로 채우고
    inner_px = (EDGE_MODULES - 2 * BORDER) * MODULE_PX
    out.paste((255, 255, 255),                            # 안쪽은 흰 여백
              (BORDER * MODULE_PX, BORDER * MODULE_PX,
               BORDER * MODULE_PX + inner_px, BORDER * MODULE_PX + inner_px))

    off = (BORDER + QUIET) * MODULE_PX
    for row in range(MODULES):
        for col in range(MODULES):
            if grid[row][col]:
                x = off + col * MODULE_PX
                y = off + row * MODULE_PX
                out.paste((0, 0, 0),
                          (x, y, x + MODULE_PX, y + MODULE_PX))

    # 가운데 로고는 모듈로 복원되지 않으므로 원본에서 그대로 옮겨 붙인다.
    half = LOGO_MODULES / 2
    c0 = int(x0 + (MODULES / 2 - half) * module)
    c1 = int(x0 + (MODULES / 2 + half) * module)
    r0 = int(y0 + (MODULES / 2 - half) * module)
    r1 = int(y0 + (MODULES / 2 + half) * module)
    logo = im.crop((c0, r0, c1, r1)).resize(
        (LOGO_MODULES * MODULE_PX, LOGO_MODULES * MODULE_PX), Image.LANCZOS)
    lo = off + int((MODULES - LOGO_MODULES) / 2) * MODULE_PX
    out.paste(logo, (lo, lo))
    return out


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    for src_name, out_name in SOURCES:
        src = os.path.join(BASE, src_name)
        if not os.path.exists(src):
            raise SystemExit(f"원본이 없습니다: {src}")
        with Image.open(src) as im:
            out_im = build(im.convert("RGB"))
        out = os.path.join(OUT_DIR, out_name)
        out_im.save(out, optimize=True)
        print(f"saved {out}  {out_im.width}x{out_im.height} "
              f"({EDGE_MODULES}모듈 x {MODULE_PX}px)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
