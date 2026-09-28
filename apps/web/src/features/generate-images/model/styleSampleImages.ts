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
//   2026-09-28, 프로덕션 `/studio/images`에서 생성 · 비율 3:4 · 1장 · model `v1` · 참조 없음
//   원본 896×1152 webp → 중앙 크롭 864×1152(폭 좌우 16px) → 480×640 webp q88(Pillow LANCZOS)
//   ※ 집 PC의 "3:4" 버킷은 실제로 896×1152(0.778)라 0.75가 아니다 — 크롭이 필요하다.
//
//   soft_portrait  1girl, solo, upper body, looking at viewer, simple background, long black hair, gentle smile, white blouse
//   chapel_glass   1girl, solo, upper body, looking at viewer, simple background, blonde hair, white dress, hands clasped, serene expression
//   royal_drama    1boy, solo, adult male, man, male focus, upper body, looking at viewer, simple background, silver hair, ornate coat, confident expression
//   sparkle_night  1girl, solo, upper body, looking at viewer, simple background, pink twintails, frilled blouse, long sleeves, smiling
//   watercolor     1girl, solo, upper body, looking at viewer, simple background, short brown hair, straw hat, light blue dress, short sleeves, soft smile
//   pixel_art      1boy, solo, upper body, looking at viewer, simple background, spiky orange hair, hoodie, headphones, grinning
//   deco_cute      1girl, solo, upper body, looking at viewer, simple background, twin braids, big eyes, ribbon, oversized sweater, cheerful
//
// 집 PC 계약 v4부터 style은 화풍·조명·채색만 정하고 구도·배경은 프롬프트 몫이라, 7장 모두 같은
// 구도·배경 태그(`upper body, looking at viewer, simple background`)를 두어 차이가 화풍에서만 나게 했다.
// 태그 순서는 인물 수·성별(`1girl`/`1boy`, `solo`) → 구도 → 배경 → 인물 묘사다.
// `royal_drama`에만 `adult male, man, male focus`를 더한 것은 그 style에서 `1boy`만 쓰면 여성으로
// 그려질 수 있어서다. 노출을 암시하는 의상(어깨 드러난 드레스·민소매)은 생성 차단을 피하려고 긴·짧은
// 소매 옷으로 바꿨다. 이 7장은 모두 차단 없이 첫 시도에 나왔다.
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
