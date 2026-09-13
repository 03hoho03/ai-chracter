// image-refact-goal-prompt.md IR-10 / image-refact-techspec.md IT-11 — styleId → 샘플 이미지 URL.
// **서버가 스타일 목록의 소스다** — FE가 모르는 id는 이미지 없이 렌더한다. 즉 이 맵에 키가 없는
// 것은 오류가 아니라 정상 상태다(준비 중 스타일과 같은 렌더 경로).
//
// ⚠️ 지금은 빈 맵이다 — 샘플 아트(`base.webp`)가 아직 없다(image-refact-progress.md S4에서 집 PC로
// 생성 예정). 생기면 `assets/image-styles/base.webp`를 `src` 임포트해 `base` 키를 채운다.
// public/이 아니라 src 임포트인 이유는 IT-11 — public/은 해시 없이 원본 이름 그대로 dist/에
// 복사되지만(실측: dist/favicon-96.png), src에서 import하면 Vite가 콘텐츠 해시를 붙여
// (dist/assets/base-<8자>.webp) 아트 교체 시 URL이 저절로 바뀐다.
export const STYLE_SAMPLE_IMAGES: Record<string, string> = {};
