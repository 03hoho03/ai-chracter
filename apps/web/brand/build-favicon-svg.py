"""apps/web/public/favicon.svg 를 Pretendard Bold의 '또' 글리프 외곽선으로 생성한다.

<text>가 아니라 <path>로 굽는 이유: 파비콘 SVG를 렌더하는 쪽(브라우저 탭, 크롤러,
피드 리더)에 Pretendard가 없으면 <text>는 시스템 고딕으로 대체되어 자형과 중심이
흔들린다. 외곽선으로 구우면 어디서 열어도 같은 그림이 된다.

실행은 apps/web/brand/generate.sh 가 담당한다 (uv 임시 환경 + 상대 경로 처리).
"""

import sys
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

# DESIGN.md 팔레트의 다크 값을 sRGB로 옮긴 것. oklch를 못 읽는 렌더러가 있어 SVG에는 hex로 넣는다
BACKGROUND = "#0d0d0d"  # oklch(0.16 0 0) — 다크 background
FOREGROUND = "#e8e8e8"  # oklch(0.93 0 0) — 다크 foreground (밝기 천장, 순백 금지)

CANVAS = 96  # viewBox 한 변
CORNER_RADIUS = 20  # 96 기준 약 21% — 앱 아이콘 관용값
GLYPH_BOX = 72  # 글리프가 들어갈 정사각 영역. 16px 탭에서 ㄸ의 두 획이 붙지 않는 하한선이라 크게 잡았다
WEIGHT = 700  # bold (DESIGN.md는 medium/semibold/bold만 허용)
CHARACTER = "또"


def main() -> int:
    font_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])

    font = instantiateVariableFont(TTFont(font_path), {"wght": WEIGHT})
    glyph_name = font.getBestCmap()[ord(CHARACTER)]
    glyph_set = font.getGlyphSet()

    bounds_pen = BoundsPen(glyph_set)
    glyph_set[glyph_name].draw(bounds_pen)
    x_min, y_min, x_max, y_max = bounds_pen.bounds

    # 글리프 실제 bbox를 GLYPH_BOX에 꽉 채우고 캔버스 정중앙에 놓는다. 폰트 메트릭(어센더/
    # 디센더)이 아니라 bbox 기준이라 시각적 중심이 맞는다
    scale = GLYPH_BOX / max(x_max - x_min, y_max - y_min)
    offset_x = (CANVAS - (x_max - x_min) * scale) / 2 - x_min * scale
    offset_y = (CANVAS + (y_max - y_min) * scale) / 2 + y_min * scale

    path_pen = SVGPathPen(glyph_set, ntos=lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
    glyph_set[glyph_name].draw(path_pen)

    out_path.write_text(
        "\n".join(
            [
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CANVAS} {CANVAS}">',
                f"  <!-- Pretendard Bold '{CHARACTER}' 외곽선. 재생성: apps/web/brand/generate.sh -->",
                f'  <rect width="{CANVAS}" height="{CANVAS}" rx="{CORNER_RADIUS}" fill="{BACKGROUND}"/>',
                f'  <path transform="translate({offset_x:.1f} {offset_y:.1f}) scale({scale:.5f} -{scale:.5f})"',
                f'        fill="{FOREGROUND}" d="{path_pen.getCommands()}"/>',
                "</svg>",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
