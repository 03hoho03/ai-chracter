import { z } from "zod";

/** tasks/prd-image-generation.md §3 — 스타일 프리셋 5종(값은 백엔드 ImageStylePreset과 동일 키). */
export const IMAGE_STYLE_PRESET_OPTIONS = [
  { value: "realistic", label: "사실적" },
  { value: "anime", label: "애니메이션" },
  { value: "illustration", label: "일러스트" },
  { value: "render3d", label: "3D 렌더" },
  { value: "none", label: "없음" },
] as const;

/** tasks/prd-image-generation.md §3 — 비율 풀 세트, 기본값 1:1. */
export const IMAGE_ASPECT_RATIO_OPTIONS = [
  { value: "1:1", label: "1:1 · 정사각형" },
  { value: "4:3", label: "4:3 · 가로" },
  { value: "3:4", label: "3:4 · 세로" },
  { value: "16:9", label: "16:9 · 와이드" },
  { value: "9:16", label: "9:16 · 세로 와이드" },
] as const;

export const IMAGE_COUNT_OPTIONS = [1, 2, 3, 4] as const;

/** POST /images/generate 요청 필드 4개뿐인 단순 폼이라 formToServer/serverToForm 분리 없이 구현한다
 * (change-password/edit-profile 선례). 실제 제출 로직은 US-008에서 이 값을 그대로 API 바디에 맞춰 붙인다. */
export const generateImagesSchema = z.object({
  prompt: z.string().trim().min(1, { message: "프롬프트를 입력해주세요" }),
  style: z.enum(["realistic", "anime", "illustration", "render3d", "none"]),
  aspectRatio: z.enum(["1:1", "4:3", "3:4", "16:9", "9:16"]),
  count: z.number().int().min(1).max(4),
});

export type GenerateImagesFormValues = z.infer<typeof generateImagesSchema>;

export const generateImagesDefaultValues: GenerateImagesFormValues = {
  prompt: "",
  style: "none",
  aspectRatio: "1:1",
  count: 1,
};
