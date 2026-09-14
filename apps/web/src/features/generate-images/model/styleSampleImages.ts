// image-refact-goal-prompt.md IR-10 / image-refact-techspec.md IT-11 — styleId → 샘플 이미지 URL.
// **서버가 스타일 목록의 소스다** — FE가 모르는 id는 이미지 없이 렌더한다. 즉 이 맵에 키가 없는
// 것은 오류가 아니라 정상 상태다(준비 중 스타일과 같은 렌더 경로).
//
// `base.webp`는 원본 `clean_r1_seed42.png`(832×1216)를 중앙 크롭 480×640 webp q88로 변환한
// 것이다 — `seed42`가 재생성 시 단서가 되지만, 정확한 생성 프롬프트는 전달받지 못해 남기지
// 못한다(IR-11의 "프롬프트를 스크립트에 남긴다"가 이 이미지엔 적용되지 않는다 — 저장소 밖에서
// 만들어졌다).
// public/이 아니라 src 임포트인 이유는 IT-11 — public/은 해시 없이 원본 이름 그대로 dist/에
// 복사되지만(실측: dist/favicon-96.png), src에서 import하면 Vite가 콘텐츠 해시를 붙여
// (dist/assets/base-<8자>.webp) 아트 교체 시 URL이 저절로 바뀐다.
import baseSample from "../style-samples/base.webp";

export const STYLE_SAMPLE_IMAGES: Record<string, string> = { base: baseSample };
