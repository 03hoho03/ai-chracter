// image-refact-goal-prompt.md IR-10 / image-refact-techspec.md IT-11 — styleId → 샘플 이미지 URL.
// **서버가 스타일 목록의 소스다** — FE가 모르는 id는 이미지 없이 렌더한다. 즉 이 맵에 키가 없는
// 것은 오류가 아니라 정상 상태다(준비 중 스타일과 같은 렌더 경로). 지금은 이 문장이 7종 전체의
// 상태다 — 샘플 아트가 아직 없어 빈 맵으로 먼저 배포한다(image-style-7-followup.md IS-20: 회색
// 타일이 "생성 기능 자체가 막힘"보다 낫다는 판단).
//
// 아트가 오면 `style-samples/<styleId>.webp`(480×640 webp q88, 3:4 중앙 크롭 —
// image-style-7-goal-prompt.md IS-12)로 넣고 여기 src import + 키를 추가한다. public/이 아니라
// src 임포트여야 하는 이유는 IT-11 — public/은 해시 없이 원본 이름 그대로 dist/에 복사되지만,
// src에서 import하면 Vite가 콘텐츠 해시를 붙여(dist/assets/<styleId>-<8자>.webp) 아트 교체 시
// URL이 저절로 바뀐다.
export const STYLE_SAMPLE_IMAGES: Record<string, string> = {};
