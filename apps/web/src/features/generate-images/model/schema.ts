import type { DefaultValues } from "react-hook-form";
import { z } from "zod";

/** model/style의 id·표시명 단일 소스가 서버로 옮겨갔다
 * (`GET /images/models`, `entities/image-model`). 한때 이 파일이 스타일 프리셋 배열
 * (`IMAGE_STYLE_PRESETS`)을 들고 있었고 그 배열이 단일 소스였다 — **그 관례가 깨진 게 아니다.**
 * 아래 `IMAGE_ASPECT_RATIOS`·`IMAGE_COUNT_OPTIONS`는 여전히 이 파일이 단일 소스다. model/style만
 * **단일 소스가 서버로 옮겨간 것**이므로, 렌더할 옵션이 없다고 이 배열을 되살리지 말 것 —
 * `features/generate-images/ui/GenerateImagesOptionsFields.tsx`가 `useImageModelsQuery`의 응답에서
 * 직접 읽는다(옛 `GenerateImagesForm.tsx`가 세 조각으로 쪼개졌다). */

/** 비율 풀 세트, 기본값 1:1. **이 배열이 단일 소스다** —
 * 아래 옵션 목록도 `generateImagesSchema`의 zod enum도 전부 여기서 도출된다.
 *
 * 한때 배열과 enum이 손으로 유지되는 두 소스였고 "둘 다 고쳐야 한다"는 경고 주석이 달려 있었다.
 * 경고는 실제 위험을 정확히 적었지만 **경고로는 못 막는다** — enum만 고쳐도 타입은 통과하고 선택지만
 * 조용히 빠진다. `2:3`을 더할 때 실제로 두 곳에 각각 손으로 넣었다.
 *
 * `2:3`의 배경: 스토리 카드 슬롯이 2:3이고 실제 생성 치수는
 * 832×1216(Animagine XL 4.0 권장 버킷 · NovelAI 기본값)이다. 세로 셋의 순서는 비율순(3:4 → 2:3 → 9:16)이다. */
export const IMAGE_ASPECT_RATIOS = ["1:1", "4:3", "3:4", "2:3", "16:9", "9:16"] as const;

// 칩(ToggleGroup)은 좁아서 이 긴 라벨이 안 들어간다. 지우지 않고
// 접근 가능한 이름(`aria-label`)용으로 남긴다.
export const IMAGE_ASPECT_RATIO_LABEL: Record<(typeof IMAGE_ASPECT_RATIOS)[number], string> = {
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

export const IMAGE_COUNT_OPTIONS = [1, 2] as const;

// radix 단일 ToggleGroup은 선택된 항목을 다시 누르면 빈 문자열을
// 흘려보낸다(`ContentTypeToggle.tsx`의 `isContentType` 선례와 같은 모양의 가드).
export function isImageAspectRatio(value: string): value is (typeof IMAGE_ASPECT_RATIOS)[number] {
  return IMAGE_ASPECT_RATIOS.some((ratio) => ratio === value);
}

/** 폼값 -> API 바디 변환은 `model/formToServer.ts`가 전담한다. 한때 "필드 4개뿐인 단순 폼이라
 * 분리 없이 간다"(change-password/edit-profile 선례)였는데, 그 결과 폼값이 그대로 POST 바디가 되면서
 * 아래 `model`/`style`의 `z.string()`과 DTO의 좁은 리터럴이 어긋난 것을 컴파일이 못 잡았다. */
/** model/style은 값을 모르는 `z.string().min(1)`로만 검증한다 — 실제 id·가용성 검증은
 * `GET /images/models` 응답과 BE의 재검증(종횡비 포함)이 한다. */
// 집 PC 계약 v3가 통보한 1000자 하드 상한을 미러한다 — 값이 바뀌면 계약 개정으로
// 통지된다. BE 미러: apps/api/src/api/images/schemas.py.
export const generateImagesSchema = z.object({
  prompt: z
    .string()
    .trim()
    .min(1, { message: "프롬프트를 입력해주세요" })
    .max(1000, { message: "프롬프트는 1000자 이내로 입력해주세요" }),
  model: z.string().min(1),
  style: z.string().min(1),
  aspectRatio: z.enum(IMAGE_ASPECT_RATIOS),
  count: z.number().int().min(Math.min(...IMAGE_COUNT_OPTIONS)).max(Math.max(...IMAGE_COUNT_OPTIONS)),
});

export type GenerateImagesFormValues = z.infer<typeof generateImagesSchema>;

/** model/style은 여기 없다 — 모델 목록이 로드된 뒤 `GenerateImagesFormProvider`가 첫 가용 모델/
 * 스타일로 `reset()`한다. `DefaultValues<T>`는 partial이라 이 누락이 타입 에러 없이 통과하므로,
 * 그 동안 `field.value`가 `undefined`인 것을 Select 쪽에서 감안해야 한다. */
export const generateImagesDefaultValues: DefaultValues<GenerateImagesFormValues> = {
  prompt: "",
  aspectRatio: "1:1",
  count: 1,
};
