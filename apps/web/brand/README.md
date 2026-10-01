# 브랜드 자산 원본

`apps/web/public/`의 자산 3개를 만드는 원본이다. **정식 디자인이 나오면 public의 파일 3개를
교체하면 끝난다** — 코드는 파일 이름만 참조하고 그림 내용에 의존하는 로직이 없다.

| 산출물 | 규격 | 쓰이는 곳 | 원본 |
|---|---|---|---|
| `public/og-default.png` | 1200x630 | 홈 `og:image`, 썸네일 없는 콘텐츠의 `og:image` 폴백 | `og-default.html` |
| `public/favicon.svg` | 정사각(96 viewBox) | 브라우저 탭, 구글 검색 결과 | `favicon.svg` (복사) |
| `public/favicon-96.png` | 96x96 | SVG를 못 읽는 크롤러용 폴백(구글 최소 48x48) | `favicon-96.html` (= favicon.svg를 굽는다) |

## 재생성

작품 댓글의 공식 스티커 8개와 원본·내보내기·검수 기록은
[`comment-stickers/README.md`](comment-stickers/README.md)에 있다.
파비콘/OG 재생성 스크립트와는 별도로 관리한다.

```sh
apps/web/brand/generate.sh
```

필요한 것: Chrome(헤드리스 스크린샷), `python3`, `pnpm install` 완료(OG 이미지가 Pretendard를 쓴다).
Chrome 경로가 다르면 `CHROME=... apps/web/brand/generate.sh`.

## 이렇게 만든 이유

- **색은 DESIGN.md 다크 팔레트**: 배경 `background`(oklch 0.16), 글자 `foreground`(oklch 0.93 —
  밝기 천장이라 순백을 쓰지 않는다), 유채색은 `primary` 한 곳만. HTML은 oklch를 그대로 쓰고
  SVG에는 sRGB hex로 넣는다(oklch를 못 읽는 렌더러가 있다).
- **파비콘은 ㄸ 말풍선 심볼**: ㄸ 전체가 말풍선 하나이고 첫 ㄷ 아래에서 꼬리가 왼쪽 아래로 내려온다.
  획 끝은 각지게 둬야 라틴 문자 CC가 아니라 한글 ㄸ으로 읽히고, 바깥 모서리를 둥글게 해 말풍선으로
  읽힌다. 글자가 아니라 도형이라 폰트 없이 SVG 경로로 직접 그렸다. 색은 다크 `primary`(oklch 0.72 0.18 0).
- **파비콘에 배경 판을 칠한다**: 투명 배경이면 라이트 테마 탭에서 밝은 글자가 보이지 않는다.
- **심볼은 캔버스의 3/4(96 중 가로 72)을 채운다**: 16px 탭에서도 두 ㄷ 사이 틈과 꼬리가 보이는 크기다.
- **PNG는 로컬 HTTP 서버 위에서 굽는다**: `file://`에서는 Chrome이 `@font-face`와 SVG `<img>`를 막는다.
- **OG 이미지의 글자 크기가 앱의 `text-2xl` 천장을 넘는다**: 여기는 UI가 아니라 1200x630 캔버스이고
  공유 카드는 축소되어 보인다. 내용은 전부 가운데 630x630 안에 두었다 — 카카오톡·트위터 `summary`
  카드가 중앙을 정사각으로 잘라 쓴다.
