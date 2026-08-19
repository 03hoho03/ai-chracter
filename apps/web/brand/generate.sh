#!/usr/bin/env bash
# 브랜드 자산 3개를 재생성한다 — apps/web/public/{og-default.png,favicon.svg,favicon-96.png}.
#
# 원본은 이 디렉터리의 og-default.html / favicon-96.html / build-favicon-svg.py이고,
# 정식 디자인이 나오면 public의 파일 3개를 교체하기만 하면 된다(코드는 파일 내용에
# 의존하지 않는다).
#
# 필요한 것: Chrome(헤드리스 스크린샷), uv(fontTools 임시 환경), python3(로컬 서버), pnpm install 완료
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

# 1) favicon.svg — Pretendard Bold '또' 글리프를 <path>로 구워낸다
uv run --quiet --with fonttools --with brotli \
  python "$BRAND/build-favicon-svg.py" "$FONT" "$PUBLIC/favicon.svg"
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
