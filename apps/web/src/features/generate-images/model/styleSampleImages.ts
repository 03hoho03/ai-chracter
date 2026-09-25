// styleId → 샘플 이미지 URL.
// **서버가 스타일 목록의 소스다** — FE가 모르는 id는 이미지 없이 렌더한다. 즉 이 맵에 키가 없는
// 것은 오류가 아니라 정상 상태다(준비 중 스타일과 같은 렌더 경로).
//
// public/이 아니라 src 임포트인 이유: public/은 해시 없이 원본 이름 그대로 dist/에
// 복사되지만(실측: dist/favicon-96.png), src에서 import하면 Vite가 콘텐츠 해시를 붙여
// (dist/assets/<styleId>-<8자>.webp) 아트 교체 시 URL이 저절로 바뀐다.
//
// ── 생성 조건 ────────────────────────────────
// 기존 `base.webp`가 프롬프트 유실로 재현 불가능했던 것을 반복하지 않으려고 전부 남긴다.
//
//   2026-09-15, 프로덕션 `/studio/images`에서 생성 · 비율 3:4 · 1장 · model `v1`
//   원본 896×1152 webp → 중앙 크롭 864×1152(폭 좌우 16px) → 480×640 webp q88(Pillow LANCZOS)
//   ※ 집 PC의 "3:4" 버킷은 실제로 896×1152(0.778)라 0.75가 아니다 — 크롭이 필요하다.
//
//   soft_portrait  1girl, solo, long black hair, gentle smile, white blouse, upper body, looking at viewer
//   chapel_glass   1girl, solo, blonde hair, white dress, hands clasped, serene expression, upper body
//   royal_drama    1boy, solo, silver hair, ornate coat, confident expression, upper body, looking at viewer
//   sparkle_night  1girl, solo, cowboy shot, standing, pink twintails, off-shoulder dress, smiling, night city background, full face visible
//   watercolor     1girl, solo, cowboy shot, standing, short brown hair, straw hat, sundress, soft smile, flower field background, full body visible
//   pixel_art      1boy, solo, spiky orange hair, hoodie, headphones, grinning, upper body
//   deco_cute      1girl, solo, twin braids, big eyes, ribbon, oversized sweater, cheerful, upper body
//
// `sparkle_night`·`watercolor`만 `cowboy shot`·배경 지정이 붙어 있다 — 그 둘은 짧은 프롬프트에서
// 극단적 클로즈업으로 치우쳐 나머지 5장과 프레이밍이 갈렸다(집 PC 계약 v3가 `sparkle_night`에 대해
// 미리 경고한 성질이다). 다시 뽑을 때 이 태그를 빼면 같은 문제가 재발한다.
import chapelGlassSample from "../style-samples/chapel_glass.webp";
import decoCuteSample from "../style-samples/deco_cute.webp";
import pixelArtSample from "../style-samples/pixel_art.webp";
import royalDramaSample from "../style-samples/royal_drama.webp";
import softPortraitSample from "../style-samples/soft_portrait.webp";
import sparkleNightSample from "../style-samples/sparkle_night.webp";
import watercolorSample from "../style-samples/watercolor.webp";

export const STYLE_SAMPLE_IMAGES: Record<string, string> = {
  soft_portrait: softPortraitSample,
  chapel_glass: chapelGlassSample,
  royal_drama: royalDramaSample,
  sparkle_night: sparkleNightSample,
  watercolor: watercolorSample,
  pixel_art: pixelArtSample,
  deco_cute: decoCuteSample,
};
