# 브랜드 자산 원본

`apps/web/public/`의 자산 3개를 만드는 원본이다. **정식 디자인이 나오면 public의 파일 3개를
교체하면 끝난다** — 코드는 파일 이름만 참조하고 그림 내용에 의존하는 로직이 없다.

| 산출물 | 규격 | 쓰이는 곳 | 원본 |
|---|---|---|---|
| `public/og-default.png` | 1200x630 | 홈 `og:image`, 썸네일 없는 콘텐츠의 `og:image` 폴백 | `og-default.html` |
| `public/favicon.svg` | 정사각(96 viewBox) | 브라우저 탭, 구글 검색 결과 | `build-favicon-svg.py` |
| `public/favicon-96.png` | 96x96 | SVG를 못 읽는 크롤러용 폴백(구글 최소 48x48) | `favicon-96.html` (= favicon.svg를 굽는다) |

## 재생성

```sh
apps/web/brand/generate.sh
```

필요한 것: Chrome(헤드리스 스크린샷), `uv`(fontTools 임시 환경), `python3`, `pnpm install` 완료.
Chrome 경로가 다르면 `CHROME=... apps/web/brand/generate.sh`.

## 이렇게 만든 이유

- **색은 DESIGN.md 다크 팔레트**: 배경 `background`(oklch 0.16), 글자 `foreground`(oklch 0.93 —
  밝기 천장이라 순백을 쓰지 않는다), 유채색은 `primary` 한 곳만. HTML은 oklch를 그대로 쓰고
  SVG에는 sRGB hex로 넣는다(oklch를 못 읽는 렌더러가 있다).
- **파비콘 글자는 `<text>`가 아니라 `<path>`**: 렌더하는 쪽에 Pretendard가 없으면 `<text>`는 시스템
  고딕으로 대체되어 자형과 중심이 흔들린다. Pretendard Bold `또` 외곽선을 구워 넣으면 어디서 열어도
  같은 그림이다.
- **파비콘에 배경 판을 칠한다**: 투명 배경이면 라이트 테마 탭에서 밝은 글자가 보이지 않는다.
- **`GLYPH_BOX`는 16px 탭 기준으로 정했다**: 값을 줄이면 `ㄸ`의 두 획이 16px에서 한 덩어리로 뭉갠다.
- **PNG는 로컬 HTTP 서버 위에서 굽는다**: `file://`에서는 Chrome이 `@font-face`와 SVG `<img>`를 막는다.
- **OG 이미지의 글자 크기가 앱의 `text-2xl` 천장을 넘는다**: 여기는 UI가 아니라 1200x630 캔버스이고
  공유 카드는 축소되어 보인다. 내용은 전부 가운데 630x630 안에 두었다 — 카카오톡·트위터 `summary`
  카드가 중앙을 정사각으로 잘라 쓴다.
