# -*- coding: utf-8 -*-
"""
앱 아이콘(.ico) 생성기.

다이얼 모양(검은 원반 + 빨간 방사형 눈금)을 그대로 축소해 만든다.
작은 크기에서는 눈금이 뭉개지므로 크기별로 눈금 수와 두께를 달리한다.
"""

import os
import sys

from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dial_timer.ico")
SIZES = (16, 24, 32, 48, 64, 128, 256)

BLACK = (18, 18, 18, 255)
RED = (216, 31, 38, 255)
WHITE = (245, 245, 245, 255)


def render(size: int) -> Image.Image:
    """4배 슈퍼샘플링으로 그린 뒤 축소해 계단 현상을 줄인다."""
    ss = 4
    n = size * ss
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    c = n / 2.0
    r_out = n / 2.0 - n * 0.02
    d.ellipse((c - r_out, c - r_out, c + r_out, c + r_out), fill=BLACK)

    # 작은 아이콘일수록 눈금을 적게 (16px에서 60개는 뭉개진다)
    ticks = 60 if size >= 64 else (30 if size >= 32 else 20)
    rim = r_out * 0.055
    tick_out = r_out - rim
    tick_len = r_out * 0.16
    tick_in = tick_out - tick_len
    half = (3.14159265 / ticks) * 0.55        # 눈금 각도 절반

    import math
    for i in range(ticks):
        mid = -math.pi / 2 + i * (2 * math.pi / ticks)
        a0, a1 = mid - half, mid + half
        d.polygon([
            (c + tick_in * math.cos(a0), c + tick_in * math.sin(a0)),
            (c + tick_out * math.cos(a0), c + tick_out * math.sin(a0)),
            (c + tick_out * math.cos(a1), c + tick_out * math.sin(a1)),
            (c + tick_in * math.cos(a1), c + tick_in * math.sin(a1)),
        ], fill=RED)

    # 안쪽 원반 + 흰 테두리 링
    r_disc = tick_in - r_out * 0.045
    d.ellipse((c - r_disc, c - r_disc, c + r_disc, c + r_disc),
              fill=BLACK, outline=WHITE,
              width=max(1, int(r_out * 0.035)))

    # 가운데 콜론 두 점 (LCD 느낌 — 작은 크기에서도 살아남는 최소 요소)
    dot = r_disc * 0.13
    for dy in (-r_disc * 0.34, r_disc * 0.34):
        d.ellipse((c - dot, c + dy - dot, c + dot, c + dy + dot), fill=WHITE)

    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    layers = [render(s) for s in SIZES]
    layers[-1].save(OUT, format="ICO",
                    sizes=[(s, s) for s in SIZES])
    print("saved", OUT, os.path.getsize(OUT), "bytes")

    preview = Image.new("RGBA", (sum(SIZES) + 10 * len(SIZES), 256),
                        (48, 48, 48, 255))
    x = 0
    for img, s in zip(layers, SIZES):
        preview.paste(img, (x, 256 - s), img)
        x += s + 10
    preview.save(os.path.join(os.path.dirname(OUT), "icon_preview.png"))
    print("saved preview")
    return 0


if __name__ == "__main__":
    sys.exit(main())
