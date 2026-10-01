#!/usr/bin/env bash
# 브랜드 자산 4개를 재생성한다 — apps/web/public/{og-default.png,favicon.svg,favicon-96.png,favicon.ico}.
#
# 원본은 이 디렉터리의 og-default.html / favicon-96.html / favicon-ico.html / favicon.svg이고,
# 정식 디자인이 나오면 public의 파일 4개를 교체하기만 하면 된다(코드는 파일 내용에
# 의존하지 않는다).
#
# 필요한 것: Chrome(헤드리스 스크린샷), python3(로컬 서버), pnpm install 완료(OG 이미지의 Pretendard)
# 사용법: apps/web/brand/generate.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BRAND="$ROOT/apps/web/brand"
PUBLIC="$ROOT/apps/web/public"
FONT="$ROOT/packages/ui/node_modules/pretendard/dist/web/variable/woff2/PretendardVariable.woff2"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
PORT="${PORT:-8799}"

[ -f "$FONT" ] || { echo "Pretendard가 없다. 먼저 pnpm install: $FONT" >&2; exit 1; }
[ -x "$CHROME" ] || { echo "Chrome이 없다. CHROME 환경변수로 경로를 넘길 수 있다: $CHROME" >&2; exit 1; }

# 1) favicon.svg — 손으로 그린 심볼이라 그대로 복사한다
cp "$BRAND/favicon.svg" "$PUBLIC/favicon.svg"
echo "favicon.svg 생성"

# 2) PNG 두 장 — Chrome 헤드리스 스크린샷. @font-face와 SVG <img>가 상대 경로로 붙어야 해서
#    저장소 루트를 document root로 하는 로컬 서버를 잠깐 띄운다(file://은 Chrome이 차단한다)
python3 -m http.server "$PORT" --directory "$ROOT" --bind 127.0.0.1 >/dev/null 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
  curl -sf "http://127.0.0.1:$PORT/apps/web/brand/og-default.html" >/dev/null && break
  sleep 0.2
done

shoot() { # shoot <html경로> <출력파일> <가로,세로>
  "$CHROME" --headless --disable-gpu --hide-scrollbars \
    --default-background-color=00000000 --force-device-scale-factor=1 \
    --window-size="$3" --screenshot="$2" \
    "http://127.0.0.1:$PORT/$1" >/dev/null 2>&1
}

shoot "apps/web/brand/og-default.html" "$PUBLIC/og-default.png" "1200,630"
echo "og-default.png 생성"
shoot "apps/web/brand/favicon-96.html" "$PUBLIC/favicon-96.png" "96,96"
echo "favicon-96.png 생성"

# 3) favicon.ico — HTML의 <link rel="icon">을 읽지 않고 /favicon.ico를 직접 찾는 크롤러·브라우저용.
#    파일이 없으면 Worker가 앱 셸 HTML을 200으로 돌려줘 아이콘 자리에 HTML이 들어간다.
#    16·32·48px PNG를 찍어 PNG 조각을 담는 ICO로 묶는다(표준 라이브러리만 쓴다)
ICO_TMP="$(mktemp -d)"
for size in 16 32 48; do
  shoot "apps/web/brand/favicon-ico.html" "$ICO_TMP/$size.png" "$size,$size"
done
python3 - "$ICO_TMP" "$PUBLIC/favicon.ico" <<'PY'
import struct, sys
from pathlib import Path

src, out = Path(sys.argv[1]), Path(sys.argv[2])
sizes = (16, 32, 48)
images = [(src / f"{size}.png").read_bytes() for size in sizes]
offset = 6 + 16 * len(images)
parts = [struct.pack("<HHH", 0, 1, len(images))]
for size, data in zip(sizes, images):
    parts.append(struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(data), offset))
    offset += len(data)
out.write_bytes(b"".join(parts + images))
PY
rm -rf "$ICO_TMP"
echo "favicon.ico 생성"
