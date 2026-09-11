import { z } from "zod";

/** tasks/archive/prd-image-generation.md §3 — 스타일 프리셋 5종(값은 백엔드 ImageStylePreset과 동일 키). */
export const IMAGE_STYLE_PRESET_OPTIONS = [
  { value: "realistic", label: "사실적" },
  { value: "anime", label: "애니메이션" },
  { value: "illustration", label: "일러스트" },
  { value: "render3d", label: "3D 렌더" },
  { value: "none", label: "없음" },
] as const;

/** tasks/archive/prd-image-generation.md §3 — 비율 풀 세트, 기본값 1:1. **이 배열이 단일 소스다** —
 * 아래 옵션 목록도 `generateImagesSchema`의 zod enum도 전부 여기서 도출된다(TS-09).
 *
 * 한때 배열과 enum이 손으로 유지되는 두 소스였고 "둘 다 고쳐야 한다"는 경고 주석이 달려 있었다.
 * 경고는 실제 위험을 정확히 적었지만 **경고로는 못 막는다** — enum만 고쳐도 타입은 통과하고 선택지만
 * 조용히 빠진다. `2:3`을 더할 때 실제로 두 곳에 각각 손으로 넣었다.
 *
 * `2:3`의 배경(card-grid-goal-prompt.md D-3): 스토리 카드 슬롯이 2:3이고 실제 생성 치수는
 * 832×1216(Animagine XL 4.0 권장 버킷 · NovelAI 기본값)이다. 세로 셋의 순서는 비율순(3:4 → 2:3 → 9:16)이다. */
export const IMAGE_ASPECT_RATIOS = ["1:1", "4:3", "3:4", "2:3", "16:9", "9:16"] as const;

const IMAGE_ASPECT_RATIO_LABEL: Record<(typeof IMAGE_ASPECT_RATIOS)[number], string> = {
  "1:1": "1:1 · 정사각형",
  "4:3": "4:3 · 가로",
  "3:4": "3:4 · 세로",
  "2:3": "2:3 · 세로 포스터",
  "16:9": "16:9 · 와이드",
  "9:16": "9:16 · 세로 와이드",
};

export const IMAGE_ASPECT_RATIO_OPTIONS = IMAGE_ASPECT_RATIOS.map((value) => ({
  value,
  label: IMAGE_ASPECT_RATIO_LABEL[value],
}));

export const IMAGE_COUNT_OPTIONS = [1, 2, 3, 4] as const;

/** POST /images/generate 요청 필드 4개뿐인 단순 폼이라 formToServer/serverToForm 분리 없이 구현한다
 * (change-password/edit-profile 선례). 실제 제출 로직은 US-008에서 이 값을 그대로 API 바디에 맞춰 붙인다. */
/** 모델 목록은 GET /images/models(entities/image-model)에서 동적으로 받지만, 폼 값 검증용
 * enum은 백엔드 ImageModelId와 동일하게 고정한다(BE가 종횡비 지원 여부까지 재검증한다). */
export const generateImagesSchema = z.object({
  prompt: z.string().trim().min(1, { message: "프롬프트를 입력해주세요" }),
  model: z.enum(["flux-schnell", "sdxl"]),
  style: z.enum(["realistic", "anime", "illustration", "render3d", "none"]),
  aspectRatio: z.enum(IMAGE_ASPECT_RATIOS),
  count: z.number().int().min(1).max(4),
});

export type GenerateImagesFormValues = z.infer<typeof generateImagesSchema>;

export const generateImagesDefaultValues: GenerateImagesFormValues = {
  prompt: "",
  model: "flux-schnell",
  style: "none",
  aspectRatio: "1:1",
  count: 1,
};
